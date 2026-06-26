"""
inspect_checkbox.py — walk the Schedule form to the checkbox step and report
what's actually on the page (URL + every checkbox label). Submits nothing.

Usage:
  python3 inspect_checkbox.py "<batch name>" "<library name>"
"""
import sys
sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright
from config import BROWSER

def main():
    if len(sys.argv) != 3:
        print(__doc__); return 2
    batch_name, library_name = sys.argv[1], sys.argv[2]
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, slow_mo=300)
        c = b.new_context(storage_state=BROWSER.storage_state)
        c.set_default_timeout(BROWSER.default_timeout_ms)
        p = c.new_page()
        p.goto("https://www.scaler.com/scm/classes/edit-super-batch")
        p.get_by_role("link", name="Schedule Classes").click()
        p.wait_for_load_state("networkidle")
        # batch
        p.locator(".css-32j6ly").first.click()
        p.locator("#react-select-3-input").fill(batch_name)
        p.get_by_text(f"{batch_name}Primary").click()
        # library (scoped option click)
        p.locator(".css-jlrko8 > .css-32j6ly").click()
        p.locator("#react-select-4-input").fill(library_name.replace("Academy: ", "").strip())
        p.wait_for_timeout(1000)
        opt = p.locator("[id^='react-select-4-option']").filter(has_text=library_name)
        if opt.count() == 0:
            p.locator("#react-select-4-input").press("Enter")
        else:
            opt.first.click()
        p.wait_for_timeout(1500)
        print("\n=== AFTER LIBRARY PICK ===")
        print("URL:", p.url)
        cbx = p.get_by_role("checkbox")
        print("Total checkboxes:", cbx.count())
        for i in range(cbx.count()):
            cb = cbx.nth(i)
            try:
                label = cb.evaluate(
                    "el => el.getAttribute('aria-label') "
                    "|| (el.labels&&el.labels[0]&&el.labels[0].innerText) "
                    "|| (el.closest('label')&&el.closest('label').innerText) "
                    "|| (el.parentElement&&el.parentElement.innerText) || ''")
            except Exception:
                label = "(unreadable)"
            print(f"  checkbox[{i}]: {label!r}")
        print("\nScroll the page in the browser if you don't see a 'Mandatory Skill")
        print("Evaluation' checkbox — tell Claude what you see. Browser stays 12s.")
        p.wait_for_timeout(12000)
        c.close(); b.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
