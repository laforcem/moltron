from shop_lookup.models import Store
from shop_lookup.safeway.normalize import to_lookup_result
from shop_lookup.safeway.parse import extract_product_fields

STORE = Store(id="1000", name="Safeway")


def test_normalizes_happy_path(fixture_loader):
    raw = fixture_loader("pdp_happy_with_aisle.json")
    fields = extract_product_fields(raw)
    result = to_lookup_result(STORE, fields)

    assert result.retailer == "safeway"
    assert result.store.id == "1000"
    assert result.product.id == "960087216"
    assert result.location.label == "Aisle 4"
    assert result.source == "safeway-pdp-api"


def test_normalizes_unavailable_as_success_not_error(fixture_loader):
    raw = fixture_loader("pdp_unavailable.json")
    fields = extract_product_fields(raw)
    result = to_lookup_result(STORE, fields)

    assert result.availability == "OUT_OF_STOCK"
    assert result.location.label == "Aisle 20"


def test_to_json_dict_shape(fixture_loader):
    raw = fixture_loader("pdp_happy_with_aisle.json")
    fields = extract_product_fields(raw)
    result = to_lookup_result(STORE, fields)
    as_json = result.to_json_dict()

    assert set(as_json.keys()) == {
        "retailer",
        "store",
        "product",
        "location",
        "availability",
        "checked_at",
        "source",
    }
