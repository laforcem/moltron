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
#
# Confirmed NOT sufficient on its own, though: a fresh single-shot context
# with reese84 already present still 403'd while a long-lived session
# succeeded at the same moment on the same IP -- something about session
# maturity beyond this one cookie also matters. `incap_ses_*` (Incapsula's
# session cookie, dynamic name) is the next suspect; under investigation.
_FINGERPRINT_COOKIE = "reese84"
_SESSION_COOKIE_PREFIX = "incap_ses_"
_FINGERPRINT_COOKIE_TIMEOUT_MS = 5000
_EXTRA_SETTLE_MS = int(os.environ.get("SHOP_LOOKUP_BROWSER_EXTRA_SETTLE_MS", "0"))


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


_FETCH_JS = """async ({url, headers}) => {
    const response = await fetch(url, {headers});
    return await response.text();
}"""


def _wait_for_incapsula_cookies(page, timeout_ms: int) -> None:  # pragma: no cover -- real-browser boundary
    """Poll document.cookie for both Incapsula cookies, tolerant of navigation.

    Incapsula's challenge can trigger a redirect/reload while this is
    polling, which destroys the page's JS execution context mid-check --
    catch that per iteration and keep polling instead of propagating it.
    Best-effort: on timeout, proceeds anyway and lets the caller's
    is_incapsula_challenge() check on the actual response catch a real block.
    """
    import time

    from playwright.sync_api import Error as PlaywrightError

    check_js = (
        f"document.cookie.includes('{_FINGERPRINT_COOKIE}=') && "
        f"/{_SESSION_COOKIE_PREFIX}/.test(document.cookie)"
    )
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            if page.evaluate(check_js):
                return
        except PlaywrightError:
            pass
        page.wait_for_timeout(200)


def _launch_and_fetch(  # pragma: no cover -- real-browser boundary, not unit-testable
    executable_path: str, bootstrap_url: str, url: str, headers: dict
) -> dict:
    import json

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable_path, headless=True)
        try:
            page = browser.new_page()
            page.goto(bootstrap_url)
            try:
                page.wait_for_load_state("networkidle", timeout=_FINGERPRINT_COOKIE_TIMEOUT_MS)
            except PlaywrightError:
                pass  # best-effort -- a lingering connection shouldn't block the cookie poll

            _wait_for_incapsula_cookies(page, _FINGERPRINT_COOKIE_TIMEOUT_MS)

            if _EXTRA_SETTLE_MS:
                page.wait_for_timeout(_EXTRA_SETTLE_MS)

            try:
                body = page.evaluate(_FETCH_JS, {"url": url, "headers": headers})
            except PlaywrightError:
                # A late Incapsula redirect can still destroy the context right
                # as the fetch fires -- one retry after a short wait covers that.
                page.wait_for_timeout(500)
                body = page.evaluate(_FETCH_JS, {"url": url, "headers": headers})
        finally:
            browser.close()

    if is_incapsula_challenge(body):
        raise BrowserBlockedError(
            "Real-browser fetch was still blocked by Incapsula after waiting "
            "for both device-fingerprint and session cookies to be set"
        )
    return json.loads(body)
