from shop_lookup.cache import FileCache
from shop_lookup.subscription_key import CachedSubscriptionKeyProvider


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
