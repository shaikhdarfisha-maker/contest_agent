"""
inspect_pickday_visual.py — click the days via our real _pick_day code,
then show/screenshot what the picker itself displays BEFORE clicking Apply.
Does not save anything. Run this yourself (not me) to avoid competing for
Scaler's 2-session limit with your own browser tab.

Usage:
    python3 inspect_pickday_visual.py <test_id> <start "YYYY-MM-DD HH:MM"> <end "...">
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
        b = pw.chromium.launch(headless=False, slow_mo=200)
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

        shown = p.evaluate("""() => {
            const el = document.querySelector('.daterangepicker .drp-selected');
            return el ? el.textContent.trim() : null;
        }""")
        print("Picker 'drp-selected' display text RIGHT BEFORE apply:", shown)
        p.screenshot(path="pickday_result.png")
        print("Screenshot saved to pickday_result.png (in this folder)")
        print()
        print("Browser stays open 15s so you can look at it yourself, then closes.")
        p.wait_for_timeout(15000)

        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
