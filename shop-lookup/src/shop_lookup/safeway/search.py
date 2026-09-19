from __future__ import annotations

import random
import uuid

import requests

from shop_lookup.browser import ChromiumFetcher, is_incapsula_challenge
from shop_lookup.errors import SubscriptionKeyError
from shop_lookup.http import request_with_retry
from shop_lookup.models import Store
from shop_lookup.subscription_key import CachedSubscriptionKeyProvider

_SEARCH_URL = "https://www.safeway.com/abs/pub/xapi/pgmsearch/v1/search/products"


class SafewaySearchClient:
    def __init__(
        self,
        key_provider: CachedSubscriptionKeyProvider,
        session: requests.Session | None = None,
        browser_fetcher=None,
    ):
        self._key_provider = key_provider
        self._session = session or requests.Session()
        self._browser_fetcher = browser_fetcher or ChromiumFetcher().fetch_json

    def search(self, store: Store, query: str, rows: int = 10) -> dict:
        headers = {"ocp-apim-subscription-key": self._key_provider.get_key()}
        params = {
            "q": query,
            "storeid": store.id,
            "rows": str(rows),
            "start": "0",
            "search-type": "keyword",
            "banner": "safeway",
            "channel": "instore",
            "featured": "true",
            "includeOffer": "true",
            "pp": "true",
            "pgm": "merch-banner",
            "dvid": "web-4.1search",
            "timezone": "America/Denver",
            "sort": "",
            "visitorId": "",
            "uuid": str(uuid.uuid4()),
            "url": "https://www.safeway.com",
            "pagename": "search",
            "request-id": str(random.randint(1, 10**9)),
        }

        full_url = requests.Request(
            "GET", _SEARCH_URL, params=params, headers=headers
        ).prepare().url

        try:
            response = request_with_retry(
                self._session, "GET", _SEARCH_URL, params=params, headers=headers
            )
        except requests.exceptions.RequestException:
            # Safeway's search endpoint has been observed to silently hang
            # (0 bytes back) for non-browser clients, rather than a clean
            # rejection -- treat any transport-level failure the same as an
            # explicit Incapsula challenge.
            return self._browser_fetcher(full_url, headers)

        if response.status_code in (401, 403) and is_incapsula_challenge(response.text):
            return self._browser_fetcher(full_url, headers)
        if response.status_code in (401, 403):
            raise SubscriptionKeyError(
                "Safeway rejected the subscription key -- it likely needs to be "
                "refreshed (see AGENTS.md)",
                detail={"status_code": response.status_code},
            )
        response.raise_for_status()
        return response.json()
