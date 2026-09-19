import pytest

from shop_lookup.cache import FileCache
from shop_lookup.errors import NotFoundError, SubscriptionKeyError
from shop_lookup.models import Store
from shop_lookup.safeway.client import SafewayPdpClient

STORE = Store(id="1000", name="Safeway")
PDP_URL = "https://www.safeway.com/abs/pub/xapi/product/v2/pdpdata"


class StaticKeyProvider:
    def get_key(self):
        return "static-key"


def test_cache_hit_avoids_second_http_call(mocked_responses, tmp_path, fake_clock, fixture_loader):
    body = fixture_loader("pdp_happy_with_aisle.json")
    mocked_responses.add(mocked_responses.GET, PDP_URL, json=body, status=200)

    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    client = SafewayPdpClient(StaticKeyProvider(), cache=cache)

    first = client.fetch_product(STORE, "960087216")
    second = client.fetch_product(STORE, "960087216")

    assert first == second == body
    assert len(mocked_responses.calls) == 1


def test_no_cache_flag_forces_second_call(mocked_responses, tmp_path, fake_clock, fixture_loader):
    body = fixture_loader("pdp_happy_with_aisle.json")
    mocked_responses.add(mocked_responses.GET, PDP_URL, json=body, status=200)
    mocked_responses.add(mocked_responses.GET, PDP_URL, json=body, status=200)

    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    client = SafewayPdpClient(StaticKeyProvider(), cache=cache)

    client.fetch_product(STORE, "960087216", use_cache=False)
    client.fetch_product(STORE, "960087216", use_cache=False)

    assert len(mocked_responses.calls) == 2


@pytest.mark.parametrize("status_code", [401, 403])
def test_rejected_key_raises_subscription_key_error(
    mocked_responses, tmp_path, fake_clock, status_code
):
    mocked_responses.add(mocked_responses.GET, PDP_URL, status=status_code)

    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    client = SafewayPdpClient(StaticKeyProvider(), cache=cache)

    with pytest.raises(SubscriptionKeyError):
        client.fetch_product(STORE, "960087216", use_cache=False)


def test_404_raises_not_found(mocked_responses, tmp_path, fake_clock):
    mocked_responses.add(mocked_responses.GET, PDP_URL, status=404)

    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    client = SafewayPdpClient(StaticKeyProvider(), cache=cache)

    with pytest.raises(NotFoundError):
        client.fetch_product(STORE, "nonexistent-bpn", use_cache=False)


def test_incapsula_challenge_falls_back_to_browser_fetch(
    mocked_responses, tmp_path, fake_clock, fixture_loader
):
    incapsula_body = (
        '<iframe src="/_Incapsula_Resource?...">Incapsula incident ID: 123</iframe>'
    )
    mocked_responses.add(mocked_responses.GET, PDP_URL, body=incapsula_body, status=403)

    expected = fixture_loader("pdp_happy_with_aisle.json")
    calls = []

    def fake_fetcher(url, headers):
        calls.append((url, headers))
        return expected

    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    client = SafewayPdpClient(StaticKeyProvider(), cache=cache, browser_fetcher=fake_fetcher)

    result = client.fetch_product(STORE, "960087216", use_cache=False)

    assert result == expected
    assert len(calls) == 1
    url, headers = calls[0]
    assert url.startswith(PDP_URL)
    assert "bpn=960087216" in url
    assert headers["ocp-apim-subscription-key"] == "static-key"
