from shop_lookup.safeway.store_resolver import extract_stores


def test_extract_stores_returns_instore_results(fixture_loader):
    raw = fixture_loader("store_resolver_60601.json")
    stores = extract_stores(raw)

    assert len(stores) == 2
    assert stores[0].id == "1000"
    assert stores[0].name == "Safeway"
    assert "1 Test Plaza" in stores[0].address
    assert "Chicago" in stores[0].address


def test_extract_stores_empty_instore_returns_empty_list():
    raw = {"instore": {"stores": []}}
    assert extract_stores(raw) == []
