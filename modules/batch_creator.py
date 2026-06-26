"""
batch_creator.py
================
System 1 - Admin V2 (https://www.scaler.com/admin/academy/v2/batches/).

Creates a contest batch by CLONING an existing "nv" batch (the real operator
workflow, captured via Playwright codegen), then renaming it and setting
strength. Selectors below are the real ones from the recording.

Recorded flow:
  1. Open the batches table.
  2. Open the Name-column filter, type the clone keyword ("nv "), Apply.
  3. Click the first "Clone" action.
  4. Fill "Enter Super Batch Name" with the new batch name.
  5. Set strength spinbutton to 1, tick the checkbox.
  6. Click "Clone" to confirm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page

from config import (
    BATCH_CLONE_FILTER_KEYWORD,
    BATCH_CLONE_STRENGTH,
    URLS,
)
from modules.logger import get_logger
from modules.utils import BrowserStepError, retry

log = get_logger(__name__)


@dataclass
class BatchResult:
    batch_name: str
    batch_id: Optional[str]


class BatchCreator:
    """Page object for creating a batch via clone in Admin V2."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @retry(exceptions=(BrowserStepError,))
    def create_batch(self, batch_name: str) -> BatchResult:
        """Clone an existing NV batch into a new contest batch."""
        log.info("Creating batch via clone: %s", batch_name)
        self.page.goto(URLS["admin_batches"])

        try:
            # Open the Name-column filter (2nd column header filter button).
            self.page.locator(
                "th:nth-child(2) > .data-table__header-item > "
                ".data-table__header-actions > "
                ".tappable.btn.btn-light.btn-small.data-table__action."
                "data-table__action--filter"
            ).click()

            # Type the clone keyword into the filter textbox and apply.
            filter_form = self.page.locator("form").filter(
                has_text="KeywordClearApply"
            )
            filter_form.get_by_role("textbox").click()
            filter_form.get_by_role("textbox").fill(BATCH_CLONE_FILTER_KEYWORD)
            self.page.get_by_role("button", name="Apply").click()
            self.page.wait_for_load_state("networkidle")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not filter batches to clone: {exc}")

        try:
            # Clone the first matching row.
            self.page.get_by_text("Clone").first.click()

            # Rename the cloned batch.
            name_box = self.page.get_by_role(
                "textbox", name="Enter Super Batch Name"
            )
            name_box.click()
            name_box.fill(batch_name)

            # Strength = 1 (spinbutton), then tick the required checkbox.
            strength = self.page.get_by_role("spinbutton")
            strength.click()
            strength.fill(str(BATCH_CLONE_STRENGTH))
            self.page.get_by_role("checkbox").check()

            # Confirm clone.
            self.page.get_by_role("button", name="Clone").click()
            self.page.wait_for_load_state("networkidle")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not complete batch clone: {exc}")

        batch_id = self._extract_batch_id(batch_name)
        log.info("Batch created via clone: %s (id=%s)", batch_name, batch_id)
        return BatchResult(batch_name=batch_name, batch_id=batch_id)

    def _extract_batch_id(self, batch_name: str) -> Optional[str]:
        """Best-effort batch-id extraction from URL or the row."""
        match = re.search(r"/batches/(\d+)", self.page.url)
        if match:
            return match.group(1)
        try:
            row = self.page.get_by_role(
                "row", name=re.compile(re.escape(batch_name))
            )
            text = row.first.inner_text(timeout=5000)
            id_match = re.search(r"\b(\d{3,})\b", text)
            if id_match:
                return id_match.group(1)
        except Exception:  # noqa: BLE001
            log.debug("Batch id not found in row; returning None.")
        return None
