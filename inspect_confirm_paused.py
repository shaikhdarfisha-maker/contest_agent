"""
inspect_confirm_paused.py — walk up to the "review changes" confirm modal,
then PAUSE so you can interactively compare a manual click against the
script's own click, in the exact same browser/page state.

Usage:
    python3 inspect_confirm_paused.py <test_id> <start "YYYY-MM-DD HH:MM"> <end "...">

When it pauses, a separate "Playwright Inspector" window opens alongside
the browser. Instructions will print in this terminal at that point.
"""
import re
import sys

sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright
from config import BROWSER
from modules.hire_test import HireTest
from modules.utils import parse_datetime


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    test_id = sys.argv[1]
    start = parse_datetime(sys.argv[2])
    end = parse_datetime(sys.argv[3])

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, slow_mo=150)
        c = b.new_context(storage_state=BROWSER.storage_state)
        c.set_default_timeout(BROWSER.default_timeout_ms)
        p = c.new_page()
        p.goto(f"https://www.scaler.com/hire/test/{test_id}/#/basic-settings")
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(1500)
        p.get_by_role("link", name="Test Settings").click(timeout=8000)
        p.wait_for_timeout(1500)

        hire = HireTest(p)
        date_span = p.get_by_text(
            re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2} (AM|PM)")
        ).first
        date_span.click(timeout=8000)
        p.wait_for_selector(".daterangepicker", timeout=10000)
        p.wait_for_timeout(500)

        custom_range = p.locator(".ranges li").filter(has_text="Custom Range")
        if custom_range.count() > 0:
            custom_range.first.click(timeout=3000)
            p.wait_for_timeout(200)

        hire._pick_day(start)
        p.wait_for_timeout(300)
        hire._pick_day(end)
        p.wait_for_timeout(300)
        hire._set_times(start, end)
        p.wait_for_timeout(300)

        confirm = p.locator(".applyBtn")
        confirm.wait_for(state="visible", timeout=10000)
        confirm.click()
        p.wait_for_timeout(1000)

        apply_changes = p.get_by_text("Apply Changes", exact=True)
        apply_changes.first.wait_for(state="visible", timeout=8000)
        apply_changes.first.scroll_into_view_if_needed()
        apply_changes.first.click()
        p.wait_for_timeout(2000)

        print()
        print("=" * 70)
        print("PAUSED. A separate 'Playwright Inspector' window should have opened.")
        print()
        print("In the BROWSER window (not the Inspector), you should see the")
        print("'Please review the recent changes...' popup with 'Confirm & Apply")
        print("Changes'. Two things to try, IN ORDER:")
        print()
        print("  1. Click 'Confirm & Apply Changes' YOURSELF, with your mouse,")
        print("     in that browser window right now. Does it close normally?")
        print()
        print("  2. In the Inspector window, click the blue 'Resume' (play) button")
        print("     to let this script continue and try its own click.")
        print()
        print("Tell Claude what happened in step 1 (worked or not).")
        print("=" * 70)
        p.pause()

        print("\nResumed. Checking if the modal is still open...")
        still_open = p.locator("text=Confirm & Apply Changes").count()
        print(f"'Confirm & Apply Changes' still present: {still_open > 0}")

        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
