from __future__ import annotations

import requests

from shop_lookup.errors import SubscriptionKeyError
from shop_lookup.http import request_with_retry
from shop_lookup.models import Store
from shop_lookup.subscription_key import CachedSubscriptionKeyProvider

_STORE_RESOLVER_URL = "https://www.safeway.com/abs/pub/xapi/storeresolver/v2/all"


class SafewayStoreResolverClient:
    def __init__(
        self,
        key_provider: CachedSubscriptionKeyProvider,
        session: requests.Session | None = None,
    ):
        self._key_provider = key_provider
        self._session = session or requests.Session()

    def find_stores(self, zip_code: str, radius: int = 50, size: int = 10) -> dict:
        headers = {
            "ocp-apim-subscription-key": self._key_provider.get_key(),
            "page-name": "fulfillment-modal",
        }
        params = {
            "zipcode": zip_code,
            "size": str(size),
            "radius": str(radius),
            "excludeBanners": "none",
            "includeNonMigratedStores": "true",
        }

        response = request_with_retry(
            self._session, "GET", _STORE_RESOLVER_URL, params=params, headers=headers
        )

        if response.status_code in (401, 403):
            raise SubscriptionKeyError(
                "Safeway rejected the subscription key -- it likely needs to be "
                "refreshed (see AGENTS.md)",
                detail={"status_code": response.status_code},
            )
        response.raise_for_status()
        return response.json()


def extract_stores(raw: dict) -> list[Store]:
    docs = raw.get("instore", {}).get("stores", [])
    stores = []
    for doc in docs:
        address = doc.get("address", {})
        formatted = ", ".join(
            part
            for part in (
                address.get("line1"),
                address.get("city"),
                address.get("state"),
                address.get("zipcode"),
            )
            if part
        )
        stores.append(
            Store(
                id=doc["locationId"],
                name=doc.get("domainName", "Safeway"),
                address=formatted,
            )
        )
    return stores
