# Agent Guidelines for Moltron

Start-of-session orientation. **Update this file as tasks progress and important context surfaces** — new hosts, credentials boundaries, model choices, open questions resolved or newly discovered. This file drifts out of date fast if only read, never written; keep it current in the same change that changes the thing it describes. Durable rules that must hold deep into a session belong in hooks or CI, not here — a file read once at the top can't be trusted to keep enforcing anything on its own.

## What this is

Assistant workload configuration for **Moltron** — working name, expect this repo to be renamed once a better one exists. A persistent personal OpenClaw assistant reachable over Telegram, with its own identity and credentials rather than borrowing the user's own.

## Repo boundary with `homelab`

Deliberate split:

- **`laforcem/homelab`** owns the VM's *existence* only — Terraform provisioning and the same `common` Ansible role every other host gets (guest agent, unattended-upgrades, SSH hardening, `ufw`, Tailscale). `homelab`'s `docs/current-state.md` gets one line pointing here.
- **This repo** owns everything that makes the box *the valet* rather than a generic Debian host: the dedicated service user, OpenClaw install/config, `obsidian-headless`, MCP server registrations, Telegram bot config, and all assistant-specific docs/skills as they accumulate.

Sibling checkout assumed: this repo and `homelab` are expected side by side (see README) even though it's no longer required for secrets.

## Host

- **valet** (`192.168.10.14`, VLAN 10) — the only host this repo configures. Provisioned/hardened by `homelab` (mirrors `terraform/warden.tf`: 2 vCPU / 4GB RAM / 32GB disk, Debian 13 cloud-init template VMID 103). Ansible in this repo connects over the LAN address directly; day-to-day admin happens over Tailscale instead (the break-glass path — SSH, OpenClaw Control UI, debugging — not the everyday interface).
- A dedicated, non-`malc` Unix service user (`moltron`) runs OpenClaw on that host, created by this repo's Ansible (workload-specific, not something `homelab`'s `common` role provides).

## Secrets

Own Bitwarden Secrets Manager project, separate from `homelab`'s — a Telegram/actual-mcp/OpenAI secret leaking here shouldn't expose the Proxmox API token or Tailscale authkey, and vice versa. `ansible/.env` (gitignored, copy from `ansible/.env.example`) holds a machine-account access token scoped to *this* project only. See README for the exact env var names.

The `moltron` service user's credentials are scoped to only what the workload currently needs (own Telegram bot token, own OpenAI/Codex OAuth credential, own `actual-mcp` token) — explicitly *not* the user's SSH keys, GitHub identity, or credentials for unrelated systems (Proxmox, NAS, network infra).

## GitHub identity (`moltron-bot`)

Full details in README — don't duplicate here, but the short version: `moltron-bot` is a plain machine-user account (not a GitHub App — see issue #2) with push access to both `laforcem/moltron` and `laforcem/homelab`, authenticated via classic PAT (`GH_TOKEN`, not `gh auth login`). Default identity on the `moltron` Unix user, but override per-commit based on autonomy level:

- Fully autonomous agent work: leave `moltron-bot` as author, optionally add a human `Co-authored-by:` trailer.
- Human actively steering: author as the human, add `Co-authored-by: moltron-bot <noreply address>` instead.

`main` branch protection (both repos) requires an approving PR review; `moltron-bot` can't bypass it — only `laforcem` can merge without a second reviewer.

## OpenClaw

- Installed natively via Ansible (`npm install -g openclaw@latest`, then `openclaw gateway install` + a systemd `--user` unit) — not Docker/`doco-cd`, to match how `homelab`'s Ansible already handles host-level services like Tailscale.
- Image understanding (receipt photos) is configured as a separate model from the main agent model, decoupled via `tools.media.image.preferredModel`.
- Delegated coding work goes through `sessions_spawn` with `runtime: "acp"` targeting the Claude ACP adapter (genuine Claude Code sessions, `resumeSessionId` for cross-device handoff). Whether an ACP-spawned session interoperates with Claude Code's own Remote Control feature is **unverified** — active work on this lives on the `issue-17-acp-remote-control` branch/worktree.
- Model choices (main agent model, image model, embedding backend for memory search) are live config, not fixed architecture — the running OpenClaw config on `valet` is the source of truth, not this file or even `ansible/roles/openclaw` (not everything is Ansible-managed).

## Media tools (`ansible/roles/media-tools`)

Deliberately raw binaries, not ClawHub skills/plugins — evaluated the skill ecosystem (`docs.openclaw.ai`, ClawHub) for YouTube download/transcript/search and decided against it: no single skill covered download+transcript+search without also pulling in a third-party OAuth proxy or Google Cloud credentials, a bigger trust/credential footprint than this repo's per-service-scoped-secret convention warrants for what `exec` plus two CLI tools can already do.

- **yt-dlp**: standalone binary from the **nightly** channel of `yt-dlp/yt-dlp-nightly-builds` (not stable, not apt/pip; nightly lives in a separate repo, not a tag on the main one) — YouTube breaks extractors often enough that yt-dlp's own maintainers recommend nightly for regular users, and stable's ~monthly cadence lags too far behind. Asset is `yt-dlp_linux`, the fully standalone PyInstaller build (not the bare `yt-dlp` asset, which needs a system Python). Installed to `/home/moltron/.local/bin/yt-dlp`, moltron-owned (not root), with a matching `systemd --user` timer (`yt-dlp-update.timer`, daily) running `yt-dlp -U` — the binary's own self-updater, which only works on this standalone form (pip/apt installs can't self-update). moltron owns it so the daily update runs unprivileged like everything else moltron runs, instead of needing a root-level periodic job just to keep one CLI tool current. To update on demand: `yt-dlp -U`.
- **deno**: yt-dlp (Nov 2025+) needs an external JS runtime to solve YouTube's signature challenges — without one, extraction silently degrades to formats that often aren't even downloadable (confirmed by hand: real downloads failed with "Requested format is not available" until deno was installed). deno is what yt-dlp enables by default; other runtimes (node, bun, quickjs) are opt-in only, since deno sandboxes the arbitrary JS pulled from YouTube more safely. No official apt package exists (Deno's own docs say Debian/Ubuntu/Arch community packages lag), and npm-distributed deno is explicitly discouraged by Deno's own docs (slower startup) — so it's a one-time raw-binary install (`denoland/deno` GitHub release zip) to `/home/moltron/.local/bin/deno`, moltron-owned. Unlike yt-dlp, this doesn't need a self-update timer: the part that actually chases YouTube's changes is `yt-dlp-ejs`, which is bundled inside the yt-dlp binary itself (so it already rides yt-dlp's own nightly self-update) — deno itself only needs to clear a minimum version floor (2.3.0+) and isn't part of that arms race. To update on demand: `deno upgrade` (Deno's own built-in self-updater, replaces its own executable in place — same shape as `yt-dlp -U`).
- No YouTube search/comments capability yet — `yt-dlp "ytsearchN:query" --dump-json` covers basic search without extra credentials if/when that's wanted; not wired up as of this writing.
- Verified end-to-end on `secretary` (since renamed to `valet`) 2026-09-11: real YouTube download via `yt-dlp`, JS challenge solved via deno (`[jsc:deno] Solving JS challenges using deno` in the log), output validated with `ffprobe`.

## Browser automation (`ansible/roles/browser-tools`)

OpenClaw's built-in browser tool (`docs.openclaw.ai/tools/browser`, bundled by default — not a ClawHub skill) gives the agent Chromium-driven browser automation: tab control, click/type/drag/select, snapshots, screenshots, PDFs. It auto-detects an existing Chromium-based browser on the host (search order: system default → Chrome → Brave → Edge → Chromium → Chrome Canary, per `/tools/browser/configuration`) rather than downloading its own binary, so a binary has to exist on `valet` first. On headless Linux with no display server, local managed profiles default to headless automatically — no Xvfb needed (unlike the Obsidian/Relay tradeoff below).

This role installs only the `chromium` apt package for that auto-detect to find. It deliberately does **not** enable the tool in OpenClaw itself — that needs `"browser"` added to both `plugins.allow` and `tools.alsoAllow` in `openclaw.json`, done by hand on the box, same precedent as `actual-mcp` below (live OpenClaw config, not Ansible-managed).

## Obsidian

`obsidian-headless` (no Electron, no Xvfb) keeps the vault synced to plain markdown on disk; OpenClaw appends to the daily note via direct file edits against that synced path rather than the bundled `obsidian` skill, which requires a running Obsidian GUI. Trade-off: no CLI search/backlink-safe writes/task management from the `obsidian` skill. **Relay** (used to share notes with the user's wife) only works inside real Obsidian — `obsidian-headless` cannot participate in a Relay-shared folder; giving the assistant access to Relay-shared notes later means revisiting this decision (e.g. real Obsidian under Xvfb).

## Actual

Uses the existing remote `actual-mcp` instance already deployed on `mrgutsy` (`budget.$DOMAIN/mcp`) — no second instance stood up here. Its `mcp.servers.actual` registration is **not** managed by this repo's Ansible: the user configures it directly on `valet`, through `moltron-mcp-guard` (see below), relying on OpenClaw's own backup/restore rather than committing it here.

## Credential handling for integrations (moltron#32 / moltron#36)

Two deliberately different policies, by credential shape:

**Credentials for CLI tools OpenClaw runs itself** (a subscription key, an API token passed as a header): use OpenClaw's own built-in protected secret store (`openclaw secrets store`, or the Control UI's Settings → Secrets page) plus its destination-locked egress proxy (`secrets.egressProxy`). The tool gets a placeholder value; OpenClaw substitutes the real one only on the outbound hop to an explicitly allowed host. This is the standing default for this credential shape going forward — not Bitwarden. Doesn't cover non-HTTP protocols (a database connection, SSH) or anything run outside OpenClaw's own exec (sandboxed/remote-node exec).

**Credentials for MCP servers** (Actual, Tandoor, and future ones): OpenClaw has no built-in equivalent for this — core's `mcp.servers.<name>.env`/`.headers` schema only accepts `string|number|boolean` (upstream `openclaw/openclaw#76493`, stalled, not worth waiting on), and the plugin API that looks like it should help (`registerMcpServerConnectionResolver`) is unconditionally *requester-scoped*: confirmed against OpenClaw's own tests that it never fires for cron/subagent/heartbeat/public-gateway turns, only chat-originated ones. Using it for an always-on integration would silently break every scheduled/background use — do not use it for this.

The actual fix: `plugins/moltron-mcp-guard/`, a local OpenClaw plugin (ships from this repo like `media-tools`, but — unlike `media-tools` — **installed on `valet` by hand via `openclaw plugins install`, never by Ansible**; see the Ansible/OpenClaw boundary note below) that stands in between OpenClaw and each real MCP server:

- **Network-shaped servers** (a URL + header, e.g. `actual`): the plugin runs a small persistent local relay (`api.registerService`). Core `mcp.servers.actual` points at `http://127.0.0.1:<port>/...` with no credential in it; the relay resolves the real value once and attaches it only on the outbound hop to the real server.
- **Locally-run-program servers** (OpenClaw currently spawns the program directly and hands it a token via env, e.g. `tandoor`): the plugin spawns the real program itself, handing it the credential directly and privately, and bridges its stdio over a private local socket to a small, generic, credential-free command that ships with the plugin; core `mcp.servers.tandoor.command` runs that bridge instead of the real program.
- Either way, the credential is a **protected** (`kind: secret`) entry in OpenClaw's own store, resolved via the plugin SDK's read-only resolver (`source: "store"`) — never `process.env`, never resolved config, never printable by any CLI/status command. Declares `configContracts.secretInputs.paths` (same mechanism the bundled `acpx` plugin uses for its own MCP `env`) so these fields are audit/reload-aware, and a `reload: { configPrefixes: [...] }` on the service so a rotated credential is picked up without a full Gateway restart.
- Both the relay and the bridge socket require a per-server local token (generated once, persisted under the plugin's state dir, logged at startup) before proxying or spawning anything — binding to `127.0.0.1`/a `0600` socket isn't sufficient on its own, since without the token any other local process could ride the injected credential for free. The token only gates use of the local stand-in; it isn't the protected credential itself. A spawned local-program gets a minimal environment (`PATH`/`HOME`/`LANG`/`TMPDIR` plus the one credential var), not OpenClaw's full process environment — otherwise a third-party MCP package (most are pulled via `npx`) would inherit unrelated secrets like `GH_TOKEN` for no reason. Found and fixed via `security-review` before this ever touched `valet`.
- Config-driven and extensible: adding a future integration of either shape is one entry in the plugin's own config list, not a code change.
- Fails loudly with two distinct messages — "no credential resolvable" vs. "credential resolved but the real service rejected it" — surfaced through OpenClaw's own status/health output, never a generic/opaque failure.
- Confirmed live: Codex/ACP-bridged sessions don't keep a separate copy of MCP credentials — they translate the same core `mcp.servers.<name>` entry at session start, so fixing the core entry once covers both the main assistant and any Codex-spawned session.

Was previously an abandoned first attempt (`moltron-mcp-secrets`) that used `registerMcpServerConnectionResolver` directly — discarded for the reason above, not reused.

## Ansible/OpenClaw config boundary

Ansible installs OpenClaw itself and supporting tooling only. It must never write to `openclaw.json`, register MCP servers, or touch the secret store — `valet` is treated as a pet, not cattle, and OpenClaw's own `backup`/`restore` (covers config, the secret store, and all other state, but explicitly *not* plugin code) is the intended recovery path for anything inside OpenClaw's own directory, not this repo's Ansible. A plugin's *code* still ships from this repo like any other tool here; getting it onto the box is a manual `openclaw plugins install`, run by hand, not an Ansible task. See [[openclaw-config-ownership]] and [[mcp-secrets-plugin]] memories for the running list of what's box-managed vs. Ansible-managed.

## Dropbox (`ansible/roles/rclone-dropbox`)

A durable, read-write `rclone mount` FUSE mount of the whole Dropbox account at `/home/moltron/dropbox`, for binary project artifacts — see `docs/rclone-dropbox.md` for the full credential setup, flag rationale, operational checks, and rollback. Deliberately separate from the *other* existing Dropbox integration, which is used for backups: separate dedicated Dropbox app, separate Bitwarden secrets, so a leak of one credential set doesn't expose the other. Dropbox OAuth token acquisition is a one-time interactive step (`rclone authorize`, needs a browser) that can't be done headlessly on `valet` — it's a manual prerequisite the human does before the three `dropbox_rclone_*` Bitwarden secrets exist for Ansible to consume; the placeholder UUIDs in `ansible/playbooks/group_vars/all.yaml` need updating once those secrets are created. `valet` is a real KVM/QEMU VM (not a container), so unprivileged FUSE mounts work with no extra `homelab`-side hardening changes needed.

## Open questions carried forward

- ACP-spawned Claude Code / Claude Code Remote Control interop — being tested on `issue-17-acp-remote-control`.
- Permanent name for the assistant/repo (currently "Moltron", explicitly provisional).
- Consequential-action policy (what requires approval vs. runs autonomously) — not yet formalized; current action surface (append a note, log a transaction) doesn't need it yet.
- `dropbox_rclone_client_id`/`dropbox_rclone_client_secret`/`dropbox_rclone_token` in `ansible/playbooks/group_vars/all.yaml` are placeholder UUIDs (issue #35) until the Dropbox app + Bitwarden secrets are created by hand.
- Browser-automation tool is not yet enabled in OpenClaw: `chromium` is installed (`ansible/roles/browser-tools`), but `plugins.allow`/`tools.alsoAllow` in `openclaw.json` still need `"browser"` added by hand on `valet`.

## Local setup

Same as `homelab`'s Ansible prerequisites:

```
uv tool install --with-executables-from ansible-core --with bitwarden-sdk ansible
cd ansible && ansible-galaxy collection install -r requirements.yaml
```

## Conventions

- Out of scope for now (don't build toward these without a new brainstorm first): Fastmail, GitHub PR workflow beyond `moltron-bot` auth, RAG/knowledge-graph work, research-job orchestration, Parcel, Maps, meal planning, Music Assistant, Plex/Jellyfin, an Apple-world bridge, synchronous conversational voice.
- Follow `homelab`'s sanitization conventions for anything captured from a live system: no credentials, MAC addresses, or personal identifying info committed. Internal topology (VLANs, RFC1918 addresses) is fine.
