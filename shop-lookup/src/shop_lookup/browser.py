from __future__ import annotations

import os
import shutil

from shop_lookup.errors import BrowserBlockedError, ShopLookupError

# Prefer whatever real Chromium-family browser is already installed on this
# host (e.g. the apt `chromium` package this repo's browser-tools role
# installs for OpenClaw's own browser tool) over bundling/downloading a
# second copy just for shop-lookup.
_ENV_VAR = "SHOP_LOOKUP_CHROMIUM_PATH"
_CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser")

_INCAPSULA_MARKERS = ("_Incapsula_Resource", "Incapsula incident ID")

# Incapsula's device-fingerprint cookie. It's set by a JS challenge that runs
# after page load and takes a moment of real execution time to complete --
# firing the real fetch before it's set gets a 403 regardless of IP or
# headless/headed mode (confirmed live: a fresh single-shot browser context
# fails every time, while a long-lived context that already has this cookie
# succeeds).
_FINGERPRINT_COOKIE = "reese84"
_FINGERPRINT_COOKIE_TIMEOUT_MS = 5000


def find_chromium_executable() -> str:
    override = os.environ.get(_ENV_VAR)
    if override:
        return override

    for name in _CANDIDATES:
        path = shutil.which(name)
        if path:
            return path

    raise ShopLookupError(
        "No Chromium-family browser found on this host (checked "
        f"{_ENV_VAR} and {', '.join(_CANDIDATES)})",
        detail={"candidates": list(_CANDIDATES)},
    )


def is_incapsula_challenge(body: str) -> bool:
    return any(marker in body for marker in _INCAPSULA_MARKERS)


class ChromiumFetcher:
    """Fetches a URL's JSON via a real, local, headless Chromium.

    Solves the Incapsula-style challenge naturally by loading a normal page
    first, then runs the actual fetch from inside that page's own JS
    context. The `launcher` seam exists so this orchestration (executable
    discovery, argument wiring) is unit-testable without ever launching a
    real browser -- the launcher itself is a thin Playwright adapter that
    can't be meaningfully unit-tested the same way.
    """

    def __init__(self, launcher=None):
        self._launcher = launcher or _launch_and_fetch

    def fetch_json(
        self, url: str, headers: dict, bootstrap_url: str = "https://www.safeway.com/"
    ) -> dict:
        executable_path = find_chromium_executable()
        return self._launcher(executable_path, bootstrap_url, url, headers)


def _launch_and_fetch(  # pragma: no cover -- real-browser boundary, not unit-testable
    executable_path: str, bootstrap_url: str, url: str, headers: dict
) -> dict:
    import json

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable_path, headless=True)
        try:
            page = browser.new_page()
            page.goto(bootstrap_url)
            try:
                page.wait_for_function(
                    f"document.cookie.includes('{_FINGERPRINT_COOKIE}=')",
                    timeout=_FINGERPRINT_COOKIE_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                pass  # best-effort -- the Incapsula check below still catches a real block
            body = page.evaluate(
                """async ({url, headers}) => {
                    const response = await fetch(url, {headers});
                    return await response.text();
                }""",
                {"url": url, "headers": headers},
            )
        finally:
            browser.close()

    if is_incapsula_challenge(body):
        raise BrowserBlockedError(
            "Real-browser fetch was still blocked by Incapsula after waiting "
            "for the device-fingerprint cookie to be set"
        )
    return json.loads(body)
