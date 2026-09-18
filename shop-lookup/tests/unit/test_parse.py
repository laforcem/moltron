import pytest

from shop_lookup.errors import NotFoundError, SchemaDriftError
from shop_lookup.safeway.parse import extract_product_fields


def test_extracts_fields_when_aisle_present(fixture_loader):
    raw = fixture_loader("pdp_happy_with_aisle.json")
    fields = extract_product_fields(raw)
    assert fields["pid"] == "960087216"
    assert fields["aisleLocation"] == "Aisle 4"


def test_extracts_fields_when_aisle_absent_no_guessing(fixture_loader):
    raw = fixture_loader("pdp_happy_no_aisle.json")
    fields = extract_product_fields(raw)
    assert fields["aisleLocation"] is None
    assert fields["aisleName"] is None


def test_missing_required_field_raises_schema_drift(fixture_loader):
    raw = fixture_loader("pdp_missing_fields.json")
    with pytest.raises(SchemaDriftError) as exc_info:
        extract_product_fields(raw)
    assert "pid" in exc_info.value.detail["missing_fields"]


def test_no_docs_raises_not_found():
    with pytest.raises(NotFoundError):
        extract_product_fields({"catalog": {"response": {"docs": []}}})
