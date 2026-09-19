# Fetching live Safeway data

`shop-lookup`'s HTTP client cannot reach `pdpdata` or the search endpoint
directly — Safeway's Incapsula bot mitigation blocks plain HTTP clients
outright (confirmed: curl, `requests`, and TLS-fingerprint-spoofed `curl_cffi`
all blocked, or the connection just hangs for search; only a real,
JS-executing browser gets through). There is no cheap client-side fix for this.

**This is now handled automatically.** `product`/`locate` try plain HTTP
first and transparently fall back to launching a short-lived headless
instance of whatever real Chromium-family browser is already on the host
(`chromium`/`chromium-browser`/`google-chrome[-stable]`/`brave-browser` on
`$PATH`, or `SHOP_LOOKUP_CHROMIUM_PATH` override) when it detects an Incapsula
challenge or a hung connection. See `shop_lookup/browser.py`. No flag needed,
no daemon, no bundled/downloaded second browser — `playwright` is a
dependency of the library, not of a separate service.

## How the fallback works

1. Launch headless Chromium (system browser, via `executable_path`).
2. Navigate to `https://www.safeway.com/` once, to let it solve Incapsula's
   challenge naturally.
3. Wait (up to a few seconds) for the `reese84` cookie to appear before
   firing the real request — see "The `reese84` cookie" below. A fresh
   context that fires the fetch immediately after `goto()` gets a 403 every
   time, regardless of IP or headless/headed mode.
4. From that same page, run the actual `fetch()` via `page.evaluate` — this
   inherits whatever context Incapsula is checking. Confirmed repeatable:
   5/5 calls succeeded across different BPNs from one page load,
   ~300-450ms/call after the initial page load (that initial load, plus
   browser startup, is the real per-invocation cost — a few seconds).
5. Close the browser.

## The `reese84` cookie

Incapsula gates access on a device-fingerprint cookie, `reese84`, set by a JS
challenge that runs after page load and takes real execution time to
complete — it is not set immediately on `goto()` returning. Confirmed live:
a long-lived browser context that had accumulated this cookie over several
real page loads succeeded, while a fresh single-shot context (headless
*and* headed, same IP, same moment) failed identically every time. An
earlier theory that this was IP/session reputation from cumulative request
volume was tested and ruled out — a human's own manual browsing from the
same IP at the same time worked fine, which reputation-based blocking
wouldn't allow.

`browser.py`'s `_launch_and_fetch` now polls for `reese84` (via
`page.wait_for_function`, capped at `_FINGERPRINT_COOKIE_TIMEOUT_MS`) before
firing the real fetch. If the cookie still isn't set in time, it proceeds
anyway — the existing `is_incapsula_challenge()` check on the response
catches a real block and raises `BrowserBlockedError`.

## Manual escape hatch

If you already have a raw response from elsewhere (a browser DevTools
capture, an agent's own browser-tool session, etc.), skip both the HTTP
attempt and the browser fallback entirely:

```bash
echo '<raw pdpdata JSON>' | shop-lookup safeway product --store <store> --from-json -
echo '<raw search JSON>'  | shop-lookup safeway locate  --store <store> --from-json -
```

## Notes

- `guest=true` (not `guest=false`) was used in the one confirmed-working live
  capture that led to this design. `product`'s params still use `guest=false`
  from the original handoff doc — untested whether that matters now that the
  real blocker (browser execution, not the guest flag) is understood.
- Subscription-key handling is unchanged from `AGENTS.md` — dynamic fetch by
  default, `SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY` as an override. The browser
  fallback still needs a valid key (it's sent as a header on the in-page
  `fetch()`, same as the plain HTTP attempt).
- Untested: how long a warm browser context stays valid before Incapsula
  requires re-solving the challenge — moot for the current per-call launch
  design (a fresh page load happens every time anyway), but would matter if
  this ever moves to a persistent-process model.
- A persistent daemon (keep one browser warm across CLI invocations) and
  leaning on OpenClaw's own browser tool were both considered and rejected —
  see `AGENTS.md`'s Shop-lookup section for that history.
