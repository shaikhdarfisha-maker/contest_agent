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

import base64
import calendar
import json
import os
import re
from datetime import datetime
from pathlib import Path
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


def _build_credentials() -> Optional[Credentials]:
    """
    Build Google credentials from a base64-encoded secret — no file required.

    Resolution order:
      1. GOOGLE_CREDS_B64 env var (set by streamlit_app bootstrap)
      2. SERVICE_ACCOUNT_B64 env var (legacy name, same mechanism)
      3. st.secrets["GOOGLE_CREDS_B64"] directly (fallback when bootstrap
         silently failed — safe no-op outside Streamlit)
      4. st.secrets["SERVICE_ACCOUNT_B64"] (legacy name)

    Returns None if no usable secret is found (caller falls back to file).
    """
    _KEYS = ("GOOGLE_CREDS_B64", "SERVICE_ACCOUNT_B64")

    def _from_b64(b64: str, source: str) -> Optional[Credentials]:
        try:
            info = json.loads(base64.b64decode(b64.strip()))
            return Credentials.from_service_account_info(info, scopes=_SCOPES)
        except Exception as exc:
            log.warning("Could not build credentials from %s: %s", source, exc)
            return None

    # 1 & 2 — env vars (populated by _bootstrap_cloud_config in streamlit_app)
    for key in _KEYS:
        b64 = os.getenv(key, "")
        if b64:
            creds = _from_b64(b64, f"env:{key}")
            if creds is not None:
                return creds

    # 3 & 4 — direct Streamlit secrets read (when env var injection was skipped)
    try:
        import streamlit as _st  # soft import — not installed outside Streamlit
        for key in _KEYS:
            b64 = str(_st.secrets.get(key, "") or "")
            if b64:
                creds = _from_b64(b64, f"st.secrets:{key}")
                if creds is not None:
                    return creds
    except Exception:
        pass  # not running inside Streamlit, or secrets not configured

    return None


def _fmt(dt: datetime) -> str:
    """
    Format a datetime for Google Sheets USER_ENTERED writes.

    ISO 8601 (YYYY-MM-DD HH:MM:SS) is unambiguous regardless of the
    spreadsheet locale.  The previous DD/MM/YYYY format failed whenever
    day > 12 because US-locale sheets tried to parse the day as a month.
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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
        # Prefer credentials built from the b64 env var (no filesystem dependency).
        # Fall back to the local service-account JSON file for local dev.
        creds = _build_credentials()
        if creds is None:
            if not creds_path or not Path(creds_path).exists():
                raise TrackerUpdateError(
                    "Google service-account credentials not found. "
                    "Set GOOGLE_CREDS_B64 in Streamlit secrets, or place "
                    "data/service_account.json locally."
                )
            creds = Credentials.from_service_account_file(creds_path, scopes=_SCOPES)
        sheet_name = GOOGLE_SHEET_NAMES.get(program.lower(), GOOGLE_SHEET_NAME)
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

    def _find_module_row(self, module: str) -> Optional[int]:
        """
        Return 1-based row index of the existing module row (col A), or None.

        Match is exact, case-insensitive, whitespace-trimmed.  Search starts at
        _first_data_row to skip banner / header rows.  If multiple rows share the
        same module name (existing duplicates), returns the FIRST match and logs a
        warning listing every duplicate row number.
        """
        rows = self._all_rows()
        mod_col = self._cols.get("module", 1) - 1  # 0-based; col A = 0
        target = module.strip().lower()
        matches: list[int] = []

        for i, row in enumerate(
            rows[self._first_data_row - 1 :], start=self._first_data_row
        ):
            if len(row) <= mod_col:
                continue
            if row[mod_col].strip().lower() == target:
                matches.append(i)

        if not matches:
            return None
        if len(matches) > 1:
            log.warning(
                "Module %r matched %d rows: %s — updating first match (row %d) only",
                module, len(matches), matches, matches[0],
            )
        return matches[0]

    def _first_empty_row(self) -> int:
        """Return the 1-based index of the first empty row below existing data."""
        rows = self._all_rows()
        # Use module column (col A) as the anchor — always a plain value, never a formula.
        mod_col = self._cols.get("module", 1) - 1
        for i in range(self._first_data_row - 1, len(rows)):
            if len(rows[i]) <= mod_col or not rows[i][mod_col].strip():
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
        overwrite: bool = False,  # retained for API compat; upsert is always the behaviour
    ) -> int:
        """
        Upsert one contest row, keyed on Module Name (col A).

        UPDATE path (module found in col A):
          Overwrites Batch Name (col B) and the 8 attempt date columns (C-J) in
          place.  Formula columns K-N (No. of Attempts, Deadline, Days Remaining,
          Status) are NOT touched — they keep computing from the dates we write.

        APPEND path (module not found):
          Writes a new row: Module Name + Batch Name + dates.  Formula columns K-N
          are left blank; Google Sheets does NOT auto-copy formulas to appended rows,
          so they must be manually dragged down after the first append for a new
          module, or the sheet can use array formulas to cover the whole column.

        Returns the 1-based row index written.
        """
        if not windows:
            raise TrackerUpdateError("At least the main contest window is required.")

        existing_row = self._find_module_row(module)
        is_update = existing_row is not None
        row = existing_row if is_update else self._first_empty_row()

        # Build cells — only manual columns; formula columns (K-N) are never written.
        cells: list[gspread.Cell] = []

        if not is_update:
            # New row: write the module name so col A is populated.
            if "module" in self._cols:
                cells.append(gspread.Cell(row, self._cols["module"], module))

        # Always write batch name and all attempt date columns.
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
        # Clear attempt columns beyond those being written so stale dates from a
        # previous 4-attempt row do not persist when a module has fewer attempts.
        for sk, ek in attempt_col_keys[len(windows):]:
            if sk in self._cols:
                cells.append(gspread.Cell(row, self._cols[sk], ""))
            if ek in self._cols:
                cells.append(gspread.Cell(row, self._cols[ek], ""))

        if dry_run:
            action = "update" if is_update else "append"
            log.info(
                "[dry-run] Would %s module %r at row %d in Google Sheet", action, module, row
            )
            return row

        # USER_ENTERED lets Sheets parse the date strings as real dates.
        self._ws.update_cells(cells, value_input_option="USER_ENTERED")

        if is_update:
            log.info(
                "Updated row %d (module=%r, batch=%r) in Google Sheet", row, module, batch_name
            )
        else:
            log.info(
                "Appended row %d (module=%r, batch=%r) in Google Sheet", row, module, batch_name
            )
            log.info(
                "NOTE: formula columns K-N are blank on new rows — "
                "drag formulas down from an existing row if needed."
            )

        return row

    # ------------------------------------------------------------------ #
    def verify_row(
        self,
        row_num: int,
        *,
        module: str,
        batch_name: str,
        windows: list[AttemptWindow],
    ) -> tuple[bool, str]:
        """
        Read back the row at row_num and verify the key fields match what was written.
        Returns (verified: bool, detail_message: str).
        Called by the orchestrator after append_contest() to confirm the write landed.
        """
        try:
            vals = self._ws.row_values(row_num)
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not read back row {row_num}: {exc}"

        def cell(col_name: str) -> str:
            idx = self._cols.get(col_name, 0) - 1  # 0-based
            return vals[idx].strip() if len(vals) > idx >= 0 else ""

        # Batch name (col B) must match exactly (case-insensitive)
        written_batch = cell("batch_name")
        if written_batch.lower() != batch_name.strip().lower():
            return False, (
                f"Row {row_num} batch name mismatch: "
                f"wrote '{batch_name}' but read back '{written_batch}'"
            )

        # A1 start (col C) must be non-empty
        a1_start = cell("a1_start")
        if not a1_start:
            return False, f"Row {row_num}: A1 start date is empty after write"

        # Module column, if present
        if "module" in self._cols:
            written_mod = cell("module")
            if written_mod and written_mod.lower() != module.strip().lower():
                return False, (
                    f"Row {row_num} module mismatch: "
                    f"wrote '{module}' but read back '{written_mod}'"
                )

        date_keys = ["a1_start","a1_end","a2_start","a2_end",
                     "a3_start","a3_end","a4_start","a4_end"]
        n_dates = sum(1 for k in date_keys if cell(k))

        return True, (
            f"Row {row_num}: batch='{written_batch}', "
            f"a1_start='{a1_start}', {n_dates}/8 date cells populated"
        )

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
