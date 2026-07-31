"""
inspect_picker_internals.py — diagnose the Contest/A1 hire-test date-picker bug.
Opens hire test 1291900, opens its date-range picker, and dumps the picker's
internal state (maxSpan, minDate, maxDate, etc.) before and after setting
start/end dates separately. Prints only — applies nothing permanent (the
picker changes are local to the open popup; no "Apply Changes" is clicked).

Usage:
    python3 inspect_picker_internals.py
"""
import sys
sys.path.insert(0, '.')
from playwright.sync_api import sync_playwright
from config import BROWSER

PICKER_FIND_JS = """() => {
    let picker = null;
    const allEls = document.querySelectorAll('*');
    outer: for (const el of allEls) {
        const jqData = jQuery.data(el);
        if (!jqData) continue;
        for (const k in jqData) {
            const v = jqData[k];
            if (v && v.startDate && v.endDate && typeof v.setStartDate === 'function') {
                picker = v; break outer;
            }
        }
    }
    return picker;
}"""


def main() -> int:
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=False, slow_mo=200)
        c = b.new_context(storage_state=BROWSER.storage_state)
        c.set_default_timeout(BROWSER.default_timeout_ms)
        p = c.new_page()

        p.goto("https://www.scaler.com/hire/test/1291900/#/basic-settings")
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(1500)
        p.get_by_role("link", name="Test Settings").click(timeout=8000)
        p.wait_for_timeout(1500)

        import re
        date_span = p.get_by_text(
            re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2} (AM|PM)")
        ).first
        date_span.click(timeout=8000)
        p.wait_for_timeout(800)

        info = p.evaluate(f"""() => {{
            const picker = ({PICKER_FIND_JS})();
            if (!picker) return {{ok: false}};
            return {{
                ok: true,
                startDate: picker.startDate ? picker.startDate.format() : null,
                endDate: picker.endDate ? picker.endDate.format() : null,
                maxSpan: JSON.stringify(picker.maxSpan || null),
                minDate: picker.minDate ? picker.minDate.format() : null,
                maxDate: picker.maxDate ? picker.maxDate.format() : null,
                autoApply: picker.autoApply,
                localeFormat: picker.locale ? picker.locale.format : null,
                timePicker24Hour: picker.timePicker24Hour,
                timePicker: picker.timePicker,
            }};
        }}""")
        print("BEFORE any changes:", info)

        # Try setStartDate with a real moment object instead of a raw string,
        # to sidestep any locale.format string-parsing mismatch entirely.
        r1 = p.evaluate("""() => {
            const picker = (""" + PICKER_FIND_JS + """)();
            if (!picker) return {ok: false};
            const m = moment('2026-07-31T21:00:00');
            picker.setStartDate(m);
            return { startDate: picker.startDate.format(), endDate: picker.endDate.format(),
                     momentValid: m.isValid(), momentFormatted: m.format() };
        }""")
        print("AFTER setStartDate(moment('2026-07-31T21:00:00')):", r1)

        r2 = p.evaluate("""() => {
            const picker = (""" + PICKER_FIND_JS + """)();
            if (!picker) return {ok: false};
            const m = moment('2026-08-07T21:00:00');
            picker.setEndDate(m);
            return { startDate: picker.startDate.format(), endDate: picker.endDate.format(),
                     momentValid: m.isValid(), momentFormatted: m.format() };
        }""")
        print("AFTER setEndDate(moment('2026-08-07T21:00:00')):", r2)

        print("\nDone. Browser stays open 8s for visual check, then closes.")
        p.wait_for_timeout(8000)
        c.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
