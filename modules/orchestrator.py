"""
orchestrator.py
===============
The intelligent operations assistant: runs the full contest-creation workflow
end to end across all four systems and records everything.

Flow:
  1. Resolve library      (library_reader)        - System 0, Excel
  2. Build contest name   (config.build_contest_name)
  3. Derive 4 windows     (utils.derive_attempt_windows)
  4. Create batch         (batch_creator)          - System 1, Admin V2
  5. Schedule class       (schedule_creator)       - System 2, CCT
  6. Add Questions -> Hire (schedule_creator)      - redirect to System 3
  7. Update Hire windows  (hire_test)              - System 3
  8. Append tracker row   (tracker)                - System 4, Excel
  9. Persist metadata     (metadata_store)         - SQLite

Each step is logged in the operational style and on failure an error screenshot
is captured (for browser steps) and the run is marked failed in SQLite. The
browser steps are skipped automatically when run with browser=False, which lets
the Excel/orchestration core be exercised without Playwright/credentials.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from config import DEFAULT_CONTEST_DURATION_MIN, DEFAULT_PROGRAM, FALLBACK_LIBRARY_NAME, GOOGLE_SHEET_ID, build_contest_name
from modules.browser import BrowserManager
from modules.batch_creator import BatchCreator
from modules.hire_test import HireTest
from modules.library_reader import LibraryMatch, LibraryReader
from modules.logger import get_logger
from modules.metadata_store import MetadataStore
from modules.schedule_creator import ScheduleCreator, ScheduleResult
from modules.tracker import ContestTracker


def _build_tracker(program: str = "academy"):
    """Return GoogleContestTracker when configured, else the Excel tracker."""
    if GOOGLE_SHEET_ID:
        try:
            from modules.google_tracker import GoogleContestTracker
            return GoogleContestTracker(program=program)
        except Exception as exc:
            log.warning("Google Sheet unavailable (%s) — falling back to Excel tracker", exc)
    return ContestTracker()
from modules.utils import (
    AmbiguousLibraryError,
    AttemptWindow,
    ContestAgentError,
    LibraryNotFoundError,
    derive_attempt_windows,
    derive_attempt_windows_by_count,
    parse_datetime,
)

log = get_logger(__name__)

# A progress callback receives (step_key, human_message, ok_flag) so a UI
# (Streamlit / CLI) can render the live checklist.
ProgressCallback = Callable[[str, str, bool], None]


@dataclass
class ContestRequest:
    module: str
    contest_name: str           # operator-provided display name (free text)
    start: datetime
    end: Optional[datetime] = None  # if None, derived from num_attempts
    num_attempts: int = 4       # used when end is None
    program: str = DEFAULT_PROGRAM
    library_name: Optional[str] = None  # explicit override for ambiguous cases
    batch_name_override: Optional[str] = None  # exact name (skips auto-naming)
    duration_min: int = DEFAULT_CONTEST_DURATION_MIN


@dataclass
class ContestOutcome:
    success: bool
    batch_name: str = ""
    library_used: str = ""
    contest_id: Optional[str] = None
    test_ids: list[str] = field(default_factory=list)
    tracker_row: Optional[int] = None
    windows: list[AttemptWindow] = field(default_factory=list)
    execution_seconds: float = 0.0
    error: Optional[str] = None


class ContestOrchestrator:
    """Coordinates the full workflow with logging, retries and bookkeeping."""

    def __init__(
        self,
        library_reader: Optional[LibraryReader] = None,
        tracker: Optional[ContestTracker] = None,
        store: Optional[MetadataStore] = None,
    ) -> None:
        self._program_hint: str = "academy"  # updated in run() before tracker is used
        self.library_reader = library_reader or LibraryReader()
        self._tracker_override = tracker
        self.store = store or MetadataStore()

    # ------------------------------------------------------------------ #
    def run(
        self,
        request: ContestRequest,
        *,
        browser: bool = True,
        dry_run_tracker: bool = False,
        overwrite_tracker: bool = False,
        skip_hire_test: bool = False,
        progress: Optional[ProgressCallback] = None,
    ) -> ContestOutcome:
        """Execute the workflow. Returns a structured outcome (never raises)."""
        started = time.perf_counter()

        def emit(step: str, msg: str, ok: bool = True) -> None:
            (log.info if ok else log.error)(msg)
            self.store.log_step(step, msg, "INFO" if ok else "ERROR")
            if progress:
                progress(step, msg, ok)

        tracker = self._tracker_override or _build_tracker(request.program)
        outcome = ContestOutcome(success=False)
        contest_db_id: Optional[int] = None

        try:
            # -- Step 1: resolve library ---------------------------------- #
            emit("library", f"Reading library mapping for '{request.module}'")
            library = self._resolve_library(request)
            outcome.library_used = library.library_name
            emit("library", f"Library resolved: {library.library_name}")

            # -- Step 2-3: name + windows --------------------------------- #
            batch_name = request.batch_name_override or build_contest_name(
                request.module, request.start
            )
            outcome.batch_name = batch_name
            if request.end is not None:
                windows = derive_attempt_windows(request.start, request.end)
                windows = windows[:request.num_attempts]
            else:
                windows = derive_attempt_windows_by_count(
                    request.start, request.num_attempts
                )
            outcome.windows = windows
            emit(
                "plan",
                f"Contest '{batch_name}' planned with {len(windows)} attempt(s)",
            )

            # -- record intent in SQLite ---------------------------------- #
            contest_db_id = self.store.create_contest(
                program=request.program,
                module=request.module,
                contest_name=request.contest_name,
                batch_name=batch_name,
                library_name=library.library_name,
                library_link=library.library_link,
                a1_start=request.start.isoformat(),
                a1_end=windows[0].end.isoformat(),
                windows_json=self.store.dumps([w.as_dict() for w in windows]),
                status="planned",
            )

            # -- Steps 4-7: browser systems ------------------------------- #
            schedule_result: Optional[ScheduleResult] = None
            if browser:
                schedule_result = self._run_browser_steps(
                    request, library, batch_name, windows, emit, contest_db_id,
                    skip_hire_test=skip_hire_test,
                )
                outcome.test_ids = schedule_result.test_ids
                outcome.contest_id = schedule_result.contest_test_id
            else:
                emit(
                    "browser",
                    "Browser steps skipped (browser=False) - Excel-only run",
                )

            # -- Step 8: tracker append ----------------------------------- #
            emit("tracker", "Updating NV Contest Tracker")
            row = tracker.append_contest(
                module=request.module,
                batch_name=batch_name,
                windows=windows,
                dry_run=dry_run_tracker,
                overwrite=overwrite_tracker,
            )
            outcome.tracker_row = row
            if contest_db_id is not None:
                self.store.update_contest(
                    contest_db_id,
                    tracker_row=row,
                    contest_id=outcome.contest_id,
                    test_ids_json=self.store.dumps(outcome.test_ids),
                    status="created",
                )
            emit("tracker", f"Tracker updated (row {row})")

            outcome.success = True
            emit("done", "Completed Successfully")

        except ContestAgentError as exc:
            outcome.error = str(exc)
            emit("error", f"Failed: {exc}", ok=False)
            if contest_db_id is not None:
                self.store.update_contest(contest_db_id, status="failed")
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            outcome.error = f"Unexpected error: {exc}"
            emit("error", outcome.error, ok=False)
            if contest_db_id is not None:
                self.store.update_contest(contest_db_id, status="failed")

        outcome.execution_seconds = round(time.perf_counter() - started, 2)
        return outcome

    # ------------------------------------------------------------------ #
    def _resolve_library(self, request: ContestRequest) -> LibraryMatch:
        if request.library_name:
            # Operator specified a library — try Excel first, else use as
            # a direct CCT library name.
            try:
                return self.library_reader.resolve_explicit(
                    request.program, request.module, request.library_name
                )
            except LibraryNotFoundError:
                log.warning(
                    "Library '%s' not in Excel; using as direct CCT library name",
                    request.library_name,
                )
                return LibraryMatch(
                    module=request.module,
                    program=request.program,
                    library_name=request.library_name,
                    library_link=None,
                    library_id=None,
                )

        # No explicit library — try auto-resolving from the Excel sheet first.
        # Falls back to NV Contests if the sheet has no entry for this module.
        try:
            match = self.library_reader.resolve(request.program, request.module)
            log.info("Library resolved: %s", match.library_name)
            return match
        except Exception:  # noqa: BLE001
            pass

        log.info("Using default library: %s", FALLBACK_LIBRARY_NAME)
        return LibraryMatch(
            module=request.module,
            program=request.program,
            library_name=FALLBACK_LIBRARY_NAME,
            library_link=None,
            library_id=None,
        )

    def _run_browser_steps(
        self,
        request: ContestRequest,
        library: LibraryMatch,
        batch_name: str,
        windows: list[AttemptWindow],
        emit: Callable[..., None],
        contest_db_id: Optional[int],
        skip_hire_test: bool = False,
    ) -> ScheduleResult:
        """Steps 4-7 inside a managed browser session."""
        with BrowserManager() as bm:
            page = bm.page

            # Step 4: create batch (Admin V2) — auto-reuses if already exists.
            emit("batch", f"Creating batch '{batch_name}' in Admin V2")
            batch = BatchCreator(page).create_batch(batch_name)
            if contest_db_id is not None:
                self.store.update_contest(contest_db_id, batch_id=batch.batch_id)
            emit("batch", f"Batch created (id={batch.batch_id})")

            # Step 5: schedule class (CCT).
            emit("schedule", "Scheduling class in CCT")
            scheduler = ScheduleCreator(page)
            schedule_result = scheduler.schedule_class(
                batch_name, library, request.start, request.duration_min
            )
            if contest_db_id is not None:
                self.store.update_contest(
                    contest_db_id, class_id=schedule_result.class_id
                )
            emit("schedule", f"Class scheduled (class_id={schedule_result.class_id})")

            test_ids: list[str] = []
            if skip_hire_test:
                emit("hire_nav", "Hire Test steps skipped (skip_hire_test=True)")
                emit("hire_update", "Hire Test steps skipped (skip_hire_test=True)")
            else:
                # Step 5b: open the "+ Add Questions" links to discover the 4
                # contest test-ids (Contest + 3 re-attempts), skipping the
                # test-group link. Then close the popups.
                emit("hire_nav", "Discovering Hire Test ids for all attempts")
                popups = scheduler.open_all_add_questions(schedule_result)
                for attempt_index, popup in popups:
                    ids = scheduler._scrape_test_ids_from_url(popup.url)
                    if ids:
                        test_ids.append(ids[0])
                    try:
                        popup.close()
                    except Exception:  # noqa: BLE001
                        pass
                emit(
                    "hire_nav",
                    f"Found {len(test_ids)} contest test id(s)",
                    ok=len(test_ids) > 0,
                )

                # Step 6: set each attempt's window on its OWN fresh page (the
                # pattern proven reliable in standalone testing). test_ids[i] maps
                # to windows[i]: 0=Contest, 1=RA1, 2=RA2, 3=RA3.
                emit("hire_update", "Updating Hire Test windows for each attempt")
                applied_count = 0
                for i, test_id in enumerate(test_ids):
                    if i >= len(windows):
                        break
                    window = windows[i]
                    try:
                        fresh = bm.new_hire_page(test_id)
                        res = HireTest(fresh).update_window(window)
                        if res.applied and res.verified:
                            applied_count += 1
                        emit(
                            "hire_update",
                            f"{window.label} (id {test_id}): "
                            f"{window.start.date()} -> {window.end.date()} "
                            f"(verified={res.verified})",
                            ok=res.verified,
                        )
                        try:
                            fresh.close()
                        except Exception:  # noqa: BLE001
                            pass
                    except Exception as exc:  # noqa: BLE001
                        emit(
                            "hire_update",
                            f"{window.label} (id {test_id}) failed: {exc}",
                            ok=False,
                        )

                emit(
                    "hire_update",
                    f"Hire Test updated for {applied_count}/{len(test_ids)} attempts",
                    ok=applied_count == len(test_ids) and len(test_ids) > 0,
                )

            bm.save_auth()
            return schedule_result


# Convenience function mirroring the natural-language entrypoint in the brief.
def create_contest(
    module: str,
    contest_name: str,
    start: str | datetime,
    end: Optional[str | datetime] = None,
    num_attempts: int = 4,
    program: str = DEFAULT_PROGRAM,
    library_name: Optional[str] = None,
    batch_name_override: Optional[str] = None,
    browser: bool = True,
    dry_run_tracker: bool = False,
    overwrite_tracker: bool = False,
    skip_hire_test: bool = False,
    progress: Optional[ProgressCallback] = None,
) -> ContestOutcome:
    """One-call helper used by the CLI/UI.

    Supply either `end` (exact end datetime for A1) or `num_attempts` (auto-
    compute all windows using ATTEMPT_DURATIONS from config).  If both are
    given, `end` wins and windows are trimmed to `num_attempts`.
    """
    request = ContestRequest(
        module=module,
        contest_name=contest_name,
        start=parse_datetime(start),
        end=parse_datetime(end) if end else None,
        num_attempts=num_attempts,
        program=program,
        library_name=library_name,
        batch_name_override=batch_name_override,
    )
    return ContestOrchestrator().run(
        request,
        browser=browser,
        dry_run_tracker=dry_run_tracker,
        overwrite_tracker=overwrite_tracker,
        skip_hire_test=skip_hire_test,
        progress=progress,
    )
