# Moltron MVP — Design

Working name: **Moltron**. Not a final name — expect this repo, and this
document's title, to be renamed once a better name exists.

## Purpose

A persistent personal assistant that lives on its own VM, reachable day to
day over Telegram, with its own identity and credentials rather than
borrowing the user's own. This document scopes the *first* slice of that
system only. Everything else from the original brainstorm — Fastmail,
GitHub identity, browser automation, RAG/knowledge graph, research
orchestration, Parcel, Maps, music, Plex, Apple integrations, conversational
voice — is deliberately deferred to future, separately-brainstormed
sub-projects.

## Success criteria

1. From Telegram on the user's iPhone, ask the assistant to append
   something to today's Obsidian daily note, and see it land through
   Obsidian Sync reliably.
2. Send a receipt photo over Telegram and have it logged as a categorized,
   split transaction in Actual.

## Repo boundary and governance

Two repos are involved, with a deliberate division of ownership:

- **`laforcem/homelab`** owns the VM's *existence* only: Terraform
  provisioning (VMID, static IP, VLAN placement, disk) and the same
  `common` Ansible role every other host gets (guest agent,
  unattended-upgrades, timezone/NTP, SSH hardening, `ufw`, Tailscale). This
  is identical infrastructure to every other VM in the estate, and keeps
  `homelab`'s claim to be the source of truth for "what's running where"
  (`docs/current-state.md`) intact — the secretary VM gets one line there,
  pointing at this repo for what actually runs on it. This mirrors how the
  `doco-cd` entry in `current-state.md` already points at `homelab`'s own
  `doco-cd/` directory as the thing driving that host's deploys, just with
  the pointer aimed at an external repo instead.
- **This repo (Moltron)** owns everything that makes the box *the
  secretary* rather than a generic Debian host: the dedicated service Unix
  user, OpenClaw install and configuration, `obsidian-headless`, MCP server
  registrations, Telegram bot configuration, and all assistant-specific
  docs/skills/roadmap content as they accumulate. `homelab`'s own
  `AGENTS.md` already states the operating principle this follows:
  "Larger standalone projects live in their own repos."

Rationale for the split: bundling a growing assistant system (memory
tooling, skills, agent instructions, roadmap) into `homelab`'s
one-compose-file-per-service convention would make it disproportionately
large and noisy relative to everything else there. But leaving the VM's
existence untracked by `homelab` would break its stated role as the single
inventory of the physical estate. Splitting at the OS boundary — `homelab`
provisions and hardens the box, this repo configures the workload — keeps
both properties true.

## VM

- Sibling to `terraform/constrainer.tf` in `homelab`: 2 vCPU / 4GB RAM /
  32GB disk, VLAN 10 (`192.168.10.0/24`), cloned from the existing Debian 13
  cloud-init template (VMID 103).
- Sized against live `pve` capacity checked during this brainstorm: 6
  physical cores total (the scarce resource — keep vCPU count
  conservative), 22GB RAM free, 148GB free on `rpool`. 4GB RAM leaves
  headroom to grow later (e.g. if browser automation is added in a future
  phase) without re-provisioning from scratch.
- `common` Ansible role applied identically to every other host: guest
  agent, unattended-upgrades, timezone/NTP, SSH hardening (no password
  auth, no root login), `ufw` deny-by-default with SSH + Tailscale allowed.
- Tailscale is the break-glass/admin path (SSH, OpenClaw Control UI,
  debugging) — not the everyday interface.

## Identity and secrets

- A dedicated, non-`malc` Unix service user on the VM runs OpenClaw. Created
  by this repo's Ansible, not `homelab`'s — it's workload-specific, not
  something every host needs.
- That user has its own credentials, scoped to only what this MVP needs:
  own Telegram bot token (via BotFather), own OpenAI (Codex/ChatGPT OAuth)
  credential, own `actual-mcp` auth token. Pulled from Bitwarden Secrets
  Manager the same way `homelab`'s Terraform and Ansible already do — no
  secrets committed to either repo.
- Explicitly does **not** get: the user's own SSH keys, GitHub identity, or
  credentials for unrelated systems (Proxmox admin, NAS admin, network
  infrastructure). GitHub integration is out of scope for this MVP
  entirely — there is nothing for the assistant to authenticate to yet.

## OpenClaw

- Confirmed via official docs (Context7 `/openclaw/openclaw`) to be a real,
  actively maintained self-hosted assistant gateway supporting Telegram,
  MCP client/server roles, and multi-agent orchestration including ACP
  (Agent Control Protocol) sessions that can drive external coding
  harnesses like Claude Code.
- **Install**: native via Ansible — `npm install -g openclaw@latest
  --allow-scripts=openclaw`, then `openclaw gateway install` and
  `systemctl --user enable --now openclaw-gateway.service` under the
  dedicated service user. (Considered Docker/`doco-cd` — the pattern used
  for most of `homelab`'s services — but chose native install to match how
  Ansible already handles host-level services like Tailscale and
  Doco-CD itself in the `utility-services` role.)
- **Main model**: `openai/gpt-5.6-sol` via ChatGPT/Codex OAuth subscription
  (`plugins.entries.codex.enabled`, `agents.defaults.model`). Chosen over
  Anthropic subscription reuse (`claude setup-token`) because the official
  docs themselves recommend API-key auth for any long-lived gateway host,
  and because third-party sources (lower confidence, unconfirmed against
  official docs) claim Anthropic tightened enforcement against
  subscription-token use outside Claude Code in January 2026 — a live,
  unresolved conflict not worth building the MVP's auth model around.
- **Delegated coding work**: `sessions_spawn` with `runtime: "acp"` and
  `agentId` targeting the Claude ACP adapter, which runs genuine Claude
  Code sessions (via `@openclaw/acpx` + the Claude ACP adapter) and
  supports `resumeSessionId` to continue a session across devices — the
  docs describe this exact pattern ("hand off a session from your laptop
  to your phone"). Whether an ACP-spawned Claude Code session can
  specifically be picked up via Claude Code's own Remote Control feature
  in the Claude app is **unverified** — worth testing once the system is
  built, not assumed going in.
- **Image understanding** (for receipt photos): configured separately via
  `tools.media.image.preferredModel`, decoupled from the main Codex-backed
  agent model, since Codex/ChatGPT OAuth is an agentic coding-focused
  surface, not necessarily the right tool for inline image transcription.

## Telegram

- Long polling (OpenClaw's default transport) — no public webhook, no
  exposed port, nothing added to Caddy.
- Access control: `channels.telegram.dmPolicy: "allowlist"`,
  `allowFrom: ["<user's Telegram user id>"]` — private, single-user only
  for this MVP.

## Obsidian

- The official `obsidian-headless` CLI (released Feb 2026) runs as a true
  no-GUI sync daemon, keeping the vault synced to plain markdown files on
  disk. No Electron process, no Xvfb, no virtual desktop.
- OpenClaw's bundled `obsidian` skill was evaluated and rejected for this
  MVP: it requires a *running* Obsidian Electron app with its CLI bridge
  enabled, which conflicts with the headless-first goal. Instead, OpenClaw
  appends to the daily note via a direct file edit against the
  `obsidian-headless`-synced vault path — the `obsidian` skill's own docs
  call direct file edits "acceptable... when safer or faster" for plain
  markdown vault files.
- Trade-off accepted: this MVP loses Obsidian-aware conveniences (CLI
  search, backlink-safe writes, task management) that the full `obsidian`
  skill would provide. Revisit running Obsidian under a minimal virtual
  display if those become worth the added complexity later.

## Actual

- `actual-mcp` is already deployed on `mrgutsy` and reachable at
  `budget.$DOMAIN/mcp` (SSE/HTTP transport, `MCP_SSE_AUTHORIZATION`
  token-gated). This MVP registers that existing remote instance as an MCP
  server in OpenClaw's config rather than standing up a second instance —
  no new deployment, reuses the existing Bitwarden-managed token.

## Out of scope for this MVP

Fastmail, GitHub identity/PR workflow, browser automation and its own
credential/profile isolation, RAG/entity-resolution/knowledge-graph work,
research-job orchestration, Parcel, Maps/local search, meal
planning/groceries, Music Assistant, Plex/Jellyfin, an Apple-world bridge,
and synchronous conversational voice. Each is a real subsystem in its own
right and deserves its own brainstorm once this foundation exists.

## Open questions carried forward (not blocking this MVP)

- Whether ACP-spawned Claude Code sessions interoperate with Claude Code's
  Remote Control feature in the Claude app — test once built.
- What the assistant/repo's permanent name will be (currently "Moltron",
  explicitly provisional).
- Consequential-action policy (what requires approval vs. runs
  autonomously) is conceptual per the original brainstorm and not
  formalized here — this MVP's action surface (append a note, log one
  transaction) doesn't yet need it decided.
- Relay (relay.md), used to share specific notes with the user's wife, is
  exclusively an Obsidian plugin — it runs inside the real Obsidian
  Electron app and has no standalone CLI/headless client. `obsidian-headless`
  cannot participate in a Relay-shared folder; that's a separate sync
  mechanism from Obsidian Sync entirely. The daily note this MVP targets is
  not Relay-shared, so this doesn't block the MVP, but giving the assistant
  write access to Relay-shared notes later would mean revisiting the
  headless-only decision (e.g. running real Obsidian under Xvfb with the
  Relay plugin installed) — its own design question, not a quick addition.
