import pytest

from shop_lookup.cache import FileCache
from shop_lookup.errors import SchemaDriftError
from shop_lookup.subscription_key import CachedSubscriptionKeyProvider, SubscriptionKeyProvider

CONFIG_URL = "https://www.safeway.com/"


class FakeSubscriptionKeyProvider:
    def __init__(self, key="fake-key-123"):
        self.key = key
        self.fetch_count = 0

    def fetch(self):
        self.fetch_count += 1
        return self.key


def test_caches_key_across_calls(tmp_path, fake_clock):
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    fake = FakeSubscriptionKeyProvider()
    provider = CachedSubscriptionKeyProvider(fake, cache=cache)

    assert provider.get_key() == "fake-key-123"
    assert provider.get_key() == "fake-key-123"
    assert fake.fetch_count == 1


def test_refetches_after_ttl_expiry(tmp_path, fake_clock):
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    fake = FakeSubscriptionKeyProvider()
    provider = CachedSubscriptionKeyProvider(fake, cache=cache)

    provider.get_key()
    fake_clock.state["now"] += 3700  # past SUBSCRIPTION_KEY_CACHE_TTL_SECONDS
    provider.get_key()
    assert fake.fetch_count == 2


def test_env_var_override_takes_priority(tmp_path, fake_clock, monkeypatch):
    monkeypatch.setenv("SHOP_LOOKUP_SAFEWAY_SUBSCRIPTION_KEY", "manually-set-key")
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    fake = FakeSubscriptionKeyProvider()
    provider = CachedSubscriptionKeyProvider(fake, cache=cache)

    assert provider.get_key() == "manually-set-key"
    assert fake.fetch_count == 0


def test_fetch_finds_key_in_config_page(mocked_responses):
    mocked_responses.add(
        mocked_responses.GET,
        CONFIG_URL,
        body='<script>window.config = {"ocp-apim-subscription-key": "real-key-456"};</script>',
        status=200,
    )
    assert SubscriptionKeyProvider().fetch() == "real-key-456"


def test_fetch_raises_schema_drift_when_key_not_found(mocked_responses):
    mocked_responses.add(mocked_responses.GET, CONFIG_URL, body="<html>no key here</html>", status=200)

    with pytest.raises(SchemaDriftError):
        SubscriptionKeyProvider().fetch()
