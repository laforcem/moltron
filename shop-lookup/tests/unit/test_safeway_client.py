import pytest

from shop_lookup.cache import FileCache
from shop_lookup.errors import SubscriptionKeyError
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
