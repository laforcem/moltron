from shop_lookup.stores import resolve_store


def test_resolve_returns_store_with_given_id():
    store = resolve_store("1000")
    assert store.id == "1000"


def test_resolve_accepts_any_id_no_local_registry():
    store = resolve_store("999999")
    assert store.id == "999999"
