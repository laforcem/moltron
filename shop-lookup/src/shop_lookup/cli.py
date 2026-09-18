"""shop-lookup CLI.

Exit codes:
  0  success (check the JSON body's availability/location -- a partial
     result, e.g. location.label == null, is still exit 0)
  1  internal/unexpected failure
  2  not_found (unknown store or product/bpn)
  3  rate_limited (retries exhausted on 429)
  4  api_changed / schema_drift
  5  subscription_key_invalid (401/403 -- key needs manual refresh, see AGENTS.md)
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

from shop_lookup.errors import ShopLookupError
from shop_lookup.safeway.client import SafewayPdpClient
from shop_lookup.safeway.normalize import to_lookup_result
from shop_lookup.safeway.parse import extract_product_fields, extract_search_fields
from shop_lookup.safeway.search import SafewaySearchClient
from shop_lookup.safeway.store_resolver import SafewayStoreResolverClient, extract_stores
from shop_lookup.stores import resolve_store
from shop_lookup.subscription_key import CachedSubscriptionKeyProvider, SubscriptionKeyProvider


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shop-lookup")
    subparsers = parser.add_subparsers(dest="retailer", required=True)

    safeway = subparsers.add_parser("safeway", help="Safeway lookups")
    safeway_subparsers = safeway.add_subparsers(dest="command", required=True)

    product = safeway_subparsers.add_parser(
        "product", help="Look up a product's in-store location by BPN"
    )
    product.add_argument("--store", required=True, help="Safeway store id")
    product.add_argument("--bpn", required=True, help="Safeway product id (BPN)")
    product.add_argument(
        "--no-cache", action="store_true", help="Bypass the local product-lookup cache"
    )

    locate = safeway_subparsers.add_parser(
        "locate", help="Fuzzy-search products by name, with price and location"
    )
    locate.add_argument("query", help="Free-text product search, e.g. 'apple'")
    locate.add_argument("--store", required=True, help="Safeway store id")
    locate.add_argument("--limit", type=int, default=10, help="Max results (default 10)")

    stores = safeway_subparsers.add_parser(
        "stores", help="Find nearby store numbers by zip code"
    )
    stores.add_argument("--zip", dest="zip_code", required=True, help="5-digit zip code")

    return parser


def _run_safeway_product(args: argparse.Namespace) -> dict:
    store = resolve_store(args.store)
    key_provider = CachedSubscriptionKeyProvider(SubscriptionKeyProvider())
    client = SafewayPdpClient(key_provider)

    raw = client.fetch_product(store, args.bpn, use_cache=not args.no_cache)
    fields = extract_product_fields(raw)
    result = to_lookup_result(store, fields)
    return result.to_json_dict()


def _run_safeway_locate(args: argparse.Namespace) -> dict:
    store = resolve_store(args.store)
    key_provider = CachedSubscriptionKeyProvider(SubscriptionKeyProvider())
    client = SafewaySearchClient(key_provider)

    raw = client.search(store, args.query, rows=max(args.limit, 1))
    all_fields = extract_search_fields(raw)
    results = [
        to_lookup_result(store, fields, source="safeway-search-api").to_json_dict()
        for fields in all_fields[: args.limit]
    ]
    return {"results": results, "count": len(results)}


def _run_safeway_stores(args: argparse.Namespace) -> dict:
    key_provider = CachedSubscriptionKeyProvider(SubscriptionKeyProvider())
    client = SafewayStoreResolverClient(key_provider)

    raw = client.find_stores(args.zip_code)
    stores = extract_stores(raw)
    return {
        "stores": [
            {"id": store.id, "name": store.name, "address": store.address} for store in stores
        ],
        "count": len(stores),
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.retailer == "safeway" and args.command == "product":
            output = _run_safeway_product(args)
        elif args.retailer == "safeway" and args.command == "locate":
            output = _run_safeway_locate(args)
        elif args.retailer == "safeway" and args.command == "stores":
            output = _run_safeway_stores(args)
        else:  # pragma: no cover - argparse enforces valid combinations
            parser.error("unsupported command")
            return 1
    except ShopLookupError as exc:
        print(json.dumps(exc.to_json_dict()))
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        print(json.dumps({"error": "internal", "message": str(exc)}))
        traceback.print_exc(file=sys.stderr)
        return 1

    print(json.dumps(output))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin script entrypoint
    sys.exit(main())
