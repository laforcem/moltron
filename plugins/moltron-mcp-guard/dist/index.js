import * as http from "node:http";
import * as https from "node:https";
import * as net from "node:net";
import * as fs from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";
import { spawn, execFileSync } from "node:child_process";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
const TOKEN_HEADER = "x-moltron-guard-token";
const DEFAULT_ENV_PASSTHROUGH = ["PATH", "HOME", "LANG", "TMPDIR"];
function readServerEntries(pluginConfig) {
  const servers = pluginConfig?.servers;
  if (!servers || typeof servers !== "object") return {};
  return servers;
}
function readEntryFromConfig(ctx, serverName) {
  const pluginEntry = ctx.config.plugins?.entries?.["moltron-mcp-guard"];
  const servers = readServerEntries(pluginEntry?.config);
  const raw = servers[serverName];
  if (!raw || typeof raw !== "object") return void 0;
  return raw;
}
function resolveSecretOrFail(entry, serverName, health, logger) {
  const value = entry.secret;
  if (typeof value === "string" && value.length > 0) return value;
  const message = `moltron-mcp-guard: no credential resolvable for MCP server "${serverName}" \u2014 check plugins.entries.moltron-mcp-guard.config.servers.${serverName}.secret; it must point at a valid entry in OpenClaw's secret store`;
  logger.error(message);
  health?.reportFailure(new Error(message));
  return void 0;
}
function checkAllowedHost(secretStoreId, requiredHost, serverName, logger) {
  let entries;
  try {
    const raw = execFileSync("openclaw", ["secrets", "store", "list", "--json"], {
      encoding: "utf8",
      timeout: 1e4
    });
    entries = JSON.parse(raw);
  } catch (error) {
    logger.error(
      `moltron-mcp-guard: "${serverName}" could not read the secret store's allowed-hosts list: ${String(error)}`
    );
    return false;
  }
  const match = entries.find((e) => e.name === secretStoreId);
  const allowedHosts = match?.allowedHosts ?? [];
  if (allowedHosts.includes(requiredHost)) return true;
  logger.error(
    `moltron-mcp-guard: "${serverName}" refusing to use "${secretStoreId}" \u2014 its allowed-hosts list (${allowedHosts.length > 0 ? allowedHosts.join(", ") : "none configured"}) does not include "${requiredHost}". Add it in Settings -> Secrets.`
  );
  return false;
}
function getOrCreateLocalToken(stateDir, serverName) {
  const dir = path.join(stateDir, "moltron-mcp-guard");
  fs.mkdirSync(dir, { recursive: true, mode: 448 });
  const tokenPath = path.join(dir, `${serverName}.token`);
  try {
    const existing = fs.readFileSync(tokenPath, "utf8").trim();
    if (existing) return existing;
  } catch {
  }
  const token = crypto.randomBytes(24).toString("hex");
  fs.writeFileSync(tokenPath, token, { mode: 384 });
  return token;
}
function buildChildEnv(entry, secret) {
  const env = {};
  for (const key of [...DEFAULT_ENV_PASSTHROUGH, ...entry.passthroughEnv ?? []]) {
    const value = process.env[key];
    if (value !== void 0) env[key] = value;
  }
  Object.assign(env, entry.env ?? {});
  env[entry.envVar] = secret;
  return env;
}
function startNetworkServer(serverName, entry, ctx) {
  const upstream = new URL(entry.upstreamUrl);
  const resolved = resolveSecretOrFail(entry, serverName, ctx.serviceHealth, ctx.logger);
  const hostAllowed = checkAllowedHost(entry.secretStoreId, upstream.hostname, serverName, ctx.logger);
  if (resolved && !hostAllowed) {
    ctx.serviceHealth?.reportFailure(
      new Error(`moltron-mcp-guard: "${serverName}" host not on the secret's allowed-hosts list`)
    );
  }
  const secret = resolved && hostAllowed ? resolved : void 0;
  const token = getOrCreateLocalToken(ctx.stateDir, serverName);
  const upstreamClient = upstream.protocol === "https:" ? https : http;
  const server = http.createServer((req, res) => {
    if (req.headers[TOKEN_HEADER] !== token) {
      res.writeHead(403, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "moltron-mcp-guard: missing or wrong local token" }));
      return;
    }
    if (!secret) {
      res.writeHead(503, { "content-type": "application/json" });
      res.end(
        JSON.stringify({
          error: `moltron-mcp-guard: no credential resolvable for "${serverName}"`
        })
      );
      return;
    }
    const headers = { ...req.headers };
    delete headers.host;
    delete headers[TOKEN_HEADER];
    headers[entry.header] = `${entry.prefix ?? ""}${secret}`;
    const proxyReq = upstreamClient.request(
      {
        protocol: upstream.protocol,
        hostname: upstream.hostname,
        port: upstream.port || (upstream.protocol === "https:" ? 443 : 80),
        path: upstream.pathname.replace(/\/$/, "") + (req.url ?? "/"),
        method: req.method,
        headers
      },
      (upstreamRes) => {
        const status = upstreamRes.statusCode ?? 502;
        if (status === 401 || status === 403) {
          const message = `moltron-mcp-guard: "${serverName}" rejected the resolved credential (HTTP ${status})`;
          ctx.logger.error(message);
          ctx.serviceHealth?.reportFailure(new Error(message));
        } else if (status < 400) {
          ctx.serviceHealth?.clearFailure();
        }
        res.writeHead(status, upstreamRes.headers);
        upstreamRes.pipe(res);
      }
    );
    proxyReq.on("error", (error) => {
      ctx.logger.error(`moltron-mcp-guard: "${serverName}" relay error: ${String(error)}`);
      if (!res.headersSent) {
        res.writeHead(502, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: `moltron-mcp-guard: upstream unreachable for "${serverName}"` }));
      }
    });
    req.pipe(proxyReq);
  });
  server.listen(entry.port, "127.0.0.1", () => {
    ctx.logger.info(
      `moltron-mcp-guard: "${serverName}" relay listening on 127.0.0.1:${entry.port} -> ${entry.upstreamUrl}. Set mcp.servers.${serverName}.headers.${JSON.stringify(TOKEN_HEADER)} to the token in ${path.join(ctx.stateDir, "moltron-mcp-guard", `${serverName}.token`)}.`
    );
  });
  return { close: () => server.close() };
}
function readTokenLine(connection, onResult) {
  let buffered = Buffer.alloc(0);
  const onData = (chunk) => {
    buffered = Buffer.concat([buffered, chunk]);
    const newlineIndex = buffered.indexOf(10);
    if (newlineIndex === -1) {
      if (buffered.length > 256) connection.destroy();
      return;
    }
    connection.off("data", onData);
    const line = buffered.subarray(0, newlineIndex).toString("utf8").trim();
    const rest = buffered.subarray(newlineIndex + 1);
    onResult(line, rest);
  };
  connection.on("data", onData);
}
function startLocalProgramServer(serverName, entry, ctx) {
  const resolved = resolveSecretOrFail(entry, serverName, ctx.serviceHealth, ctx.logger);
  const hostAllowed = entry.expectedHost ? checkAllowedHost(entry.secretStoreId, entry.expectedHost, serverName, ctx.logger) : true;
  if (resolved && !hostAllowed) {
    ctx.serviceHealth?.reportFailure(
      new Error(`moltron-mcp-guard: "${serverName}" host not on the secret's allowed-hosts list`)
    );
  }
  const secret = resolved && hostAllowed ? resolved : void 0;
  const token = getOrCreateLocalToken(ctx.stateDir, serverName);
  const socketDir = path.join(ctx.stateDir, "moltron-mcp-guard");
  fs.mkdirSync(socketDir, { recursive: true, mode: 448 });
  const socketPath = path.join(socketDir, `${serverName}.sock`);
  fs.rmSync(socketPath, { force: true });
  const server = net.createServer((connection) => {
    readTokenLine(connection, (presentedToken, rest) => {
      if (presentedToken !== token) {
        connection.destroy();
        return;
      }
      if (!secret) {
        connection.destroy();
        return;
      }
      const child = spawn(entry.command, entry.args ?? [], {
        cwd: entry.cwd,
        env: buildChildEnv(entry, secret),
        stdio: ["pipe", "pipe", "pipe"]
      });
      let stderrTail = "";
      child.stderr.on("data", (chunk) => {
        stderrTail = (stderrTail + chunk.toString("utf8")).slice(-2048);
      });
      if (rest.length > 0) child.stdin.write(rest);
      connection.pipe(child.stdin);
      child.stdout.pipe(connection);
      const startedAt = Date.now();
      child.on("exit", (code) => {
        connection.destroy();
        if (code !== 0 && Date.now() - startedAt < 1e4) {
          const message = `moltron-mcp-guard: "${serverName}" exited during startup (code ${code}) \u2014 likely a rejected credential or misconfiguration. Last output: ${stderrTail.trim() || "(none)"}`;
          ctx.logger.error(message);
          ctx.serviceHealth?.reportFailure(new Error(message));
        } else if (code === 0) {
          ctx.serviceHealth?.clearFailure();
        }
      });
      child.on("error", (error) => {
        const message = `moltron-mcp-guard: "${serverName}" failed to start: ${String(error)}`;
        ctx.logger.error(message);
        ctx.serviceHealth?.reportFailure(new Error(message));
        connection.destroy();
      });
      connection.on("close", () => {
        if (!child.killed) child.kill();
      });
    });
  });
  server.listen(socketPath, () => {
    fs.chmodSync(socketPath, 384);
    ctx.logger.info(
      `moltron-mcp-guard: "${serverName}" bridge socket at ${socketPath}. Set mcp.servers.${serverName}.command/args to run bridge.mjs ${socketPath} <token>, using the token in ${path.join(socketDir, `${serverName}.token`)}.`
    );
  });
  return {
    close: () => {
      server.close();
      fs.rmSync(socketPath, { force: true });
    }
  };
}
var index_default = definePluginEntry({
  id: "moltron-mcp-guard",
  name: "Moltron MCP Guard",
  description: "Stands in between OpenClaw and real MCP servers, resolving each one's credential from OpenClaw's own protected secret store instead of mcp.servers.<name>.env/.headers plaintext.",
  register(api) {
    const entries = readServerEntries(
      api.pluginConfig
    );
    for (const serverName of Object.keys(entries)) {
      let handle;
      api.registerService({
        id: `moltron-mcp-guard:${serverName}`,
        reload: {
          configPrefixes: [`plugins.entries.moltron-mcp-guard.config.servers.${serverName}`]
        },
        start(ctx) {
          const entry = readEntryFromConfig(ctx, serverName);
          if (!entry) {
            const message = `moltron-mcp-guard: "${serverName}" has no valid config entry`;
            ctx.logger.error(message);
            ctx.serviceHealth?.reportFailure(new Error(message));
            return;
          }
          handle = entry.kind === "network" ? startNetworkServer(serverName, entry, ctx) : startLocalProgramServer(serverName, entry, ctx);
        },
        stop() {
          handle?.close();
          handle = void 0;
        }
      });
    }
  }
});
export {
  index_default as default
};
