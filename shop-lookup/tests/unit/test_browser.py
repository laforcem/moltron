import pytest

from shop_lookup.browser import ChromiumFetcher, find_chromium_executable, is_incapsula_challenge
from shop_lookup.errors import ShopLookupError


def test_env_var_override_wins(monkeypatch, tmp_path):
    fake_binary = tmp_path / "my-chromium"
    fake_binary.write_text("#!/bin/sh\n")
    fake_binary.chmod(0o755)
    monkeypatch.setenv("SHOP_LOOKUP_CHROMIUM_PATH", str(fake_binary))

    assert find_chromium_executable() == str(fake_binary)


def test_finds_first_matching_candidate_on_path(monkeypatch):
    monkeypatch.delenv("SHOP_LOOKUP_CHROMIUM_PATH", raising=False)

    def fake_which(name):
        return "/usr/bin/chromium" if name == "chromium" else None

    monkeypatch.setattr("shop_lookup.browser.shutil.which", fake_which)

    assert find_chromium_executable() == "/usr/bin/chromium"


def test_raises_clear_error_when_nothing_found(monkeypatch):
    monkeypatch.delenv("SHOP_LOOKUP_CHROMIUM_PATH", raising=False)
    monkeypatch.setattr("shop_lookup.browser.shutil.which", lambda _name: None)

    with pytest.raises(ShopLookupError):
        find_chromium_executable()


def test_is_incapsula_challenge_detects_marker():
    body = '<iframe src="/_Incapsula_Resource?...">Request unsuccessful. Incapsula incident ID: 123</iframe>'
    assert is_incapsula_challenge(body) is True


def test_is_incapsula_challenge_false_for_normal_json():
    assert is_incapsula_challenge('{"catalog": {"response": {"docs": []}}}') is False


def test_fetcher_finds_executable_and_delegates_to_launcher(monkeypatch):
    monkeypatch.setattr("shop_lookup.browser.shutil.which", lambda name: f"/usr/bin/{name}")

    calls = []

    def fake_launcher(executable_path, bootstrap_url, url, headers):
        calls.append((executable_path, bootstrap_url, url, headers))
        return {"ok": True}

    fetcher = ChromiumFetcher(launcher=fake_launcher)
    result = fetcher.fetch_json("https://example.invalid/data", {"h": "v"})

    assert result == {"ok": True}
    assert calls == [
        ("/usr/bin/chromium", "https://www.safeway.com/", "https://example.invalid/data", {"h": "v"})
    ]
