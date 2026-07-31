"""
inspect_confirm_button.py — open a hire test, walk through setting a date,
then when the "review changes" modal appears, inspect EVERY element matching
"Confirm & Apply Changes" (count, visibility, position, tag, id, class),
click the one Playwright would pick, and report what happened.

Usage:
    python3 inspect_confirm_button.py <test_id> <start "YYYY-MM-DD HH:MM"> <end "...">
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
        print("Clicked picker's internal Apply button.")
        p.wait_for_timeout(1000)

        apply_changes = p.get_by_text("Apply Changes", exact=True)
        apply_changes.first.wait_for(state="visible", timeout=8000)
        apply_changes.first.scroll_into_view_if_needed()
        apply_changes.first.click()
        print("Clicked page-level 'Apply Changes' button.")
        p.wait_for_timeout(2000)

        # Wait for the review-changes modal to actually appear.
        try:
            p.wait_for_selector("text=Confirm & Apply Changes", timeout=6000)
        except Exception as e:
            print("Modal never appeared:", e)

        matches = p.get_by_text("Confirm & Apply Changes")
        n = matches.count()
        print(f"\n=== Found {n} element(s) matching 'Confirm & Apply Changes' ===")
        for i in range(n):
            el = matches.nth(i)
            try:
                vis = el.is_visible()
                box = el.bounding_box()
                info = el.evaluate("""e => ({
                    tag: e.tagName, id: e.id, className: e.className,
                    disabled: e.disabled, outerHTML: e.outerHTML.substring(0, 200)
                })""")
                print(f"[{i}] visible={vis} box={box}")
                print(f"    tag={info['tag']} id={info['id']!r} class={info['className']!r} disabled={info['disabled']}")
                print(f"    html={info['outerHTML']!r}")
            except Exception as e:
                print(f"[{i}] error reading element: {e}")

        if n > 0:
            print("\nClicking element [0] (what Playwright's .first would pick)...")
            matches.first.click(timeout=5000)
            p.wait_for_timeout(2000)
            still_open_after_click = p.locator("text=Confirm & Apply Changes").count()
            print(f"Still present after normal click: {still_open_after_click > 0}")

            if still_open_after_click > 0:
                print("\nTrying direct Angular function call instead of a simulated click...")
                result = p.evaluate("""() => {
                    const el = document.getElementById('save_setting');
                    if (!el) return {ok: false, reason: 'element not found'};
                    const scope = angular.element(el).scope();
                    if (!scope) return {ok: false, reason: 'no angular scope on element'};
                    if (typeof scope.saveTestBasicSettings !== 'function') {
                        return {ok: false, reason: 'saveTestBasicSettings not a function on this scope'};
                    }
                    try {
                        scope.saveTestBasicSettings(null, true);
                        scope.$apply();
                        return {ok: true};
                    } catch (e) {
                        return {ok: false, reason: 'threw: ' + e.message};
                    }
                }""")
                print("Direct Angular call result:", result)
                p.wait_for_timeout(2000)
                still_open_after_direct = p.locator("text=Confirm & Apply Changes").count()
                print(f"Still present after direct call: {still_open_after_direct > 0}")
            still_open = p.locator("text=Confirm & Apply Changes").count()
            print(f"'Confirm & Apply Changes' still present after click: {still_open > 0}")

        p.screenshot(path="confirm_button_result.png")
        print("\nScreenshot saved to confirm_button_result.png")
        print("Browser stays open 20s for you to look, then closes.")
        p.wait_for_timeout(20000)

        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
