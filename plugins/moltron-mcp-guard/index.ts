// `openclaw plugins install` needs compiled JS for a TypeScript entry — the
// raw-.ts fallback only works for a source-checkout/dev path, not a normal
// install. After editing this file, rebuild with:
//   npx esbuild index.ts --outfile=dist/index.js --format=esm --platform=node --target=node22
import * as http from "node:http";
import * as https from "node:https";
import * as net from "node:net";
import * as fs from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import type {
  OpenClawPluginApi,
  OpenClawPluginServiceContext,
} from "openclaw/plugin-sdk/plugin-entry";

// Workaround for openclaw/openclaw#76493: mcp.servers.<name>.env/.headers only
// accept string|number|boolean, so a credential for an MCP server otherwise has
// to be plaintext in openclaw.json. registerMcpServerConnectionResolver looks
// like the fix, but it's unconditionally treated as "requester-scoped" and
// never fires for cron/subagent/heartbeat/public-gateway turns (confirmed
// against openclaw's own tests) — wrong tool for an always-on integration.
//
// Instead: mcp.servers.<name> points at a local, credential-free stand-in this
// plugin runs. The real credential is resolved once (via this plugin's own
// `secret` config field, declared under configContracts.secretInputs.paths so
// core resolves it from a SecretRef the same way it does for its own
// supported surface — never process.env, never a CLI-visible value) and held
// only in this plugin's memory.
//
// Both entry points additionally require a per-server local token (generated
// once, persisted under stateDir, logged at startup) before anything is
// proxied or spawned — binding to 127.0.0.1 / a 0600 socket limits this to
// local processes already, but without a token any local process could ride
// the injected credential for free. The operator copies the logged token into
// mcp.servers.<name>.headers / .args once; it gates use of the local
// stand-in, it is not the protected credential itself.

type NetworkServerEntry = {
  kind: "network";
  secret: string;
  port: number;
  upstreamUrl: string;
  header: string;
  prefix?: string;
};

type LocalProgramServerEntry = {
  kind: "local-program";
  secret: string;
  command: string;
  args?: string[];
  envVar: string;
  cwd?: string;
  /** Extra process.env keys to pass through verbatim, beyond the minimal default set. */
  passthroughEnv?: string[];
  /** Extra static (non-secret) environment variables the real program needs, e.g. a URL. */
  env?: Record<string, string>;
};

type ServerEntry = NetworkServerEntry | LocalProgramServerEntry;

const TOKEN_HEADER = "x-moltron-guard-token";
const DEFAULT_ENV_PASSTHROUGH = ["PATH", "HOME", "LANG", "TMPDIR"];

function readServerEntries(
  pluginConfig: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const servers = pluginConfig?.servers;
  if (!servers || typeof servers !== "object") return {};
  return servers as Record<string, unknown>;
}

function readEntryFromConfig(
  ctx: OpenClawPluginServiceContext,
  serverName: string,
): ServerEntry | undefined {
  const pluginEntry = (
    ctx.config as unknown as {
      plugins?: { entries?: Record<string, { config?: Record<string, unknown> }> };
    }
  ).plugins?.entries?.["moltron-mcp-guard"];
  const servers = readServerEntries(pluginEntry?.config);
  const raw = servers[serverName];
  if (!raw || typeof raw !== "object") return undefined;
  return raw as ServerEntry;
}

// A resolved `secret` should already be a plain string by the time it reaches
// this plugin's own config (core resolves configContracts.secretInputs.paths
// entries at ordinary config-load time, same as it does for its own supported
// SecretRef surface). If it isn't — resolution failed, or nothing was
// configured — that's the "no credential resolvable" failure, distinct from
// "the real service rejected the credential we did resolve".
function resolveSecretOrFail(
  entry: ServerEntry,
  serverName: string,
  health: OpenClawPluginServiceContext["serviceHealth"],
  logger: OpenClawPluginServiceContext["logger"],
): string | undefined {
  const value = entry.secret;
  if (typeof value === "string" && value.length > 0) return value;
  const message = `moltron-mcp-guard: no credential resolvable for MCP server "${serverName}" — check plugins.entries.moltron-mcp-guard.config.servers.${serverName}.secret; it must point at a valid entry in OpenClaw's secret store`;
  logger.error(message);
  health?.reportFailure(new Error(message));
  return undefined;
}

// One random token per server, generated on first use and reused across
// restarts (so the operator only has to copy it into mcp.servers.<name> once).
// Low-sensitivity by design: it only gates access to this local stand-in, it
// never protects the real upstream credential directly, so persisting it
// alongside other plugin state (0600) is fine.
function getOrCreateLocalToken(stateDir: string, serverName: string): string {
  const dir = path.join(stateDir, "moltron-mcp-guard");
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const tokenPath = path.join(dir, `${serverName}.token`);
  try {
    const existing = fs.readFileSync(tokenPath, "utf8").trim();
    if (existing) return existing;
  } catch {
    // fall through to generate
  }
  const token = crypto.randomBytes(24).toString("hex");
  fs.writeFileSync(tokenPath, token, { mode: 0o600 });
  return token;
}

function buildChildEnv(
  entry: LocalProgramServerEntry,
  secret: string,
): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const key of [...DEFAULT_ENV_PASSTHROUGH, ...(entry.passthroughEnv ?? [])]) {
    const value = process.env[key];
    if (value !== undefined) env[key] = value;
  }
  Object.assign(env, entry.env ?? {});
  env[entry.envVar] = secret;
  return env;
}

function startNetworkServer(
  serverName: string,
  entry: NetworkServerEntry,
  ctx: OpenClawPluginServiceContext,
): { close(): void } {
  const secret = resolveSecretOrFail(entry, serverName, ctx.serviceHealth, ctx.logger);
  const token = getOrCreateLocalToken(ctx.stateDir, serverName);
  const upstream = new URL(entry.upstreamUrl);
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
          error: `moltron-mcp-guard: no credential resolvable for "${serverName}"`,
        }),
      );
      return;
    }

    const headers: http.OutgoingHttpHeaders = { ...req.headers };
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
        headers,
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
      },
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
      `moltron-mcp-guard: "${serverName}" relay listening on 127.0.0.1:${entry.port} -> ${entry.upstreamUrl}. ` +
        `Set mcp.servers.${serverName}.headers.${JSON.stringify(TOKEN_HEADER)} to the token in ${path.join(ctx.stateDir, "moltron-mcp-guard", `${serverName}.token`)}.`,
    );
  });

  return { close: () => server.close() };
}

// Reads a single newline-terminated token line off a fresh connection before
// treating anything further on it as real stdio traffic. Anything after the
// newline in the same chunk is buffered and replayed once the child spawns.
function readTokenLine(
  connection: net.Socket,
  onResult: (token: string, rest: Buffer) => void,
): void {
  let buffered = Buffer.alloc(0);
  const onData = (chunk: Buffer) => {
    buffered = Buffer.concat([buffered, chunk]);
    const newlineIndex = buffered.indexOf(0x0a);
    if (newlineIndex === -1) {
      if (buffered.length > 256) connection.destroy(); // not a token line
      return;
    }
    connection.off("data", onData);
    const line = buffered.subarray(0, newlineIndex).toString("utf8").trim();
    const rest = buffered.subarray(newlineIndex + 1);
    onResult(line, rest);
  };
  connection.on("data", onData);
}

function startLocalProgramServer(
  serverName: string,
  entry: LocalProgramServerEntry,
  ctx: OpenClawPluginServiceContext,
): { close(): void } {
  const secret = resolveSecretOrFail(entry, serverName, ctx.serviceHealth, ctx.logger);
  const token = getOrCreateLocalToken(ctx.stateDir, serverName);
  const socketDir = path.join(ctx.stateDir, "moltron-mcp-guard");
  fs.mkdirSync(socketDir, { recursive: true, mode: 0o700 });
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

      const child: ChildProcessWithoutNullStreams = spawn(entry.command, entry.args ?? [], {
        cwd: entry.cwd,
        env: buildChildEnv(entry, secret),
        stdio: ["pipe", "pipe", "pipe"],
      });

      let stderrTail = "";
      child.stderr.on("data", (chunk: Buffer) => {
        stderrTail = (stderrTail + chunk.toString("utf8")).slice(-2048);
      });

      if (rest.length > 0) child.stdin.write(rest);
      connection.pipe(child.stdin);
      child.stdout.pipe(connection);

      const startedAt = Date.now();
      child.on("exit", (code) => {
        connection.destroy();
        if (code !== 0 && Date.now() - startedAt < 10_000) {
          const message = `moltron-mcp-guard: "${serverName}" exited during startup (code ${code}) — likely a rejected credential or misconfiguration. Last output: ${stderrTail.trim() || "(none)"}`;
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
    fs.chmodSync(socketPath, 0o600);
    ctx.logger.info(
      `moltron-mcp-guard: "${serverName}" bridge socket at ${socketPath}. ` +
        `Set mcp.servers.${serverName}.command/args to run bridge.mjs ${socketPath} <token>, ` +
        `using the token in ${path.join(socketDir, `${serverName}.token`)}.`,
    );
  });

  return {
    close: () => {
      server.close();
      fs.rmSync(socketPath, { force: true });
    },
  };
}

export default definePluginEntry({
  id: "moltron-mcp-guard",
  name: "Moltron MCP Guard",
  description:
    "Stands in between OpenClaw and real MCP servers, resolving each one's credential from OpenClaw's own protected secret store instead of mcp.servers.<name>.env/.headers plaintext.",
  register(api: OpenClawPluginApi) {
    const entries = readServerEntries(
      api.pluginConfig as Record<string, unknown> | undefined,
    );

    for (const serverName of Object.keys(entries)) {
      let handle: { close(): void } | undefined;
      api.registerService({
        id: `moltron-mcp-guard:${serverName}`,
        reload: {
          configPrefixes: [`plugins.entries.moltron-mcp-guard.config.servers.${serverName}`],
        },
        start(ctx) {
          const entry = readEntryFromConfig(ctx, serverName);
          if (!entry) {
            const message = `moltron-mcp-guard: "${serverName}" has no valid config entry`;
            ctx.logger.error(message);
            ctx.serviceHealth?.reportFailure(new Error(message));
            return;
          }
          handle =
            entry.kind === "network"
              ? startNetworkServer(serverName, entry, ctx)
              : startLocalProgramServer(serverName, entry, ctx);
        },
        stop() {
          handle?.close();
          handle = undefined;
        },
      });
    }
  },
});
