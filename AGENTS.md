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

Registers the existing remote `actual-mcp` instance already deployed on `mrgutsy` (`budget.$DOMAIN/mcp`) as an MCP server — no second instance stood up here.

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
