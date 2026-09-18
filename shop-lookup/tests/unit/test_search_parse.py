import pytest

from shop_lookup.errors import SchemaDriftError
from shop_lookup.safeway.parse import extract_search_fields


def test_extracts_multiple_results(fixture_loader):
    raw = fixture_loader("search_baking_chocolate.json")
    results = extract_search_fields(raw)

    assert len(results) == 2
    assert results[0]["pid"] == "960152740"
    assert results[0]["price"] == 4.99
    assert results[0]["aisleLocation"] == "Aisle 4"


def test_skips_docs_missing_required_fields(fixture_loader):
    raw = fixture_loader("search_baking_chocolate.json")
    raw["primaryProducts"]["response"]["docs"].append({"name": "no pid here"})

    results = extract_search_fields(raw)
    assert len(results) == 2


def test_missing_shape_raises_schema_drift():
    with pytest.raises(SchemaDriftError):
        extract_search_fields({"primaryProducts": {}})


def test_empty_docs_is_not_an_error():
    raw = {"primaryProducts": {"response": {"docs": []}}}
    assert extract_search_fields(raw) == []
