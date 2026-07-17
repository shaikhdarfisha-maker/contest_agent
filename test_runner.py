"""
test_runner.py
==============
Runs contest creation for every module across all programs to discover
errors before the production rollout.

Batch names use "Test" instead of a month (e.g. "Advanced DSA 1: NV Contest Test").
Results are written to the "Agent Testing" tab in the Google Sheet.

Usage
-----
    # All programs, all modules:
    python3 test_runner.py

    # Specific programs only:
    python3 test_runner.py --programs academy dsml

    # Single module quick test:
    python3 test_runner.py --programs academy --module "Advanced DSA 1"

    # Skip browser (library/config validation only, no CCT):
    python3 test_runner.py --no-browser
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, time

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID, PROGRAMS
from modules.library_reader import LibraryReader
from modules.logger import get_logger
from modules.orchestrator import create_contest

# Force headless — test runner must never open a visible browser window
os.environ.setdefault("HEADLESS", "true")

log = get_logger("test_runner")

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_TEST_SHEET_NAME = "agent testing"
_PROGRAMS = list(PROGRAMS.keys())  # ["academy", "dsml", "devops", "aiml"]

# Header row written once if the sheet is empty
_HEADERS = [
    "Timestamp", "Program", "Module", "Batch Name",
    "Status", "Test IDs", "Error",
]


# --------------------------------------------------------------------------- #
# Google Sheet writer
# --------------------------------------------------------------------------- #
def _get_test_worksheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON, scopes=_SCOPES
    )
    client = gspread.authorize(creds)
    sh = client.open_by_key(GOOGLE_SHEET_ID)

    # Create tab if it doesn't exist
    try:
        ws = sh.worksheet(_TEST_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=_TEST_SHEET_NAME, rows=500, cols=10)
        log.info("Created new tab '%s'", _TEST_SHEET_NAME)

    # Write headers if sheet is empty
    if not ws.get_all_values():
        ws.append_row(_HEADERS, value_input_option="USER_ENTERED")

    return ws


def _write_result(ws: gspread.Worksheet, row: list) -> None:
    ws.append_row(row, value_input_option="USER_ENTERED")


# --------------------------------------------------------------------------- #
# Test loop
# --------------------------------------------------------------------------- #
def run_all(
    programs: list[str],
    module_filter: str | None,
    browser: bool,
    module_set: set[tuple[str, str]] | None = None,
) -> None:
    reader = LibraryReader()
    ws = _get_test_worksheet()

    start_dt = datetime.combine(datetime.today(), time(21, 0))
    results: list[dict] = []

    for prog in programs:
        modules = reader.all_module_names(prog)
        if module_filter:
            modules = [m for m in modules if module_filter.lower() in m.lower()]
        if module_set is not None:
            modules = [m for m in modules if (prog, m) in module_set]

        log.info("=== %s: %d module(s) ===", prog.upper(), len(modules))

        for module in modules:
            batch_name = f"{module}: NV Contest Test"
            log.info("[%s] Running: %s", prog, module)

            outcome = create_contest(
                module=module,
                contest_name=batch_name,
                start=start_dt,
                program=prog,
                batch_name_override=batch_name,
                browser=browser,
                dry_run_tracker=True,   # don't touch production tracker tabs
                overwrite_tracker=True,
                skip_hire_test=True,    # skip Hire Test (~40s×4) to speed up tests
                progress=lambda step, msg, ok: None,
            )

            status = "✅ Success" if outcome.success else "❌ Failed"
            test_ids = ", ".join(outcome.test_ids) if outcome.test_ids else "—"
            error = outcome.error or ""
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")

            row = [ts, prog.upper(), module, batch_name, status, test_ids, error]
            _write_result(ws, row)
            results.append({
                "program": prog,
                "module": module,
                "status": status,
                "error": error,
            })

            icon = "✅" if outcome.success else "❌"
            print(f"  {icon} [{prog}] {module}")
            if not outcome.success:
                print(f"     → {error}")

    # Final summary
    success = sum(1 for r in results if "✅" in r["status"])
    failed  = sum(1 for r in results if "❌" in r["status"])
    print(f"\n{'='*60}")
    print(f"  DONE — {success} passed, {failed} failed out of {len(results)}")
    print(f"  Results written to '{_TEST_SHEET_NAME}' tab in Google Sheet")
    print(f"{'='*60}")

    if failed:
        print("\nFailed modules:")
        for r in results:
            if "❌" in r["status"]:
                print(f"  [{r['program']}] {r['module']}: {r['error'][:80]}")


# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(description="Test agent against all modules")
    p.add_argument(
        "--programs", nargs="+", default=_PROGRAMS,
        choices=_PROGRAMS, help="Programs to test (default: all)"
    )
    p.add_argument("--module", default=None, help="Filter to a specific module name")
    p.add_argument("--no-browser", action="store_true", help="Skip browser steps")
    p.add_argument(
        "--failed-only", action="store_true",
        help="Re-run only modules that failed in the last test run (reads Google Sheet)"
    )
    args = p.parse_args()

    if not GOOGLE_SHEET_ID:
        print("ERROR: GOOGLE_SHEET_ID not set in .env — cannot write results.")
        sys.exit(1)

    module_set = None
    if args.failed_only:
        from google.oauth2.service_account import Credentials as _Creds
        import gspread as _gs
        _creds = _Creds.from_service_account_file(
            GOOGLE_SERVICE_ACCOUNT_JSON, scopes=_SCOPES
        )
        _ws = _gs.authorize(_creds).open_by_key(GOOGLE_SHEET_ID).worksheet(_TEST_SHEET_NAME)
        _rows = _ws.get_all_values()
        seen: set[tuple[str, str]] = set()
        module_set = set()
        for r in _rows[1:]:
            if len(r) > 4 and "Failed" in r[4]:
                key = (r[1].lower(), r[2])
                if key not in seen:
                    seen.add(key)
                    module_set.add(key)
        print(f"--failed-only: {len(module_set)} unique failed module(s) loaded from Sheet\n")

    print(f"Testing {args.programs} — browser={'off' if args.no_browser else 'ON'}")
    print(f"Results → Google Sheet tab: '{_TEST_SHEET_NAME}'\n")

    run_all(
        programs=args.programs,
        module_filter=args.module,
        browser=not args.no_browser,
        module_set=module_set,
    )


if __name__ == "__main__":
    main()
