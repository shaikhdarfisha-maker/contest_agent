"""
google_tracker.py
=================
Writes contest rows to a Google Sheet, mirroring the column layout of the
Excel tracker (Module=A, Batch Name=B, A1 start=C … A4 end=J).

Formula columns (K-N: No. of Attempts, Deadline, Days Remaining, Status) are
never written — they are left for Google Sheets to compute.

Authentication uses a service account JSON key file. Share the target sheet
with the service account's email address (viewer + editor).

Required .env vars:
    GOOGLE_SHEET_ID              — the long ID from the sheet URL
    GOOGLE_SERVICE_ACCOUNT_JSON  — path to the downloaded service-account JSON
    GOOGLE_SHEET_NAME            — tab name (defaults to TRACKER_SHEET from config)
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from config import (
    GOOGLE_SERVICE_ACCOUNT_JSON,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEET_NAME,
    GOOGLE_SHEET_NAMES,
    TRACKER_COLS,
    TRACKER_COLS_BY_PROGRAM,
    TRACKER_FIRST_DATA_ROW,
    TRACKER_FIRST_DATA_ROW_BY_PROGRAM,
)
from modules.logger import get_logger
from modules.utils import AttemptWindow, DuplicateContestError, TrackerUpdateError

log = get_logger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Columns the agent must NOT write (formula / auto-computed in the sheet).
_FORMULA_COLS = {11, 12, 13, 14}  # K, L, M, N


def _fmt(dt: datetime) -> str:
    """Format a datetime so Google Sheets parses it as a date (USER_ENTERED)."""
    return dt.strftime("%d/%m/%Y %H:%M")


class GoogleContestTracker:
    """Safe, formula-preserving writer for a Google Sheets contest tracker."""

    def __init__(
        self,
        sheet_id: str = GOOGLE_SHEET_ID,
        program: str = "academy",
        creds_path: str = GOOGLE_SERVICE_ACCOUNT_JSON,
    ) -> None:
        if not sheet_id:
            raise TrackerUpdateError(
                "GOOGLE_SHEET_ID is not set. Add it to .env."
            )
        if not creds_path:
            raise TrackerUpdateError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is not set. Add it to .env."
            )
        sheet_name = GOOGLE_SHEET_NAMES.get(program.lower(), GOOGLE_SHEET_NAME)
        creds = Credentials.from_service_account_file(creds_path, scopes=_SCOPES)
        client = gspread.authorize(creds)
        sh = client.open_by_key(sheet_id)
        self._ws = sh.worksheet(sheet_name)
        self._program = program
        self._cols: dict[str, int] = TRACKER_COLS_BY_PROGRAM.get(program.lower(), TRACKER_COLS)
        self._first_data_row: int = TRACKER_FIRST_DATA_ROW_BY_PROGRAM.get(program.lower(), TRACKER_FIRST_DATA_ROW)
        log.info("Google Sheet '%s' opened for program '%s'", sheet_name, program)

    # ------------------------------------------------------------------ #
    def _all_rows(self) -> list[list[str]]:
        return self._ws.get_all_values()

    def _find_row(self, batch_name: str) -> Optional[int]:
        """Return 1-based row index of an existing batch, or None."""
        rows = self._all_rows()
        bat_col = self._cols["batch_name"] - 1  # 0-based
        target = batch_name.strip().lower()
        for i, row in enumerate(
            rows[self._first_data_row - 1 :], start=self._first_data_row
        ):
            if len(row) <= bat_col:
                continue
            if row[bat_col].strip().lower() == target:
                return i
        return None

    def _first_empty_row(self) -> int:
        """Return the 1-based index of the first empty row below existing data."""
        rows = self._all_rows()
        # Use batch_name column as the anchor — present in every program layout.
        check_col = self._cols["batch_name"] - 1
        for i in range(self._first_data_row - 1, len(rows)):
            if len(rows[i]) <= check_col or not rows[i][check_col].strip():
                return i + 1  # convert to 1-based
        return len(rows) + 1  # append after last row

    # ------------------------------------------------------------------ #
    def append_contest(
        self,
        *,
        module: str,
        batch_name: str,
        windows: list[AttemptWindow],
        dry_run: bool = False,
        overwrite: bool = False,
    ) -> int:
        """
        Write one contest row. Returns the 1-based row index written.

        Only the manual columns are written; formula columns (K-N) are untouched.
        Attempt windows beyond the list are left blank.
        """
        if not windows:
            raise TrackerUpdateError("At least the main contest window is required.")

        existing_row = self._find_row(batch_name)
        if existing_row is not None and not overwrite:
            raise DuplicateContestError(
                f"A row for batch '{batch_name}' already exists in the Google Sheet."
            )

        row = existing_row or self._first_empty_row()

        # Build (row, col, value) triples for all manual cells.
        cells: list[gspread.Cell] = []
        if "module" in self._cols:
            cells.append(gspread.Cell(row, self._cols["module"], module))
        cells.append(gspread.Cell(row, self._cols["batch_name"], batch_name))

        attempt_col_keys = [
            ("a1_start", "a1_end"),
            ("a2_start", "a2_end"),
            ("a3_start", "a3_end"),
            ("a4_start", "a4_end"),
        ]
        for win, (sk, ek) in zip(windows, attempt_col_keys):
            cells.append(gspread.Cell(row, self._cols[sk], _fmt(win.start)))
            cells.append(gspread.Cell(row, self._cols[ek], _fmt(win.end)))

        if dry_run:
            log.info("[dry-run] Would write '%s' at row %d in Google Sheet", batch_name, row)
            return row

        # USER_ENTERED lets Sheets parse the date strings as real dates.
        self._ws.update_cells(cells, value_input_option="USER_ENTERED")
        action = "Updated" if existing_row else "Appended"
        log.info("%s '%s' at row %d in Google Sheet", action, batch_name, row)
        return row

    # ------------------------------------------------------------------ #
    def suggest_next_name(self, module: str) -> str:
        """
        Read existing rows to find the latest NV Contest month for this module
        and suggest the next month's name.
        """
        month_index = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
        found: list[tuple[int, int]] = []

        rows = self._all_rows()
        bat_col = self._cols["batch_name"] - 1
        # For sheets without a module column, match by checking the batch_name
        # prefix; for sheets with a module column, use the dedicated column.
        mod_col: Optional[int] = (self._cols["module"] - 1) if "module" in self._cols else None
        module_norm = module.strip().lower()

        for row in rows[self._first_data_row - 1 :]:
            if len(row) <= bat_col:
                continue
            if mod_col is not None:
                if len(row) <= mod_col:
                    continue
                if row[mod_col].strip().lower() != module_norm:
                    continue
            else:
                # No module column: match by batch_name starting with the module.
                if not row[bat_col].strip().lower().startswith(module_norm):
                    continue
            m = re.search(r"NV\s+Contest\s+(\w+)\s+(\d{4})", row[bat_col], re.I)
            if m:
                mon_str = m.group(1).lower()
                if mon_str in month_index:
                    found.append((int(m.group(2)), month_index[mon_str]))

        if not found:
            now = datetime.now()
            return f"{module}: NV Contest {now.strftime('%B')} {now.year}"

        latest_year, latest_month = max(found)
        next_year = latest_year + (1 if latest_month == 12 else 0)
        next_month = 1 if latest_month == 12 else latest_month + 1
        return f"{module}: NV Contest {calendar.month_name[next_month]} {next_year}"
