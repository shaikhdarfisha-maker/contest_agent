import sys
sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright
from config import BROWSER, URLS

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=False)
    c = b.new_context(storage_state=BROWSER.storage_state)
    p = c.new_page()
    p.goto(URLS['hire_test_base'] + '/1277558/#/basic-settings')
    p.wait_for_load_state('networkidle')
    p.wait_for_timeout(2000)
    p.evaluate("() => { document.querySelectorAll('.tour-backdrop,[class*=tour]').forEach(e => e.remove()) }")
    input('>>> In the browser: open Test Settings, click the date field so the calendar shows, THEN press Enter here...')

    candidates = ['td', '.day', '[role=gridcell]', '.datepicker td', '.calendar td', '.uib-day button']
    for sel in candidates:
        els = p.locator(sel)
        n = els.count()
        if 0 < n < 80:
            print('=== selector', repr(sel), '->', n, 'elements ===')
            for i in range(min(n, 15)):
                try:
                    txt = els.nth(i).inner_text().strip()
                    cls = els.nth(i).get_attribute('class')
                    print('  text=', repr(txt), ' class=', cls)
                except Exception:
                    pass
            print()
    print('Done. Close the browser window.')
    p.wait_for_timeout(1000)
    c.close()
    b.close()
