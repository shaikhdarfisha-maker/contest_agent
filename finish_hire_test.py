"""
finish_hire_test.py
===================
Targeted helper: open ONE existing Hire Test by its id and apply the contest
start/end dates, using the tour-overlay-aware HireTest module. No batch creation
or scheduling. Use to finish a contest whose Hire Test step failed.

Usage:
    python3 finish_hire_test.py <test_id> <start "YYYY-MM-DD HH:MM"> <end "...">
Example:
    python3 finish_hire_test.py 1277558 "2026-06-26 21:00" "2026-07-03 21:00"
"""

import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

from config import BROWSER, URLS
from modules.hire_test import HireTest
from modules.utils import AttemptWindow, parse_datetime


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    test_id = sys.argv[1]
    start = parse_datetime(sys.argv[2])
    end = parse_datetime(sys.argv[3])
    window = AttemptWindow("Contest", start, end)

    url = f"{URLS['hire_test_base']}/{test_id}/#/basic-settings"
    print(f"Opening Hire Test {test_id} at {url}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=BROWSER.slow_mo_ms)
        context = browser.new_context(storage_state=BROWSER.storage_state)
        context.set_default_timeout(BROWSER.default_timeout_ms)
        page = context.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")

        hire = HireTest(page)
        result = hire.update_window(window)

        print()
        print("Applied   :", result.applied)
        print("Verified  :", result.verified)
        print("Window    :", result.start, "->", result.end)
        print("Done. Review the browser, then close it.")
        page.wait_for_timeout(4000)
        context.close()
        browser.close()
    return 0 if True else 1


if __name__ == "__main__":
    sys.exit(main())
