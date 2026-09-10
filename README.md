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

Reuses `homelab`'s `terraform/.env` (gitignored, not part of this repo) for
the Bitwarden Secrets Manager access token.

## Usage

```
cd ansible
set -a && source ../homelab/terraform/.env && set +a
ansible-playbook playbooks/main.yaml
```

Assumes this repo and `homelab` are checked out as sibling directories. Ansible
currently connects over the LAN (`192.168.10.105`), the same as `homelab`'s
own Ansible connects to `constrainer` — administering `secretary` day to day
happens over Tailscale instead, per the design doc.
