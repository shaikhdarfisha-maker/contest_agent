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
)
from modules.browser import check_session_interstitial
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
    # Attempt windows re-derived from the actual ID count returned by CCT.
    # Set by the orchestrator after hire-test ID discovery.
    actual_windows: list = field(default_factory=list)

    @property
    def contest_test_id(self) -> Optional[str]:
        return self.test_ids[0] if self.test_ids else None


class ScheduleCreator:
    """Page object for CCT class scheduling + reaching Hire Test."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self._available_slots: list[str] = []   # populated by _select_slot_for_datetime
        self._single_contest_ids: set[str] = set()  # IDs found via Contest Requirements fallback

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
        check_session_interstitial(self.page)
        self.page.get_by_role("link", name="Schedule Classes").click()
        self.page.wait_for_selector(".css-32j6ly", state="visible", timeout=20_000)

        # --- batch react-select ------------------------------------------ #
        try:
            self.page.locator(".css-32j6ly").first.click()
            # Fill using whichever react-select input is focused after click.
            self.page.keyboard.type(batch_name)
            # Wait for at least one option to appear, then click the match.
            # React-select option IDs are dynamic; match any *-option-* div.
            self.page.wait_for_selector("[id*='-option-']", timeout=15_000)
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
        self._select_library_in_dropdown(library.library_name)

        # --- mandatory skill evaluation checkbox ------------------------- #
        # Rule: tick the class whose label contains 'contest' or 'test' but
        # NOT 'discussion'. When the library has many contest classes (e.g.
        # NV Contests), prefer the one that also matches the module name.
        # If the Excel-mapped library doesn't have the class, automatically
        # fall back to NV Contests (covers modules not yet remapped in Excel).
        _NV = "NV Contests"
        try:
            self._check_skill_eval_checkbox(preferred_name=library.skill_eval_label or library.module)
        except Exception as exc:  # noqa: BLE001
            if library.library_name == _NV:
                raise BrowserStepError(f"Could not tick Mandatory Skill Eval: {exc}")
            log.info(
                "Skill-eval class not found in '%s'; retrying with NV Contests.",
                library.library_name,
            )
            try:
                self._dismiss_modal_backdrop()
                self._select_library_in_dropdown(_NV)
                self._check_skill_eval_checkbox(preferred_name=library.skill_eval_label or library.module)
            except Exception as exc2:  # noqa: BLE001
                raise BrowserStepError(
                    f"Could not tick Mandatory Skill Eval in '{library.library_name}' "
                    f"or NV Contests fallback: {exc2}"
                )

        # --- schedule slot ------------------------------------------------ #
        # Read ALL options from the dropdown at runtime and pick the one
        # whose pattern contains the requested weekday + time.
        try:
            self._select_slot_for_datetime(start)
        except BrowserStepError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not select schedule slot: {exc}")

        # --- start date calendar ----------------------------------------- #
        from datetime import date as _date, timedelta as _td
        today = _date.today()
        if start.date() < today:
            raise BrowserStepError(
                f"Start date {start.date()} is in the past. "
                f"Please use {today} or later."
            )
        try:
            self.page.locator("i").nth(1).click()  # open the calendar
            # Try the requested date first; if the cell is disabled (e.g. today
            # when it's past the slot time), advance day by day up to 7 days.
            target = start.date()
            clicked = False
            for _ in range(7):
                day_cell = str(target.day)
                cell = self.page.get_by_role("gridcell", name=day_cell, exact=True).first
                if cell.count() > 0 and not cell.is_disabled():
                    cell.click()
                    if target != start.date():
                        log.warning(
                            "Start date %s unavailable in CCT calendar; used %s instead.",
                            start.date(), target,
                        )
                    clicked = True
                    break
                target += _td(days=1)
            if not clicked:
                raise BrowserStepError(
                    f"Could not find an available calendar cell near {start.date()}."
                )
        except BrowserStepError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not set start date: {exc}")

        # --- confirm ----------------------------------------------------- #
        try:
            self.page.get_by_text("Confirm Schedule").click()
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not click 'Confirm Schedule': {exc}")

        # Inspect the confirm modal BEFORE committing — aborts on time mismatch
        # or CCT-side validation errors without ever clicking 'Confirm & Schedule'.
        self._validate_confirm_modal(requested_start=start)

        try:
            self.page.get_by_text("Confirm & Schedule").click()
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not click 'Confirm & Schedule': {exc}")

        self._wait_for_schedule_outcome()

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
        log.info("Opening scheduled class to add questions (all attempts) — current URL: %s", self.page.url)
        try:
            # CCT now navigates to /view-schedule/<id> directly after confirming,
            # so "View Scheduled Classes" button is not present on that page.
            # Only click it when we're still on the edit-sbat-group page.
            if "/view-schedule/" not in self.page.url:
                self.page.get_by_text("View Scheduled Classes").click()
                self.page.wait_for_selector("[role='cell']", state="visible", timeout=20_000)
                self.page.get_by_role("cell").filter(
                    has_text=re.compile(r"^$")
                ).first.click()
                self.page.wait_for_timeout(400)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not open scheduled class (page was: {self.page.url}): {exc}")

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

    def collect_hire_test_ids(self, batch_name: str) -> list[str]:
        """
        Discover Hire Test IDs for all attempts (Contest + RA1-3).

        Confirmed flow (verified against live Scaler DOM 2026-07-21):
          1. Navigate to view-schedule/<id> via "View Scheduled Classes" if needed.
          2. Each row's Edit-column pencil icon is:
               <a class="link" href="/scm/classes/edit-sbat-group/<id>">
             Read those sbat IDs — selector: a[href*='/scm/classes/edit-sbat-group/']
          3. Visit each edit-sbat-group page and click '+ Add Question' in the
             Contest Requirements section → popup opens at the Hire Test URL.
          4. Extract hire-test IDs from popup URLs; close popups.

        NOTE: This is a known-fragile integration point. Scaler has changed the
        hire-test entry path at least three times. Selector above was verified
        against live DOM on 2026-07-21; re-check on UI regressions.
        """
        # ── 1. Navigate to view-schedule if needed ──────────────────────────
        if "/view-schedule/" not in self.page.url:
            log.info("Clicking 'View Scheduled Classes' to reach view-schedule page")
            try:
                self.page.wait_for_selector("text=View Scheduled Classes", timeout=10_000)
                self.page.get_by_text("View Scheduled Classes").click()
                self.page.wait_for_url("**/view-schedule/**", timeout=20_000)
            except Exception as exc:  # noqa: BLE001
                raise BrowserStepError(
                    f"Could not reach view-schedule from {self.page.url}: {exc}"
                )

        view_url = self.page.url
        log.info("On view-schedule: %s", view_url)

        # ── 2. Wait for the Upcoming Classes table ───────────────────────────
        try:
            self.page.wait_for_selector("table", timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(
                f"Upcoming Classes table did not appear on {view_url}: {exc}"
            )

        # ── 3. Read edit-sbat-group IDs from pencil anchors ─────────────────
        sbat_ids = self._read_sbat_ids_from_table(batch_name)
        if not sbat_ids:
            raise BrowserStepError(
                f"No edit-sbat-group pencil links found on {view_url}. "
                "The Upcoming Classes table may be empty or the selector changed."
            )
        log.info("edit-sbat-group IDs from pencil links: %s", sbat_ids)

        # ── 4. Visit each edit page, click '+ Add Question', collect test IDs ─
        test_ids: list[str] = []
        for sbat_id in sbat_ids:
            for tid in self._visit_sbat_and_collect_test_ids(sbat_id):
                if tid not in test_ids:
                    test_ids.append(tid)

        if not test_ids:
            raise BrowserStepError(
                f"Visited {len(sbat_ids)} edit-sbat-group page(s) "
                f"({', '.join(sbat_ids)}) but found no hire-test IDs. "
                "Ensure the class has a Group Contest saved (Contest Requirements "
                "section must be filled in and saved before the 'Group Contest "
                "Summary' section appears on the edit-sbat-group page)."
            )

        log.info("Collected %d hire-test ID(s): %s", len(test_ids), test_ids)
        return test_ids

    def _read_sbat_ids_from_table(self, batch_name: str) -> list[str]:
        """
        Read edit-sbat-group IDs from pencil anchors in the Upcoming Classes table.

        Confirmed anchor selector (verified live 2026-07-21):
            a[href*='/scm/classes/edit-sbat-group/']
        Filters by batch_name; falls back to all anchors if no match.
        """
        sbat_ids: list[str] = []
        batch_lower = batch_name.lower()

        # Filter rows by batch name first.
        rows = self.page.locator("table tr")
        for i in range(rows.count()):
            row = rows.nth(i)
            try:
                row_text = (row.inner_text(timeout=500) or "").lower()
            except Exception:  # noqa: BLE001
                continue
            if batch_lower not in row_text:
                continue
            for a in row.locator(
                "a[href*='/scm/classes/edit-sbat-group/']"
            ).element_handles():
                href = a.get_attribute("href") or ""
                m = re.search(r"/scm/classes/edit-sbat-group/(\d+)", href)
                if m and m.group(1) not in sbat_ids:
                    sbat_ids.append(m.group(1))

        if sbat_ids:
            return sbat_ids

        # Fallback: all pencil anchors in the table (no batch filter).
        log.warning(
            "No rows matched batch_name %r — reading all edit-sbat-group anchors",
            batch_name,
        )
        for a in self.page.locator(
            "table a[href*='/scm/classes/edit-sbat-group/']"
        ).element_handles():
            href = a.get_attribute("href") or ""
            m = re.search(r"/scm/classes/edit-sbat-group/(\d+)", href)
            if m and m.group(1) not in sbat_ids:
                sbat_ids.append(m.group(1))

        return sbat_ids

    def _visit_sbat_and_collect_test_ids(self, sbat_id: str) -> list[str]:
        """
        Navigate to edit-sbat-group/<sbat_id> and collect hire-test IDs.

        PRIMARY path — Group Contest Summary (verified DOM 2026-07-22):
          The section has one card per attempt (Contest, Re-attempt 1–3).
          Card headers: "Contest  1288152"  "Re-attempt 1  1288153".

        FALLBACK path — Contest Requirements (single-contest classes):
          Some classes (scheduled with a non-group-contest library class) show
          only a Contest Requirements row with one ID, e.g.:
            Contest  1288233  120 Mins  45 Days  + Add Questions
          This indicates re-attempts were NOT created in CCT. The caller
          receives the single ID and the count-check will abort with a clear
          message when the plan expected more attempts.

        IDs collected via the fallback are stored in self._single_contest_ids
        so the orchestrator can emit a specific error explaining the cause.
        """
        sbat_url = f"https://www.scaler.com/scm/classes/edit-sbat-group/{sbat_id}"
        log.info("Visiting edit-sbat-group: %s", sbat_url)

        try:
            self.page.goto(sbat_url, wait_until="domcontentloaded")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not navigate to %s: %s", sbat_url, exc)
            return []

        # Wait for the page to settle — try Group Contest Summary first,
        # but don't fail immediately if it's absent.
        _has_group_summary = False
        try:
            self.page.wait_for_selector(
                "text=Group Contest Summary", timeout=12_000
            )
            _has_group_summary = True
        except Exception:  # noqa: BLE001
            pass

        if _has_group_summary:
            # Scroll into view so cards below the fold finish rendering.
            try:
                self.page.get_by_text(
                    "Group Contest Summary"
                ).first.scroll_into_view_if_needed()
                self.page.wait_for_timeout(400)
            except Exception:  # noqa: BLE001
                pass

            # Parse (label, hire-test-id) pairs from card headers via body text.
            # Slice starting at "Group Contest Summary" to exclude the "Contest 7444"
            # contest-type ID in the Contest Requirements section above.
            cards: list[dict] = self.page.evaluate(r"""
                () => {
                    const text = document.body.innerText || "";
                    const idx  = text.indexOf("Group Contest Summary");
                    if (idx === -1) return [];
                    const section = text.slice(idx);
                    const re = /(Contest|Re-attempt\s+\d+)\s+(\d{5,8})/gi;
                    const found = [];
                    let m;
                    while ((m = re.exec(section)) !== null) {
                        found.push({ label: m[1].trim(), test_id: m[2] });
                    }
                    return found;
                }
            """)

            if cards:
                test_ids: list[str] = []
                for card in cards:
                    label, tid = card["label"], card["test_id"]
                    log.info("Group Contest Summary: %s → hire-test ID %s", label, tid)
                    if tid not in test_ids:
                        test_ids.append(tid)
                return test_ids

            log.warning(
                "Group Contest Summary text found on %s but no (label, ID) pairs — "
                "falling through to Contest Requirements extraction",
                sbat_url,
            )
            # Fall through: section header present but empty (single-contest class
            # where CCT renders the heading without populating cards).

        # ── Fallback: no Group Contest Summary (or empty summary) ─────────────
        # The class was created as a single contest (not a group contest).
        # Read the hire-test ID from the Contest Requirements row:
        #   "Contest  <id>  <n> Mins  <n> Days  + Add Questions"
        log.warning(
            "No 'Group Contest Summary' on %s — falling back to Contest Requirements. "
            "This class was likely scheduled with a non-group-contest library class "
            "(re-attempts not created in CCT).",
            sbat_url,
        )

        # Wait for Contest Requirements to settle.
        try:
            self.page.wait_for_selector("text=Contest Requirements", timeout=10_000)
        except Exception:  # noqa: BLE001
            log.warning("Contest Requirements section also absent on %s", sbat_url)
            return []

        # Extract hire-test ID(s) from the Contest Requirements section.
        #
        # What the edit-sbat-group DOM looks like for a single-contest class:
        #   innerText: "Contest  Edit  30068203  120 Mins  45 Days  + Add Questions"
        #   where 30068203 = test GROUP id (text), 1289197 = hire-test id (INPUT value)
        #
        # The hire-test ID is stored in <input value="1289197"> — NOT in innerText.
        # The test group ID IS in innerText and appears before "120 Mins", so any
        # text-first regex would capture it instead.
        #
        # Priority order (each only runs when the previous found nothing):
        #   1. "+ Add Questions" link hrefs  — authoritative, no false positives
        #   2. <input> values in CR section  — catches unambiguous single-input rows
        #   3. Targeted regex on innerText   — fallback for pages without the link
        #   4. Broad scan (innerText / textContent) — last resort
        cr_result: dict = self.page.evaluate(
            r"""(sbatId) => {
                const str = String(sbatId);

                function crSection(body) {
                    const crIdx = body.indexOf("Contest Requirements");
                    if (crIdx === -1) return body.slice(0, 3000);
                    const gcsIdx = body.indexOf("Group Contest Summary", crIdx);
                    return body.slice(crIdx, gcsIdx === -1 ? crIdx + 3000 : gcsIdx);
                }

                const innerText = document.body.innerText || "";
                const section   = crSection(innerText);

                const aq_ids      = new Set();   // "+ Add Questions" hrefs
                const input_ids   = new Set();   // <input value> in CR section
                const targeted_ids = new Set();  // regex before Mins/Days
                const broad_ids   = new Set();   // broad scan fallback
                let m;

                // Source 1 — "+ Add Questions" link hrefs (most authoritative).
                // These link directly to /hire/test/<id>/ — unambiguous.
                // Scoped to links whose text contains "+ Add Questions" so we
                // don't accidentally capture test-group or other admin links.
                document.querySelectorAll("a").forEach(function(a) {
                    if (!/\+\s*add\s+questions/i.test((a.textContent || "").trim())) return;
                    const hm = (a.getAttribute("href") || "").match(/\/hire\/test\/(\d+)/);
                    if (hm) aq_ids.add(hm[1]);
                });

                if (aq_ids.size > 0) {
                    return {
                        ids: Array.from(aq_ids), source: "add-questions-href",
                        aq_ids: Array.from(aq_ids), input_ids: [],
                        targeted_ids: [], broad_ids: [], preview: section.slice(0, 500),
                    };
                }

                // Source 2 — <input> element values near Contest Requirements.
                // The hire-test ID is often stored only in an <input value="...">.
                // We scan the page but only accept the result when exactly one
                // unambiguous candidate is found.
                document.querySelectorAll("input").forEach(function(el) {
                    const v = (el.value || "").trim();
                    if (/^\d{5,8}$/.test(v) && v !== str) input_ids.add(v);
                });

                if (input_ids.size === 1) {
                    return {
                        ids: Array.from(input_ids), source: "input-value",
                        aq_ids: [], input_ids: Array.from(input_ids),
                        targeted_ids: [], broad_ids: [], preview: section.slice(0, 500),
                    };
                }

                // Source 3 — targeted regex: ID immediately before "NNN Mins"/"NNN Days".
                const tRe = /(\d{5,8})\s+\d+\s+(?:Mins|Days)/gi;
                while ((m = tRe.exec(section)) !== null) {
                    if (m[1] !== str) targeted_ids.add(m[1]);
                }

                if (targeted_ids.size > 0) {
                    return {
                        ids: Array.from(targeted_ids), source: "targeted-regex",
                        aq_ids: [], input_ids: Array.from(input_ids),
                        targeted_ids: Array.from(targeted_ids), broad_ids: [],
                        preview: section.slice(0, 500),
                    };
                }

                // Source 4 — broad scan of innerText then textContent.
                const bRe = /\b(\d{5,8})\b/g;
                while ((m = bRe.exec(section)) !== null) {
                    if (m[1] !== str) broad_ids.add(m[1]);
                }
                if (broad_ids.size === 0) {
                    const tc = document.body.textContent || "";
                    const cRe = /\b(\d{5,8})\b/g;
                    while ((m = cRe.exec(crSection(tc))) !== null) {
                        if (m[1] !== str) broad_ids.add(m[1]);
                    }
                }

                return {
                    ids: Array.from(broad_ids), source: "broad",
                    aq_ids: [], input_ids: Array.from(input_ids),
                    targeted_ids: [], broad_ids: Array.from(broad_ids),
                    preview: section.slice(0, 500),
                };
            }""",
            sbat_id,
        )

        cr_ids: list[str] = cr_result.get("ids", [])
        section_preview: str = cr_result.get("preview", "")
        log.info(
            "Contest Requirements section (first 500 chars):\n%s", section_preview
        )
        log.info(
            "CR extraction: source=%s  aq_ids=%s  input_ids=%s  targeted=%s  broad=%s",
            cr_result.get("source"), cr_result.get("aq_ids"),
            cr_result.get("input_ids"), cr_result.get("targeted_ids"),
            cr_result.get("broad_ids"),
        )

        if cr_ids:
            for tid in cr_ids:
                log.info("Contest Requirements (single-contest): hire-test ID %s", tid)
            # Tag these so orchestrator can emit a specific error if count < planned.
            self._single_contest_ids.update(cr_ids)
            return cr_ids

        log.warning(
            "No hire-test IDs found on %s via Group Contest Summary or Contest "
            "Requirements (5-8 digit numbers found in section: none). "
            "Section preview logged above.",
            sbat_url,
        )
        return []

    @retry(exceptions=(BrowserStepError,))
    def open_add_questions(self, result: ScheduleResult) -> ScheduleResult:
        """
        Open View Scheduled Classes, open the class row, click "+ Add Questions"
        which opens a popup (the Hire Test). Capture that popup page.
        """
        log.info("Opening View Scheduled Classes to add questions — current URL: %s", self.page.url)
        try:
            if "/view-schedule/" not in self.page.url:
                self.page.get_by_text("View Scheduled Classes").click()
                self.page.wait_for_selector("[role='cell']", state="visible", timeout=20_000)
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
    # Short common words to skip when doing fuzzy matching
    _FUZZY_SKIP = {
        "and", "or", "to", "of", "for", "the", "in", "on",
        "a", "an", "is", "are", "its", "with", "at",
    }

    def _dismiss_modal_backdrop(self) -> None:
        """Wait for any open CCT modal backdrop to clear before interacting."""
        backdrop = self.page.locator("[data-testid='backdrop']")
        try:
            if backdrop.count() > 0 and backdrop.first.is_visible():
                # Try Escape first — closes most CCT dialogs without side effects.
                self.page.keyboard.press("Escape")
                backdrop.first.wait_for(state="hidden", timeout=4_000)
        except Exception:  # noqa: BLE001
            pass

    def _select_library_in_dropdown(self, library_name: str) -> None:
        """Open the library react-select and choose the given library name."""
        try:
            # Click the input directly — more stable than clicking the dropdown
            # arrow (.css-jlrko8 > .css-32j6ly) which now matches multiple controls.
            self.page.locator("#react-select-4-input").click()
            search = library_name.replace("Academy: ", "").strip()
            inp = self.page.locator("#react-select-4-input")
            inp.fill(search)

            try:
                self.page.wait_for_selector(
                    "[id^='react-select-4-option']", timeout=3_000
                )
            except Exception:  # noqa: BLE001
                self.page.wait_for_timeout(300)

            option = self.page.locator(
                "[id^='react-select-4-option']"
            ).filter(has_text=library_name)
            if option.count() == 0:
                option = self.page.get_by_role("option").filter(has_text=library_name)
            if option.count() == 0:
                visible = self.page.locator("[id^='react-select-4-option']")
                available = [
                    visible.nth(i).inner_text(timeout=500)
                    for i in range(min(visible.count(), 8))
                ]
                raise BrowserStepError(
                    f"Library '{library_name}' not found in the dropdown. "
                    f"Visible options: {available}. "
                    f"Check the Library override or contact support."
                )
            option.first.click()

            try:
                self.page.wait_for_selector(
                    "[id^='react-select-4-option']", state="detached", timeout=3_000
                )
            except Exception:  # noqa: BLE001
                self.page.wait_for_timeout(200)
        except BrowserStepError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(
                f"Could not select library '{library_name}': {exc}"
            )

    def _read_all_slot_options(self) -> list[str]:
        """
        Open the CCT slot dropdown with an empty search and return every
        option label string. Stores results so callers can enumerate them.
        """
        try:
            inp = self.page.locator("#react-select-5-input")
            if inp.count() > 0 and inp.first.is_visible():
                inp.first.click()
                inp.first.fill("")
            else:
                self.page.locator(
                    ".Select_root__Gqx23.ClassesScheduleSelect_root__KQfRb > "
                    ".css-127wfx0-control > .css-jlrko8 > .css-32j6ly"
                ).click(timeout=10_000)
                self.page.locator("#react-select-5-input").fill("")
            self.page.wait_for_selector("[id^='react-select-5-option']", timeout=5_000)
            self.page.wait_for_timeout(300)  # let all options render
            opts = self.page.locator("[id^='react-select-5-option']")
            labels: list[str] = []
            for i in range(opts.count()):
                try:
                    text = opts.nth(i).inner_text(timeout=500).strip()
                    if text:
                        labels.append(text)
                except Exception:  # noqa: BLE001
                    pass
            return labels
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not enumerate slot dropdown options: %s", exc)
            return []

    def _pick_slot_option(self, label: str) -> None:
        """Click the slot dropdown option whose text matches label."""
        opt = self.page.get_by_text(label, exact=True)
        if opt.count() > 0:
            opt.first.click()
            return
        opts = self.page.locator("[id^='react-select-5-option']").filter(has_text=label)
        if opts.count() > 0:
            opts.first.click()
            return
        raise BrowserStepError(f"Slot option '{label}' disappeared before click.")

    @staticmethod
    def _parse_slot_pairs(label: str) -> list[tuple[str, str]]:
        """
        Parse a CCT slot label into its individual (weekday, time) component pairs.

        e.g. "Wed 07:30 AM | Fri 07:30 AM | Sat 09:00 PM (GMT+05:30)"
             → [("Wed", "07:30 AM"), ("Fri", "07:30 AM"), ("Sat", "09:00 PM")]

        Required because naive substring matching ("Fri" in label AND "09:00 PM"
        in label) gives false positives when the two tokens come from DIFFERENT
        components of a multi-day slot (e.g. "Fri 07:30 AM | Sat 09:00 PM").
        """
        pairs: list[tuple[str, str]] = []
        for part in re.split(r"\s*\|\s*", label):
            part = re.sub(r"\s*\(GMT[^)]*\)", "", part).strip()
            m = re.match(
                r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2}:\d{2}\s+(?:AM|PM))",
                part, re.I,
            )
            if m:
                pairs.append((m.group(1).capitalize(), m.group(2).upper()))
        return pairs

    def _select_slot_for_datetime(self, start: datetime) -> str:
        """
        Read ALL CCT slot dropdown options at runtime, then select the option
        whose pattern includes the requested weekday AND time as a PAIR
        (i.e. both tokens from the same slot component, not independent substrings).

        Matching priority:
          1. Exact: some component of the option is exactly (requested_day, requested_time).
          2. Relaxed: some component contains the requested weekday (any time).
          3. No match → BrowserStepError listing all available patterns.

        Saves the full option list to self._available_slots for use in
        the confirm-modal mismatch error message.
        Returns the selected option label.
        """
        _DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        requested_day = _DAY_ABBR[start.weekday()]
        h12 = start.hour % 12 or 12
        ampm = "AM" if start.hour < 12 else "PM"
        requested_time = f"{h12:02d}:{start.minute:02d} {ampm}"

        options = self._read_all_slot_options()
        self._available_slots = options

        log.info(
            "Slot dropdown: %d option(s). Looking for %s at %s IST.",
            len(options), requested_day, requested_time,
        )

        if not options:
            raise BrowserStepError(
                "CCT schedule-slot dropdown returned no options."
            )

        # 1. Exact match: some (day, time) PAIR in the label == (requested_day, requested_time)
        for label in options:
            pairs = self._parse_slot_pairs(label)
            if any(d == requested_day and t == requested_time for d, t in pairs):
                self._pick_slot_option(label)
                log.info("Slot selected (exact weekday+time pair match): %s", label)
                return label

        # 2. Relaxed: some pair's day == requested_day (any time); picks the first
        for label in options:
            pairs = self._parse_slot_pairs(label)
            if any(d == requested_day for d, _ in pairs):
                log.warning(
                    "No slot has %s at %s IST — selecting first slot containing %s: %s",
                    requested_day, requested_time, requested_day, label,
                )
                self._pick_slot_option(label)
                return label

        # 3. No match at all
        patterns_txt = "\n".join(f"  • {s}" for s in options)
        raise BrowserStepError(
            f"No CCT slot contains '{requested_day}' "
            f"(requested: {start:%d %b %Y %H:%M} IST). "
            f"Available patterns:\n{patterns_txt}"
        )

    def _check_skill_eval_checkbox(self, preferred_name: str = "") -> None:
        """
        Tick the class that represents the contest or skill-eval test for this
        library. Rule: the label must contain 'contest' OR 'test' (case-insensitive)
        and must NOT contain 'discussion'.

        When preferred_name is given (the module name), prefer a label that also
        contains it — handles NV Contests library which has one class per module.
        Falls back to word-level fuzzy matching if exact substring fails.
        """
        import re as _re

        # Strip program-suffix tags like "(AIML)" before matching against CCT
        # class names — the xlsx module name carries these tags for batch naming,
        # but CCT classes don't include them.
        preferred_name = _re.sub(r'\s*\([^)]+\)\s*$', '', preferred_name).strip()

        want  = _re.compile(r"contest|test|neovarsity", _re.I)
        avoid = _re.compile(r"Discussion", _re.I)

        # Wait for the class list to populate. When preferred_name is given,
        # wait for any label (the class may not contain "contest"/"neovarsity"
        # in its name). Otherwise require the want filter to match.
        try:
            wait_loc = (
                self.page.locator("label").filter(has_not_text=avoid)
                if preferred_name
                else self.page.locator("label").filter(has_text=want).filter(has_not_text=avoid)
            )
            wait_loc.first.wait_for(state="attached", timeout=15_000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(
                f"Class-list labels never appeared after library selection: {exc}"
            )

        def _available_class_names(labels_loc) -> str:
            names = []
            for i in range(min(labels_loc.count(), 200)):
                try:
                    txt = labels_loc.nth(i).inner_text(timeout=500).strip()
                    if txt:
                        names.append(txt[:70])
                except Exception:  # noqa: BLE001
                    pass
            return "; ".join(names) if names else "(none found)"

        def _find_target():
            # Split CamelCase boundaries before lowercasing so "MLCoding" → "ML Coding"
            # and the pattern matches class names that have a space where the module doesn't.
            _camel = _re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', preferred_name)
            _camel = _re.sub(r'([a-z\d])([A-Z])', r'\1 \2', _camel)
            pref_lower = _camel.lower() if preferred_name else ""
            # Build a flexible regex: tolerate
            #  - singular/plural mismatch ("Algorithms" ↔ "Algorithm")
            #  - colon-spacing mismatch ("ML : Adv" ↔ "ML: Adv")
            #  - word-space mismatch ("MLCoding" ↔ "ML Coding")
            _norm = _re.sub(r'\s*:\s*', ':', pref_lower)  # collapse spaces around ':'
            _esc  = _re.escape(_norm).replace(':', r'\s*:\s*').replace('\\ ', r'\s*')
            if _esc.endswith("s"):
                _esc = _esc[:-1] + "s?"
            pref_pat = _re.compile(_esc + r"(?!\d)", _re.I) if pref_lower else None
            reattempt_re = _re.compile(r"re.?attempt", _re.I)

            if pref_lower:
                # When preferred_name is given, search ALL non-Discussion labels —
                # some classes are named without "contest"/"neovarsity" and would be
                # silently excluded by the want filter.
                labels = self.page.locator("label").filter(has_not_text=avoid)
                n = labels.count()
                contest_re = _re.compile(r"\bcontest\b", _re.I)
                core_re = _re.compile(r"\bcore\b", _re.I)
                candidates: list[tuple[int, str]] = []
                for i in range(n):
                    try:
                        txt = labels.nth(i).inner_text(timeout=500).strip()
                    except Exception:
                        continue
                    if not pref_pat.search(txt):
                        continue
                    if reattempt_re.search(txt):
                        continue
                    candidates.append((i, txt))
                if not candidates:
                    return None
                # Prefer a label that explicitly says "contest"; deprioritize "core"
                # (e.g. "Neovarsity Core" is a lecture class, not a group contest).
                def _score(txt: str) -> int:
                    if contest_re.search(txt):
                        return 2
                    if core_re.search(txt):
                        return 0
                    return 1
                best_i, best_txt = max(candidates, key=lambda c: _score(c[1]))
                log.info(
                    "Skill-eval candidates for '%s': %s — chose: %s",
                    preferred_name,
                    [t for _, t in candidates],
                    best_txt,
                )
                lbl = labels.nth(best_i)
            else:
                # No preferred name — pick the first contest/test/neovarsity class.
                labels = (
                    self.page.locator("label")
                    .filter(has_text=want)
                    .filter(has_not_text=avoid)
                )
                if labels.count() == 0:
                    return None
                lbl = labels.first

            if lbl is not None:
                for_id = lbl.get_attribute("for")
                if for_id:
                    cb = self.page.locator(f"[id='{for_id}']")
                    if cb.count():
                        return cb.first
                inner = lbl.locator("input[type='checkbox']")
                if inner.count():
                    return inner.first
                sibling = lbl.locator(
                    "xpath=preceding-sibling::input[@type='checkbox'][1]"
                    " | following-sibling::input[@type='checkbox'][1]"
                    " | ../input[@type='checkbox'][1]"
                )
                if sibling.count():
                    return sibling.first
                # Last resort: return the label — clicking it toggles
                # the associated checkbox regardless of DOM structure.
                return lbl
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

            if preferred_name:
                # Atomic JS approach: scroll AND click in one browser-side call.
                # Avoids stale Playwright locators caused by virtual-scroll DOM recycling.
                ticked = self.page.evaluate("""
                    async ([preferredName]) => {
                        const avoid     = /Discussion/i;
                        const noRetry   = /re.?attempt/i;
                        const prefLower = preferredName.toLowerCase();

                        // Normalize spaces around colons ("ML : Adv" → "ML:Adv")
                        // and strip all whitespace so "MLCoding" ↔ "ML Coding" match.
                        const normColon = s => s.replace(/\s*:\s*/g, ':');
                        const rmSpace   = s => s.replace(/\s+/g, '');
                        const norm      = s => rmSpace(normColon(s));

                        // Tolerate singular/plural mismatch ("algorithms" ↔ "algorithm").
                        const prefBase = prefLower.endsWith('s')
                            ? prefLower.slice(0, -1) : prefLower;
                        const normPref = norm(prefLower);
                        const normBase = norm(prefBase);
                        const tryClick = () => {
                            const lbls = Array.from(document.querySelectorAll('label'))
                                .filter(l => !avoid.test(l.innerText));
                            // Collect all candidates matching the preferred name.
                            const cands = [];
                            for (const lbl of lbls) {
                                const txt     = lbl.innerText.trim().toLowerCase();
                                const normTxt = norm(txt);
                                // startsWith on normalized strings tolerates colon-spacing,
                                // word-space differences, and singular/plural mismatches.
                                const matchFull = normTxt.startsWith(normPref);
                                const matchBase = normBase !== normPref && normTxt.startsWith(normBase);
                                if (!matchFull && !matchBase) continue;
                                const matchLen = matchFull ? normPref.length : normBase.length;
                                const nextCh = normTxt[matchLen];
                                if (nextCh !== undefined && /\d/.test(nextCh)) continue;
                                if (noRetry.test(lbl.innerText)) continue;
                                cands.push(lbl);
                            }
                            if (cands.length === 0) return false;
                            // Prefer a label that says "contest"; deprioritize "core"
                            // (e.g. "Neovarsity Core" is a lecture class, not group contest).
                            const score = l => {
                                const t = l.innerText.toLowerCase();
                                if (/\bcontest\b/.test(t)) return 2;
                                if (/\bcore\b/.test(t)) return 0;
                                return 1;
                            };
                            let found = cands.reduce((best, c) => score(c) >= score(best) ? c : best, cands[0]);
                            if (!found) return false;
                            const forId = found.getAttribute('for');
                            if (forId) {
                                const cb = document.getElementById(forId);
                                if (cb) { cb.click(); return true; }
                            }
                            const inner = found.querySelector('input[type="checkbox"]');
                            if (inner) { inner.click(); return true; }
                            found.click();
                            return true;
                        };

                        if (tryClick()) return true;

                        // Find scroll container
                        const anchor = document.querySelector("input[type='checkbox']");
                        if (!anchor) return false;
                        let el = anchor.parentElement;
                        while (el && el !== document.body) {
                            const s = window.getComputedStyle(el);
                            if ((s.overflowY==='auto'||s.overflowY==='scroll')
                                    && el.scrollHeight > el.clientHeight) break;
                            el = el.parentElement;
                        }
                        const container = (el && el !== document.body) ? el : null;

                        // Scroll until we find the class or truly hit the bottom.
                        // Re-checking actual scroll position after each step detects
                        // lazy-rendered lists whose scrollHeight grows during scrolling —
                        // 4 consecutive clamped steps = genuinely at the end.
                        for (let pos = 150, stall = 0; stall < 4; pos += 150) {
                            if (container) container.scrollTop = pos;
                            else window.scrollTo(0, pos);
                            await new Promise(r => setTimeout(r, 80));
                            if (tryClick()) return true;
                            const actualPos = container ? container.scrollTop : window.scrollY;
                            stall = (actualPos < pos - 5) ? stall + 1 : 0;
                        }
                        return false;
                    }
                """, [preferred_name])

                if ticked:
                    log.info("Skill-eval checkbox ticked via JS scroll.")
                    return  # done — no Playwright chosen element needed

                # JS scroll ended without finding the class — log what Python
                # sees in the DOM right now to diagnose name-matching issues.
                _all_lbl = self.page.locator("label").filter(has_not_text=avoid)
                _n = _all_lbl.count()
                log.info(
                    "JS scroll found no match for %r — %d labels in DOM. "
                    "First 100 (truncated):",
                    preferred_name, _n,
                )
                for _i in range(min(_n, 100)):
                    try:
                        _t = _all_lbl.nth(_i).inner_text(timeout=300).strip()
                        if _t:
                            log.info("  label[%d]: %r", _i, _t[:120])
                    except Exception:  # noqa: BLE001
                        pass

            # Playwright fallback scroll loop (for no-preferred_name case).
            # Reset scroll to top first so items at position 0 aren't missed.
            self.page.evaluate("""() => {
                const cb = document.querySelector("input[type='checkbox']");
                if (!cb) return;
                let el = cb.parentElement;
                while (el && el !== document.body) {
                    const s = window.getComputedStyle(el);
                    if ((s.overflowY==='auto'||s.overflowY==='scroll')
                            && el.scrollHeight > el.clientHeight) {
                        el.scrollTop = 0; return;
                    }
                    el = el.parentElement;
                }
                window.scrollTo(0, 0);
            }""")
            self.page.wait_for_timeout(200)
            for _ in range(80):
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
            # Build a helpful error listing every class now visible after scrolling.
            # Use the same broad filter as _find_target() (no `want` restriction)
            # so classes without "contest/neovarsity" in their name are visible too.
            all_labels = self.page.locator("label").filter(has_not_text=avoid)
            hint = (
                f" Available classes: {_available_class_names(all_labels)}."
                f" Use the Library override field to specify the correct library."
                if preferred_name else ""
            )
            raise BrowserStepError(
                f"Module '{preferred_name}' not found in NV Contests library after scrolling the full list.{hint}"
                if preferred_name else
                "Could not find 'Mandatory Skill Evaluation Test' checkbox "
                "(excluding Contest Discussion) even after scrolling the full list."
            )

        log.info("Skill-eval checkbox found; ticking it.")
        try:
            chosen.scroll_into_view_if_needed(timeout=5_000)
        except Exception:  # noqa: BLE001
            pass
        try:
            chosen.check()
        except Exception:
            # `chosen` may be a label element (returned as last resort).
            # Clicking a label always toggles its associated checkbox.
            chosen.click()

    def _validate_confirm_modal(self, requested_start: datetime) -> None:
        """
        Inspect the CCT confirm modal shown after 'Confirm Schedule'.

        Raises BrowserStepError without clicking 'Confirm & Schedule' if:
          - CCT shows validation error lines (duplicate class, conflict, etc.)
          - The proposed date/time diverges from requested_start by > 5 minutes.

        If the proposed datetime can't be parsed, a warning is logged and we
        proceed so a transient DOM change never silently blocks scheduling.
        """
        try:
            self.page.wait_for_selector("text=Confirm & Schedule", timeout=12_000)
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(
                f"Confirm modal did not appear after 'Confirm Schedule' "
                f"(page: {self.page.url}): {exc}"
            )

        try:
            body = self.page.inner_text("body") or ""
        except Exception:  # noqa: BLE001
            body = ""

        # ── CCT validation errors ──────────────────────────────────────────
        error_lines = [
            ln.strip()
            for ln in body.splitlines()
            if ln.strip()
            and re.search(
                r"already\s+has\s+a\s+class|already\s+scheduled|topic.*already",
                ln, re.I,
            )
        ]
        if error_lines:
            raise BrowserStepError(
                "CCT validation errors (aborting before scheduling):\n"
                + "\n".join(f"  • {ln}" for ln in error_lines)
            )

        # ── Proposed date/time check ───────────────────────────────────────
        # Modal shows e.g. "24 Jul 2026 / 07:00 AM" or "24 Jul 2026, Fri, 7:00 am"
        m = re.search(
            r"Proposed Date.*?"
            r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"\s+(\d{4}).*?(\d{1,2}):(\d{2})\s*(AM|PM)",
            body, re.I | re.DOTALL,
        )
        if not m:
            log.warning(
                "Could not parse 'Proposed Date & Time' from confirm modal — proceeding."
            )
            return

        import calendar as _cal
        _abbr = {a.lower(): i for i, a in enumerate(_cal.month_abbr) if a}
        day, mon_s, year, hr, mn, ampm = m.groups()
        month = _abbr.get(mon_s.lower(), 0)
        if not month:
            log.warning("Unknown month abbreviation %r in confirm modal — proceeding.", mon_s)
            return

        hour = int(hr) % 12 + (12 if ampm.upper() == "PM" else 0)
        try:
            proposed = datetime(int(year), month, int(day), hour, int(mn))
        except ValueError as exc:  # noqa: BLE001
            log.warning("Could not construct proposed datetime: %s — proceeding.", exc)
            return

        diff_secs = abs((proposed - requested_start).total_seconds())
        if diff_secs > 300:  # > 5-minute divergence
            if self._available_slots:
                slots_hint = " Available patterns:\n" + "\n".join(
                    f"  • {s}" for s in self._available_slots
                )
            else:
                # Fall back to parsing slot-like lines from the modal body.
                found = re.findall(
                    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[^\n]*?\d{1,2}:\d{2}\s*(?:AM|PM)[^\n]*",
                    body, re.I,
                )
                slots_hint = (
                    " Available patterns:\n" + "\n".join(f"  • {s.strip()}" for s in found[:10])
                ) if found else ""
            raise BrowserStepError(
                f"Time mismatch — you requested {requested_start:%d %b %Y %H:%M} IST "
                f"but CCT proposes {proposed:%d %b %Y %H:%M} IST.{slots_hint} "
                f"Aborting without scheduling."
            )

        log.info(
            "Confirm modal: proposed %s matches requested %s — proceeding.",
            proposed.strftime("%d %b %Y %H:%M"),
            requested_start.strftime("%d %b %Y %H:%M"),
        )

    def _wait_for_schedule_outcome(self) -> None:
        """
        After 'Confirm & Schedule' is clicked, wait for:
          - success: 'View Scheduled Classes' text appears OR URL → /view-schedule/
          - error:   CCT shows validation error lines

        Raises BrowserStepError on error state or 45-second timeout.
        """
        try:
            self.page.wait_for_function(
                "() => document.body.innerText.includes('View Scheduled Classes') "
                "|| location.href.includes('/view-schedule/')",
                timeout=45_000,
            )
            return  # success
        except Exception:
            pass

        try:
            body = self.page.inner_text("body") or ""
        except Exception:  # noqa: BLE001
            body = ""

        error_lines = [
            ln.strip()
            for ln in body.splitlines()
            if ln.strip()
            and re.search(
                r"already\s+has\s+a\s+class|already\s+scheduled|failed|error",
                ln, re.I,
            )
        ]
        if error_lines:
            raise BrowserStepError(
                "CCT returned errors after scheduling:\n"
                + "\n".join(f"  • {ln}" for ln in error_lines[:5])
            )
        raise BrowserStepError(
            f"Schedule did not complete — 'View Scheduled Classes' never appeared "
            f"(page URL: {self.page.url})."
        )

    def verify_scheduled_date(self, requested_start: datetime) -> tuple[bool, str]:
        """
        Read the scheduled class date from the current page and compare to requested_start.
        Call this immediately after _wait_for_schedule_outcome() returns success.

        Returns (verified: bool, detail: str).
        detail is always timezone-explicit (IST / GMT+05:30).
        A False result means the page does not show the expected date — abort the run.
        """
        url = self.page.url
        try:
            body = self.page.inner_text("body", timeout=8_000) or ""
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not read page body for post-schedule verification: {exc}"

        req_d  = requested_start.date()
        months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        m_abbr = months[req_d.month - 1]
        m_full = requested_start.strftime("%B")

        found = (
            bool(re.search(rf"\b{req_d.day}\s+(?:{m_abbr}|{m_full})\s+{req_d.year}\b", body, re.I))
            or bool(re.search(rf"\b(?:{m_abbr}|{m_full})\s+{req_d.day},?\s+{req_d.year}\b", body, re.I))
            or (req_d.strftime("%Y-%m-%d") in body)
            or (req_d.strftime("%d/%m/%Y") in body)
        )

        req_str = (
            f"{m_abbr} {req_d.day}, {req_d.year} "
            f"{requested_start.strftime('%I:%M %p')} IST (GMT+05:30)"
        )
        if found:
            tm = re.search(r"\b\d{1,2}:\d{2}\s*(?:AM|PM)\b", body, re.I)
            shown = f"({tm.group(0).strip()} IST)" if tm else "(time pre-verified in confirm modal)"
            return True, f"Date confirmed: {req_str} — page shows {shown}"

        visible = re.findall(
            r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b",
            body, re.I,
        )[:5]
        return False, (
            f"MISMATCH — requested {req_str} but that date not found on view-schedule page. "
            f"Dates visible on page: {visible or ['(none)']}. URL: {url}"
        )

    def _extract_class_id(self) -> Optional[str]:
        match = re.search(r"/(?:edit-sbat-group|view-schedule)/(\d+)", self.page.url)
        return match.group(1) if match else None

    def _scrape_test_ids_from_url(self, url: str) -> list[str]:
        """The Hire Test popup URL contains the contest test id."""
        match = re.search(r"/hire/test/(\d+)", url)
        return [match.group(1)] if match else []
