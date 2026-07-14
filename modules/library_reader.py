"""
library_reader.py
=================
Reads Library__All_Programs.xlsx and resolves (program, module) -> library.

The workbook has one sheet per program with slightly different column layouts
(see config.PROGRAMS). The operator always supplies the program, which removes
the cross-program ambiguity. Within a program a module can still map to more
than one library (e.g. Academy "Advance Programming Concepts" has Java and
Python variants); we prefer a "Live"/non-deprecated row when the sheet exposes
a status column, otherwise we raise AmbiguousLibraryError with the candidates
so the caller can decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openpyxl import load_workbook

from config import LIBRARY_WORKBOOK, PROGRAMS, SheetSpec
from modules.logger import get_logger
from modules.utils import AmbiguousLibraryError, LibraryNotFoundError

log = get_logger(__name__)

# Tokens in a library name that indicate a deprecated/non-live row, used as a
# fallback when the sheet has no explicit status column.
_DEPRECATED_TOKENS = ("(na)", "(old", "inverted", "oldv", "(2024)", "(old)")


@dataclass(frozen=True)
class LibraryMatch:
    """Resolved library for a module within a program."""

    module: str
    program: str
    library_name: str
    library_link: Optional[str]
    library_id: Optional[str]


def _norm(text: object) -> str:
    return str(text or "").strip().lower()


def _extract_library_id(link: Optional[str]) -> Optional[str]:
    """Pull the trailing numeric id out of .../edit-library/277 style links."""
    if not link:
        return None
    tail = str(link).rstrip("/").rsplit("/", 1)[-1]
    return tail if tail.isdigit() else None


class LibraryReader:
    """Loads and queries a single library workbook."""

    def __init__(self, workbook_path: Path = LIBRARY_WORKBOOK) -> None:
        self.workbook_path = workbook_path
        if not self.workbook_path.exists():
            raise FileNotFoundError(f"Library workbook not found: {workbook_path}")
        # read_only + data_only: we only need the resolved values, fast.
        self._wb = load_workbook(
            self.workbook_path, read_only=True, data_only=True
        )

    # ---------------------------------------------------------------------- #
    def _header_index(self, rows: list[tuple], spec: SheetSpec) -> dict[str, int]:
        """Find column indices by matching header text (case-insensitive)."""
        header = rows[0]
        index: dict[str, int] = {}
        wanted = {
            "module": _norm(spec.module_col),
            "library": _norm(spec.library_col),
            "link": _norm(spec.link_col) if spec.link_col else None,
            "status": _norm(spec.status_col) if spec.status_col else None,
        }
        for col_i, cell in enumerate(header):
            cell_norm = _norm(cell)
            for key, want in wanted.items():
                if want and cell_norm == want:
                    index[key] = col_i
        if "module" not in index or "library" not in index:
            raise LibraryNotFoundError(
                f"Could not locate module/library headers in sheet "
                f"'{spec.sheet_name}'. Found headers: {header}"
            )
        return index

    def _candidates(self, program: str, module: str) -> list[LibraryMatch]:
        spec = PROGRAMS.get(program.lower())
        if spec is None:
            raise LibraryNotFoundError(
                f"Unknown program '{program}'. Known: {list(PROGRAMS)}"
            )
        if spec.sheet_name not in self._wb.sheetnames:
            raise LibraryNotFoundError(
                f"Sheet '{spec.sheet_name}' not found in {self.workbook_path.name}"
            )

        ws = self._wb[spec.sheet_name]
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            raise LibraryNotFoundError(f"Sheet '{spec.sheet_name}' is empty")

        idx = self._header_index(rows, spec)
        target = _norm(module)
        matches: list[LibraryMatch] = []

        for row in rows[1:]:
            if _norm(row[idx["module"]]) != target:
                continue
            link = row[idx["link"]] if "link" in idx else None
            matches.append(
                LibraryMatch(
                    module=str(row[idx["module"]]).strip(),
                    program=program.lower(),
                    library_name=str(row[idx["library"]]).strip(),
                    library_link=str(link).strip() if link else None,
                    library_id=_extract_library_id(link),
                )
            )
        return matches

    # ---------------------------------------------------------------------- #
    def resolve(
        self, program: str, module: str, *, prefer_live: bool = True
    ) -> LibraryMatch:
        """
        Resolve a module to a single library within a program.

        Raises:
            LibraryNotFoundError   - no row for that module.
            AmbiguousLibraryError  - several plausible rows and none preferred.
        """
        matches = self._candidates(program, module)
        if not matches:
            raise LibraryNotFoundError(
                f"No library found for module '{module}' in program '{program}'."
            )
        if len(matches) == 1:
            log.info("Library resolved: %s -> %s", module, matches[0].library_name)
            return matches[0]

        # Multiple candidates: try to prefer a non-deprecated / live one.
        if prefer_live:
            live = [
                m
                for m in matches
                if not any(tok in _norm(m.library_name) for tok in _DEPRECATED_TOKENS)
            ]
            if len(live) == 1:
                log.info(
                    "Library resolved (live-preferred): %s -> %s",
                    module,
                    live[0].library_name,
                )
                return live[0]
            if live:
                matches = live  # narrow, but still ambiguous

        raise AmbiguousLibraryError(
            f"Module '{module}' in program '{program}' maps to multiple libraries: "
            + "; ".join(m.library_name for m in matches)
            + ". Disambiguate by passing an explicit library_name."
        )

    def resolve_by_name_only(self, program: str, library_name: str) -> LibraryMatch:
        """Find any row in the program sheet whose library name matches, ignoring module."""
        spec = PROGRAMS.get(program.lower())
        if spec is None:
            raise LibraryNotFoundError(f"Unknown program '{program}'.")
        if spec.sheet_name not in self._wb.sheetnames:
            raise LibraryNotFoundError(
                f"Sheet '{spec.sheet_name}' not found in {self.workbook_path.name}"
            )
        ws = self._wb[spec.sheet_name]
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            raise LibraryNotFoundError(f"Sheet '{spec.sheet_name}' is empty")
        idx = self._header_index(rows, spec)
        target = _norm(library_name)
        for row in rows[1:]:
            if _norm(row[idx["library"]]) == target:
                link = row[idx["link"]] if "link" in idx else None
                return LibraryMatch(
                    module=str(row[idx["module"]]).strip(),
                    program=program.lower(),
                    library_name=str(row[idx["library"]]).strip(),
                    library_link=str(link).strip() if link else None,
                    library_id=_extract_library_id(link),
                )
        raise LibraryNotFoundError(
            f"Fallback library '{library_name}' not found in program '{program}'."
        )

    def resolve_explicit(
        self, program: str, module: str, library_name: str
    ) -> LibraryMatch:
        """Resolve when the operator has already named the exact library."""
        target = _norm(library_name)
        for m in self._candidates(program, module):
            if _norm(m.library_name) == target:
                return m
        raise LibraryNotFoundError(
            f"Library '{library_name}' not found for module '{module}' "
            f"in program '{program}'."
        )
