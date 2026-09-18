import pytest

from shop_lookup.errors import SubscriptionKeyError
from shop_lookup.models import Store
from shop_lookup.safeway.search import SafewaySearchClient

STORE = Store(id="1000", name="Safeway")
SEARCH_URL = "https://www.safeway.com/abs/pub/xapi/pgmsearch/v1/search/products"


class StaticKeyProvider:
    def get_key(self):
        return "static-key"


def test_search_returns_raw_response(mocked_responses, fixture_loader):
    body = fixture_loader("search_baking_chocolate.json")
    mocked_responses.add(mocked_responses.GET, SEARCH_URL, json=body, status=200)

    client = SafewaySearchClient(StaticKeyProvider())
    result = client.search(STORE, "baking chocolate")

    assert result == body


@pytest.mark.parametrize("status_code", [401, 403])
def test_rejected_key_raises_subscription_key_error(mocked_responses, status_code):
    mocked_responses.add(mocked_responses.GET, SEARCH_URL, status=status_code)

    client = SafewaySearchClient(StaticKeyProvider())
    with pytest.raises(SubscriptionKeyError):
        client.search(STORE, "anything")
