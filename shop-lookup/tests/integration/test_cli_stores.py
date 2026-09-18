import json

from shop_lookup.cli import main

CONFIG_URL = "https://www.safeway.com/"
STORE_RESOLVER_URL = "https://www.safeway.com/abs/pub/xapi/storeresolver/v2/all"
KEY_PAGE_BODY = '<script>window.config = {"ocp-apim-subscription-key": "test-key-abc"};</script>'


def test_stores_by_zip(mocked_responses, cache_dir, fixture_loader, capsys):
    mocked_responses.add(mocked_responses.GET, CONFIG_URL, body=KEY_PAGE_BODY, status=200)
    mocked_responses.add(
        mocked_responses.GET,
        STORE_RESOLVER_URL,
        json=fixture_loader("store_resolver_60601.json"),
        status=200,
    )

    exit_code = main(["safeway", "stores", "--zip", "60601"])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["count"] == 2
    assert out["stores"][0]["id"] == "1000"
    assert "1 Test Plaza" in out["stores"][0]["address"]
