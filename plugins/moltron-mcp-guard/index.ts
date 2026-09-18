import * as http from "node:http";
import * as https from "node:https";
import * as net from "node:net";
import * as fs from "node:fs";
import * as path from "node:path";
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
};

type ServerEntry = NetworkServerEntry | LocalProgramServerEntry;

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

function startNetworkServer(
  serverName: string,
  entry: NetworkServerEntry,
  ctx: OpenClawPluginServiceContext,
): { close(): void } {
  const secret = resolveSecretOrFail(entry, serverName, ctx.serviceHealth, ctx.logger);
  const upstream = new URL(entry.upstreamUrl);
  const upstreamClient = upstream.protocol === "https:" ? https : http;

  const server = http.createServer((req, res) => {
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
      `moltron-mcp-guard: "${serverName}" relay listening on 127.0.0.1:${entry.port} -> ${entry.upstreamUrl}`,
    );
  });

  return { close: () => server.close() };
}

function startLocalProgramServer(
  serverName: string,
  entry: LocalProgramServerEntry,
  ctx: OpenClawPluginServiceContext,
): { close(): void } {
  const secret = resolveSecretOrFail(entry, serverName, ctx.serviceHealth, ctx.logger);
  const socketDir = path.join(ctx.stateDir, "moltron-mcp-guard");
  fs.mkdirSync(socketDir, { recursive: true, mode: 0o700 });
  const socketPath = path.join(socketDir, `${serverName}.sock`);
  fs.rmSync(socketPath, { force: true });

  const server = net.createServer((connection) => {
    if (!secret) {
      connection.destroy();
      return;
    }

    const child: ChildProcessWithoutNullStreams = spawn(entry.command, entry.args ?? [], {
      cwd: entry.cwd,
      env: { ...process.env, [entry.envVar]: secret },
      stdio: ["pipe", "pipe", "pipe"],
    });

    let stderrTail = "";
    child.stderr.on("data", (chunk: Buffer) => {
      stderrTail = (stderrTail + chunk.toString("utf8")).slice(-2048);
    });

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

  server.listen(socketPath, () => {
    fs.chmodSync(socketPath, 0o600);
    ctx.logger.info(`moltron-mcp-guard: "${serverName}" bridge socket at ${socketPath}`);
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
