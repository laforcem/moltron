from __future__ import annotations

from shop_lookup.models import Store


def resolve_store(store_id: str) -> Store:
    """Wraps a raw Safeway store number as a Store.

    No local alias registry -- store discovery is `safeway stores --zip`
    (backed by Safeway's own store-locator API), and this repo doesn't hold
    a copy of Safeway's store directory to validate against.
    """
    return Store(id=store_id, name="Safeway", address=None)
