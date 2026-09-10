# Moltron MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note for this plan specifically:** several steps below require live, interactive human action that cannot be scripted or delegated — registering a Telegram bot via @BotFather, completing an OpenAI Codex OAuth browser flow, logging into Obsidian Sync (`ob login`), and creating secrets in the Bitwarden Secrets Manager UI. A subagent cannot do these. Flag each such step to the user and wait for them to complete it and hand back the resulting token/ID before continuing. Given the user's standing instruction to never advance through a multi-step process automatically, treat every task boundary below as a stop-and-confirm point regardless of which execution mode is chosen.

**Goal:** Stand up a dedicated Proxmox VM running OpenClaw as a private Telegram-reachable assistant that can append to today's Obsidian daily note and log a categorized transaction in Actual from a receipt photo.

**Architecture:** Two repos. `laforcem/homelab` (Terraform + a new minimal Ansible role) provisions and hardens the VM and gets it onto Tailscale — no different in kind from any other host in that estate. This repo (Moltron) owns everything above the OS: a dedicated service user, native OpenClaw install, Telegram/MCP/image-model configuration, and the `obsidian-headless` sync daemon.

**Tech Stack:** Terraform (`bpg/proxmox`), Ansible (`community.general`, `bitwarden.secrets`), OpenClaw (native npm install, systemd), `obsidian-headless` (npm install, systemd), Bitwarden Secrets Manager.

## Global Constraints

- VM: 2 vCPU / 4GB RAM / 32GB disk, VLAN 10 (`192.168.10.0/24`), cloned from the existing Debian 13 template (VMID 103) — matches `terraform/constrainer.tf`'s pattern.
- VMID 105, IP `192.168.10.105` (next free slot after `constrainer` at .104).
- Telegram: long polling only, `dmPolicy: "allowlist"`, single user in `allowFrom`.
- Main agent model: `openai/gpt-5.6-sol` via ChatGPT/Codex OAuth (not an Anthropic API key or subscription token).
- Image/vision model: kept separate from the main agent model via `tools.media.image.preferredModel`.
- Obsidian: `obsidian-headless` only — no Electron, no Xvfb, no virtual desktop.
- Actual: reuse the existing `budget.$DOMAIN/mcp` deployment on `mrgutsy` — no new `actual-mcp` instance.
- All secrets (Telegram bot token, OpenAI credentials, image-model API key, `actual-mcp` auth token, Tailscale authkey) come from Bitwarden Secrets Manager — nothing committed to either repo.
- The service user on the VM has no access to the user's own SSH keys, GitHub identity, or unrelated-system credentials.

---

## File structure

**`laforcem/homelab`** (modify):
- `terraform/secretary.tf` — new, sibling to `constrainer.tf`.
- `ansible/inventory/hosts.yaml` — add a `secretary` group.
- `ansible/playbooks/group_vars/secretary.yaml` — new, Tailscale authkey lookup for this group.
- `ansible/roles/secretary-network/tasks/main.yaml` — new, minimal role: Tailscale as a plain client (no `--advertise-routes`, unlike `constrainer`). Does not touch `utility-services`.
- `ansible/playbooks/main.yaml` — add a play targeting `hosts: secretary` with the new role.
- `docs/current-state.md` — add the host row and a workloads entry pointing at this repo.

**Moltron repo** (this repo, create):
- `ansible/ansible.cfg`, `ansible/requirements.yaml`, `ansible/inventory/hosts.yaml` — mirrors `homelab`'s Ansible conventions.
- `ansible/playbooks/group_vars/all.yaml` — Bitwarden secret lookups for this repo's own secrets.
- `ansible/roles/moltron-user/tasks/main.yaml` — creates the dedicated service Unix user.
- `ansible/roles/openclaw/tasks/main.yaml` — installs Node/OpenClaw, runs onboarding, installs the gateway systemd service.
- `ansible/roles/openclaw/templates/openclaw.json.j2` — the channel/model/MCP/media config.
- `ansible/roles/obsidian-headless/tasks/main.yaml` — installs `obsidian-headless`, sets up the sync systemd service.
- `ansible/playbooks/main.yaml` — runs all three roles against the `secretary` host.
- `README.md` — secrets prerequisites and usage, mirrors `homelab/ansible/README.md`.

---

## Task 1: Provision the secretary VM (Terraform, `homelab`)

**Repo:** `laforcem/homelab`

**Files:**
- Create: `terraform/secretary.tf`

**Interfaces:**
- Produces: a running VM at `192.168.10.105` (VMID 105), SSH-reachable as `malc` with the same key `constrainer.tf` uses, for Task 2 onward.

- [ ] **Step 1: Write `terraform/secretary.tf`**

```hcl
resource "proxmox_virtual_environment_vm" "secretary" {
    name = "secretary"
    node_name = "pve0"
    scsi_hardware = "virtio-scsi-single"
    clone { vm_id = proxmox_virtual_environment_vm.template.id }
    cpu { cores = 2 }
    memory { dedicated = 4096 }
    agent {
        enabled = true
        timeout = "10s"
    }
    network_device { bridge = "vmbr0" }
    disk {
        datastore_id = "local-zfs"
        interface = "scsi0"
        size = 32
    }
    initialization {
        datastore_id = "local-zfs"
        ip_config {
            ipv4 {
                address = "192.168.10.105/24"
                gateway = "192.168.10.1"
            }
        }
        user_account {
            username = "malc"
            keys = [trimspace(data.local_file.pubkey.content)]
        }
    }
    operating_system {
        type = "l26"
    }
}
```

- [ ] **Step 2: Plan and review**

```bash
cd terraform
set -a && source .env && set +a
terraform plan
```

Expected: plan shows one resource to add (`proxmox_virtual_environment_vm.secretary`), nothing to change or destroy.

- [ ] **Step 3: Apply — STOP and confirm with the user before running this.** It creates a real VM on the physical Proxmox host.

```bash
terraform apply
```

Expected: apply succeeds; `qm list` on `pve` shows VMID 105 named `secretary`, status `running`.

- [ ] **Step 4: Verify SSH reachability**

```bash
ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new malc@192.168.10.105 'hostname'
```

Expected: prints `secretary`.

- [ ] **Step 5: Commit**

```bash
git add terraform/secretary.tf
git commit -m "terraform: provision secretary VM (VMID 105)"
```

---

## Task 2: Base hardening + Tailscale (Ansible, `homelab`)

**Repo:** `laforcem/homelab`

**Files:**
- Modify: `ansible/inventory/hosts.yaml`
- Create: `ansible/playbooks/group_vars/secretary.yaml`
- Create: `ansible/roles/secretary-network/tasks/main.yaml`
- Modify: `ansible/playbooks/main.yaml`

**Interfaces:**
- Consumes: VM at `192.168.10.105` from Task 1.
- Produces: a hardened host reachable over Tailscale as `secretary`, ready for Task 3 onward (this repo's Ansible targets it by Tailscale hostname or `192.168.10.105`).

- [ ] **Step 1: Add the `secretary` group to inventory**

Edit `ansible/inventory/hosts.yaml`:

```yaml
all:
  vars:
    ansible_user: malc
  children:
    utility:
      hosts:
        constrainer:
          ansible_host: 192.168.10.104
    secretary:
      hosts:
        secretary:
          ansible_host: 192.168.10.105
    k3s:
```

- [ ] **Step 2: Add the Tailscale authkey lookup for this group**

Create `ansible/playbooks/group_vars/secretary.yaml` (reuses the same reusable Tailscale authkey `utility.yaml` already references — it's a network-wide provisioning key, not a personal credential):

```yaml
tailscale_authkey: "{{ lookup('bitwarden.secrets.lookup', '7f852b6a-a703-4bbe-85bb-b4aa01192cb0') }}"
```

- [ ] **Step 3: Write the minimal Tailscale-client role**

Create `ansible/roles/secretary-network/tasks/main.yaml`:

```yaml
- name: Add Tailscale signing key
  ansible.builtin.get_url:
    url: https://pkgs.tailscale.com/stable/debian/trixie.noarmor.gpg
    dest: /usr/share/keyrings/tailscale-archive-keyring.gpg
    mode: 0644

- name: Add Tailscale apt repo
  ansible.builtin.get_url:
    url: https://pkgs.tailscale.com/stable/debian/trixie.tailscale-keyring.list
    dest: /etc/apt/sources.list.d/tailscale.list
    mode: 0644

- name: Install Tailscale
  ansible.builtin.apt:
    name: tailscale
    state: present
    update_cache: true

- name: Resolve Tailscale auth key
  ansible.builtin.set_fact:
    tailscale_authkey_resolved: "{{ tailscale_authkey }}"
  no_log: true

- name: Start Tailscale (plain client, no subnet routing)
  ansible.builtin.command:
    cmd: >-
      tailscale up
      --authkey={{ tailscale_authkey_resolved }}
      --hostname=secretary
```

This deliberately omits `--advertise-routes` — unlike `constrainer`, `secretary` is not a subnet router, just an admin-access endpoint.

- [ ] **Step 4: Wire the new role into the playbook**

Modify `ansible/playbooks/main.yaml`, appending:

```yaml
- name: Configure secretary host
  hosts: secretary
  become: true
  roles:
    - secretary-network
```

- [ ] **Step 5: Run it**

```bash
cd ansible
set -a && source ../terraform/.env && set +a
ansible-playbook playbooks/main.yaml --limit secretary,pve0
```

(`common` runs on `hosts: all` so it applies automatically; `--limit` here scopes to the new host plus the implicit `all` matches — adjust to plain `ansible-playbook playbooks/main.yaml` if `--limit` excludes hosts unexpectedly; verify with `--list-hosts` first if unsure.)

Expected: playbook completes with no failed tasks. `tailscale status` on `secretary` shows it connected under the same tailnet as `constrainer`.

- [ ] **Step 6: Verify Tailscale reachability, then commit**

```bash
ssh secretary 'tailscale status --self'
```

Expected: shows `secretary` online.

```bash
git add ansible/inventory/hosts.yaml ansible/playbooks/group_vars/secretary.yaml \
  ansible/roles/secretary-network/tasks/main.yaml ansible/playbooks/main.yaml
git commit -m "ansible: harden secretary VM, join Tailscale as plain client"
```

---

## Task 3: Record the new host in `docs/current-state.md`

**Repo:** `laforcem/homelab`

**Files:**
- Modify: `docs/current-state.md`

**Interfaces:**
- Consumes: nothing new — this is documentation only.

- [ ] **Step 1: Add a row to the Hosts table**

Add after the `constrainer` row:

```markdown
| `secretary` | VMID 105, personal assistant host — workload config lives in the Moltron repo (not this one) | `192.168.10.105` | Debian 13 |
```

- [ ] **Step 2: Add a one-line Workloads note**

Under the Workloads section, add a short block analogous to the `doco-cd` entry:

```markdown
**secretary** — trusted VLAN 10, admin access via Tailscale only:

| Service | Route |
|---|---|
| OpenClaw (personal assistant) | not proxied — Telegram long polling; config and deploy tooling live in the separate Moltron repo, not this one |
```

- [ ] **Step 3: Commit**

```bash
git add docs/current-state.md
git commit -m "docs: record secretary VM in current-state"
```

---

## Task 4: Moltron repo Ansible scaffolding + dedicated service user

**Repo:** Moltron (this repo)

**Files:**
- Create: `ansible/ansible.cfg`
- Create: `ansible/requirements.yaml`
- Create: `ansible/inventory/hosts.yaml`
- Create: `ansible/playbooks/group_vars/all.yaml`
- Create: `ansible/roles/moltron-user/tasks/main.yaml`
- Create: `ansible/playbooks/main.yaml`
- Create: `README.md`

**Interfaces:**
- Consumes: `secretary` host reachable over Tailscale from Task 2, as `malc` (the only account that exists on it so far).
- Produces: a Unix user (`moltron`) on `secretary` that Tasks 5–7 install and run OpenClaw and `obsidian-headless` as. Later tasks reference this username directly.

- [ ] **Step 1: Ansible scaffolding**

`ansible/ansible.cfg`:

```ini
[defaults]
inventory = inventory/hosts.yaml
roles_path = roles
interpreter_python = auto_silent
```

`ansible/requirements.yaml`:

```yaml
collections:
  - name: community.general
  - name: bitwarden.secrets
```

`ansible/inventory/hosts.yaml`:

```yaml
all:
  vars:
    ansible_user: malc
  hosts:
    secretary:
      ansible_host: secretary
```

(Uses the Tailscale MagicDNS name `secretary` rather than the raw `192.168.10.105`, since this repo's Ansible should only ever reach the host over Tailscale, not the LAN — matching "Tailscale is the maintenance entrance" from the design.)

- [ ] **Step 2: Create the Bitwarden-backed group_vars stub**

`ansible/playbooks/group_vars/all.yaml` — placeholder structure only; real secret IDs get filled in as each later task creates its Bitwarden entry:

```yaml
# Populated incrementally as later tasks create Bitwarden Secrets Manager entries.
# Each lookup below is added by the task that first needs it — see per-task steps.
```

- [ ] **Step 3: Write the service-user role**

`ansible/roles/moltron-user/tasks/main.yaml`:

```yaml
- name: Create dedicated moltron service user
  ansible.builtin.user:
    name: moltron
    shell: /bin/bash
    create_home: true
    system: false

- name: Enable lingering for moltron (systemd --user services survive logout)
  ansible.builtin.command:
    cmd: loginctl enable-linger moltron
    creates: /var/lib/systemd/linger/moltron
```

`create_home: true` gives it `/home/moltron`; `system: false` keeps it a normal user (needed for `loginctl enable-linger` and systemd `--user` units in later tasks). No SSH key is added for this user — it's never logged into directly; `malc` (via Ansible, over Tailscale) is the only way in, matching "no access to the user's own SSH keys" from the design in the other direction: `moltron` doesn't get `malc`'s keys either.

- [ ] **Step 4: Wire up the playbook**

`ansible/playbooks/main.yaml`:

```yaml
- name: Configure Moltron secretary workload
  hosts: secretary
  become: true
  roles:
    - moltron-user
```

- [ ] **Step 5: Write the README**

`README.md`:

```markdown
# Moltron

Personal assistant workload configuration. Provisions and hardens the VM
itself in `laforcem/homelab`; this repo configures everything that runs on
it.

## Prerequisites

Same as `homelab`'s Ansible setup:

\`\`\`
uv tool install --with-executables-from ansible-core --with bitwarden-sdk ansible
cd ansible && ansible-galaxy collection install -r requirements.yaml
\`\`\`

## Secrets

Reuses `homelab`'s `terraform/.env` (gitignored, not part of this repo) for
the Bitwarden Secrets Manager access token:

\`\`\`
cd ansible
set -a && source ../homelab/terraform/.env && set +a
ansible-playbook playbooks/main.yaml
\`\`\`

## Usage

\`\`\`
cd ansible
set -a && source ../homelab/terraform/.env && set +a
ansible-playbook playbooks/main.yaml
\`\`\`
```

- [ ] **Step 6: Run it**

```bash
cd ansible
set -a && source ../homelab/terraform/.env && set +a
ansible-playbook playbooks/main.yaml
```

Expected: no failed tasks.

- [ ] **Step 7: Verify, then commit**

```bash
ssh secretary 'id moltron && loginctl show-user moltron -p Linger'
```

Expected: `moltron` user exists; `Linger=yes`.

```bash
git add ansible/ README.md
git commit -m "ansible: scaffold Moltron repo, create dedicated service user"
```

---

## Task 5: Install OpenClaw and complete Codex OAuth onboarding

**Repo:** Moltron (this repo)

**Files:**
- Create: `ansible/roles/openclaw/tasks/main.yaml`
- Modify: `ansible/playbooks/main.yaml`

**Interfaces:**
- Consumes: `moltron` user from Task 4.
- Produces: a running `openclaw-gateway` systemd `--user` service under `moltron`, authenticated against a ChatGPT/Codex subscription, listening for onboarding continuation over SSH. Task 6/7/8 all write into `~moltron/.openclaw/openclaw.json`, which this task's onboarding step creates.

- [ ] **Step 1: Write the install role**

`ansible/roles/openclaw/tasks/main.yaml`:

```yaml
- name: Install Node.js 22.x (nodesource)
  ansible.builtin.shell: |
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  args:
    creates: /etc/apt/sources.list.d/nodesource.list

- name: Install nodejs
  ansible.builtin.apt:
    name: nodejs
    state: present
    update_cache: true

- name: Install OpenClaw globally (as moltron)
  become: true
  become_user: moltron
  ansible.builtin.command:
    cmd: npm install -g openclaw@latest --allow-scripts=openclaw --prefix ~moltron/.npm-global
    creates: /home/moltron/.npm-global/bin/openclaw

- name: Add npm-global bin to moltron's PATH
  become: true
  become_user: moltron
  ansible.builtin.lineinfile:
    path: /home/moltron/.bashrc
    line: 'export PATH="$HOME/.npm-global/bin:$PATH"'
    create: true
```

- [ ] **Step 2: Wire it into the playbook**

Modify `ansible/playbooks/main.yaml`, adding `openclaw` to the `secretary` play's role list (after `moltron-user`).

- [ ] **Step 3: Run it**

```bash
ansible-playbook playbooks/main.yaml
```

Expected: no failed tasks; `ssh secretary 'sudo -u moltron /home/moltron/.npm-global/bin/openclaw --version'` prints a version string.

- [ ] **Step 4: STOP — manual interactive onboarding.** This cannot be scripted: Codex OAuth is a browser flow that prints a URL and expects a pasted `code#state` back into the terminal. Tell the user to run this themselves and report back once done:

```bash
ssh secretary
sudo -u moltron -i
export PATH="$HOME/.npm-global/bin:$PATH"
openclaw onboard --install-daemon
# Choose: OpenAI Code subscription (OAuth). Open the printed URL on any
# device, authorize, and paste the resulting code#state back into this
# prompt when asked.
```

Expected once complete: `~moltron/.openclaw/openclaw.json` exists with `agents.defaults.model` set to `openai/gpt-5.6-sol`, and `openclaw gateway status` (run as `moltron`) reports the daemon running.

- [ ] **Step 5: Verify the systemd service, then commit**

```bash
ssh secretary 'sudo -u moltron systemctl --user status openclaw-gateway.service'
```

Expected: `active (running)`.

```bash
git add ansible/roles/openclaw/tasks/main.yaml ansible/playbooks/main.yaml
git commit -m "ansible: install OpenClaw natively, onboard Codex OAuth"
```

---

## Task 6: Configure the Telegram channel

**Repo:** Moltron (this repo)

**Files:**
- Create: `ansible/roles/openclaw/templates/openclaw.json.j2` (Telegram section only for this task — other tasks add to it)
- Modify: `ansible/roles/openclaw/tasks/main.yaml`
- Modify: `ansible/playbooks/group_vars/all.yaml`

**Interfaces:**
- Consumes: `openclaw.json` created by Task 5's onboarding.
- Produces: a Telegram channel the user can message privately. Later tasks (7, 8) extend the same config file's `mcp.servers` and `tools.media` sections.

- [ ] **Step 1: STOP — manual bot creation.** Tell the user to do this themselves in the Telegram app and report back the bot token and their own numeric Telegram user ID:

1. Message `@BotFather`, send `/newbot`, follow the prompts, copy the resulting bot token.
2. Message `@userinfobot` (or similar) to get your own numeric Telegram user ID.

- [ ] **Step 2: Store the bot token in Bitwarden Secrets Manager**

Tell the user to create a new secret in the same Bitwarden Secrets Manager project `homelab`'s Terraform uses, named e.g. `moltron-telegram-bot-token`, value = the bot token from Step 1. Copy its secret ID.

- [ ] **Step 3: Add the lookup to group_vars**

Append to `ansible/playbooks/group_vars/all.yaml`:

```yaml
telegram_bot_token: "{{ lookup('bitwarden.secrets.lookup', '<secret-id-from-step-2>') }}"
telegram_allowed_user_id: "<numeric-telegram-user-id-from-step-1>"
```

- [ ] **Step 4: Configure the channel via the CLI (idempotent, safe to re-run)**

Add to `ansible/roles/openclaw/tasks/main.yaml`:

```yaml
- name: Configure Telegram channel
  become: true
  become_user: moltron
  environment:
    PATH: "/home/moltron/.npm-global/bin:{{ ansible_env.PATH }}"
  ansible.builtin.command:
    cmd: "{{ item }}"
  loop:
    - >-
      openclaw config set channels.telegram.botToken "{{ telegram_bot_token }}"
    - >-
      openclaw config set channels.telegram.enabled true
    - >-
      openclaw config set channels.telegram.dmPolicy "allowlist"
    - >-
      openclaw config set channels.telegram.allowFrom '["{{ telegram_allowed_user_id }}"]'
  no_log: true
  notify: Restart openclaw gateway
```

- [ ] **Step 5: Add the restart handler**

Create `ansible/roles/openclaw/handlers/main.yaml`:

```yaml
- name: Restart openclaw gateway
  become: true
  become_user: moltron
  ansible.builtin.systemd:
    name: openclaw-gateway.service
    scope: user
    state: restarted
```

- [ ] **Step 6: Run it**

```bash
ansible-playbook playbooks/main.yaml
```

Expected: no failed tasks; gateway restarts.

- [ ] **Step 7: End-to-end verify**

Send `/start` to the bot from the allowed Telegram account. Expected: the bot completes pairing and responds. Send a message from a *different* Telegram account (or ask the user to confirm they haven't). Expected: no response — allowlist rejects it.

- [ ] **Step 8: Commit**

```bash
git add ansible/roles/openclaw/tasks/main.yaml ansible/roles/openclaw/handlers/main.yaml \
  ansible/playbooks/group_vars/all.yaml
git commit -m "ansible: configure Telegram channel with single-user allowlist"
```

---

## Task 7: Register the existing `actual-mcp` remote server

**Repo:** Moltron (this repo)

**Files:**
- Modify: `ansible/roles/openclaw/tasks/main.yaml`
- Modify: `ansible/playbooks/group_vars/all.yaml`

**Interfaces:**
- Consumes: the already-deployed `budget.$DOMAIN/mcp` endpoint and its existing `MCP_SSE_AUTHORIZATION` token (from `homelab/actual/compose.yaml` / `homelab/actual/.env`, not this repo).
- Produces: an `actual` entry in `mcp.servers` that Task 9's end-to-end test exercises.

- [ ] **Step 1: Retrieve the existing token's Bitwarden secret ID**

Tell the user to look up the Bitwarden Secrets Manager entry already backing `MCP_SSE_AUTHORIZATION` in `homelab/actual/`'s deploy secrets, and confirm its secret ID (do not create a new one — this reuses the existing token per the design).

- [ ] **Step 2: Add the lookup**

Append to `ansible/playbooks/group_vars/all.yaml`:

```yaml
actual_mcp_token: "{{ lookup('bitwarden.secrets.lookup', '<existing-secret-id-from-step-1>') }}"
```

- [ ] **Step 3: Register the MCP server**

Add to `ansible/roles/openclaw/tasks/main.yaml`:

```yaml
- name: Register actual-mcp remote server
  become: true
  become_user: moltron
  environment:
    PATH: "/home/moltron/.npm-global/bin:{{ ansible_env.PATH }}"
  ansible.builtin.command:
    cmd: >-
      openclaw config set mcp.servers.actual.url
      "https://budget.{{ domain }}/mcp"
  vars:
    domain: "{{ lookup('env', 'DOMAIN') | default('example.com', true) }}"
  no_log: false

- name: Set actual-mcp transport and auth header
  become: true
  become_user: moltron
  environment:
    PATH: "/home/moltron/.npm-global/bin:{{ ansible_env.PATH }}"
  ansible.builtin.command:
    cmd: "{{ item }}"
  loop:
    - 'openclaw config set mcp.servers.actual.transport "sse"'
    - >-
      openclaw config set mcp.servers.actual.headers
      '{"Authorization": "Bearer {{ actual_mcp_token }}"}'
  no_log: true
  notify: Restart openclaw gateway
```

(The real domain value should be sourced the same way `homelab`'s own templated routes are — substitute the actual `$DOMAIN` value used elsewhere in that repo rather than the `example.com` fallback shown here.)

- [ ] **Step 4: Run and verify**

```bash
ansible-playbook playbooks/main.yaml
ssh secretary "sudo -u moltron bash -c 'export PATH=\$HOME/.npm-global/bin:\$PATH && openclaw mcp doctor --probe'"
```

Expected: `actual` server reports reachable/healthy.

- [ ] **Step 5: Commit**

```bash
git add ansible/roles/openclaw/tasks/main.yaml ansible/playbooks/group_vars/all.yaml
git commit -m "ansible: register existing actual-mcp remote server"
```

---

## Task 8: Install and configure `obsidian-headless`

**Repo:** Moltron (this repo)

**Files:**
- Create: `ansible/roles/obsidian-headless/tasks/main.yaml`
- Modify: `ansible/playbooks/main.yaml`

**Interfaces:**
- Consumes: `moltron` user from Task 4.
- Produces: a synced vault at `/home/moltron/Obsidian/<vault-name>` on `secretary`, kept live by a systemd `--user` service. Task 9's end-to-end test appends to the daily note inside this path.

- [ ] **Step 1: Write the install role**

`ansible/roles/obsidian-headless/tasks/main.yaml`:

```yaml
- name: Install obsidian-headless globally (as moltron)
  become: true
  become_user: moltron
  ansible.builtin.command:
    cmd: npm install -g obsidian-headless --prefix ~moltron/.npm-global
    creates: /home/moltron/.npm-global/bin/ob

- name: Create Obsidian sync systemd unit directory
  become: true
  become_user: moltron
  ansible.builtin.file:
    path: /home/moltron/.config/systemd/user
    state: directory
    mode: "0755"

- name: Install Obsidian sync systemd service
  become: true
  become_user: moltron
  ansible.builtin.copy:
    dest: /home/moltron/.config/systemd/user/obsidian-sync.service
    mode: "0644"
    content: |
      [Unit]
      Description=Obsidian headless sync (continuous)
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=simple
      WorkingDirectory=/home/moltron/Obsidian
      Environment=PATH=/home/moltron/.npm-global/bin:/usr/bin:/bin
      ExecStart=/home/moltron/.npm-global/bin/ob sync --continuous
      Restart=on-failure
      RestartSec=10
      TimeoutStartSec=30

      [Install]
      WantedBy=default.target
  notify: Reload moltron systemd user daemon
```

- [ ] **Step 2: Add the reload handler**

Add to `ansible/roles/obsidian-headless` — create `ansible/roles/obsidian-headless/handlers/main.yaml`:

```yaml
- name: Reload moltron systemd user daemon
  become: true
  become_user: moltron
  ansible.builtin.systemd:
    daemon_reload: true
    scope: user
```

- [ ] **Step 3: Wire it into the playbook**

Add `obsidian-headless` to the `secretary` play's role list in `ansible/playbooks/main.yaml`.

- [ ] **Step 4: Run it**

```bash
ansible-playbook playbooks/main.yaml
```

Expected: no failed tasks; `ob` binary present, systemd unit installed but not yet started (sync isn't configured yet).

- [ ] **Step 5: STOP — manual interactive login and vault setup.** `ob login` is an interactive Obsidian Sync account login that cannot be scripted. Tell the user to run this themselves and report back:

```bash
ssh secretary
sudo -u moltron -i
export PATH="$HOME/.npm-global/bin:$PATH"
ob login
mkdir -p ~/Obsidian
cd ~/Obsidian
ob sync-list-remote
ob sync-setup --vault "<their actual vault name from the list above>"
ob sync-status
```

Expected: `ob sync-status` reports the vault is configured and synced.

- [ ] **Step 6: Start and verify the continuous sync service**

```bash
ssh secretary "sudo -u moltron bash -c 'systemctl --user daemon-reload && systemctl --user enable --now obsidian-sync.service'"
ssh secretary "sudo loginctl enable-linger moltron"
ssh secretary "sudo -u moltron systemctl --user status obsidian-sync.service"
```

Expected: `active (running)`.

- [ ] **Step 7: Confirm a real file exists**

```bash
ssh secretary "find /home/moltron/Obsidian -iname '*.md' | head -5"
```

Expected: prints at least one markdown file from the real vault, confirming sync pulled actual content down.

- [ ] **Step 8: Commit**

```bash
git add ansible/roles/obsidian-headless/ ansible/playbooks/main.yaml
git commit -m "ansible: install and configure obsidian-headless sync"
```

---

## Task 9: Configure the image-vision model and end-to-end test both success criteria

**Repo:** Moltron (this repo)

**Files:**
- Modify: `ansible/roles/openclaw/tasks/main.yaml`
- Modify: `ansible/playbooks/group_vars/all.yaml`

**Interfaces:**
- Consumes: everything from Tasks 5–8.
- Produces: nothing further — this is the MVP's final task, validating both success criteria from the spec.

- [ ] **Step 1: Create a scoped OpenAI API key for image understanding**

Tell the user to create a new, minimal-scope OpenAI API key (pay-as-you-go, separate from the Codex OAuth subscription used for the main agent model — Codex OAuth is an agentic coding surface, not meant for inline image transcription) and store it in Bitwarden Secrets Manager as e.g. `moltron-openai-vision-key`. Copy its secret ID.

- [ ] **Step 2: Add the lookup**

Append to `ansible/playbooks/group_vars/all.yaml`:

```yaml
openai_vision_api_key: "{{ lookup('bitwarden.secrets.lookup', '<secret-id-from-step-1>') }}"
```

- [ ] **Step 3: Configure the media/image model**

Add to `ansible/roles/openclaw/tasks/main.yaml`:

```yaml
- name: Set OpenAI API key for image understanding
  become: true
  become_user: moltron
  environment:
    PATH: "/home/moltron/.npm-global/bin:{{ ansible_env.PATH }}"
  ansible.builtin.command:
    cmd: >-
      openclaw config set providers.openai.apiKey "{{ openai_vision_api_key }}"
  no_log: true

- name: Configure image media understanding
  become: true
  become_user: moltron
  environment:
    PATH: "/home/moltron/.npm-global/bin:{{ ansible_env.PATH }}"
  ansible.builtin.command:
    cmd: "{{ item }}"
  loop:
    - 'openclaw config set tools.media.image.enabled true'
    - 'openclaw config set tools.media.image.preferredModel "openai/gpt-4o-mini"'
  notify: Restart openclaw gateway
```

- [ ] **Step 4: Run it**

```bash
ansible-playbook playbooks/main.yaml
```

Expected: no failed tasks; gateway restarts.

- [ ] **Step 5: Test success criterion 1 — Obsidian daily note append**

From the allowed Telegram account, send: *"Add 'testing Moltron end to end' to today's daily note."*

Verify on the VM:

```bash
ssh secretary "sudo -u moltron find /home/moltron/Obsidian -iname '*$(date +%Y-%m-%d)*.md' -exec grep -l 'testing Moltron end to end' {} \;"
```

Expected: the command finds and prints the daily note's path, confirming the line landed. Also verify from the Obsidian app on another device (after it syncs) that the line appears.

- [ ] **Step 6: Test success criterion 2 — receipt photo to Actual transaction**

From the allowed Telegram account, send a real receipt photo with the caption: *"Log this transaction."*

Expected: the assistant responds confirming a transaction was created; verify directly in Actual (web UI or via `actual-mcp`) that a new transaction exists with a plausible payee/amount/date matching the receipt.

- [ ] **Step 7: Commit**

```bash
git add ansible/roles/openclaw/tasks/main.yaml ansible/playbooks/group_vars/all.yaml
git commit -m "ansible: configure image-vision model; MVP end-to-end verified"
```

---

## Self-review notes

- **Spec coverage**: both success criteria are explicitly tested in Task 9. Repo boundary (Task 1–3 vs 4–9), identity/secrets posture (dedicated user, Bitwarden throughout, no shared credentials), Telegram allowlist, Codex OAuth model choice, `obsidian-headless`-only approach, and actual-mcp reuse are each their own task.
- **Placeholder scan**: the only bracketed values left (`<secret-id-from-step-N>`, `<their actual vault name>`, `$DOMAIN`) name real external IDs/values that don't exist until a prior manual step creates them — the same pattern `homelab`'s own committed Terraform/Ansible already uses for Bitwarden secret IDs. These aren't unresolved design decisions.
- **Type/name consistency**: `moltron` (service user), `secretary` (hostname/VM name), `192.168.10.105` (IP), `openclaw-gateway.service` / `obsidian-sync.service` (unit names), and `mcp.servers.actual` (MCP entry name) are used consistently from the task that introduces them through to Task 9.
