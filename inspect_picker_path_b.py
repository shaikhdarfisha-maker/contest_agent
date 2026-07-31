"""
inspect_picker_path_b.py — test whether REAL click-based day/time picking
(Path B: _pick_day + _set_times, genuine Playwright clicks, not JS-injected
state) correctly persists to the server, as a diagnostic for why
_set_picker_dates_js's JS-only state change isn't reaching AngularJS $scope.

Usage:
    python3 inspect_picker_path_b.py <test_id> <start "YYYY-MM-DD HH:MM"> <end "...">
"""
import re
import sys
from datetime import datetime

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

        hire = HireTest(p)
        hire._dismiss_tour_overlay()
        p.get_by_role("link", name="Test Settings").click(timeout=8000)
        p.wait_for_timeout(1500)

        date_span = p.get_by_text(
            re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2} (AM|PM)")
        ).first
        date_span.click(timeout=8000)
        p.wait_for_selector(".daterangepicker", timeout=10000)
        p.wait_for_timeout(500)

        chosen_before = p.evaluate("""() => {
            const el = document.querySelector('.daterangepicker');
            const d = jQuery(el).data('daterangepicker');
            return d ? d.chosenLabel : null;
        }""")
        print("chosenLabel BEFORE clicking Custom Range:", chosen_before)

        try:
            custom_range = p.locator(".ranges li").filter(has_text="Custom Range")
            custom_range.first.click(timeout=3000)
            print("Clicked 'Custom Range' in the sidebar.")
            p.wait_for_timeout(300)
        except Exception as e:
            print("Could not click 'Custom Range':", e)

        chosen_after = p.evaluate("""() => {
            const el = document.querySelector('.daterangepicker');
            const d = jQuery(el).data('daterangepicker');
            return d ? d.chosenLabel : null;
        }""")
        print("chosenLabel AFTER clicking Custom Range:", chosen_after)

        print("Picking start day via real click...")
        hire._pick_day(start)
        p.wait_for_timeout(300)
        print("Picking end day via real click...")
        hire._pick_day(end)
        p.wait_for_timeout(300)
        print("Setting time dropdowns via real select_option...")
        hire._set_times(start, end)
        p.wait_for_timeout(300)

        # Read back what the picker's own display currently shows before
        # clicking Apply, to sanity-check the clicks landed correctly.
        shown = p.evaluate("""() => {
            const el = document.querySelector('.daterangepicker .drp-selected');
            return el ? el.textContent.trim() : null;
        }""")
        print("Picker 'drp-selected' display text:", shown)

        confirm = p.locator(".applyBtn")
        confirm.wait_for(state="visible", timeout=10000)
        confirm.click()
        print("Clicked picker's internal Apply button.")
        p.wait_for_timeout(1000)

        apply_btn = p.get_by_text("Apply Changes", exact=True)
        apply_btn.first.wait_for(state="visible", timeout=8000)
        apply_btn.first.click()
        print("Clicked page-level 'Apply Changes'.")
        p.wait_for_timeout(3000)

        verified = hire._verify(
            __import__("modules.utils", fromlist=["AttemptWindow"]).AttemptWindow(
                "Contest", start, end
            ),
            test_id=test_id,
        )
        print("Verified:", verified)

        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
