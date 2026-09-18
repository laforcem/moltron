from __future__ import annotations

import os
import re

import requests

from shop_lookup.cache import FileCache
from shop_lookup.config import REQUEST_TIMEOUT_SECONDS, SUBSCRIPTION_KEY_CACHE_TTL_SECONDS
from shop_lookup.errors import SchemaDriftError

_CACHE_KEY = "safeway-subscription-key"

# Preferred source: an operator (human or agent) who has manually confirmed
# a working key can set this directly, e.g. after Safeway rotates it and the
# dynamic fetch below starts failing. Matches this repo's existing pattern
# of injecting service credentials as environment variables (see AGENTS.md
# "Secrets") rather than a CLI argument, which would leak into shell
# history/process listings.
_ENV_VAR = "SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY"

# Safeway's own storefront ships its current API client key to every visitor
# as part of its public page config -- this is the same value any browser
# already sends, not a private credential. We read it back out of that
# public config at runtime instead of hardcoding a copy that will go stale
# whenever Safeway rotates it.
#
# NOTE: the exact page/pattern below is a best-effort default and should be
# re-verified against the live site (a parallel discovery effort is
# confirming Safeway's current client config shape); adjust _KEY_PATTERN or
# the fetch target here if that comes back with something more precise.
_CONFIG_URL = "https://www.safeway.com/"
_KEY_PATTERN = re.compile(r'ocp-apim-subscription-key["\']?\s*[:=]\s*["\']([\w-]+)["\']', re.IGNORECASE)


class SubscriptionKeyProvider:
    """Fetches the current Safeway client subscription key."""

    def __init__(self, session: requests.Session | None = None):
        self._session = session or requests.Session()

    def fetch(self) -> str:
        response = self._session.get(_CONFIG_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        match = _KEY_PATTERN.search(response.text)
        if not match:
            raise SchemaDriftError(
                "Could not locate the subscription key in Safeway's public client config",
                detail={"source": _CONFIG_URL},
            )
        return match.group(1)


class CachedSubscriptionKeyProvider:
    """Wraps any SubscriptionKeyProvider with a short-TTL file cache."""

    def __init__(self, provider: SubscriptionKeyProvider, cache: FileCache | None = None):
        self._provider = provider
        self._cache = cache or FileCache()

    def get_key(self) -> str:
        env_key = os.environ.get(_ENV_VAR)
        if env_key:
            return env_key

        cached = self._cache.get(_CACHE_KEY)
        if cached is not None:
            return cached["key"]

        key = self._provider.fetch()
        self._cache.set(_CACHE_KEY, {"key": key}, SUBSCRIPTION_KEY_CACHE_TTL_SECONDS)
        return key
