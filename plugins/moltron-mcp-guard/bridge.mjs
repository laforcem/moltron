#!/usr/bin/env node
// Secret-free. This is what mcp.servers.<name>.command should point at for a
// "local-program" moltron-mcp-guard entry, instead of the real program.
// Its only job is: connect to the private local socket moltron-mcp-guard is
// listening on for this server, present the local gating token, and copy
// stdin/stdout to/from it. The real program and its credential live only on
// the other end of that socket, inside the plugin's own supervised child
// process — never here. The token isn't the protected credential itself; it
// only gates who may use this stand-in.
//
// Usage: node bridge.mjs <socket-path> <token>
// Both are logged by moltron-mcp-guard at startup ("bridge socket at ...").

import { connect } from "node:net";

const socketPath = process.argv[2];
const token = process.argv[3];
if (!socketPath || !token) {
  process.stderr.write("moltron-mcp-guard bridge: usage: bridge.mjs <socket-path> <token>\n");
  process.exit(1);
}

const socket = connect(socketPath);

socket.on("connect", () => {
  socket.write(`${token}\n`);
  process.stdin.pipe(socket);
  socket.pipe(process.stdout);
});

socket.on("error", (error) => {
  process.stderr.write(`moltron-mcp-guard bridge: could not reach ${socketPath}: ${error}\n`);
  process.exit(1);
});

socket.on("close", () => {
  process.exit(0);
});

process.stdin.on("error", () => socket.destroy());
process.stdout.on("error", () => socket.destroy());
