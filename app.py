"""
app.py
======
Command-line entrypoint for the Contest Agent.

Examples
--------
    # Full run (browser + tracker write):
    python app.py --module "Advanced DSA 4" \
                  --contest-name "Advanced DSA 4 July Contest" \
                  --start "2026-07-20 21:00" --end "2026-07-30 21:00"

    # Safe dry run, no browser, tracker not written:
    python app.py --module "Advanced DSA 4" --contest-name x \
                  --start "2026-07-20 21:00" --end "2026-07-30 21:00" \
                  --no-browser --dry-run-tracker

    # DevOps program, explicit library override:
    python app.py --module "AWS 1" --program devops \
                  --contest-name "AWS 1 Contest" \
                  --start "2026-07-01 21:00" --end "2026-07-15 21:00"
"""

from __future__ import annotations

import argparse
import sys

from config import DEFAULT_PROGRAM
from modules.logger import get_logger
from modules.orchestrator import ContestOutcome, create_contest

log = get_logger("app")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Neovarsity Contest Creation Agent")
    p.add_argument("--module", required=True, help="Module name, e.g. 'Advanced DSA 4'")
    p.add_argument("--contest-name", required=True, help="Operator display name")
    p.add_argument("--start", required=True, help="Contest start (e.g. '2026-07-20 21:00')")
    p.add_argument("--end", required=True, help="Contest end (e.g. '2026-07-30 21:00')")
    p.add_argument("--program", default=DEFAULT_PROGRAM, choices=["academy", "devops", "dsml", "aiml"])
    p.add_argument("--library-name", default=None, help="Explicit library override (ambiguous modules)")
    p.add_argument("--batch-name-override", default=None, help="Exact batch name (skips auto-naming, e.g. for July label)")
    p.add_argument("--no-browser", action="store_true", help="Skip browser steps (Excel-only)")
    p.add_argument("--dry-run-tracker", action="store_true", help="Do not write the tracker")
    p.add_argument("--overwrite-tracker", action="store_true", help="Overwrite existing tracker row if it already exists")
    return p.parse_args(argv)


def _print_summary(outcome: ContestOutcome) -> None:
    line = "=" * 56
    print("\n" + line)
    if outcome.success:
        print("  CONTEST SUCCESSFULLY CREATED")
    else:
        print("  CONTEST CREATION FAILED")
    print(line)
    print(f"  Batch Name      : {outcome.batch_name}")
    print(f"  Library Used    : {outcome.library_used}")
    print(f"  Contest ID      : {outcome.contest_id or '-'}")
    print(f"  Test IDs        : {', '.join(outcome.test_ids) or '-'}")
    print(f"  Tracker Updated : row {outcome.tracker_row}" if outcome.tracker_row else "  Tracker Updated : -")
    print(f"  Execution Time  : {outcome.execution_seconds}s")
    if outcome.error:
        print(f"  Error           : {outcome.error}")
    print(line + "\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    outcome = create_contest(
        module=args.module,
        contest_name=args.contest_name,
        start=args.start,
        end=args.end,
        program=args.program,
        library_name=args.library_name,
        batch_name_override=args.batch_name_override,
        browser=not args.no_browser,
        dry_run_tracker=args.dry_run_tracker,
        overwrite_tracker=args.overwrite_tracker,
        progress=lambda step, msg, ok: None,  # logger already prints
    )
    _print_summary(outcome)
    return 0 if outcome.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
