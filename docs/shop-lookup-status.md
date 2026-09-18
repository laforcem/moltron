# shop-lookup status (2026-09-18)

Working notes for picking this back up — not a design doc (see `AGENTS.md`'s
`## Shop-lookup` section for the settled design decisions and non-goals).

## Branch

`worktree-shop-lookup-cli`, pushed to `origin`. No PR yet — deliberately: the
plan from the start was one PR covering the complete Safeway flow (product
lookup + search/`locate`), assembled jointly with a second, Windows-native
Claude Code session ("Authorized" in `ListAgents`) that's been doing live
browser-based discovery against safeway.com.

Commits so far:
- `37e5f94` — Phase 1 CLI: `shop-lookup safeway product --store --bpn`, full
  module breakdown per the approved plan (cache, retry/backoff, typed errors,
  normalization), 27 tests, no live network calls in the suite.
- `9402bb6` — `SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY` env-var override (takes
  priority over the dynamic fetch/cache) plus a distinct `subscription_key_invalid`
  error (exit 5) on 401/403. Deliberately did **not** build automatic
  key-rotation recovery — see "Deferred" below.

## What's working

`shop-lookup safeway product --store <alias-or-id> --bpn <bpn>` against the
confirmed `pdpdata` endpoint. Tested with mocked HTTP; live end-to-end run
against the real API is blocked on the subscription-key issue below.

## What's not done yet

- **`locate <query>` / free-text search command**: "Authorized" found the
  real endpoint (`GET https://www.safeway.com/abs/pub/xapi/pgmsearch/v1/search/products`,
  anonymous, no cookies/`hhid`, results carry location fields directly under
  `primaryProducts.response.docs[]` — full param list and two decoy
  endpoints to avoid are in that session's message history). Not
  implemented — this is the main remaining piece before a PR.
- **Subscription-key discovery**: the dynamic-fetch placeholder in
  `subscription_key.py` doesn't actually work (confirmed by hand) — the real
  key lives inside a content-hashed Next.js JS chunk referenced from the
  homepage, not the plain HTML, and "Authorized"'s investigation found
  multiple misleadingly-named env branches where the obviously-right one
  wasn't the live one, with no known rotation cadence. Decided **not** to
  build automated discovery/candidate-validation for this (see `AGENTS.md`
  "Deliberately not built") — it's an investigative task suited to an agent
  with browser tooling, not stable-shaped enough for hardcoded parsing, and
  no actual rotation has been observed yet. Today, a working key has to be
  found by hand and set via `SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY`.
- **Price comparison**: explicit future phase, not started.
- **Ansible role / deployment to `valet`**: explicit future phase, not started.
- **CI**: not started.

## New cross-cutting blocker surfaced during this work: secrets management

Not specific to shop-lookup — this came up because the subscription-key
question forced a real answer to "how would a credential actually get from
'a human found it in a browser' to 'a process running as the `moltron` user
can use it,'" and the honest answer today is: an env var, by hand, or
eventually via Bitwarden Secrets Manager → the `moltron` systemd `--user`
unit's environment file — the same mechanism already used for the Telegram
bot token etc.

Along the way, corrected a wrong claim about OpenClaw's own `SecretRef`
system (see conversation): fact-checked against
`docs/reference/secretref-credential-surface.md` in `openclaw/openclaw`
directly. Findings:
- Core `mcp.servers.<name>.env`/`.headers` is confirmed **not** SecretRef-eligible
  (matches [issue #32](https://github.com/laforcem/moltron/issues/32) —
  this is why `moltron-mcp-secrets` exists, see [[mcp-secrets-plugin]]).
- The full supported-target list is entirely `openclaw.json` config paths
  for specific named subsystems (channels, model providers, a fixed set of
  named plugins, gateway auth, TTS/talk, skills, auth profiles) — there is
  **no generic mechanism at all** for injecting a secret into an arbitrary
  `exec` tool's environment, for any tool, not just MCP servers. So
  OpenClaw's Secret Manager was never going to help shop-lookup regardless
  of the MCP-specific bug.

**laforcem's stated position** (2026-09-18): not urgent from a threat-model
standpoint — `valet` sits on the most trusted network — but this is now the
umpteenth workload that's effectively gated behind "just put it in plain
text on disk, mostly-securely." Wants a proper answer eventually: a single
pane of glass across all the credentials scattered across moltron/OpenClaw's
various integrations (Telegram, OpenAI, actual-mcp, now shop-lookup's
subscription key, whatever comes next) to see/revoke/rotate any of them,
given how much a Jarvis-style agent with this much access can actually do.
This is **not scoped or designed yet** — flagged here as its own future
workstream/brainstorm, not something to fold into shop-lookup's PR.

## To resume

1. Check in with "Authorized" (`ListAgents`) for anything further on the
   search endpoint or subscription-key discovery.
2. Implement `safeway/search.py` + `locate` CLI subcommand against the
   confirmed search endpoint.
3. Decide whether the secrets-management workstream happens before or
   independent of this PR (currently leaning independent — shop-lookup's
   local-dev env-var override is good enough to keep building against).
4. Assemble the single PR once `locate` is in.
