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
connects over the LAN (`192.168.10.105`), the same as `homelab`'s own
Ansible connects to `constrainer` — administering `secretary` day to day
happens over Tailscale instead, per the design doc.
