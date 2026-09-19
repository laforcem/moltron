import io
import json

import shop_lookup.cli as cli_module
from shop_lookup.cli import main

CONFIG_URL = "https://www.safeway.com/"
PDP_URL = "https://www.safeway.com/abs/pub/xapi/product/v2/pdpdata"
SEARCH_URL = "https://www.safeway.com/abs/pub/xapi/pgmsearch/v1/search/products"
KEY_PAGE_BODY = '<script>window.config = {"ocp-apim-subscription-key": "test-key-abc"};</script>'


def test_successful_lookup(mocked_responses, cache_dir, fixture_loader, capsys):
    mocked_responses.add(mocked_responses.GET, CONFIG_URL, body=KEY_PAGE_BODY, status=200)
    mocked_responses.add(
        mocked_responses.GET, PDP_URL, json=fixture_loader("pdp_happy_with_aisle.json"), status=200
    )

    exit_code = main(["safeway", "product", "--store", "1000", "--bpn", "960087216"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["location"]["label"] == "Aisle 4"
    assert out["retailer"] == "safeway"


def test_schema_drift_surfaces_as_typed_error(mocked_responses, cache_dir, fixture_loader, capsys):
    mocked_responses.add(mocked_responses.GET, CONFIG_URL, body=KEY_PAGE_BODY, status=200)
    mocked_responses.add(
        mocked_responses.GET, PDP_URL, json=fixture_loader("pdp_missing_fields.json"), status=200
    )

    exit_code = main(["safeway", "product", "--store", "1000", "--bpn", "960087216"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 4
    assert out["error"] == "api_changed"


def test_rate_limited_exhausted_surfaces_as_typed_error(mocked_responses, cache_dir, capsys, monkeypatch):
    from shop_lookup import http as http_module

    monkeypatch.setattr(http_module.time, "sleep", lambda _seconds: None)

    mocked_responses.add(mocked_responses.GET, CONFIG_URL, body=KEY_PAGE_BODY, status=200)
    for _ in range(10):
        mocked_responses.add(mocked_responses.GET, PDP_URL, status=429)

    exit_code = main(["safeway", "product", "--store", "1000", "--bpn", "960087216"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 3
    assert out["error"] == "rate_limited"


def test_locate_returns_multiple_results(mocked_responses, cache_dir, fixture_loader, capsys):
    mocked_responses.add(mocked_responses.GET, CONFIG_URL, body=KEY_PAGE_BODY, status=200)
    mocked_responses.add(
        mocked_responses.GET,
        SEARCH_URL,
        json=fixture_loader("search_baking_chocolate.json"),
        status=200,
    )

    exit_code = main(["safeway", "locate", "baking chocolate", "--store", "1000"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["count"] == 2
    assert out["results"][0]["product"]["price"] == 4.99
    assert out["results"][0]["location"]["label"] == "Aisle 4"
    assert out["results"][0]["source"] == "safeway-search-api"


def test_product_from_json_skips_network_entirely(
    mocked_responses, cache_dir, fixture_loader, capsys, monkeypatch
):
    raw = fixture_loader("pdp_happy_with_aisle.json")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(raw)))

    exit_code = main(["safeway", "product", "--store", "1000", "--from-json", "-"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["location"]["label"] == "Aisle 4"
    assert len(mocked_responses.calls) == 0


def test_locate_from_json_skips_network_entirely(
    mocked_responses, cache_dir, fixture_loader, capsys, monkeypatch
):
    raw = fixture_loader("search_baking_chocolate.json")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(raw)))

    exit_code = main(["safeway", "locate", "--store", "1000", "--from-json", "-"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["count"] == 2
    assert len(mocked_responses.calls) == 0


def test_product_without_bpn_or_from_json_is_an_error(cache_dir, capsys):
    exit_code = main(["safeway", "product", "--store", "1000"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert "bpn" in out["message"]


def test_locate_without_query_or_from_json_is_an_error(cache_dir, capsys):
    exit_code = main(["safeway", "locate", "--store", "1000"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert "query" in out["message"]


def test_unexpected_exception_surfaces_as_internal_error(cache_dir, capsys, monkeypatch):
    def boom(_args):
        raise ValueError("something unrelated broke")

    monkeypatch.setattr(cli_module, "_run_safeway_product", boom)

    exit_code = main(["safeway", "product", "--store", "1000", "--bpn", "1"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert out["error"] == "internal"
    assert "something unrelated broke" in out["message"]
