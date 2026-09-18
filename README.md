# Moltron

Personal assistant workload configuration. The VM itself is provisioned and
hardened in `laforcem/homelab` (Terraform + a minimal Tailscale-client
Ansible role); this repo configures everything that runs on it.

## Prerequisites

Same as `homelab`'s Ansible setup:

```
uv tool install --with-executables-from ansible-core --with bitwarden-sdk ansible
cd ansible && ansible-galaxy collection install -r requirements.yaml
```

## Secrets

Uses its own Bitwarden Secrets Manager project (separate from `homelab`'s) —
a Telegram/actual-mcp/OpenAI secret leaking shouldn't also expose the
Proxmox API token or Tailscale authkey, and vice versa. `ansible/.env`
(gitignored, copy from `ansible/.env.example`) must contain a machine
account access token scoped to *this* project:
```
BW_ACCESS_TOKEN=<bws machine account access token, Moltron project>
BWS_ACCESS_TOKEN=$BW_ACCESS_TOKEN
```

## Usage

```
cd ansible
set -a && source .env && set +a
ansible-playbook playbooks/main.yaml
```

Assumes this repo and `homelab` are checked out as sibling directories (not
required for secrets anymore, but `homelab`'s own Terraform/Ansible still
provision and harden the VM this repo configures). Ansible currently
connects over the LAN (`192.168.10.14`), the same as `homelab`'s own
Ansible connects to `warden` — administering `valet` day to day
happens over Tailscale instead, per the design doc.

## GitHub identity

The `moltron` service user on `valet` has its own GitHub identity
(`moltron-bot`, a plain machine-user account — see issue #2 for why not a
GitHub App) with push access to `laforcem/moltron` and `laforcem/homelab`.
Default `git config user.name`/`user.email` on that user are set to
`moltron-bot`'s identity (a GitHub-issued noreply address, not a real inbox
— both repos are public), since that's the account actually authenticating.
Claude Code is not yet installed on `valet` — when it is, it inherits
this same identity automatically since it runs as the same `moltron` user.

Authenticated via a classic PAT (`public_repo` scope) delivered through
Bitwarden Secrets Manager, exposed to `moltron` as `GH_TOKEN` — both in
`~/.profile` (login shells) and `~/.config/environment.d/` (systemd --user
services, so any future Claude Code unit inherits it too). Not a fine-grained
PAT: those can't write to repos where the token owner is a collaborator
rather than the owner, which ruled that option out here. Not `gh auth
login`: it hard-requires classic-token scopes (`repo`, `read:org`, `gist`)
the bot doesn't need or have.

This is a default identity, not a fixed authorship policy. Override
per-commit depending on how autonomous vs. supervised the work is:

- Fully autonomous agent work: leave the default (`moltron-bot` as author),
  optionally add a `Co-authored-by: <human name> <human email>` trailer.
- Human actively steering: author as the human
  (`git -c user.name=... -c user.email=... commit ...` or `git commit
  --author="..."`) and add `Co-authored-by: moltron-bot <noreply address>`
  instead.

Branch protection on `main` (both repos) requires an approving PR review
before merge and isn't bypassable by `moltron-bot` — only `laforcem` can
merge without a second reviewer, since admin-bypass is enabled and
`moltron-bot` is a non-admin collaborator.
