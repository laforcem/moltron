# Fetching live Safeway data (browser tool recipe)

`shop-lookup`'s own HTTP client cannot reach `pdpdata` or the search endpoint
directly — Safeway's Incapsula bot mitigation blocks plain HTTP clients
outright (confirmed: curl, `requests`, and TLS-fingerprint-spoofed `curl_cffi`
all blocked; only a real, JS-executing browser gets through). There is no
cheap client-side fix for this.

**Use OpenClaw's browser tool for the fetch, then pipe the result into
`shop-lookup` for parsing/normalization.**

## Recipe

1. Navigate to a normal Safeway page once (e.g. any product page, or the
   homepage) to let the browser solve Incapsula's challenge naturally. This
   only needs to happen once per browser session/context, not per lookup.
2. From that same page, run a `fetch()` for the actual data you need, e.g.:
   ```js
   fetch("https://www.safeway.com/abs/pub/xapi/product/v2/pdpdata?bpn=960087216&banner=safeway&storeId=<store>&bannerId=1&includeProductRating=true&realTimeReviewRating=true&guest=true&includeOffer=true&pgm=abs", {
     headers: { "ocp-apim-subscription-key": "<current key>" }
   }).then(r => r.json())
   ```
   Executed in-page (e.g. via the browser tool's JS-evaluation capability),
   this inherits whatever context Incapsula is checking. Confirmed
   repeatable: 5/5 calls succeeded across different BPNs from one page load,
   ~300-450ms per call after the initial page load.
3. Pipe the resulting JSON into `shop-lookup` to get the normalized shape
   (location, price, typed errors) instead of hand-parsing the raw response:
   ```bash
   echo '<raw pdpdata JSON>' | shop-lookup safeway product --store <store> --from-json -
   echo '<raw search JSON>'  | shop-lookup safeway locate  --store <store> --from-json -
   ```

## Notes

- `guest=true` (not `guest=false`) was used in the one confirmed-working live
  capture. Untested whether `guest=false` also works now that the real
  blocker (browser execution) is understood, but no reason to deviate from
  what's confirmed.
- Subscription-key handling is unchanged from `AGENTS.md` — dynamic fetch by
  default, `SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY` as an override. `--from-json`
  mode doesn't need a key at all, since `shop-lookup` isn't making the HTTP
  call.
- Untested: how long a warm browser context stays valid before Incapsula
  requires re-solving the challenge. If lookups start failing after a page's
  been open a while, that's the next thing to characterize.
- This recipe is deliberately not automated into a daemon (see
  `docs/shop-lookup-status.md` history) — reusing OpenClaw's own
  already-installed/enabled browser tool was chosen over building and
  operating a second, `shop-lookup`-specific browser stack on `valet`.
