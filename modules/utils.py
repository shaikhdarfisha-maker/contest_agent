"""
utils.py
========
Cross-cutting helpers: typed exceptions, a retry/backoff decorator, datetime
parsing/snapping, and the re-attempt window derivation that turns the single
operator-supplied A1 window into the full 4-attempt schedule.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional, TypeVar

from config import ATTEMPT_DURATIONS, REATTEMPT_RULE, MAX_RETRIES, RETRY_BACKOFF_SECONDS
from modules.logger import get_logger

log = get_logger(__name__)

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Domain exceptions
# --------------------------------------------------------------------------- #
class ContestAgentError(Exception):
    """Base class for all agent errors."""


class LibraryNotFoundError(ContestAgentError):
    """Raised when a module has no library mapping in the given program."""


class AmbiguousLibraryError(ContestAgentError):
    """Raised when a module maps to multiple libraries and none can be chosen."""


class DuplicateContestError(ContestAgentError):
    """Raised when a contest/batch with the same name already exists."""


class BrowserStepError(ContestAgentError):
    """Raised when a browser automation step fails after retries."""


class TrackerUpdateError(ContestAgentError):
    """Raised when the tracker cannot be updated safely."""


class SessionExpiredError(ContestAgentError):
    """Raised when the browser is redirected to a login/SSO page mid-run."""


class SessionLimitError(ContestAgentError):
    """Raised when Scaler's 2-session limit is hit and cannot be auto-cleared."""


# --------------------------------------------------------------------------- #
# Retry decorator
# --------------------------------------------------------------------------- #
def retry(
    exceptions: tuple[type[Exception], ...] = (Exception,),
    tries: int = MAX_RETRIES,
    backoff: float = RETRY_BACKOFF_SECONDS,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry a callable with linear backoff, logging each failed attempt."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Optional[Exception] = None
            for attempt in range(1, tries + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203
                    last_exc = exc
                    log.warning(
                        "%s failed (attempt %d/%d): %s",
                        fn.__name__,
                        attempt,
                        tries,
                        exc,
                    )
                    if attempt < tries:
                        time.sleep(backoff * attempt)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# Datetime helpers
# --------------------------------------------------------------------------- #
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %I:%M %p",
    "%d %b %Y, %a, %I:%M %p",
    "%d %b %Y %I:%M %p",
    "%Y-%m-%d",
)


def parse_datetime(value: str | datetime) -> datetime:
    """Parse a variety of date string formats (or pass through a datetime)."""
    if isinstance(value, datetime):
        return value
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognised datetime format: {value!r}")


def snap_midnight(dt: datetime) -> datetime:
    """Return the same calendar day at 00:00."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class AttemptWindow:
    """One contest window (the main contest or a re-attempt)."""

    label: str
    start: datetime
    end: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }


def derive_attempt_windows(
    a1_start: datetime, a1_end: datetime
) -> list[AttemptWindow]:
    """
    Expand the operator-supplied first window into the full 4-attempt schedule
    using the configured ReattemptRule.

    Rule (see config.REATTEMPT_RULE):
        A1: as supplied
        A2: starts when A1 ends (snapped to 00:00), runs `a2_days`
        A3: starts when A2 ends,                    runs `a3_days`
        A4: starts when A3 ends,                    runs `a4_days`
    """
    rule = REATTEMPT_RULE
    snap = snap_midnight if rule.snap_to_midnight else (lambda d: d)

    a1 = AttemptWindow("Contest", a1_start, a1_end)

    a2_start = snap(a1_end)
    a2_end = a2_start + timedelta(days=rule.a2_days)
    a2 = AttemptWindow("Re-attempt 1", a2_start, a2_end)

    a3_start = a2_end
    a3_end = a3_start + timedelta(days=rule.a3_days)
    a3 = AttemptWindow("Re-attempt 2", a3_start, a3_end)

    a4_start = a3_end
    a4_end = a4_start + timedelta(days=rule.a4_days)
    a4 = AttemptWindow("Re-attempt 3", a4_start, a4_end)

    return [a1, a2, a3, a4]


def derive_attempt_windows_by_count(
    start: datetime, num_attempts: int
) -> list[AttemptWindow]:
    """
    Auto-calculate all attempt windows from start date and attempt count using
    ATTEMPT_DURATIONS from config.

    Rules:
        A1 starts at `start` (operator's chosen time, e.g. 21:00).
        A1 ends at start + duration[0] days (same time of day).
        A2+ start at midnight of the preceding window's end day.
        Each subsequent window uses its configured duration.
    """
    durations = ATTEMPT_DURATIONS.get(num_attempts, ATTEMPT_DURATIONS[4])
    labels = ["Contest", "Re-attempt 1", "Re-attempt 2", "Re-attempt 3"]
    windows: list[AttemptWindow] = []
    current_start = start
    for i, days in enumerate(durations):
        current_end = current_start + timedelta(days=days)
        windows.append(AttemptWindow(labels[i], current_start, current_end))
        # Re-attempts begin at midnight of the end day
        current_start = snap_midnight(current_end)
    return windows
