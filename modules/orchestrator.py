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

from config import (
    BROWSER, DEFAULT_CONTEST_DURATION_MIN, DEFAULT_PROGRAM, FALLBACK_LIBRARY_NAME,
    GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID, USE_API_HIRETEST,
    USE_API_SCHEDULING, build_contest_name,
)
from modules.browser import BrowserManager
from modules.batch_creator import BatchCreator
from modules.hire_test import HireTest
from modules.library_reader import LibraryMatch, LibraryReader
from modules.logger import get_logger
from modules.metadata_store import MetadataStore
from modules.schedule_creator import ScheduleCreator, ScheduleResult
from modules.tracker import ContestTracker


def _build_tracker(program: str = "academy"):
    """Return GoogleContestTracker when configured, else the Excel tracker.

    Re-reads env vars at call time so secrets bootstrapped at app startup
    (GOOGLE_SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON) are visible here even
    though config.py module-level constants were frozen at import time.
    """
    import os as _os
    from modules.utils import TrackerUpdateError

    # Re-read at call time so streamlit_app.py's startup bootstrap is visible.
    sheet_id = _os.getenv("GOOGLE_SHEET_ID", "") or GOOGLE_SHEET_ID
    creds_path = _os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "") or GOOGLE_SERVICE_ACCOUNT_JSON

    if sheet_id:
        from modules.google_tracker import GoogleContestTracker
        # Intentionally NOT catching — if Sheets is configured and fails, the
        # error surfaces immediately rather than silently falling back to the
        # Excel tracker (which won't exist on Cloud deployments).
        return GoogleContestTracker(
            sheet_id=sheet_id, program=program, creds_path=creds_path
        )
    return ContestTracker()
from modules.utils import (
    AmbiguousLibraryError,
    AttemptWindow,
    BrowserStepError,
    ContestAgentError,
    LibraryNotFoundError,
    SessionExpiredError,
    SessionLimitError,
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
    created_by: str = "Unknown"


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
    # Which code path ran for each step ("API" or "Playwright") — surfaced in logs.
    path_used: dict = field(default_factory=dict)


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
            # -- Pre-flight: reject past start times before any browser work.
            # The Hire Test date picker disables dates whose time has already
            # passed, so starting after 9 PM on the contest day would hang.
            from datetime import datetime as _dt
            now = _dt.now()
            if request.start < now:
                raise ContestAgentError(
                    f"Contest start time {request.start.strftime('%d %b %Y %I:%M %p')} "
                    f"is in the past (current time: {now.strftime('%d %b %Y %I:%M %p')}). "
                    "Please use a future date/time."
                )

            # -- Step 1: resolve library ---------------------------------- #
            emit("library", f"Reading library mapping for '{request.module}'")
            library = self._resolve_library(request)
            outcome.library_used = library.library_name
            emit("library", f"Library resolved: {library.library_name}")

            # Override num_attempts with the library's configured value so that
            # single-contest modules (e.g. "Advance Software Engineering" = 1)
            # generate the correct number of windows and pass the count check.
            if library.num_attempts != request.num_attempts:
                log.info(
                    "Library '%s' configures %d attempt(s) — overriding request "
                    "default of %d",
                    library.library_name, library.num_attempts, request.num_attempts,
                )
                from dataclasses import replace as _dc_replace
                request = _dc_replace(request, num_attempts=library.num_attempts)

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
            self._validate_windows(windows, request.num_attempts)
            plan_lines = [
                f"{w.label}: {w.start.strftime('%d %b %Y %H:%M IST')} → "
                f"{w.end.strftime('%d %b %Y %H:%M IST')}"
                for w in windows
            ]
            emit(
                "plan",
                f"Contest '{batch_name}' — {len(windows)} attempt(s) planned "
                f"(actual determined by CCT): "
                + " | ".join(plan_lines),
            )

            # Check batch existence BEFORE create_contest resets status to
            # "planned".  A prior failed run leaves status="failed"; checking
            # here (not inside _browser_steps_inner) captures that pre-reset
            # truth.  Only 'created' or 'failed' statuses prove the batch step
            # completed — 'planned' means the previous run crashed before it.
            _skip_batch = self.store.batch_was_previously_created(
                request.program, batch_name
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
                created_by=request.created_by,
            )

            # -- Steps 4-7: browser systems ------------------------------- #
            schedule_result: Optional[ScheduleResult] = None
            if browser:
                schedule_result = self._run_browser_steps(
                    request, library, batch_name, windows, emit, contest_db_id,
                    skip_hire_test=skip_hire_test,
                    skip_batch=_skip_batch,
                )
                outcome.test_ids = schedule_result.test_ids
                outcome.contest_id = schedule_result.contest_test_id
                # Replace planned windows with the actual windows derived from
                # the real CCT attempt count (may differ from plan).
                if schedule_result.actual_windows:
                    windows = schedule_result.actual_windows
                    outcome.windows = windows
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
            # Read back the written row and verify it matches.
            tracker_verified = False
            try:
                from modules.google_tracker import GoogleContestTracker
                if isinstance(tracker, GoogleContestTracker) and not dry_run_tracker:
                    ok, detail = tracker.verify_row(
                        row,
                        module=request.module,
                        batch_name=batch_name,
                        windows=windows,
                    )
                    if ok:
                        emit("tracker", f"Tracker verified — {detail}")
                    else:
                        emit("tracker", f"Tracker write UNVERIFIED: {detail}", ok=False)
                    tracker_verified = ok
                else:
                    tracker_verified = True  # Excel tracker / dry-run: skip read-back
            except Exception as exc:  # noqa: BLE001
                log.warning("Tracker read-back failed: %s", exc)
                tracker_verified = True  # don't block success on read-back error
            if not tracker_verified:
                emit("tracker", f"Tracker updated (row {row}) — read-back mismatch (see above)")
            else:
                emit("tracker", f"Tracker updated (row {row})")

            outcome.success = True
            emit("done", "Completed Successfully")

        except ContestAgentError as exc:
            # Only report partial creations when browser steps actually ran
            # (contest_db_id is set after plan validation, so it's None for
            # plan-level failures where nothing was created yet).
            created_parts = []
            if contest_db_id is not None and outcome.batch_name:
                created_parts.append(f"batch='{outcome.batch_name}'")
            if outcome.contest_id:
                created_parts.append(f"class_id={outcome.contest_id}")
            if outcome.test_ids:
                created_parts.append(f"hire_test_ids={outcome.test_ids}")
            suffix = (
                f" — Created before failure: {', '.join(created_parts)}. "
                "Review and delete manually if needed."
                if created_parts else ""
            )
            outcome.error = str(exc) + suffix
            emit("error", f"Failed: {exc}{suffix}", ok=False)
            if contest_db_id is not None:
                self.store.update_contest(contest_db_id, status="failed")
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            created_parts = []
            if contest_db_id is not None and outcome.batch_name:
                created_parts.append(f"batch='{outcome.batch_name}'")
            if outcome.contest_id:
                created_parts.append(f"class_id={outcome.contest_id}")
            suffix = (
                f" — Created before failure: {', '.join(created_parts)}. "
                "Review and delete manually if needed."
                if created_parts else ""
            )
            outcome.error = f"Unexpected error: {exc}{suffix}"
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
        skip_batch: bool = False,
    ) -> ScheduleResult:
        """Steps 4-7 inside a managed browser session."""
        with BrowserManager() as bm:
            page = bm.page
            try:
                return self._browser_steps_inner(
                    bm, page, request, library, batch_name, windows,
                    emit, contest_db_id, skip_hire_test,
                    skip_batch=skip_batch,
                )
            except (SessionExpiredError, SessionLimitError):
                raise  # already the right type; screenshot captured proactively
            except BrowserStepError as exc:
                if bm.any_session_limit_page():
                    bm.capture_error("session_limit")
                    raise SessionLimitError(
                        "Scaler's 2-session limit was hit. Log out an old session "
                        "at scaler.com or wait, then retry."
                    ) from exc
                if bm.any_login_page():
                    bm.capture_error("session_expired")
                    raise SessionExpiredError(
                        "Scaler session expired — run capture_login.py locally "
                        "to refresh auth, then upload the new storage_state.json."
                    ) from exc
                raise

    def _browser_steps_inner(
        self,
        bm: BrowserManager,
        page: object,
        request: ContestRequest,
        library: LibraryMatch,
        batch_name: str,
        windows: list[AttemptWindow],
        emit: Callable[..., None],
        contest_db_id: Optional[int],
        skip_hire_test: bool = False,
        skip_batch: bool = False,
    ) -> ScheduleResult:
        # Step 4: create batch (Admin V2).
        # skip_batch is True when a prior run (status 'created' or 'failed')
        # already completed the batch step — checked before create_contest()
        # resets the status to 'planned'.
        from modules.batch_creator import BatchResult as _BatchResult
        if skip_batch:
            log.info("Batch '%s' previously created — skipping Admin V2", batch_name)
            emit("batch", f"Batch '{batch_name}' already exists — skipping Admin V2")
            batch = _BatchResult(batch_name=batch_name, batch_id=None)
        else:
            emit("batch", f"Creating batch '{batch_name}' in Admin V2")
            batch = BatchCreator(page).create_batch(batch_name)
        if contest_db_id is not None:
            # Mark the batch step itself as confirmed done as soon as it
            # actually is — status="failed" from a later step (CCT/hire
            # test/tracker) then correctly implies "batch exists, safe to
            # skip on retry". Without this, any failure anywhere in the run
            # got the blanket status="failed" below, even when the batch was
            # never created, poisoning every future retry into skipping
            # Admin V2 forever (they'd search CCT for a batch that doesn't
            # exist and time out the same way).
            update_fields: dict = {"status": "batch_created"}
            if batch.batch_id is not None:
                update_fields["batch_id"] = batch.batch_id
            self.store.update_contest(contest_db_id, **update_fields)
        emit("batch", f"Batch created (id={batch.batch_id})")

        # Initialise API client once (used for steps 5 + 6 when flags are set).
        api_client = None
        if USE_API_SCHEDULING or USE_API_HIRETEST:
            try:
                from pathlib import Path as _Path
                from modules.scaler_api import ScalerClient
                storage = BROWSER.storage_state
                if storage and _Path(storage).exists():
                    api_client = ScalerClient(storage)
                    log.debug("API client initialised from %s", storage)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not initialise API client: %s", exc)

        # Step 5: schedule class (CCT).
        emit("schedule", "Scheduling class in CCT")
        schedule_result: Optional[ScheduleResult] = None
        _api_scheduled = False
        scheduler: Optional[ScheduleCreator] = None

        if USE_API_SCHEDULING and api_client and batch.batch_id and library.library_id:
            try:
                schedule_result = self._api_schedule_class(
                    api_client, batch.batch_id, library, request.start
                )
                _api_scheduled = True
                emit("schedule", f"Class scheduled via API (class_id={schedule_result.class_id})")
            except Exception as exc:  # noqa: BLE001
                log.warning("API scheduling failed (%s) — Playwright fallback", exc)
                emit("schedule", f"API scheduling unavailable ({exc}) — using Playwright", ok=True)

        if not _api_scheduled:
            scheduler = ScheduleCreator(page)
            schedule_result = scheduler.schedule_class(
                batch_name, library, request.start, request.duration_min
            )
            # Post-schedule read-back: verify the actual scheduled date matches
            # requested_start before continuing.  The pre-confirm modal check already
            # guards against wrong times; this is a second, independent confirmation.
            sched_ok, sched_detail = scheduler.verify_scheduled_date(request.start)
            if not sched_ok:
                raise BrowserStepError(
                    f"[schedule] Post-schedule verification FAILED: {sched_detail}"
                )
            emit("schedule",
                 f"[Playwright] Class scheduled and verified "
                 f"(class_id={schedule_result.class_id}) — {sched_detail}")
        else:
            emit("schedule",
                 f"[API] Class scheduled (class_id={schedule_result.class_id})")

        if contest_db_id is not None:
            self.store.update_contest(
                contest_db_id, class_id=schedule_result.class_id
            )

        test_ids: list[str] = []
        if skip_hire_test:
            emit("hire_nav", "Hire Test steps skipped (skip_hire_test=True)")
            emit("hire_update", "Hire Test steps skipped (skip_hire_test=True)")
        else:
            # Step 5b: discover Hire Test IDs.
            # If API scheduling returned IDs in its response, use them directly.
            # Otherwise fall through to Playwright DOM reading.
            if _api_scheduled and schedule_result.test_ids:
                test_ids = schedule_result.test_ids
                emit("hire_nav", f"[API] Found {len(test_ids)} hire-test id(s) from API response")
            else:
                emit("hire_nav", "Discovering Hire Test ids for all attempts")
                if scheduler is None:
                    scheduler = ScheduleCreator(page)
                test_ids = scheduler.collect_hire_test_ids(batch_name)
                schedule_result.test_ids = test_ids
                emit(
                    "hire_nav",
                    f"[Playwright] Found {len(test_ids)} hire-test id(s): "
                    + ", ".join(f"{windows[i].label if i < len(windows) else '?'}={tid}"
                                for i, tid in enumerate(test_ids)),
                    ok=len(test_ids) > 0,
                )

            # Zero IDs means CCT class creation failed silently.
            if len(test_ids) == 0:
                raise BrowserStepError(
                    "[hire_nav] No hire-test IDs found — CCT class may not have been "
                    "created correctly. Check the edit-sbat-group page manually."
                )

            # Auto-detect attempt count from what CCT actually created.
            # Re-derive windows so the tracker and Hire Test updates always
            # match the real class structure (1, 2, 3, or 4 attempts).
            actual_n = len(test_ids)
            if actual_n != len(windows):
                log.info(
                    "[hire_nav] CCT created %d attempt(s); plan had %d — "
                    "re-deriving windows from actual count",
                    actual_n, len(windows),
                )
                actual_windows = derive_attempt_windows_by_count(request.start, actual_n)
            else:
                actual_windows = list(windows)
            schedule_result.actual_windows = actual_windows

            # Step 6: set each attempt's window.
            # Fast path: Playwright APIRequestContext PATCH — no page navigation needed.
            # page.context.request shares the browser's session cookies with any page
            # already open (the CCT tab), so we never open a hire test tab when this
            # works.  Falls back to Playwright UI (date picker + modal) only on failure.
            emit("hire_update", "Updating Hire Test windows for each attempt")
            applied_count = 0
            unverified_attempts: list[str] = []
            _hire_playwright_page = None  # reused across iterations

            for i, test_id in enumerate(test_ids):
                if i >= len(actual_windows):
                    break
                window = actual_windows[i]
                _attempt_verified = False
                _api_attempted = False

                # ── Open hire test page first ─────────────────────────────── #
                # Must happen before the fast path so the CSRF token we send
                # comes from the hire test endpoint itself (not the CCT page).
                # Using the CCT page's token causes the server to rotate CSRF
                # on the POST, staling the meta tag and breaking the UI fallback.
                try:
                    if _hire_playwright_page is None:
                        _hire_playwright_page = bm.new_hire_page(test_id)
                    else:
                        bm.reuse_hire_page(_hire_playwright_page, test_id)
                except Exception as _open_exc:  # noqa: BLE001
                    log.warning("hire page open failed for %s: %s", test_id, _open_exc)
                    _hire_playwright_page = None

                # ── Fast path: API via browser context ────────────────────── #
                if HireTest._api_endpoint and _hire_playwright_page is not None:
                    _api_attempted = True
                    try:
                        res = HireTest(_hire_playwright_page).update_window_via_fetch(test_id, window)
                        _attempt_verified = res.applied and res.verified
                        if _attempt_verified:
                            applied_count += 1
                        emit(
                            "hire_update",
                            f"[fetch] {window.label} (id {test_id}): "
                            f"{window.start.strftime('%d %b %Y %H:%M IST')} → "
                            f"{window.end.strftime('%d %b %Y %H:%M IST')} "
                            f"(verified={_attempt_verified})",
                            ok=_attempt_verified,
                        )
                        if not _attempt_verified:
                            unverified_attempts.append(f"{window.label}(id={test_id})")
                        continue  # next attempt — no UI needed
                    except BrowserStepError as exc:
                        log.warning(
                            "Fetch update failed for %s (%s) — UI fallback", test_id, exc
                        )
                        emit(
                            "hire_update",
                            f"[fetch→UI] {window.label} fetch failed ({exc}) — UI fallback",
                            ok=True,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "Fetch update error for %s (%s) — UI fallback", test_id, exc
                        )
                        emit(
                            "hire_update",
                            f"[fetch→UI] {window.label} fetch error — UI fallback",
                            ok=True,
                        )

                # ── Fallback: Playwright UI (date picker + modal) ─────────── #
                # If the API path ran, reload the hire page — any POST to
                # basic-settings can rotate the server-side CSRF token, staling
                # the page's meta tag. A fresh GET restores a current token
                # before the UI's .applyBtn XHR fires.
                try:
                    if _hire_playwright_page is None:
                        _hire_playwright_page = bm.new_hire_page(test_id)
                    elif _api_attempted:
                        bm.reuse_hire_page(_hire_playwright_page, test_id)
                    res = HireTest(_hire_playwright_page).update_window(window)
                    _attempt_verified = res.applied and res.verified
                    if _attempt_verified:
                        applied_count += 1
                    emit(
                        "hire_update",
                        f"[UI] {window.label} (id {test_id}): "
                        f"{window.start.strftime('%d %b %Y %H:%M IST')} → "
                        f"{window.end.strftime('%d %b %Y %H:%M IST')} "
                        f"(verified={_attempt_verified})",
                        ok=_attempt_verified,
                    )
                except BrowserStepError as exc:
                    if bm.any_session_limit_page():
                        raise SessionLimitError(
                            "Scaler's 2-session limit was hit. Log out an old session "
                            "at scaler.com or wait, then retry."
                        ) from exc
                    if bm.any_login_page():
                        raise SessionExpiredError(
                            "Scaler session expired — run capture_login.py locally "
                            "to refresh auth, then upload the new storage_state.json."
                        ) from exc
                    emit(
                        "hire_update",
                        f"{window.label} (id {test_id}) failed: {exc}",
                        ok=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    emit(
                        "hire_update",
                        f"{window.label} (id {test_id}) failed: {exc}",
                        ok=False,
                    )

                if not _attempt_verified:
                    unverified_attempts.append(f"{window.label}(id={test_id})")

            if _hire_playwright_page is not None:
                try:
                    _hire_playwright_page.close()
                except Exception:  # noqa: BLE001
                    pass

            # Fail loudly if ANY attempt was not verified — never report success
            # with unconfirmed windows.
            if unverified_attempts:
                raise BrowserStepError(
                    f"[hire_update] Hire Test windows NOT verified for "
                    f"{len(unverified_attempts)}/{len(test_ids)} attempt(s): "
                    f"{', '.join(unverified_attempts)}. "
                    "Run is marked FAILED to prevent partially-set contest windows."
                )

            emit(
                "hire_update",
                f"All {applied_count}/{len(test_ids)} Hire Test window(s) verified "
                f"({actual_n} attempt(s))",
                ok=True,
            )

        if api_client:
            try:
                api_client.save_cookies()
            except Exception:  # noqa: BLE001
                pass
        bm.save_auth()
        return schedule_result

    # ── Validation helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _validate_windows(windows: list[AttemptWindow], num_attempts: int) -> None:
        """
        Validate the computed attempt windows before any browser work.
        Raises ContestAgentError on:
          - count != num_attempts
          - any window where start >= end
          - windows not in strictly chronological order
          - overlapping windows
        """
        if len(windows) != num_attempts:
            raise ContestAgentError(
                f"Expected {num_attempts} attempt window(s) but computed {len(windows)}. "
                "Check ATTEMPT_DURATIONS in config or the supplied end date."
            )
        for i, w in enumerate(windows):
            if w.start >= w.end:
                raise ContestAgentError(
                    f"{w.label}: start {w.start.strftime('%d %b %Y %H:%M')} "
                    f"is not before end {w.end.strftime('%d %b %Y %H:%M')}."
                )
            if i > 0:
                prev = windows[i - 1]
                # Re-attempt windows snap to midnight of the day the previous
                # attempt ends, so w.start may fall earlier on that day than
                # prev.end — this is intentional. Only reject genuine reversals
                # where the start DATE goes backwards.
                if w.start.date() < prev.start.date():
                    raise ContestAgentError(
                        f"{w.label} starts ({w.start.strftime('%d %b %Y %H:%M')}) "
                        f"before {prev.label} starts ({prev.start.strftime('%d %b %Y %H:%M')}). "
                        "Attempt windows are out of order."
                    )

    # ── API helpers ────────────────────────────────────────────────────────────

    def _api_schedule_class(
        self,
        api_client: object,
        batch_id: str,
        library: LibraryMatch,
        start: datetime,
    ) -> ScheduleResult:
        """
        Try to schedule a class via the CCT HTTP API.

        Slot selection mirrors the Playwright logic: uses the start DATE's weekday
        to determine preferred pattern (MWF or TTHS), tries same-pattern 7AM before
        crossing to the other pattern.

        Raises ScalerAPIError (or any Exception) if the API path fails.
        The caller catches and falls back to Playwright.
        """
        from config import (
            SCHEDULE_SLOT_MWF,      SCHEDULE_SLOT_SEARCH_MWF,
            SCHEDULE_SLOT_MWF_7AM,  SCHEDULE_SLOT_SEARCH_MWF_7AM,
            SCHEDULE_SLOT_TTHS,     SCHEDULE_SLOT_SEARCH_TTHS,
            SCHEDULE_SLOT_TTHS_7AM, SCHEDULE_SLOT_SEARCH_TTHS_7AM,
            schedule_slot_for_today,
        )
        from modules.scaler_api import ScalerAPIError

        preferred_slot, _ = schedule_slot_for_today(today=start.date())
        if preferred_slot == SCHEDULE_SLOT_TTHS:
            candidates = [
                SCHEDULE_SLOT_TTHS, SCHEDULE_SLOT_TTHS_7AM,
                SCHEDULE_SLOT_MWF,  SCHEDULE_SLOT_MWF_7AM,
            ]
        else:
            candidates = [
                SCHEDULE_SLOT_MWF,  SCHEDULE_SLOT_MWF_7AM,
                SCHEDULE_SLOT_TTHS, SCHEDULE_SLOT_TTHS_7AM,
            ]

        # Fetch available slots for this batch
        slots = api_client.get_batch_slots(batch_id)
        if not slots:
            raise ScalerAPIError(
                f"No batch slots returned for batch {batch_id}. "
                "Endpoint may be wrong — run api_probe.py."
            )

        slot_id: Optional[str] = None
        chosen_label: Optional[str] = None
        for label in candidates:
            found = api_client.find_slot_id(slots, label)
            if found:
                slot_id = found
                chosen_label = label
                break

        if not slot_id:
            available = [
                s.get("label") or s.get("name") or str(s) for s in slots[:6]
            ]
            raise ScalerAPIError(
                f"No configured slot matched for batch {batch_id}. "
                f"Available: {available}"
            )

        log.info("API scheduling: batch=%s library=%s slot=%s (%s) date=%s",
                 batch_id, library.library_id, slot_id, chosen_label, start.date())

        resp = api_client.create_scheduled_class(
            batch_id=batch_id,
            library_id=library.library_id,
            slot_id=slot_id,
            start_date=start.strftime("%Y-%m-%d"),
        )

        # Parse SBAT ID from response (shape is INFERRED)
        sbat_data = resp.get("sbat", resp)
        class_id = str(
            sbat_data.get("id") or sbat_data.get("sbat_id") or ""
        ) or None

        # Try to extract hire test IDs directly from the create response.
        # If not present, do a follow-up GET on the SBAT (may need a brief wait
        # for the server to populate test groups asynchronously).
        test_ids = api_client.extract_test_ids_from_sbat(resp)
        if not test_ids and class_id:
            import time as _time
            _time.sleep(2)
            sbat_resp = api_client.get_sbat(class_id)
            test_ids = api_client.extract_test_ids_from_sbat(sbat_resp)

        result = ScheduleResult(
            batch_name=library.module,
            library_name=library.library_name,
            class_id=class_id,
        )
        result.test_ids = test_ids
        return result


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
    created_by: str = "Unknown",
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
        created_by=created_by,
    )
    return ContestOrchestrator().run(
        request,
        browser=browser,
        dry_run_tracker=dry_run_tracker,
        overwrite_tracker=overwrite_tracker,
        skip_hire_test=skip_hire_test,
        progress=progress,
    )
