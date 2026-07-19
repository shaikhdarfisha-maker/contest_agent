"""
browser.py
==========
Playwright lifecycle management shared by every page object:

  * launches Chromium headless (HEADLESS env var, default true),
  * reuses a persisted storage_state so we don't script the login each run,
  * detects mid-run SSO redirects so the orchestrator can abort cleanly,
  * captures a screenshot automatically on any failure.

Page objects (batch_creator, schedule_creator, hire_test) receive the live
`page` from here and only own their own selectors and step logic.

Headless is the only supported mode on Streamlit Community Cloud.  To open
a visible browser locally for debugging set HEADLESS=false in your .env.
Use capture_login.py (not this module) for the one-time auth capture.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from config import BROWSER, SCREENSHOTS_DIR
from modules.logger import get_logger

log = get_logger(__name__)

# URL fragments that indicate a login / SSO redirect page.
_LOGIN_URL_PATTERNS = (
    "accounts.google.com",
    "/login",
    "/sign-in",
    "signin",
    "/auth",
)

# Chromium flags for low-memory / sandboxless environments
# (Streamlit Community Cloud / Docker / CI).  Safe to pass on macOS too.
_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]


class BrowserManager:
    """Context-managed Playwright browser with auth reuse and error capture."""

    def __init__(self, headless: Optional[bool] = None) -> None:
        self.headless = BROWSER.headless if headless is None else headless
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # -- lifecycle --------------------------------------------------------- #
    def __enter__(self) -> "BrowserManager":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            slow_mo=BROWSER.slow_mo_ms,
            args=_LAUNCH_ARGS,
        )

        storage = BROWSER.storage_state
        storage_exists = bool(storage) and Path(storage).exists()
        self._context = self._browser.new_context(
            storage_state=storage if storage_exists else None
        )
        self._context.set_default_timeout(BROWSER.default_timeout_ms)
        self._context.set_default_navigation_timeout(BROWSER.nav_timeout_ms)
        self._page = self._context.new_page()

        if not storage_exists:
            log.warning(
                "No saved auth state at %s — run capture_login.py to create one.",
                storage,
            )
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if exc is not None:
            self.capture_error("unhandled_exception")
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    # -- accessors --------------------------------------------------------- #
    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserManager used outside its context.")
        return self._page

    def new_hire_page(self, test_id: str) -> Page:
        """Open a fresh page at a Hire Test's basic-settings, return it."""
        from config import URLS

        if self._context is None:
            raise RuntimeError("BrowserManager used outside its context.")
        page = self._context.new_page()
        page.goto(f"{URLS['hire_test_base']}/{test_id}/#/basic-settings")
        page.wait_for_load_state("networkidle")
        return page

    def save_auth(self) -> None:
        """Persist cookies/localStorage so subsequent runs skip the login."""
        if self._context and BROWSER.storage_state:
            self._context.storage_state(path=BROWSER.storage_state)
            log.info("Saved auth state to %s", BROWSER.storage_state)

    # -- session detection ------------------------------------------------- #
    def is_login_page(self, page: Optional[Page] = None) -> bool:
        """Return True if the given page (or main page) is on a login/SSO URL."""
        check = page or self._page
        if check is None:
            return False
        try:
            url = check.url.lower()
            return any(p in url for p in _LOGIN_URL_PATTERNS)
        except Exception:  # noqa: BLE001
            return False

    def any_login_page(self) -> bool:
        """Return True if ANY open page in the context is on a login/SSO URL."""
        if self._context is None:
            return False
        try:
            return any(
                any(pat in p.url.lower() for pat in _LOGIN_URL_PATTERNS)
                for p in self._context.pages
            )
        except Exception:  # noqa: BLE001
            return False

    # -- diagnostics ------------------------------------------------------- #
    def capture_error(self, label: str) -> Optional[Path]:
        """Save a full-page screenshot for post-mortem debugging."""
        if self._page is None:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"error_{label}_{ts}.png"
        try:
            self._page.screenshot(path=str(path), full_page=True)
            log.error("Captured error screenshot: %s", path.name)
            return path
        except Exception as shot_exc:  # pragma: no cover - best effort
            log.error("Failed to capture screenshot: %s", shot_exc)
            return None
