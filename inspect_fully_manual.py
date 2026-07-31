"""
inspect_fully_manual.py — open a hire test in Playwright's browser (using
the saved login session) and pause IMMEDIATELY, before any automated click
happens. You do every single step by hand: open Test Settings, open the
date picker, click Custom Range, pick both days, set times, click the
picker's Apply, click the page's Apply Changes, click Confirm & Apply
Changes. This isolates whether the saved session itself is the problem,
or whether it's specifically something the automated steps do.

Usage:
    python3 inspect_fully_manual.py <test_id>
"""
import sys

sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright
from config import BROWSER


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    test_id = sys.argv[1]

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, slow_mo=150)
        c = b.new_context(storage_state=BROWSER.storage_state)
        c.set_default_timeout(BROWSER.default_timeout_ms)
        p = c.new_page()
        p.goto(f"https://www.scaler.com/hire/test/{test_id}/#/basic-settings")
        p.wait_for_load_state("networkidle")

        print()
        print("=" * 70)
        print("PAUSED immediately — nothing has been clicked yet.")
        print()
        print("Do EVERY step yourself now, with your mouse, in the browser window:")
        print("  1. Click 'Test Settings' tab (if not already there)")
        print("  2. Click the date field to open the picker")
        print("  3. Click 'Custom Range' in the left sidebar")
        print("  4. Click the start day, then the end day, on the calendars")
        print("  5. Set the time dropdowns if needed")
        print("  6. Click the picker's own 'Apply' button")
        print("  7. Click the page's blue 'Apply Changes' button")
        print("  8. If a 'review changes' popup appears, click")
        print("     'Confirm & Apply Changes'")
        print()
        print("Tell Claude whether it saved correctly at the end.")
        print("When done, click the Inspector's Resume button to close this.")
        print("=" * 70)
        p.pause()

        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
