from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Optional

from shop_lookup.config import xdg_cache_dir


class FileCache:
    """A small file-based TTL cache.

    Corrupt, missing, or expired entries are treated as a cache miss rather
    than raised as errors -- a broken cache file should never take down a
    lookup.
    """

    def __init__(self, base_dir: Optional[Path] = None, clock: Callable[[], float] = time.time):
        self._base_dir = base_dir or xdg_cache_dir()
        self._clock = clock

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._base_dir / f"{digest}.json"

    def get(self, key: str) -> Optional[dict]:
        path = self._path_for(key)
        try:
            raw = path.read_text()
            entry = json.loads(raw)
        except (OSError, ValueError):
            return None

        if not isinstance(entry, dict) or "expires_at" not in entry or "value" not in entry:
            return None
        if self._clock() >= entry["expires_at"]:
            return None
        return entry["value"]

    def set(self, key: str, value: dict, ttl_seconds: float) -> None:
        path = self._path_for(key)
        entry = {"expires_at": self._clock() + ttl_seconds, "value": value}
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry))
        except OSError:
            pass
