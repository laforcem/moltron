from shop_lookup.cache import FileCache


def test_set_then_get_within_ttl(tmp_path, fake_clock):
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    cache.set("k", {"v": 1}, ttl_seconds=100)
    assert cache.get("k") == {"v": 1}


def test_get_returns_none_after_expiry(tmp_path, fake_clock):
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    cache.set("k", {"v": 1}, ttl_seconds=10)
    fake_clock.state["now"] += 11
    assert cache.get("k") is None


def test_get_missing_key_returns_none(tmp_path, fake_clock):
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    assert cache.get("missing") is None


def test_get_corrupt_file_returns_none(tmp_path, fake_clock):
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    cache.set("k", {"v": 1}, ttl_seconds=100)
    path = cache._path_for("k")
    path.write_text("not json")
    assert cache.get("k") is None


def test_get_valid_json_wrong_shape_returns_none(tmp_path, fake_clock):
    cache = FileCache(base_dir=tmp_path, clock=fake_clock)
    path = cache._path_for("k")
    path.write_text('{"unexpected": "shape"}')
    assert cache.get("k") is None


def test_set_swallows_oserror_from_unwritable_dir(tmp_path, fake_clock):
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("i am a file, not a directory")
    cache = FileCache(base_dir=blocked / "cache", clock=fake_clock)

    cache.set("k", {"v": 1}, ttl_seconds=100)  # must not raise

    assert cache.get("k") is None
