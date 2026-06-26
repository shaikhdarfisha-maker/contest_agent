"""
logger.py
=========
Structured, timestamped logging to both the console and a per-run file in
logs/. The format matches the operational style requested in the brief
("09:31  Batch Created Successfully") while remaining greppable.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import LOGS_DIR

_RUN_STARTED = datetime.now()
_DEFAULT_LOGFILE = LOGS_DIR / f"run_{_RUN_STARTED:%Y%m%d_%H%M%S}.log"


class _ConsoleFormatter(logging.Formatter):
    """Compact HH:MM  LEVEL  message format for the console."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        return f"{ts}  {record.levelname:<7} {record.getMessage()}"


def get_logger(
    name: str = "contest_agent", logfile: Optional[Path] = None
) -> logging.Logger:
    """Return a configured logger. Idempotent: handlers are only added once."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(_ConsoleFormatter())
    logger.addHandler(console)

    file_handler = logging.FileHandler(logfile or _DEFAULT_LOGFILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    logger.debug("Logger initialised; run log at %s", logfile or _DEFAULT_LOGFILE)
    return logger
