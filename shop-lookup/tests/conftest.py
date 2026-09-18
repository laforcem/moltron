import json
from pathlib import Path

import pytest
import responses as responses_lib

from shop_lookup.cache import FileCache

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def fixture_loader():
    return load_fixture


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    cache_path = tmp_path / "shop-lookup-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return cache_path


@pytest.fixture
def fake_clock():
    state = {"now": 1_000_000.0}

    def clock():
        return state["now"]

    clock.state = state
    return clock


@pytest.fixture
def file_cache(cache_dir, fake_clock):
    return FileCache(base_dir=cache_dir, clock=fake_clock)


@pytest.fixture
def mocked_responses():
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps
