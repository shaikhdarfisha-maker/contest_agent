"""
finish_reattempts.py
====================
Set dates on specific Hire Test re-attempt IDs directly, using the proven
two-panel date picker. Tests re-attempt date-setting in isolation (no new
contest). Each id gets the next derived window after the main contest.

Usage:
    python3 finish_reattempts.py <a1_start> <a1_end> <ra1_id> <ra2_id> <ra3_id>
Example (Advanced DSA 2 July; main contest already set):
    python3 finish_reattempts.py "2026-06-26 21:00" "2026-07-03 21:00" 1277559 1277560 1277561
"""

import sys
sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright
from config import BROWSER, URLS
from modules.hire_test import HireTest
from modules.utils import derive_attempt_windows, parse_datetime


def main() -> int:
    if len(sys.argv) != 6:
        print(__doc__)
        return 2
    a1s = parse_datetime(sys.argv[1])
    a1e = parse_datetime(sys.argv[2])
    ra_ids = sys.argv[3:6]  # RA1, RA2, RA3 test ids

    windows = derive_attempt_windows(a1s, a1e)
    # windows[0] = Contest (already set), windows[1..3] = the 3 re-attempts
    ra_windows = windows[1:4]

    print("Re-attempt plan:")
    for tid, w in zip(ra_ids, ra_windows):
        print(f"  {tid}: {w.label}  {w.start} -> {w.end}")
    print()

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, slow_mo=BROWSER.slow_mo_ms)
        c = b.new_context(storage_state=BROWSER.storage_state)
        c.set_default_timeout(BROWSER.default_timeout_ms)
        results = []
        for tid, w in zip(ra_ids, ra_windows):
            p = c.new_page()
            p.goto(f"{URLS['hire_test_base']}/{tid}/#/basic-settings")
            p.wait_for_load_state("networkidle")
            try:
                res = HireTest(p).update_window(w)
                print(f"  {tid}: applied={res.applied} verified={res.verified}")
                results.append(res.verified)
            except Exception as e:
                print(f"  {tid}: ERROR {str(e)[:80]}")
                results.append(False)
            p.wait_for_timeout(1500)
            p.close()
        c.close()
        b.close()

    ok = sum(1 for r in results if r)
    print(f"\nDone. {ok}/{len(ra_ids)} re-attempts set and verified.")
    return 0 if ok == len(ra_ids) else 1


if __name__ == "__main__":
    sys.exit(main())
