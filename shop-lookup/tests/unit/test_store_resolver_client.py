import pytest

from shop_lookup.errors import SubscriptionKeyError
from shop_lookup.safeway.store_resolver import SafewayStoreResolverClient

STORE_RESOLVER_URL = "https://www.safeway.com/abs/pub/xapi/storeresolver/v2/all"


class StaticKeyProvider:
    def get_key(self):
        return "static-key"


def test_find_stores_returns_raw_response(mocked_responses, fixture_loader):
    body = fixture_loader("store_resolver_60601.json")
    mocked_responses.add(mocked_responses.GET, STORE_RESOLVER_URL, json=body, status=200)

    client = SafewayStoreResolverClient(StaticKeyProvider())
    result = client.find_stores("60601")

    assert result == body


@pytest.mark.parametrize("status_code", [401, 403])
def test_rejected_key_raises_subscription_key_error(mocked_responses, status_code):
    mocked_responses.add(mocked_responses.GET, STORE_RESOLVER_URL, status=status_code)

    client = SafewayStoreResolverClient(StaticKeyProvider())
    with pytest.raises(SubscriptionKeyError):
        client.find_stores("60601")
