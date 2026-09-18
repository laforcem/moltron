"""Hardcoded, non-configurable constants.

These are intentionally not exposed as CLI flags or environment overrides:
this is public code, and the cache/retry behavior is part of being a
conservative, low-volume client rather than something a fork should be able
to casually dial up.
"""

import os
from pathlib import Path

SUBSCRIPTION_KEY_CACHE_TTL_SECONDS = 3600
PRODUCT_LOOKUP_CACHE_TTL_SECONDS = 600

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 20.0
JITTER_FRACTION = 0.25

REQUEST_TIMEOUT_SECONDS = 10.0


def xdg_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "shop-lookup"
