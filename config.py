"""
config.py
=========
Single source of truth for all configuration. Everything that could change
between environments (URLs, file paths, sheet names, the re-attempt timing
rule, the contest-name convention) lives here and is overridable via the
environment / .env file. Avoid hardcoding these values anywhere else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
DATA_DIR = BASE_DIR / "data"

for _d in (LOGS_DIR, SCREENSHOTS_DIR, DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def _env_path(var: str, default: Path) -> Path:
    raw = os.getenv(var)
    return Path(raw).expanduser().resolve() if raw else default


# Source workbooks. Defaults point at ./data so you can drop the files there,
# but production should set these in .env to the real shared locations.
LIBRARY_WORKBOOK: Path = _env_path(
    "LIBRARY_WORKBOOK", DATA_DIR / "Library__All_Programs.xlsx"
)
TRACKER_WORKBOOK: Path = _env_path(
    "TRACKER_WORKBOOK", DATA_DIR / "NV_contests_Tracker_Q2-2026_.xlsx"
)

# Local metadata store (never written into the production tracker).
METADATA_DB: Path = _env_path("METADATA_DB", DATA_DIR / "contest_agent.sqlite3")


# --------------------------------------------------------------------------- #
# Program / library lookup
# --------------------------------------------------------------------------- #
# The library workbook has one sheet per program. The operator supplies the
# program, so we know which sheet to read and how its columns are laid out.
@dataclass(frozen=True)
class SheetSpec:
    """Describes where module/library columns live within a library sheet."""

    sheet_name: str
    module_col: str          # header text for the module column
    library_col: str         # header text for the library-name column
    link_col: Optional[str]  # header text for the library-link column (if any)
    status_col: Optional[str] = None  # e.g. DevOps "CC" = Live/Old


PROGRAMS: dict[str, SheetSpec] = {
    "academy": SheetSpec(
        sheet_name="Academy Libraries",
        module_col="module_name",
        library_col="library name",
        link_col="Library Link",
    ),
    "devops": SheetSpec(
        sheet_name="DevOps Libraries",
        module_col="Module Name",
        library_col="Library Name",
        link_col="Link",
        status_col="CC",
    ),
    "dsml": SheetSpec(
        sheet_name="DSML Libraries",
        module_col="Module Name",
        library_col="Library Name",
        link_col="Link",
        status_col="CC",
    ),
    "aiml": SheetSpec(
        sheet_name="AIML Libraries",
        module_col="Module Name",
        library_col="Library Name",
        link_col="Link",
        status_col="CC",
    ),
}

DEFAULT_PROGRAM = os.getenv("DEFAULT_PROGRAM", "academy").lower()


# --------------------------------------------------------------------------- #
# Tracker append target
# --------------------------------------------------------------------------- #
# NOTE the trailing space in the real sheet name. The tracker is a production
# file: we append a row using ONLY the columns the ops team fills manually and
# preserve every existing formula/format. See tracker.py for the exact logic.
TRACKER_SHEET = os.getenv("TRACKER_SHEET", "Academy New Contests ")

# 1-based column indices in that sheet (Module, Batch, then 4 attempt windows).
# Columns K-N (No. of Attempts / Deadline / Days Remaining / Status) are
# spreadsheet formulas and are intentionally NOT written by the agent.
TRACKER_COLS = {
    "module": 1,        # A
    "batch_name": 2,    # B  (often a CONCATENATE formula in existing rows)
    "a1_start": 3,      # C
    "a1_end": 4,        # D
    "a2_start": 5,      # E
    "a2_end": 6,        # F
    "a3_start": 7,      # G
    "a3_end": 8,        # H
    "a4_start": 9,      # I
    "a4_end": 10,       # J
}
# First data row (row 1 = banner, row 2 = headers, row 3 = sub-headers).
TRACKER_FIRST_DATA_ROW = int(os.getenv("TRACKER_FIRST_DATA_ROW", "4"))


# --------------------------------------------------------------------------- #
# Contest naming convention
# --------------------------------------------------------------------------- #
# Confirmed from both the tracker and the CCT screenshot:
#   "Advanced DSA 4: NV Contest June 2026"
CONTEST_NAME_TEMPLATE = os.getenv(
    "CONTEST_NAME_TEMPLATE", "{module}: NV Contest {month} {year}"
)


def build_contest_name(module: str, start: datetime) -> str:
    """Render the canonical batch/contest name from the module + start date."""
    return CONTEST_NAME_TEMPLATE.format(
        module=module.strip(),
        month=start.strftime("%B"),
        year=start.year,
    )


# --------------------------------------------------------------------------- #
# Re-attempt window derivation rule
# --------------------------------------------------------------------------- #
# Inferred from the modal pattern across the tracker and the Group Contest
# Summary screenshot for "Advanced DSA 4":
#   A1 : operator-supplied  (e.g. 25 May 21:00 -> 4 Jun 21:00)
#   A2 : starts when A1 ends, snapped to 00:00; +7 days
#   A3 : starts when A2 ends (00:00);           +9 days
#   A4 : starts when A3 ends (00:00);           +10 days
# Durations are config so changing the cadence is a one-line edit.
@dataclass(frozen=True)
class ReattemptRule:
    snap_to_midnight: bool = True
    a2_days: int = int(os.getenv("REATTEMPT_A2_DAYS", "7"))
    a3_days: int = int(os.getenv("REATTEMPT_A3_DAYS", "9"))
    a4_days: int = int(os.getenv("REATTEMPT_A4_DAYS", "10"))


REATTEMPT_RULE = ReattemptRule()

# --------------------------------------------------------------------------- #
# Smart date defaults (Streamlit UI auto-calculation)
# --------------------------------------------------------------------------- #
# When the operator picks a number of attempts without supplying an end date,
# each attempt window is sized according to this table (days per window):
#   1 attempt  (contest only):         30 days
#   2 attempts (contest + 1 re-try):   15 days each
#   3 attempts (contest + 2 re-tries):  7 days each
#   4 attempts (contest + 3 re-tries):  7 days each
ATTEMPT_DURATIONS: dict[int, list[int]] = {
    1: [30],
    2: [15, 15],
    3: [7, 7, 7],
    4: [7, 7, 7, 7],
}


# --------------------------------------------------------------------------- #
# Browser / target systems
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = os.getenv("HEADLESS", "false").lower() == "true"
    slow_mo_ms: int = int(os.getenv("SLOW_MO_MS", "0"))
    default_timeout_ms: int = int(os.getenv("DEFAULT_TIMEOUT_MS", "30000"))
    nav_timeout_ms: int = int(os.getenv("NAV_TIMEOUT_MS", "45000"))
    # Persisted auth state so we don't script the SSO login every run.
    storage_state: Optional[str] = os.getenv("STORAGE_STATE_PATH") or str(
        DATA_DIR / "storage_state.json"
    )
    user_data_dir: Optional[str] = os.getenv("USER_DATA_DIR") or None


BROWSER = BrowserConfig()

# Retry policy for flaky UI / network steps.
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(os.getenv("RETRY_BACKOFF_SECONDS", "2.0"))

# Target system URLs (System 1-3 from the brief).
URLS = {
    "admin_batches": os.getenv(
        "URL_ADMIN_BATCHES",
        "https://www.scaler.com/admin/academy/v2/batches",
    ),
    "schedule_classes": os.getenv(
        "URL_SCHEDULE_CLASSES",
        "https://www.scaler.com/scm/classes/schedule-classes",
    ),
    "view_schedule": os.getenv(
        "URL_VIEW_SCHEDULE",
        "https://www.scaler.com/scm/classes/view-schedule",
    ),
    # Hire test base; the concrete test id is appended at runtime.
    "hire_test_base": os.getenv(
        "URL_HIRE_TEST_BASE", "https://www.scaler.com/hire/test"
    ),
}

# Default contest duration shown in CCT / Hire Test (minutes).
DEFAULT_CONTEST_DURATION_MIN = int(os.getenv("DEFAULT_CONTEST_DURATION_MIN", "90"))


# --------------------------------------------------------------------------- #
# Real-workflow settings (captured from operator's Playwright recording)
# --------------------------------------------------------------------------- #
# Batches are created by CLONING an existing "nv" batch, not Create New.
# The operator filters the batches table by this keyword and clones the first
# matching row, then renames it and sets strength.
BATCH_CLONE_FILTER_KEYWORD = os.getenv("BATCH_CLONE_FILTER_KEYWORD", "nv ")
# Exact batch name to clone. Always clones this specific batch.
BATCH_CLONE_TEMPLATE_NAME = os.getenv(
    "BATCH_CLONE_TEMPLATE_NAME",
    "Backend LLD and Development 1: NV Contest July 2026",
)
# Strength set on the cloned contest batch (always 1 per operator).
BATCH_CLONE_STRENGTH = os.getenv("BATCH_CLONE_STRENGTH", "1")

# Library name used when a module has no entry in the library sheet.
FALLBACK_LIBRARY_NAME = os.getenv("FALLBACK_LIBRARY_NAME", "NV Contests")

# Shared password for the Streamlit UI. Set via APP_PASSWORD env var.
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# CCT schedule-slot labels. The slot chosen depends on the day the agent runs:
#   - MWF   if today is Monday / Wednesday / Friday
#   - T-Th-Sat otherwise
SCHEDULE_SLOT_MWF = os.getenv(
    "SCHEDULE_SLOT_MWF",
    "Mon 09:00 PM | Wed 09:00 PM | Fri 09:00 PM (GMT+05:30)",
)
SCHEDULE_SLOT_TTHS = os.getenv(
    "SCHEDULE_SLOT_TTHS",
    "Tue 09:00 PM | Thu 09:00 PM | Sat 09:00 PM (GMT+05:30)",
)
# Search text typed into the slot dropdown for each (narrows the options list).
SCHEDULE_SLOT_SEARCH_MWF = os.getenv("SCHEDULE_SLOT_SEARCH_MWF", "mon 09")
SCHEDULE_SLOT_SEARCH_TTHS = os.getenv("SCHEDULE_SLOT_SEARCH_TTHS", "tue 09")


def schedule_slot_for_today(today=None) -> tuple[str, str]:
    """
    Return (slot_label, slot_search_text) for the run day.
    MWF on Mon/Wed/Fri (weekday 0/2/4), else T-Th-Sat.
    """
    from datetime import date as _date

    d = today or _date.today()
    if d.weekday() in (0, 2, 4):  # Mon, Wed, Fri
        return SCHEDULE_SLOT_MWF, SCHEDULE_SLOT_SEARCH_MWF
    return SCHEDULE_SLOT_TTHS, SCHEDULE_SLOT_SEARCH_TTHS
