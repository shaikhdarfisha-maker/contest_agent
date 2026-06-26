"""
hire_test.py
============
System 3 - Hire Test test settings (opened as a popup from CCT "Add Questions").

The date control is a bootstrap-daterangepicker with TWO month panels shown
side by side (.drp-calendar.left = earlier month, .drp-calendar.right = later
month) plus start/end time dropdowns and a Confirm button (.applyBtn).

Correct flow (confirmed from live screenshots):
  1. Remove the onboarding "tour-backdrop" overlay (it intercepts clicks).
  2. Open Test Settings.
  3. Click the date field (the "<Month> DD, YYYY ..." span) to open the picker.
  4. Click the START day in whichever panel shows the start month.
  5. Click the END day in whichever panel shows the end month.
  6. Set start and end time dropdowns (hour / minute / AM-PM).
  7. Click Confirm, then Apply Changes -> Confirm & Apply Changes.
  8. Verify the field text now reflects the requested start AND end dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from playwright.sync_api import Page

from modules.logger import get_logger
from modules.utils import AttemptWindow, BrowserStepError, retry

log = get_logger(__name__)


@dataclass
class HireTestResult:
    test_id: str
    applied: bool
    start: datetime
    end: datetime
    verified: bool


class HireTest:
    """Page object for updating a Hire Test's start/end window (popup page)."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @retry(exceptions=(BrowserStepError,))
    def update_window(self, window: AttemptWindow) -> HireTestResult:
        """Set and apply the start/end date+time for the main Contest window."""
        test_id = self._test_id_from_url()
        log.info(
            "Updating Hire Test %s: %s -> %s",
            test_id,
            window.start,
            window.end,
        )

        self._dismiss_tour_overlay()

        # Open Test Settings tab.
        try:
            self.page.get_by_role("link", name="Test Settings").click()
            self.page.wait_for_load_state("networkidle")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not open Test Settings: {exc}")
        self._dismiss_tour_overlay()

        # Open the date-range picker by clicking the date field span.
        try:
            self.page.get_by_text(
                re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4} \d{2}:\d{2} (AM|PM)")
            ).first.click()
            self.page.wait_for_selector(".daterangepicker", timeout=10000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not open date-range picker: {exc}")

        # Pick start and end days in the correct month panels.
        try:
            self._pick_day(window.start)
            self._pick_day(window.end)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not pick start/end days: {exc}")

        # Set the time dropdowns (start = left selects, end = right selects).
        try:
            self._set_times(window.start, window.end)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not set time dropdowns precisely: %s", exc)

        # Confirm within the picker, then apply on the page.
        try:
            confirm = self.page.locator(".applyBtn")
            confirm.wait_for(state="visible", timeout=10000)
            # Wait until enabled (range valid) before clicking.
            for _ in range(20):
                if confirm.is_enabled():
                    break
                self.page.wait_for_timeout(250)
            confirm.click()
            self.page.wait_for_timeout(800)

            # Click "Apply Changes" (may open a confirm prompt, or apply directly).
            apply_btn = self.page.get_by_text("Apply Changes", exact=True)
            apply_btn.first.scroll_into_view_if_needed()
            apply_btn.first.click()
            self.page.wait_for_timeout(800)

            # If a "Confirm & Apply Changes" modal appears, click it. It's not
            # always present, so treat its absence as already-applied.
            final = self.page.locator("#save_setting")
            if final.count() == 0:
                final = self.page.get_by_text("Confirm & Apply Changes")
            try:
                if final.count() > 0:
                    final.first.wait_for(state="visible", timeout=5000)
                    final.first.scroll_into_view_if_needed()
                    final.first.click()
            except Exception:  # noqa: BLE001
                log.debug("No 'Confirm & Apply Changes' modal to click.")
            self.page.wait_for_load_state("networkidle")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not apply changes: {exc}")

        verified = self._verify(window)
        if not verified:
            raise BrowserStepError(
                "Applied, but verification failed: the date field does not show "
                "the requested start AND end dates."
            )
        log.info("Hire Test %s applied and verified", test_id)
        return HireTestResult(
            test_id=test_id,
            applied=True,
            start=window.start,
            end=window.end,
            verified=verified,
        )

    # ------------------------------------------------------------------ #
    def _pick_day(self, dt: datetime) -> None:
        """
        Click the day cell for `dt` in whichever calendar panel currently shows
        that month/year. Navigates the picker (prev/next arrows) if needed.
        """
        target_month = dt.strftime("%b %Y")  # e.g. "Jun 2026"
        day = str(dt.day)

        for _ in range(6):  # up to 6 nav steps to bring the month into view
            left_hdr = self._panel_header(".drp-calendar.left")
            right_hdr = self._panel_header(".drp-calendar.right")

            if target_month in (left_hdr or ""):
                panel = ".drp-calendar.left"
            elif target_month in (right_hdr or ""):
                panel = ".drp-calendar.right"
            else:
                # Navigate: if target is before left header, go prev; else next.
                if self._month_is_before(target_month, left_hdr):
                    self.page.locator(".drp-calendar.left .prev").click()
                else:
                    self.page.locator(".drp-calendar.right .next").click()
                self.page.wait_for_timeout(300)
                continue

            # Click the day cell that is "available" (not off-month/disabled).
            cell = self.page.locator(
                f"{panel} td.available:not(.off)"
            ).filter(has_text=re.compile(rf"^{day}$"))
            cell.first.click()
            return
        raise BrowserStepError(f"Could not bring {target_month} into the picker.")

    def _panel_header(self, panel_sel: str) -> Optional[str]:
        try:
            return self.page.locator(
                f"{panel_sel} .month"
            ).first.inner_text(timeout=3000).strip()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _month_is_before(target: str, header: Optional[str]) -> bool:
        """True if target month/year is earlier than the header month/year."""
        if not header:
            return False
        try:
            t = datetime.strptime(target, "%b %Y")
            h = datetime.strptime(header, "%b %Y")
            return t < h
        except Exception:  # noqa: BLE001
            return False

    def _set_times(self, start: datetime, end: datetime) -> None:
        """Set the hour/minute/AM-PM dropdowns for start and end."""
        selects = self.page.locator(".daterangepicker select")
        # Expected order: [startHour, startMin, startAmPm, endHour, endMin, endAmPm]
        if selects.count() < 6:
            return
        values = [
            start.strftime("%I").lstrip("0") or "12",
            start.strftime("%M"),
            start.strftime("%p"),
            end.strftime("%I").lstrip("0") or "12",
            end.strftime("%M"),
            end.strftime("%p"),
        ]
        for i, val in enumerate(values):
            try:
                selects.nth(i).select_option(label=val)
            except Exception:  # noqa: BLE001
                try:
                    selects.nth(i).select_option(value=val)
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ #
    def _dismiss_tour_overlay(self) -> None:
        for name in ("Skip", "Close", "Got it", "Next", "Done"):
            try:
                btn = self.page.get_by_role("button", name=name)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click(timeout=2000)
                    self.page.wait_for_timeout(200)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.page.evaluate(
                """
                () => {
                  const sels = ['.tour-backdrop', '.introjs-overlay',
                                '.introjs-helperLayer', '[class*="tour"]'];
                  for (const s of sels)
                    document.querySelectorAll(s).forEach(el => el.remove());
                }
                """
            )
            self.page.wait_for_timeout(150)
        except Exception:  # noqa: BLE001
            log.debug("Tour overlay removal script did not run cleanly.")

    def _test_id_from_url(self) -> str:
        match = re.search(r"/hire/test/(\d+)", self.page.url)
        return match.group(1) if match else "unknown"

    def _verify(self, window: AttemptWindow) -> bool:
        """
        Real verification: the date field must show BOTH the requested start
        date and the requested end date (e.g. 'June 26, 2026' and 'July 3, 2026').
        """
        try:
            body = self.page.locator("body").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001
            return False

        def variants(d: datetime) -> list[str]:
            full = d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else ""
            # %-d may not work on all platforms; build day without leading zero.
            day = str(d.day)
            return [f"{d.strftime('%B')} {day}, {d.year}"]

        start_ok = any(v in body for v in variants(window.start))
        end_ok = any(v in body for v in variants(window.end))
        if not (start_ok and end_ok):
            log.warning(
                "Verify: start_ok=%s end_ok=%s (looking for %s / %s)",
                start_ok,
                end_ok,
                variants(window.start),
                variants(window.end),
            )
        return start_ok and end_ok
