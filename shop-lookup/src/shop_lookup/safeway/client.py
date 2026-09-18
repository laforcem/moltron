from __future__ import annotations

import requests

from shop_lookup.cache import FileCache
from shop_lookup.config import PRODUCT_LOOKUP_CACHE_TTL_SECONDS
from shop_lookup.errors import NotFoundError, SubscriptionKeyError
from shop_lookup.http import request_with_retry
from shop_lookup.models import Store
from shop_lookup.subscription_key import CachedSubscriptionKeyProvider

_PDP_URL = "https://www.safeway.com/abs/pub/xapi/product/v2/pdpdata"


class SafewayPdpClient:
    def __init__(
        self,
        key_provider: CachedSubscriptionKeyProvider,
        session: requests.Session | None = None,
        cache: FileCache | None = None,
    ):
        self._key_provider = key_provider
        self._session = session or requests.Session()
        self._cache = cache or FileCache()

    def fetch_product(self, store: Store, bpn: str, use_cache: bool = True) -> dict:
        cache_key = f"pdp:{store.id}:{bpn}"

        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        headers = {"ocp-apim-subscription-key": self._key_provider.get_key()}
        params = {
            "bpn": bpn,
            "banner": "safeway",
            "storeId": store.id,
            "bannerId": "1",
            "includeProductRating": "true",
            "realTimeReviewRating": "true",
            "guest": "false",
            "includeOffer": "true",
            "pgm": "abs",
        }

        response = request_with_retry(
            self._session, "GET", _PDP_URL, params=params, headers=headers
        )

        if response.status_code == 404:
            raise NotFoundError(
                f"No product found for bpn={bpn} at store {store.id}",
                detail={"bpn": bpn, "store_id": store.id},
            )
        if response.status_code in (401, 403):
            raise SubscriptionKeyError(
                "Safeway rejected the subscription key -- it likely needs to be "
                "refreshed (see AGENTS.md)",
                detail={"status_code": response.status_code},
            )
        response.raise_for_status()

        raw = response.json()
        if use_cache:
            self._cache.set(cache_key, raw, PRODUCT_LOOKUP_CACHE_TTL_SECONDS)
        return raw
