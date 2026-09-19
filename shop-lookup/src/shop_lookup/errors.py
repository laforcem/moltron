"""Typed error hierarchy.

A product that is found but unavailable, or found but missing location
data, is NOT an error here -- it's a normal successful LookupResult with
those fields reflecting that state. These error types are reserved for
cases where no usable result can be produced at all.
"""

from __future__ import annotations


class ShopLookupError(Exception):
    """Base class for all shop-lookup errors."""

    exit_code = 1
    kind = "internal"

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_json_dict(self) -> dict:
        return {"error": self.kind, "message": self.message, "detail": self.detail}


class NotFoundError(ShopLookupError):
    """No such store, or no such product at the given store."""

    exit_code = 2
    kind = "not_found"


class RateLimitedError(ShopLookupError):
    """Retries against 429 were exhausted."""

    exit_code = 3
    kind = "rate_limited"


class SchemaDriftError(ShopLookupError):
    """The upstream response no longer matches the expected shape."""

    exit_code = 4
    kind = "api_changed"


class TransientAPIError(ShopLookupError):
    """Retries against 5xx were exhausted."""

    exit_code = 1
    kind = "transient_api_error"


class SubscriptionKeyError(ShopLookupError):
    """The subscription key was rejected (401/403).

    This does not attempt automatic recovery -- refreshing the key is an
    occasional, manual/agent-driven task (see AGENTS.md), not something this
    CLI does for itself. Set SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY once a
    working value is found.
    """

    exit_code = 5
    kind = "subscription_key_invalid"


class BrowserBlockedError(ShopLookupError):
    """The real-browser fallback fetch was also met with an Incapsula challenge.

    Distinct from SubscriptionKeyError: the key may be fine -- this is
    Incapsula risk-scoring the browser's own IP/session, not rejecting the
    key itself. Retrying immediately with the same key is unlikely to help.
    """

    exit_code = 6
    kind = "still_blocked"
