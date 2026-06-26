"""
setup_auth.py
=============
One-time helper to log in to Scaler (SSO) by hand and persist the browser
auth state so the agent's subsequent runs are non-interactive.

Run:
    python setup_auth.py

A headed browser opens at the Admin V2 batches page. Complete the login, then
return to the terminal and press Enter. The cookies/localStorage are saved to
the path in STORAGE_STATE_PATH (config.BROWSER.storage_state).
"""

from __future__ import annotations

from config import URLS
from modules.browser import BrowserManager
from modules.logger import get_logger

log = get_logger("setup_auth")


def main() -> None:
    with BrowserManager(headless=False) as bm:
        bm.page.goto(URLS["admin_batches"])
        print(
            "\nComplete the Scaler login in the opened browser window.\n"
            "Once you can see the Admin V2 batches page, return here and press "
            "Enter to save the session..."
        )
        input()
        bm.save_auth()
        print("Auth state saved. Future runs will reuse this session.")


if __name__ == "__main__":
    main()
