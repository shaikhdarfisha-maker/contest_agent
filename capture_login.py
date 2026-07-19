"""
capture_login.py
================
One-time local helper to refresh the Scaler SSO session and persist it so
the headless agent can reuse it on subsequent runs (including Community Cloud).

Run:
    python capture_login.py

A headed Chromium window opens. Complete the Google/corporate SSO login, then
return to this terminal and press Enter at each prompt.  The session is saved
to data/storage_state.json and a base64 copy is printed for pasting into the
STORAGE_STATE_B64 Streamlit secret.

Both files are gitignored — do NOT commit them.
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
    print("A headed browser will open. Complete the Scaler SSO login,")
    print("then return here and press Enter at each step.\n")

    with BrowserManager(headless=False) as bm:
        bm.page.goto(URLS["admin_batches"])
        print("Step 1 — Log in to Admin V2 (scaler.com/admin).")
        print("Once the Batches table is visible, press Enter ...")
        input()

        bm.page.goto("https://www.scaler.com/scm/classes/schedule-classes")
        print("\nStep 2 — Verify CCT access (scaler.com/scm).")
        print("Once the Schedule Classes page loads, press Enter ...")
        input()

        bm.save_auth()

    state_path = Path(BROWSER.storage_state)
    if not state_path.exists():
        print("\n❌ storage_state.json not found — save_auth() may have failed.")
        return

    b64 = base64.b64encode(state_path.read_bytes()).decode()
    b64_path = state_path.with_suffix(".b64")
    b64_path.write_text(b64)

    print(f"\n✅ Auth state saved  → {state_path}")
    print(f"✅ Base64 copy saved → {b64_path}")
    print("\n── For Streamlit Community Cloud ─────────────────────────────────────")
    print("Add this to your app secrets (Settings → Secrets):")
    print(f'\nSTORAGE_STATE_B64 = "{b64}"')
    print("\n──────────────────────────────────────────────────────────────────────")
    print("For a local / server deployment, just keep data/storage_state.json.")
    print("The file is gitignored — never commit it.\n")


if __name__ == "__main__":
    main()
