"""
smoke_test.py
=============
Fast, dependency-light checks for the non-browser core. Run:

    python smoke_test.py

Validates library resolution, ambiguity/not-found handling, the re-attempt
derivation rule, contest naming, tracker dry-run append, and duplicate
detection - all against the real workbooks in ./data. No Playwright or network
required. Exits non-zero on any failure.
"""

from __future__ import annotations

import sys
from datetime import datetime

from config import build_contest_name
from modules.library_reader import LibraryReader
from modules.tracker import ContestTracker
from modules.utils import (
    AmbiguousLibraryError,
    DuplicateContestError,
    LibraryNotFoundError,
    derive_attempt_windows,
)

PASS, FAIL = "PASS", "FAIL"
failures = 0


def check(name: str, cond: bool) -> None:
    global failures
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond:
        failures += 1


def main() -> int:
    print("Library resolution")
    r = LibraryReader()
    m = r.resolve("academy", "Advanced DSA 4")
    check("Advanced DSA 4 -> id 277", m.library_id == "277")
    check("devops AWS 1 resolves", r.resolve("devops", "AWS 1").library_id == "592")

    try:
        r.resolve("academy", "Advance Programming Concepts")
        check("ambiguous raises", False)
    except AmbiguousLibraryError:
        check("ambiguous raises", True)

    try:
        r.resolve("academy", "Does Not Exist")
        check("not-found raises", False)
    except LibraryNotFoundError:
        check("not-found raises", True)

    print("Re-attempt derivation (matches Advanced DSA 4 screenshot)")
    wins = derive_attempt_windows(
        datetime(2026, 5, 25, 21, 0), datetime(2026, 6, 4, 21, 0)
    )
    check("4 windows", len(wins) == 4)
    check("A2 starts 4 Jun 00:00", wins[1].start == datetime(2026, 6, 4, 0, 0))
    check("A2 ends 11 Jun (7d)", wins[1].end == datetime(2026, 6, 11, 0, 0))
    check("A3 ends 20 Jun (9d)", wins[2].end == datetime(2026, 6, 20, 0, 0))
    check("A4 ends 30 Jun (10d)", wins[3].end == datetime(2026, 6, 30, 0, 0))

    print("Naming")
    name = build_contest_name("Advanced DSA 4", datetime(2026, 6, 25))
    check("name convention", name == "Advanced DSA 4: NV Contest June 2026")

    print("Tracker dry-run + duplicate detection")
    t = ContestTracker()
    row = t.append_contest(
        module="Advanced DSA 4",
        batch_name=build_contest_name("Advanced DSA 4", datetime(2026, 9, 1)),
        windows=derive_attempt_windows(
            datetime(2026, 9, 1, 21, 0), datetime(2026, 9, 10, 21, 0)
        ),
        dry_run=True,
    )
    check("dry-run returns a row", isinstance(row, int) and row >= 4)

    try:
        t.append_contest(
            module="Advanced DSA 4",
            batch_name=build_contest_name("Advanced DSA 4", datetime(2026, 6, 25)),
            windows=wins,
            dry_run=True,
        )
        check("duplicate raises", False)
    except DuplicateContestError:
        check("duplicate raises", True)

    print()
    if failures:
        print(f"{failures} check(s) FAILED")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
