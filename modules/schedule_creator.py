"""
schedule_creator.py
===================
System 2 - Classroom Creation Tool (CCT).
URL: https://www.scaler.com/scm/classes/schedule-classes (reached via
edit-super-batch > Schedule Classes link).

Real recorded flow:
  1. Open Schedule Classes.
  2. Batch react-select: type the batch name, click the "...Primary" option.
  3. Library react-select: type the library, click the exact match option.
  4. Tick "Mandatory Skill Evaluation".
  5. Slot react-select: type slot search text, click the day-appropriate slot
     (MWF or T-Th-Sat depending on the run day).
  6. Open the date calendar, click the start day cell.
  7. Confirm Schedule -> Confirm & Schedule.
  8. View Scheduled Classes -> open the class row.
  9. "+ Add Questions" opens a popup (the Hire Test) -> capture it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from playwright.sync_api import Page

from config import (
    DEFAULT_CONTEST_DURATION_MIN,
    URLS,
    schedule_slot_for_today,
)
from modules.library_reader import LibraryMatch
from modules.logger import get_logger
from modules.utils import BrowserStepError, retry

log = get_logger(__name__)


@dataclass
class ScheduleResult:
    batch_name: str
    library_name: str
    class_id: Optional[str] = None
    test_ids: list[str] = field(default_factory=list)
    hire_test_url: Optional[str] = None
    # The popup page (Hire Test) opened by "+ Add Questions".
    hire_page: object = None

    @property
    def contest_test_id(self) -> Optional[str]:
        return self.test_ids[0] if self.test_ids else None


class ScheduleCreator:
    """Page object for CCT class scheduling + reaching Hire Test."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @retry(exceptions=(BrowserStepError,))
    def schedule_class(
        self,
        batch_name: str,
        library: LibraryMatch,
        start: datetime,
        duration_min: int = DEFAULT_CONTEST_DURATION_MIN,
    ) -> ScheduleResult:
        """Create and save the scheduled class for this batch + library."""
        log.info(
            "Scheduling class for batch '%s' with library '%s'",
            batch_name,
            library.library_name,
        )
        self.page.goto("https://www.scaler.com/scm/classes/edit-super-batch")
        self.page.get_by_role("link", name="Schedule Classes").click()
        self.page.wait_for_load_state("networkidle")

        # --- batch react-select ------------------------------------------ #
        try:
            self.page.locator(".css-32j6ly").first.click()
            # Fill using whichever react-select input is focused after click.
            self.page.keyboard.type(batch_name)
            # Wait for at least one option to appear, then click the match.
            # React-select option IDs are dynamic; match any *-option-* div.
            self.page.wait_for_selector("[id*='-option-']", timeout=5_000)
            option = self.page.locator("[id*='-option-']").filter(has_text=batch_name)
            if option.count() == 0:
                option = self.page.locator("[class*='option']").filter(has_text=batch_name)
            option.first.click()
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not select batch '{batch_name}': {exc}")

        # --- library react-select ---------------------------------------- #
        # IMPORTANT: scope the option click to the react-select menu. The
        # library name can also appear elsewhere on the page as a link that
        # navigates to the Edit Library editor; clicking that would break the
        # flow. We click the option inside the open menu only.
        try:
            self.page.locator(".css-jlrko8 > .css-32j6ly").click()
            search = library.library_name.replace("Academy: ", "").strip()
            inp = self.page.locator("#react-select-4-input")
            inp.fill(search)

            # Wait up to 3s for at least one matching option to appear.
            try:
                self.page.wait_for_selector(
                    "[id^='react-select-4-option']", timeout=3_000
                )
            except Exception:  # noqa: BLE001
                self.page.wait_for_timeout(800)

            # Prefer an option within the react-select menu (id starts with
            # react-select-4-option). Fall back to a role=option match.
            option = self.page.locator(
                "[id^='react-select-4-option']"
            ).filter(has_text=library.library_name)
            if option.count() == 0:
                option = self.page.get_by_role("option").filter(
                    has_text=library.library_name
                )
            if option.count() == 0:
                # Last resort: press Enter to choose the highlighted option.
                inp.press("Enter")
            else:
                option.first.click()

            # Confirm the selection landed: wait for the dropdown to close.
            try:
                self.page.wait_for_selector(
                    "[id^='react-select-4-option']", state="detached", timeout=3_000
                )
            except Exception:  # noqa: BLE001
                # Dropdown still open — try Enter as a second kick.
                inp.press("Enter")
                self.page.wait_for_timeout(500)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(
                f"Could not select library '{library.library_name}': {exc}"
            )

        # --- mandatory skill evaluation checkbox ------------------------- #
        # Rule: tick the class whose label contains 'contest' or 'test' but
        # NOT 'discussion'. When the library has many contest classes (e.g.
        # NV Contests), prefer the one that also matches the module name.
        try:
            self._check_skill_eval_checkbox(preferred_name=library.module)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not tick Mandatory Skill Eval: {exc}")

        # --- schedule slot (day-dependent) ------------------------------- #
        try:
            slot_label, slot_search = schedule_slot_for_today()
            self.page.locator(
                ".Select_root__Gqx23.ClassesScheduleSelect_root__KQfRb > "
                ".css-127wfx0-control > .css-jlrko8 > .css-32j6ly"
            ).click()
            self.page.locator("#react-select-5-input").fill(slot_search)
            self.page.get_by_text(slot_label, exact=True).click()
            log.info("Selected schedule slot: %s", slot_label)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not select schedule slot: {exc}")

        # --- start date calendar ----------------------------------------- #
        from datetime import date as _date
        today = _date.today()
        if start.date() < today:
            raise BrowserStepError(
                f"Start date {start.date()} is in the past. "
                f"Please use {today} or later."
            )
        try:
            self.page.locator("i").nth(1).click()  # open the calendar
            day_cell = str(start.day)
            self.page.get_by_role("gridcell", name=day_cell, exact=True).click()
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not set start date: {exc}")

        # --- confirm ----------------------------------------------------- #
        try:
            self.page.get_by_text("Confirm Schedule").click()
            self.page.get_by_text("Confirm & Schedule").click()
            self.page.wait_for_load_state("networkidle")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not confirm schedule: {exc}")

        class_id = self._extract_class_id()
        log.info("Scheduled class saved (class_id=%s)", class_id)
        return ScheduleResult(
            batch_name=batch_name,
            library_name=library.library_name,
            class_id=class_id,
        )

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    @retry(exceptions=(BrowserStepError,))
    def open_all_add_questions(self, result: ScheduleResult):
        """
        Open the scheduled class, then return a list of (attempt_index, popup)
        for EACH '+ Add Questions' link in the Group Contest Summary, in order:
          index 0 = main Contest, 1 = Re-attempt 1, 2 = Re-attempt 2, 3 = Re-attempt 3.

        Each link opens its own Hire Test popup. We open them one at a time,
        capturing the popup, so the caller can set dates per attempt.

        Returns: list[tuple[int, Page]]
        """
        log.info("Opening scheduled class to add questions (all attempts)")
        try:
            self.page.get_by_text("View Scheduled Classes").click()
            self.page.wait_for_load_state("networkidle")
            self.page.get_by_role("cell").filter(
                has_text=re.compile(r"^$")
            ).first.click()
            self.page.wait_for_timeout(800)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not open scheduled class: {exc}")

        links = self.page.get_by_role("link", name="+ Add Questions")
        count = links.count()
        log.info("Found %d '+ Add Questions' link(s)", count)
        if count == 0:
            raise BrowserStepError("No '+ Add Questions' links found.")

        # The Group Contest Summary includes a non-contest link to the test
        # GROUP (URL contains '/edit-test-group/'). Skip it: only the individual
        # contest links (/hire/test/<id>/...) map to Contest + re-attempts.
        popups: list[tuple[int, object]] = []
        attempt_index = 0
        for i in range(count):
            try:
                with self.page.expect_popup() as popup_info:
                    self.page.get_by_role(
                        "link", name="+ Add Questions"
                    ).nth(i).click()
                popup = popup_info.value
                popup.wait_for_load_state("load")
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not open Add Questions link #%d: %s", i, exc)
                continue

            url = popup.url
            if "edit-test-group" in url or not re.search(r"/hire/test/\d+", url):
                log.info("Skipping non-contest link #%d: %s", i, url)
                try:
                    popup.close()
                except Exception:  # noqa: BLE001
                    pass
                continue

            popups.append((attempt_index, popup))
            log.info(
                "Attempt %d (link #%d) Hire Test: %s", attempt_index, i, url
            )
            attempt_index += 1

        # Record the main contest test id (first popup) for bookkeeping.
        if popups:
            result.hire_page = popups[0][1]
            result.hire_test_url = popups[0][1].url
            result.test_ids = [
                self._scrape_test_ids_from_url(p.url)[0]
                for _, p in popups
                if self._scrape_test_ids_from_url(p.url)
            ]
        return popups

    @retry(exceptions=(BrowserStepError,))
    def open_add_questions(self, result: ScheduleResult) -> ScheduleResult:
        """
        Open View Scheduled Classes, open the class row, click "+ Add Questions"
        which opens a popup (the Hire Test). Capture that popup page.
        """
        log.info("Opening View Scheduled Classes to add questions")
        try:
            self.page.get_by_text("View Scheduled Classes").click()
            self.page.wait_for_load_state("networkidle")
            # Open the (first) class row.
            self.page.get_by_role("cell").filter(
                has_text=re.compile(r"^$")
            ).first.click()
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not open scheduled class: {exc}")

        try:
            with self.page.expect_popup() as popup_info:
                self.page.get_by_role(
                    "link", name="+ Add Questions"
                ).nth(1).click()
            hire_page = popup_info.value
            hire_page.wait_for_load_state("load")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not open Add Questions popup: {exc}")

        result.hire_page = hire_page
        result.hire_test_url = hire_page.url
        result.test_ids = self._scrape_test_ids_from_url(hire_page.url)
        log.info("Add Questions opened Hire Test: %s", result.hire_test_url)
        return result

    # ------------------------------------------------------------------ #
    def _check_skill_eval_checkbox(self, preferred_name: str = "") -> None:
        """
        Tick the class that represents the contest or skill-eval test for this
        library. Rule: the label must contain 'contest' OR 'test' (case-insensitive)
        and must NOT contain 'discussion'.

        When preferred_name is given (the module name), prefer a label that also
        contains it — handles NV Contests library which has one class per module.
        Falls back to the first matching label if no preferred match is found.
        """
        import re as _re

        want  = _re.compile(r"contest|test", _re.I)
        avoid = _re.compile(r"Discussion", _re.I)

        # Wait for the async class list to begin rendering.
        try:
            self.page.wait_for_selector("input[type='checkbox']", timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(
                f"Class-list checkboxes never appeared after library selection: {exc}"
            )

        def _find_target():
            # Match via label element text.
            labels = (
                self.page.locator("label")
                .filter(has_text=want)
                .filter(has_not_text=avoid)
            )
            # If a module-specific preferred name is given, require a match.
            # Multiple classes mean this is NV Contests — picking the wrong
            # one silently is worse than failing fast.
            if preferred_name and labels.count() > 1:
                preferred = labels.filter(has_text=preferred_name)
                if preferred.count() == 0:
                    raise BrowserStepError(
                        f"Module '{preferred_name}' not found in NV Contests library. "
                        f"Use the Library override field to specify the correct library."
                    )
                labels = preferred
            if labels.count() > 0:
                lbl = labels.first
                for_id = lbl.get_attribute("for")
                if for_id:
                    cb = self.page.locator(f"#{for_id}")
                    if cb.count():
                        return cb.first
                inner = lbl.locator("input[type='checkbox']")
                if inner.count():
                    return inner.first
            # Fallback: aria-label on the checkbox itself.
            candidates = self.page.get_by_role(
                "checkbox",
                name=_re.compile(r"Mandatory Skill Evaluation Test", _re.I),
            )
            for i in range(candidates.count()):
                aria = candidates.nth(i).get_attribute("aria-label") or ""
                if want.search(aria) and not avoid.search(aria):
                    return candidates.nth(i)
            return None

        chosen = _find_target()

        if chosen is None:
            log.info("Skill-eval checkbox not yet in DOM; scrolling list container.")
            for _ in range(80):  # 80 × 200 px = up to 16 000 px
                self.page.evaluate("""() => {
                    const cb = document.querySelector("input[type='checkbox']");
                    if (!cb) return;
                    let el = cb.parentElement;
                    while (el && el !== document.body) {
                        const s = window.getComputedStyle(el);
                        if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                                && el.scrollHeight > el.clientHeight) {
                            el.scrollTop += 200;
                            return;
                        }
                        el = el.parentElement;
                    }
                    window.scrollBy(0, 200);
                }""")
                self.page.wait_for_timeout(100)
                chosen = _find_target()
                if chosen is not None:
                    break

        if chosen is None:
            raise BrowserStepError(
                "Could not find 'Mandatory Skill Evaluation Test' checkbox "
                "(excluding Contest Discussion) even after scrolling the full list."
            )

        log.info("Skill-eval checkbox found; ticking it.")
        try:
            chosen.scroll_into_view_if_needed(timeout=5_000)
        except Exception:  # noqa: BLE001
            pass
        chosen.check()

    def _extract_class_id(self) -> Optional[str]:
        match = re.search(r"/edit-sbat-group/(\d+)", self.page.url)
        return match.group(1) if match else None

    def _scrape_test_ids_from_url(self, url: str) -> list[str]:
        """The Hire Test popup URL contains the contest test id."""
        match = re.search(r"/hire/test/(\d+)", url)
        return [match.group(1)] if match else []
