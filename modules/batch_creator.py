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
    BATCH_CLONE_TEMPLATE_NAME,
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
        """Clone an existing NV batch, or reuse it if it already exists."""
        log.info("Creating batch via clone: %s", batch_name)
        self.page.goto(URLS["admin_batches"])

        # Guard: reuse if a previous (failed) run already created this batch.
        existing_id = self._find_existing_batch(batch_name)
        if existing_id is not None:
            log.warning(
                "Batch '%s' already exists (id=%s) — reusing to avoid duplicate",
                batch_name, existing_id or "unknown",
            )
            return BatchResult(batch_name=batch_name, batch_id=existing_id or None)

        # Batch doesn't exist — reload and filter by template keyword to clone.
        self.page.goto(URLS["admin_batches"])
        try:
            self.page.locator(
                "th:nth-child(2) > .data-table__header-item > "
                ".data-table__header-actions > "
                ".tappable.btn.btn-light.btn-small.data-table__action."
                "data-table__action--filter"
            ).click()
            filter_form = self.page.locator("form").filter(
                has_text="KeywordClearApply"
            )
            filter_form.get_by_role("textbox").click()
            filter_form.get_by_role("textbox").fill(BATCH_CLONE_FILTER_KEYWORD)
            self.page.get_by_role("button", name="Apply").click()
            self.page.wait_for_load_state("domcontentloaded")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not filter batches to clone: {exc}")

        try:
            template = BATCH_CLONE_TEMPLATE_NAME
            if template:
                row = self.page.locator("tr").filter(has_text=template)
                row.get_by_text("Clone").click()
            else:
                self.page.get_by_text("Clone").first.click()

            name_box = self.page.get_by_role(
                "textbox", name="Enter Super Batch Name"
            )
            name_box.click()
            name_box.fill(batch_name)

            strength = self.page.get_by_role("spinbutton")
            strength.click()
            strength.fill(str(BATCH_CLONE_STRENGTH))
            self.page.get_by_role("checkbox").check()

            self.page.get_by_role("button", name="Clone").click()
            # domcontentloaded is enough — we don't need all XHR to settle
            self.page.wait_for_load_state("domcontentloaded")
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Clone step threw — checking if batch '%s' already exists: %s",
                batch_name, exc,
            )
            self.page.goto(URLS["admin_batches"])
            fallback_id = self._find_existing_batch(batch_name)
            if fallback_id is not None:
                log.warning(
                    "Batch '%s' found after clone error (id=%s) — reusing",
                    batch_name, fallback_id,
                )
                return BatchResult(batch_name=batch_name, batch_id=fallback_id or None)
            raise BrowserStepError(f"Could not complete batch clone: {exc}")

        # Skip the round-trip back to the list just to read the ID —
        # batch_id is nice-to-have metadata but not required for the workflow.
        log.info("Batch created via clone: %s", batch_name)
        return BatchResult(batch_name=batch_name, batch_id=None)

    def _find_existing_batch(self, batch_name: str) -> Optional[str]:
        """Filter the batches table for batch_name; return its id if found, else None."""
        try:
            self.page.locator(
                "th:nth-child(2) > .data-table__header-item > "
                ".data-table__header-actions > "
                ".tappable.btn.btn-light.btn-small.data-table__action."
                "data-table__action--filter"
            ).click()
            filter_form = self.page.locator("form").filter(
                has_text="KeywordClearApply"
            )
            filter_form.get_by_role("textbox").click()
            filter_form.get_by_role("textbox").fill(batch_name)
            self.page.get_by_role("button", name="Apply").click()
            self.page.wait_for_load_state("domcontentloaded")

            row = self.page.locator("tr").filter(has_text=batch_name)
            if row.count() == 0:
                return None
            text = row.first.inner_text(timeout=3_000)
            id_match = re.search(r"\b(\d{3,})\b", text)
            return id_match.group(1) if id_match else ""
        except Exception:  # noqa: BLE001
            return None

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
