# shop-lookup

Local lookup of a grocery product's in-store physical location, price, and fuzzy name search. Safeway only, for now — see `AGENTS.md` at the repo root for the design rationale and scope decisions.

## Usage

```
uv run shop-lookup safeway stores --zip 60601
uv run shop-lookup safeway product --store 1000 --bpn 960087216
uv run shop-lookup safeway locate "apple" --store 1000
```

`stores --zip` finds nearby store numbers (no local registry -- always a live lookup against Safeway's own store locator). `--store` everywhere else is that raw Safeway store number, nothing else. `--bpn` is a specific Safeway product id. Add `--no-cache` to `product` to bypass the local product-lookup cache. `--limit` on `locate` caps result count (default 10).

Output is a single JSON object on stdout. A partial result (e.g. `location.label: null`) is still exit code 0 — check the body, not just the exit code, for whether a physical location was actually found.

Safeway's bot mitigation blocks plain HTTP outright for `pdpdata`/search. `product`/`locate` handle this automatically: on a detected challenge (or a hung connection), they fall back to fetching via a real local Chromium (found on `$PATH` — `chromium`, `chromium-browser`, `google-chrome[-stable]`, or `brave-browser`; override with `SHOP_LOOKUP_CHROMIUM_PATH`). No bundled/downloaded browser, no daemon — a plain, short-lived headless launch per call that needs it. See `docs/shop-lookup-live-fetch-recipe.md` for background.

Both commands also accept `--from-json <path|->` to normalize a raw response you already have from elsewhere, skipping the network path (and the browser fallback) entirely.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | internal/unexpected failure |
| 2 | not_found (unknown store or product/bpn) |
| 3 | rate_limited |
| 4 | api_changed / schema_drift |
| 5 | subscription_key_invalid (401/403 -- key needs manual refresh) |

## Subscription key

Safeway's `pdpdata`/search/store-locator endpoints require an `ocp-apim-subscription-key` header. This is Safeway's own public client-side key (shipped to every visitor's browser), not a credential issued to us — the CLI fetches it dynamically at runtime by default (best-effort; the exact extraction is fragile against Safeway's frontend and may need re-verifying by hand if it starts failing).

If it does need refreshing, find a working value (e.g. via browser DevTools against a real Safeway page load) and set it directly rather than passing it as a CLI argument (which would leak into shell history/process listings):

```
export SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY=<value>
```

This takes priority over the dynamic fetch and any cached value. There's no automatic rotation/discovery beyond this — see the open item in `AGENTS.md` for why that's deliberately deferred.

## Development

```
uv sync --extra dev
uv run pytest
```

The test suite never makes live network calls — all HTTP is mocked via `responses`, and no fixture/test data uses a real store number, address, or zip code. To try it against the real Safeway API, run the CLI directly (see Usage above).
