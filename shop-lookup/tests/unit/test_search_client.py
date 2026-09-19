import pytest
import requests

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


def test_incapsula_challenge_falls_back_to_browser_fetch(mocked_responses, fixture_loader):
    incapsula_body = (
        '<iframe src="/_Incapsula_Resource?...">Incapsula incident ID: 123</iframe>'
    )
    mocked_responses.add(mocked_responses.GET, SEARCH_URL, body=incapsula_body, status=403)

    expected = fixture_loader("search_baking_chocolate.json")
    calls = []

    def fake_fetcher(url, headers):
        calls.append((url, headers))
        return expected

    client = SafewaySearchClient(StaticKeyProvider(), browser_fetcher=fake_fetcher)
    result = client.search(STORE, "baking chocolate")

    assert result == expected
    assert len(calls) == 1
    assert calls[0][1]["ocp-apim-subscription-key"] == "static-key"


@pytest.mark.parametrize("status_code", [401, 403])
def test_plain_rejection_raises_subscription_key_error(mocked_responses, status_code):
    mocked_responses.add(mocked_responses.GET, SEARCH_URL, status=status_code)

    client = SafewaySearchClient(StaticKeyProvider())
    with pytest.raises(SubscriptionKeyError):
        client.search(STORE, "anything")


def test_connection_timeout_falls_back_to_browser_fetch(fixture_loader):
    expected = fixture_loader("search_baking_chocolate.json")

    class TimeoutSession(requests.Session):
        def request(self, *args, **kwargs):
            raise requests.exceptions.ReadTimeout("timed out")

    def fake_fetcher(url, headers):
        return expected

    client = SafewaySearchClient(
        StaticKeyProvider(), session=TimeoutSession(), browser_fetcher=fake_fetcher
    )
    result = client.search(STORE, "baking chocolate")

    assert result == expected
