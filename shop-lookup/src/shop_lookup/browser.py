from __future__ import annotations

import os
import shutil

from shop_lookup.errors import ShopLookupError

# Prefer whatever real Chromium-family browser is already installed on this
# host (e.g. the apt `chromium` package this repo's browser-tools role
# installs for OpenClaw's own browser tool) over bundling/downloading a
# second copy just for shop-lookup.
_ENV_VAR = "SHOP_LOOKUP_CHROMIUM_PATH"
_CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser")

_INCAPSULA_MARKERS = ("_Incapsula_Resource", "Incapsula incident ID")


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
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable_path, headless=True)
        try:
            page = browser.new_page()
            page.goto(bootstrap_url)
            return page.evaluate(
                """async ({url, headers}) => {
                    const response = await fetch(url, {headers});
                    return await response.json();
                }""",
                {"url": url, "headers": headers},
            )
        finally:
            browser.close()
