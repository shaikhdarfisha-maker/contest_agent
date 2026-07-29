"""
capture_login.py
================
One-time local helper to refresh the Scaler SSO session.

Run:
    python capture_login.py

A Chromium window opens. Log in to Scaler in THAT window. The script
detects automatically when you reach the admin page and saves the session.

The file is gitignored — do NOT commit it.
"""

from __future__ import annotations

import base64
from pathlib import Path

from config import BROWSER, URLS
from modules.browser import BrowserManager
from modules.logger import get_logger

log = get_logger("capture_login")


def main() -> None:
    print("\n=== NV Contest Agent — Capture Login ===\n")
    print("A Chromium window will open NOW.")
    print("Log in to Scaler inside THAT window (not your normal Chrome).")
    print("The script will detect automatically when you reach the admin page.\n")

    with BrowserManager(headless=False) as bm:
        bm.page.goto(URLS["admin_batches"], wait_until="domcontentloaded")

        # Step 1: wait silently until admin page is reached (up to 3 minutes).
        print("Waiting for you to log in and reach the Admin V2 Batches page ...")
        print("(URL must contain /admin/academy/v2)\n")
        try:
            bm.page.wait_for_url(
                "**/admin/academy/v2**",
                timeout=180_000,  # 3 minutes
                wait_until="domcontentloaded",
            )
        except Exception:
            print("\n❌ Timed out (3 min). Please re-run and log in faster.")
            return

        print(f"✅ Admin V2 detected: {bm.page.url}")
        print("   Waiting for the Batches table to fully load ...")
        try:
            bm.page.wait_for_selector(".data-table__action--filter", timeout=15_000)
        except Exception:
            pass  # table may have a different selector — proceed anyway

        # Step 2: verify CCT access.
        print("\nNavigating to CCT (Schedule Classes) to verify access ...")
        bm.page.goto(
            "https://www.scaler.com/scm/classes/schedule-classes",
            wait_until="domcontentloaded",
        )
        try:
            bm.page.wait_for_url("**/scm/**", timeout=15_000)
            print(f"✅ CCT detected: {bm.page.url}")
        except Exception:
            print(f"⚠️  CCT URL check: {bm.page.url} (proceeding anyway)")

        bm.save_auth()

    state_path = Path(BROWSER.storage_state)
    if not state_path.exists():
        print("\n❌ storage_state.json not found — save_auth() may have failed.")
        return

    b64 = base64.b64encode(state_path.read_bytes()).decode()
    b64_path = state_path.with_suffix(".b64")
    b64_path.write_text(b64)

    print(f"\n✅ Auth state saved  → {state_path}")
    print("   Restart ./start.sh to pick up the new session.\n")


if __name__ == "__main__":
    main()
