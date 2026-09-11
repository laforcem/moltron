# Agent Guidelines for Moltron

Start-of-session orientation. **Update this file as tasks progress and important context surfaces** — new hosts, credentials boundaries, model choices, open questions resolved or newly discovered. This file drifts out of date fast if only read, never written; keep it current in the same change that changes the thing it describes. Durable rules that must hold deep into a session belong in hooks or CI, not here — a file read once at the top can't be trusted to keep enforcing anything on its own.

## What this is

Assistant workload configuration for **Moltron** — working name, expect this repo to be renamed once a better one exists. A persistent personal OpenClaw assistant reachable over Telegram, with its own identity and credentials rather than borrowing the user's own.

## Repo boundary with `homelab`

Deliberate split:

- **`laforcem/homelab`** owns the VM's *existence* only — Terraform provisioning and the same `common` Ansible role every other host gets (guest agent, unattended-upgrades, SSH hardening, `ufw`, Tailscale). `homelab`'s `docs/current-state.md` gets one line pointing here.
- **This repo** owns everything that makes the box *the secretary* rather than a generic Debian host: the dedicated service user, OpenClaw install/config, `obsidian-headless`, MCP server registrations, Telegram bot config, and all assistant-specific docs/skills as they accumulate.

Sibling checkout assumed: this repo and `homelab` are expected side by side (see README) even though it's no longer required for secrets.

## Host

- **secretary** (`192.168.10.105`, VLAN 10) — the only host this repo configures. Provisioned/hardened by `homelab` (mirrors `terraform/constrainer.tf`: 2 vCPU / 4GB RAM / 32GB disk, Debian 13 cloud-init template VMID 103). Ansible in this repo connects over the LAN address directly; day-to-day admin happens over Tailscale instead (the break-glass path — SSH, OpenClaw Control UI, debugging — not the everyday interface).
- A dedicated, non-`malc` Unix service user (`moltron`) runs OpenClaw on that host, created by this repo's Ansible (workload-specific, not something `homelab`'s `common` role provides).

## Secrets

Own Bitwarden Secrets Manager project, separate from `homelab`'s — a Telegram/actual-mcp/OpenAI secret leaking here shouldn't expose the Proxmox API token or Tailscale authkey, and vice versa. `ansible/.env` (gitignored, copy from `ansible/.env.example`) holds a machine-account access token scoped to *this* project only. See README for the exact env var names.

The `moltron` service user's credentials are scoped to only what the current MVP needs (own Telegram bot token, own OpenAI/Codex OAuth credential, own `actual-mcp` token) — explicitly *not* the user's SSH keys, GitHub identity, or credentials for unrelated systems (Proxmox, NAS, network infra).

## GitHub identity (`moltron-bot`)

Full details in README — don't duplicate here, but the short version: `moltron-bot` is a plain machine-user account (not a GitHub App — see issue #2) with push access to both `laforcem/moltron` and `laforcem/homelab`, authenticated via classic PAT (`GH_TOKEN`, not `gh auth login`). Default identity on the `moltron` Unix user, but override per-commit based on autonomy level:

- Fully autonomous agent work: leave `moltron-bot` as author, optionally add a human `Co-authored-by:` trailer.
- Human actively steering: author as the human, add `Co-authored-by: moltron-bot <noreply address>` instead.

`main` branch protection (both repos) requires an approving PR review; `moltron-bot` can't bypass it — only `laforcem` can merge without a second reviewer.

## OpenClaw

- Installed natively via Ansible (`npm install -g openclaw@latest`, then `openclaw gateway install` + a systemd `--user` unit) — not Docker/`doco-cd`, to match how `homelab`'s Ansible already handles host-level services like Tailscale.
- Image understanding (receipt photos) is configured as a separate model from the main agent model, decoupled via `tools.media.image.preferredModel`.
- Delegated coding work goes through `sessions_spawn` with `runtime: "acp"` targeting the Claude ACP adapter (genuine Claude Code sessions, `resumeSessionId` for cross-device handoff). Whether an ACP-spawned session interoperates with Claude Code's own Remote Control feature is **unverified** — active work on this lives on the `issue-17-acp-remote-control` branch/worktree.
- Model choices (main agent model, image model, embedding backend for memory search) are live config, not fixed architecture — the running OpenClaw config on `secretary` is the source of truth, not this file or even `ansible/roles/openclaw` (not everything is Ansible-managed).

## Obsidian

`obsidian-headless` (no Electron, no Xvfb) keeps the vault synced to plain markdown on disk; OpenClaw appends to the daily note via direct file edits against that synced path rather than the bundled `obsidian` skill, which requires a running Obsidian GUI. Trade-off: no CLI search/backlink-safe writes/task management from the `obsidian` skill. **Relay** (used to share notes with the user's wife) only works inside real Obsidian — `obsidian-headless` cannot participate in a Relay-shared folder; giving the assistant access to Relay-shared notes later means revisiting this decision (e.g. real Obsidian under Xvfb).

## Actual

Registers the existing remote `actual-mcp` instance already deployed on `mrgutsy` (`budget.$DOMAIN/mcp`) as an MCP server — no second instance stood up here.

## Open questions carried forward

- ACP-spawned Claude Code / Claude Code Remote Control interop — being tested on `issue-17-acp-remote-control`.
- Permanent name for the assistant/repo (currently "Moltron", explicitly provisional).
- Consequential-action policy (what requires approval vs. runs autonomously) — not yet formalized; current action surface (append a note, log a transaction) doesn't need it yet.

## Local setup

Same as `homelab`'s Ansible prerequisites:

```
uv tool install --with-executables-from ansible-core --with bitwarden-sdk ansible
cd ansible && ansible-galaxy collection install -r requirements.yaml
```

## Conventions

- Out of scope for the current MVP (don't build toward these without a new brainstorm first): Fastmail, GitHub PR workflow beyond `moltron-bot` auth, browser automation, RAG/knowledge-graph work, research-job orchestration, Parcel, Maps, meal planning, Music Assistant, Plex/Jellyfin, an Apple-world bridge, synchronous conversational voice.
- Follow `homelab`'s sanitization conventions for anything captured from a live system: no credentials, MAC addresses, or personal identifying info committed. Internal topology (VLANs, RFC1918 addresses) is fine.
