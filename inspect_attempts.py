"""
inspect_attempts.py
===================
Diagnostic: open the scheduled class for a given batch and REPORT the
'+ Add Questions' links (count + each popup's URL/test-id) WITHOUT setting any
dates. Confirms attempt ordering before the agent writes re-attempt windows.

Usage:
    python3 inspect_attempts.py "Advanced DSA 2: NV Contest July 2026"
"""

import sys
sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright
from config import BROWSER, URLS


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    batch_name = sys.argv[1]

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, slow_mo=BROWSER.slow_mo_ms)
        c = b.new_context(storage_state=BROWSER.storage_state)
        c.set_default_timeout(BROWSER.default_timeout_ms)
        p = c.new_page()
        p.goto("https://www.scaler.com/scm/classes/edit-super-batch")
        print("Navigate to the scheduled class for:", batch_name)
        print("In the browser: open Schedule > View Scheduled Classes, find the")
        print("class, and open its Group Contest Summary (the 4 cards).")
        input(">>> When you can SEE the 4 contest cards with '+ Add Questions', press Enter...")

        links = p.get_by_role("link", name="+ Add Questions")
        n = links.count()
        print(f"\nFound {n} '+ Add Questions' link(s).")
        # Open each in order, report URL, then close.
        for i in range(n):
            try:
                with p.expect_popup() as info:
                    p.get_by_role("link", name="+ Add Questions").nth(i).click()
                pop = info.value
                pop.wait_for_load_state("load")
                print(f"  link #{i}: {pop.url}")
                pop.close()
                p.wait_for_timeout(400)
            except Exception as e:
                print(f"  link #{i}: ERROR {str(e)[:60]}")
        print("\nDone. Note the order of test-ids vs Contest/Re-attempt 1/2/3.")
        p.wait_for_timeout(2000)
        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
