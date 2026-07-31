"""
inspect_overlap.py — walk through the automated flow exactly like
update_window() does, then right before clicking Confirm & Apply Changes,
check EXACTLY what element the browser considers to be at that button's
screen position (elementFromPoint) — reveals whether something invisible
is covering it. Then does the real click and reports what changed.

Usage:
    python3 inspect_overlap.py <test_id> <start "YYYY-MM-DD HH:MM"> <end "...">
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
            p.wait_for_timeout(1000)

        hire._pick_day(start)
        p.wait_for_timeout(800)
        hire._pick_day(end)
        p.wait_for_timeout(800)
        hire._set_times(start, end)
        p.wait_for_timeout(800)

        confirm = p.locator(".applyBtn")
        confirm.wait_for(state="visible", timeout=10000)
        confirm.click()
        p.wait_for_timeout(1500)

        apply_changes = p.get_by_text("Apply Changes", exact=True)
        apply_changes.first.wait_for(state="visible", timeout=8000)
        apply_changes.first.scroll_into_view_if_needed()
        apply_changes.first.click()
        p.wait_for_timeout(1500)

        final = p.locator("#save_setting")
        final.first.wait_for(state="visible", timeout=8000)
        box = final.first.bounding_box()
        print(f"\nButton bounding box: {box}")

        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        elem_info = p.evaluate(f"""() => {{
            const el = document.elementFromPoint({cx}, {cy});
            if (!el) return {{found: false}};
            let path = [];
            let cur = el;
            for (let i = 0; i < 5 && cur; i++) {{
                path.push({{
                    tag: cur.tagName, id: cur.id, className: cur.className,
                    zIndex: getComputedStyle(cur).zIndex,
                    position: getComputedStyle(cur).position,
                    pointerEvents: getComputedStyle(cur).pointerEvents,
                    opacity: getComputedStyle(cur).opacity,
                }});
                cur = cur.parentElement;
            }}
            return {{found: true, isTargetButton: el.id === 'save_setting', path: path}};
        }}""")
        print(f"\n=== What's ACTUALLY at the button's center point ({cx}, {cy}) ===")
        print(f"Is it the save_setting button itself? {elem_info.get('isTargetButton')}")
        for i, node in enumerate(elem_info.get("path", [])):
            print(f"  [{i}] tag={node['tag']} id={node['id']!r} class={node['className']!r} "
                  f"z-index={node['zIndex']!r} position={node['position']!r} "
                  f"pointer-events={node['pointerEvents']!r} opacity={node['opacity']!r}")

        print("\nNow doing the real click and checking result...")
        final.first.click(timeout=5000)
        p.wait_for_timeout(2000)
        still_open = p.locator("text=Confirm & Apply Changes").count()
        print(f"'Confirm & Apply Changes' still present after click: {still_open > 0}")

        p.screenshot(path="overlap_result.png")
        print("Screenshot saved to overlap_result.png")
        print("Browser stays open 15s, then closes.")
        p.wait_for_timeout(15000)

        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
