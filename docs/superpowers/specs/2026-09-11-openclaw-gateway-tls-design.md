# OpenClaw Gateway TLS Design

## Problem

The OpenClaw gateway on `secretary` (`192.168.10.105`) is bound to the LAN
(`gateway.bind=lan`) for mobile app pairing, but is reachable only over plain
`http`/`ws://` at its raw IP. This has two consequences:

- No TLS, unlike every other `*.lan.$DOMAIN` / `*.$DOMAIN` destination in the
  homelab (AdGuard, Portainer, Grafana, etc.), all of which terminate TLS via
  Caddy's Porkbun DNS-01 wildcard certs.
- OpenClaw itself downgrades mobile pairing to "limited access" over
  plaintext `ws://`, per issue #20 — full access requires `wss://`.

An AdGuard DNS rewrite for `secretary.laforce.dev → 192.168.10.105` already
exists, pointing a hostname directly at the VM and bypassing Caddy entirely
— this is the root of the "no TLS" problem, not a fix for it.

## Decisions made and rejected alternatives

**Keep OpenClaw native on its own VM; don't containerize it.** secretary was
deliberately given its own VM (not a Docker container on `vm100`/`vm101`) so
that a misbehaving agent's blast radius stays contained to a single,
disposable VM. A container on `vm100` would share that host's kernel and
Docker daemon with AdGuard Home (the LAN's DNS) and Portainer — a materially
worse blast radius for an agentic AI with elevated tool-execution privileges.
This also matches OpenClaw's own documented deployment guidance: every
top-level install path (README, `docs/install/index.md`, the onboarding
wizard) leads with the native `npm install -g openclaw@latest` + daemon
install, and the one place the docs state an explicit preference
(`docs/platforms/chromeos.md`) says to prefer native over Docker.
Tool-execution sandboxing (`agents.defaults.sandbox.backend: docker`) is
orthogonal to this decision — it can run inside secretary's own VM boundary
independent of how the gateway itself is deployed, and is out of scope here.

**Terminate TLS on vm100's existing Caddy, not a new Caddy on secretary.**
vm100 already runs Caddy with a working Porkbun DNS-01 wildcard cert for
`*.lan.{$DOMAIN}`. Standing up a second, independent Caddy instance on
secretary would require a new Porkbun API credential scoped into secretary's
own Bitwarden project, a new ansible role, and — per this repo's own stated
boundary — would reach into network/TLS territory that this repo's CLAUDE.md
explicitly leaves to `homelab` (Terraform, the shared hardening role, and by
extension the Caddy/DNS/TLS layer that goes with the Docker estate). Routing
config for a LAN-facing hostname belongs in `homelab`'s Caddyfile, same as
every other `*.lan.$DOMAIN` route.

**Encrypt the vm100→secretary backend hop; don't leave it plaintext.**
Fronting a service with TLS while proxying to it over plaintext HTTP would
only be TLS in appearance. vm100's Caddyfile already has a precedent for
this exact problem (the Portainer block terminates TLS on a self-signed
backend cert, and Caddy connects with `tls_insecure_skip_verify`). OpenClaw
supports the same shape via `gateway.tls.enabled`, generating its own
self-signed cert when no cert/key path is given (confirmed in OpenClaw's
`2026.6.11` release notes: blank cert/key paths fall back to OpenClaw's
defaults rather than erroring).

**No Tailscale-specific carve-out.** secretary runs no Tailscale client of
its own — `homelab`'s `common` role's `tailscale0` firewall rules are inert
boilerplate applied to every host; the actual Tailscale daemon and subnet
route (`192.168.10.0/24`) are installed only by `utility-services`, scoped to
`constrainer`. Tailscale-connected devices already reach secretary at its
plain LAN IP via that subnet route, resolving `*.lan.laforce.dev` the same
way LAN clients do. So there's exactly one access path to design for, not
two: everyone goes through `openclaw.lan.laforce.dev` → vm100's Caddy →
secretary. Direct access to secretary's gateway port from anywhere other
than vm100 is firewalled off.

## Design

### 1. Hostname & DNS

- New hostname: `openclaw.lan.laforce.dev` (names the exposed service, not
  the host — consistent with this being the gateway specifically, should
  secretary ever front more than one thing).
- AdGuard DNS rewrite: replace the existing `secretary.laforce.dev →
  192.168.10.105` entry with `openclaw.lan.laforce.dev → 192.168.10.100`
  (vm100's IP — clients now resolve to Caddy, not the VM directly). This is
  a manual change in AdGuard's UI (not committed as code in either repo).

### 2. Gateway config (`secretary`, moltron's `ansible/roles/openclaw`)

- `gateway.bind`: unchanged (`lan`) — Caddy still connects over the network.
- `gateway.tls.enabled: true`, cert/key paths left unset so OpenClaw
  generates its own self-signed certificate.
- `gateway.trustedProxies: ["192.168.10.100"]` (vm100's LAN IP) — required
  so OpenClaw attributes the forwarded client IP correctly and doesn't
  reject Caddy's connection as unattributed proxy traffic.

### 3. Caddy config (`vm100`, homelab's `caddy/vm100/conf/Caddyfile`)

New handler block alongside the existing `@adguard`/`@portainer`/etc:

```caddyfile
@openclaw host openclaw.lan.{$DOMAIN}
handle @openclaw {
    reverse_proxy 192.168.10.105:18789 {
        transport http {
            tls
            tls_insecure_skip_verify
        }
    }
}
```

No separate WebSocket configuration is needed — Caddy's `reverse_proxy`
forwards `Upgrade`/`Connection` headers transparently, which is what
resolves issue #20's `wss://` requirement.

### 4. Firewall (`secretary`)

A new `ufw` rule, added via moltron's own ansible (not `homelab`'s shared
`common` role, since this is gateway-specific, not host-baseline):

```
ufw allow from 192.168.10.100 to any port 18789 proto tcp
```

This is the only inbound path to the gateway port; the LAN-wide
default-deny from `homelab`'s `common` role is otherwise unchanged.

## Verification

- `openclaw doctor --json` on secretary after config changes, checked
  structurally (exit code / expected keys) rather than dumped raw, per this
  session's secret-handling convention — the token/cert material it may
  surface should not be printed to a terminal transcript.
- `openclaw qr` reports full (non-limited) access once pairing happens over
  `wss://openclaw.lan.laforce.dev`, rather than today's "limited" plaintext
  warning.
- From a host other than vm100: `curl -k https://192.168.10.105:18789`
  times out or is refused (firewall).
- From both a LAN client and a Tailscale-connected client (via
  `constrainer`'s subnet route): `https://openclaw.lan.laforce.dev` resolves
  and serves the gateway with a valid cert.

## Out of scope

- Containerizing OpenClaw, or any k3s/Docker migration for secretary.
- Tool-execution sandboxing (`agents.defaults.sandbox`) — independent
  decision, doesn't block this work.
- Any change to how `secretary` is provisioned/hardened (that stays
  `homelab`'s `common` role).
