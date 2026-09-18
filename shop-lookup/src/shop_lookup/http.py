from __future__ import annotations

import random
import time

import requests

from shop_lookup.config import (
    BASE_BACKOFF_SECONDS,
    JITTER_FRACTION,
    MAX_BACKOFF_SECONDS,
    MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
)
from shop_lookup.errors import RateLimitedError, TransientAPIError

_RETRYABLE_5XX = range(500, 600)


def _backoff_delay(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, MAX_BACKOFF_SECONDS)
    base = min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
    return base + random.uniform(0, JITTER_FRACTION * base)


def request_with_retry(
    session: requests.Session, method: str, url: str, **kwargs
) -> requests.Response:
    kwargs.setdefault("timeout", REQUEST_TIMEOUT_SECONDS)

    for attempt in range(MAX_RETRIES + 1):
        response = session.request(method, url, **kwargs)

        if response.status_code == 429:
            if attempt >= MAX_RETRIES:
                raise RateLimitedError(
                    "Safeway rate-limited this request",
                    detail={"status_code": 429},
                )
            retry_after = response.headers.get("Retry-After")
            delay = _backoff_delay(attempt, float(retry_after) if retry_after else None)
            time.sleep(delay)
            continue

        if response.status_code in _RETRYABLE_5XX:
            if attempt >= MAX_RETRIES:
                raise TransientAPIError(
                    "Safeway returned a persistent server error",
                    detail={"status_code": response.status_code},
                )
            time.sleep(_backoff_delay(attempt, None))
            continue

        return response

    raise AssertionError("unreachable: loop always returns or raises")  # pragma: no cover
