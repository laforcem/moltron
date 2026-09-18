import pytest
import requests

from shop_lookup import http as http_module
from shop_lookup.errors import RateLimitedError, TransientAPIError
from shop_lookup.http import request_with_retry

URL = "https://example.invalid/thing"


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(http_module.time, "sleep", lambda _seconds: None)


def test_retries_429_then_succeeds(mocked_responses):
    mocked_responses.add(mocked_responses.GET, URL, status=429)
    mocked_responses.add(mocked_responses.GET, URL, status=200, json={"ok": True})

    response = request_with_retry(requests.Session(), "GET", URL)
    assert response.status_code == 200


def test_429_exhausted_raises_rate_limited(mocked_responses):
    for _ in range(10):
        mocked_responses.add(mocked_responses.GET, URL, status=429)

    with pytest.raises(RateLimitedError):
        request_with_retry(requests.Session(), "GET", URL)


def test_retries_5xx_then_succeeds(mocked_responses):
    mocked_responses.add(mocked_responses.GET, URL, status=503)
    mocked_responses.add(mocked_responses.GET, URL, status=200, json={"ok": True})

    response = request_with_retry(requests.Session(), "GET", URL)
    assert response.status_code == 200


def test_5xx_exhausted_raises_transient_api_error(mocked_responses):
    for _ in range(10):
        mocked_responses.add(mocked_responses.GET, URL, status=500)

    with pytest.raises(TransientAPIError):
        request_with_retry(requests.Session(), "GET", URL)


def test_non_retryable_4xx_returns_immediately(mocked_responses):
    mocked_responses.add(mocked_responses.GET, URL, status=404)

    response = request_with_retry(requests.Session(), "GET", URL)
    assert response.status_code == 404


def test_429_honors_retry_after_header(mocked_responses, monkeypatch):
    mocked_responses.add(mocked_responses.GET, URL, status=429, headers={"Retry-After": "2"})
    mocked_responses.add(mocked_responses.GET, URL, status=200, json={"ok": True})

    delays = []
    monkeypatch.setattr(http_module.time, "sleep", lambda seconds: delays.append(seconds))

    request_with_retry(requests.Session(), "GET", URL)

    assert delays == [2.0]
