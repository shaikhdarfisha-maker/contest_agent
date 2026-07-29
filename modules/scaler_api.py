"""
scaler_api.py
=============
Direct HTTP client for Scaler's internal CCT and Hire Test APIs.
Replaces Playwright UI automation for:
  - Step 3 (CCT scheduling):         USE_API_SCHEDULING=true
  - Step 6 (Hire Test window-setting): USE_API_HIRETEST=true

Auth flow (two-layer):
  1. _scaler_session cookie from data/storage_state.json
  2. POST /generate-jwt  → short-lived JWT Bearer token  (auto-refresh on 401)
  3. Authorization: Bearer <jwt> on all CCT and Hire Test API calls

ENDPOINT STATUS:
  /generate-jwt              — CONFIRMED (captured in probe)
  All other paths marked     — INFERRED from URL structure + Rails conventions
  Override any path via env var (see constants below).
  Run scripts/api_probe.py --interactive after capture_login.py to capture exact paths.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

log = logging.getLogger(__name__)

# ── Endpoint configuration ───────────────────────────────────────────────────
# All paths INFERRED unless marked CONFIRMED.
# Override via environment variables after running api_probe.py.
_BASE      = "https://www.scaler.com"
_JWT_URL   = os.getenv("SCALER_JWT_URL",   f"{_BASE}/generate-jwt")   # CONFIRMED
_CCT_API   = os.getenv("SCALER_CCT_API",   f"{_BASE}/scm/api")        # INFERRED
_HIRE_API  = os.getenv("SCALER_HIRE_API",  f"{_BASE}/hire/api/v1")    # INFERRED


# ── Exceptions ───────────────────────────────────────────────────────────────

class ScalerAPIError(Exception):
    """Base — unexpected API response."""


class ScalerAuthError(ScalerAPIError):
    """401 — session or JWT expired."""


class ScalerValidationError(ScalerAPIError):
    """4xx — server rejected the request payload."""


# ── Client ───────────────────────────────────────────────────────────────────

class ScalerClient:
    """
    HTTP client for Scaler's internal CCT and Hire Test APIs.

    Initialise with the path to storage_state.json (Playwright format).
    Cookies are loaded at init time; call save_cookies() after each run
    to persist any updated session cookie values.
    """

    _UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, storage_state: str | Path) -> None:
        self._storage_path = Path(storage_state)
        self._sess = requests.Session()
        self._sess.headers.update({
            "User-Agent": self._UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": _BASE,
        })
        self._jwt: Optional[str] = None
        self._jwt_expires: Optional[datetime] = None
        self._load_cookies()

    # ── Cookie helpers ────────────────────────────────────────────────────────

    def _load_cookies(self) -> None:
        data = json.loads(self._storage_path.read_text())
        for c in data.get("cookies", []):
            self._sess.cookies.set(
                c["name"], c["value"],
                domain=c.get("domain", ""),
                path=c.get("path", "/"),
            )
        log.debug("Loaded %d cookies from %s", len(data.get("cookies", [])), self._storage_path)

    def save_cookies(self) -> None:
        """Persist updated session cookies back to storage_state.json."""
        try:
            data = json.loads(self._storage_path.read_text())
        except Exception:
            data = {"cookies": []}
        by_key = {(c["name"], c.get("domain", "")): c for c in data.get("cookies", [])}
        for c in self._sess.cookies:
            key = (c.name, c.domain or "")
            if key in by_key:
                by_key[key] = {**by_key[key], "value": c.value}
        data["cookies"] = list(by_key.values())
        self._storage_path.write_text(json.dumps(data, indent=2))
        log.debug("Saved cookies to %s", self._storage_path)

    # ── JWT helpers ───────────────────────────────────────────────────────────

    def _ensure_jwt(self, referer: str = f"{_BASE}/scm/classes/schedule-classes") -> None:
        if self._jwt and self._jwt_expires and datetime.now() < self._jwt_expires:
            return
        self._mint_jwt(referer)

    def _mint_jwt(self, referer: str) -> None:
        cookie_count = len(self._sess.cookies)
        log.info(
            "Minting JWT: POST %s  referer=%s  cookies_attached=%d",
            _JWT_URL, referer, cookie_count,
        )
        resp = self._sess.post(
            _JWT_URL,
            headers={
                "Referer": referer,
                "Content-Type": "application/json",
                # Rails AJAX identification — some endpoints gate on this.
                "X-Requested-With": "XMLHttpRequest",
            },
            # Send an explicit empty JSON body; some Rails endpoints reject
            # requests where Content-Type is application/json but body is absent.
            json={},
            timeout=20,
        )
        log.info(
            "JWT response: HTTP %d  url=%s  body_preview=%r",
            resp.status_code, resp.url, resp.text[:300],
        )
        if resp.status_code == 401:
            raise ScalerAuthError(
                f"JWT endpoint HTTP 401 — the request was rejected "
                f"(url={resp.url}, cookies={cookie_count}, "
                f"response_body={resp.text[:200]!r}). "
                f"This is NOT a session expiry — the same session completed "
                f"batch creation and CCT scheduling. "
                f"The endpoint path, method, required headers, or body may be wrong. "
                f"Run capture_login.py then scripts/api_probe.py --interactive "
                f"to capture the exact endpoint details."
            )
        if not resp.ok:
            raise ScalerAPIError(
                f"JWT endpoint HTTP {resp.status_code} "
                f"(url={resp.url}, body={resp.text[:300]!r})"
            )
        try:
            data = resp.json()
        except Exception:
            raise ScalerAPIError(
                f"JWT endpoint returned non-JSON HTTP {resp.status_code} "
                f"(url={resp.url}, body={resp.text[:200]!r})"
            )

        # Try common key names — confirmed key will be known after probe
        token = (
            data.get("jwt")
            or data.get("token")
            or data.get("access_token")
            or data.get("auth_token")
            or ""
        )
        if not token:
            raise ScalerAPIError(
                f"JWT response HTTP 200 but no recognised token key. "
                f"Keys present: {list(data.keys())!r}. "
                f"Run api_probe.py to capture the exact key name and add it here."
            )

        self._jwt = token
        self._jwt_expires = self._parse_jwt_expiry(token)
        self._sess.headers["Authorization"] = f"Bearer {token}"
        log.info(
            "JWT minted OK, expires ~%s, token prefix=%s",
            self._jwt_expires, token[:12] + "…",
        )

    @staticmethod
    def _parse_jwt_expiry(token: str) -> datetime:
        try:
            parts = token.split(".")
            if len(parts) == 3:
                pad = 4 - len(parts[1]) % 4
                payload = json.loads(base64.b64decode(parts[1] + "=" * pad))
                return datetime.fromtimestamp(payload["exp"])
        except Exception:
            pass
        return datetime.now() + timedelta(minutes=50)

    # ── HTTP core ─────────────────────────────────────────────────────────────

    def _req(
        self,
        method: str,
        url: str,
        *,
        referer: Optional[str] = None,
        **kw: Any,
    ) -> requests.Response:
        ref = referer or f"{_BASE}/scm/classes/schedule-classes"
        self._ensure_jwt(ref)
        kw.setdefault("headers", {})
        kw["headers"]["Referer"] = ref
        log.info("%s %s", method.upper(), url)
        resp = self._sess.request(method, url, timeout=30, **kw)
        log.info(
            "%s %s → HTTP %d  body_preview=%r",
            method.upper(), url, resp.status_code, resp.text[:200],
        )
        if resp.status_code == 401:
            # Stale JWT — re-mint and retry once
            log.info("HTTP 401 — re-minting JWT and retrying once")
            self._jwt = None
            self._ensure_jwt(ref)
            kw["headers"]["Referer"] = ref
            resp = self._sess.request(method, url, timeout=30, **kw)
            log.info(
                "%s %s (retry) → HTTP %d  body_preview=%r",
                method.upper(), url, resp.status_code, resp.text[:200],
            )
        return resp

    @staticmethod
    def _raise(resp: requests.Response, op: str) -> None:
        if resp.ok:
            return
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:400]
        raise ScalerValidationError(
            f"{op} — HTTP {resp.status_code} from {resp.url}. "
            f"Detail: {detail}. "
            f"If 404: endpoint path is wrong — run api_probe.py to capture the real path "
            f"then set SCALER_CCT_API or SCALER_HIRE_API in .env."
        )

    # ── CCT API ───────────────────────────────────────────────────────────────

    def get_batch_slots(self, batch_id: str | int) -> list[dict]:
        """
        GET available schedule slot patterns for a batch.

        Expected response (INFERRED):
          [{"id": 123, "label": "Mon 09:00 PM | Wed 09:00 PM | Fri 09:00 PM (GMT+05:30)"},
           {"id": 124, "label": "Tue 09:00 PM | Thu 09:00 PM | Sat 09:00 PM (GMT+05:30)"},
           ...]

        INFERRED endpoint: GET {_CCT_API}/super_batches/{id}/batch_slots
        """
        url = f"{_CCT_API}/super_batches/{batch_id}/batch_slots"
        resp = self._req("GET", url)
        self._raise(resp, "get_batch_slots")
        data = resp.json()
        if isinstance(data, list):
            return data
        # Handle wrapped responses
        for key in ("batch_slots", "slots", "data", "results"):
            if key in data:
                return data[key]
        return data

    def find_slot_id(self, slots: list[dict], label: str) -> Optional[str]:
        """
        Find a slot ID by matching config label text against the API response.

        Returns the slot's ID field as a string, or None if not found.
        The match tries: exact label → leading-token match (e.g. "mon 09").
        """
        label_lower = label.lower().strip()
        # Leading search key: e.g. "Mon 09:00 PM |..." → "mon 09"
        leading = label_lower[:6]

        for slot in slots:
            slot_label = (
                slot.get("label")
                or slot.get("name")
                or slot.get("slot_label")
                or slot.get("title")
                or ""
            ).lower()
            sid = str(slot.get("id") or slot.get("slot_id") or slot.get("batch_slot_id") or "")
            if not sid:
                continue
            if slot_label == label_lower:
                return sid
            if leading and slot_label.startswith(leading):
                return sid
        return None

    def create_scheduled_class(
        self,
        *,
        batch_id: str | int,
        library_id: str | int,
        slot_id: str | int,
        start_date: str,  # "YYYY-MM-DD"
    ) -> dict:
        """
        POST to create a scheduled class (equivalent to CCT 'Confirm & Schedule').

        Returns the API response — expected to contain the SBAT ID and optionally
        the hire_test_ids for each attempt.

        INFERRED endpoint: POST {_CCT_API}/sbats
        Payload shape INFERRED from what the CCT UI collects.
        Override base via SCALER_CCT_API env var.
        """
        url = f"{_CCT_API}/sbats"
        payload = {
            "sbat": {
                "super_batch_id": int(batch_id),
                "library_id":     int(library_id),
                "batch_slot_id":  int(slot_id),
                "start_date":     start_date,
            }
        }
        log.info("POST %s  payload=%s", url, payload)
        resp = self._req("POST", url, json=payload)
        self._raise(resp, "create_scheduled_class")
        return resp.json()

    def get_sbat(self, sbat_id: str | int) -> dict:
        """
        GET a scheduled batch (SBAT) by ID.
        Response expected to include hire_test_ids or similar for each attempt.

        INFERRED endpoint: GET {_CCT_API}/sbats/{id}
        """
        url = f"{_CCT_API}/sbats/{sbat_id}"
        resp = self._req("GET", url)
        self._raise(resp, "get_sbat")
        return resp.json()

    def extract_test_ids_from_sbat(self, sbat_data: dict) -> list[str]:
        """
        Parse hire-test IDs from a SBAT API response.

        Tries multiple likely response shapes since the exact shape is INFERRED.
        Returns IDs in attempt order: [Contest, Re-attempt-1, Re-attempt-2, Re-attempt-3].
        """
        ids: list[str] = []
        data = sbat_data.get("sbat", sbat_data)  # unwrap if nested

        # Shape 1: {"test_groups": [{"hire_test_id": 1288152}, ...]}
        for tg in data.get("test_groups", []):
            tid = str(tg.get("hire_test_id") or tg.get("test_id") or "")
            if tid and tid not in ids:
                ids.append(tid)

        # Shape 2: {"hire_test_ids": [1288152, 1288153, ...]}
        if not ids:
            for tid in data.get("hire_test_ids", []):
                s = str(tid)
                if s and s not in ids:
                    ids.append(s)

        # Shape 3: {"contest_ids": [...]}
        if not ids:
            for tid in data.get("contest_ids", []):
                s = str(tid)
                if s and s not in ids:
                    ids.append(s)

        return ids

    # ── Hire Test API ─────────────────────────────────────────────────────────

    def get_hire_test(self, test_id: str | int) -> dict:
        """
        GET a hire test's current settings, including start_time / end_time.

        INFERRED endpoint: GET {_HIRE_API}/tests/{id}
        Override base via SCALER_HIRE_API env var.
        """
        url = f"{_HIRE_API}/tests/{test_id}"
        ref = f"{_BASE}/hire/test/{test_id}/"
        resp = self._req("GET", url, referer=ref)
        self._raise(resp, "get_hire_test")
        return resp.json()

    def update_hire_test_window(
        self,
        test_id: str | int,
        *,
        start: datetime,
        end: datetime,
    ) -> dict:
        """
        PATCH the contest window (start_time / end_time) for a hire test attempt.

        Sends UTC ISO strings. Immediately reads back to verify the write.

        INFERRED endpoint: PATCH {_HIRE_API}/tests/{id}
        Payload: {"test": {"start_time": "...", "end_time": "..."}}
        Override base via SCALER_HIRE_API env var.
        """
        def _to_utc(dt: datetime) -> str:
            if dt.tzinfo:
                return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        url = f"{_HIRE_API}/tests/{test_id}"
        ref = f"{_BASE}/hire/test/{test_id}/"
        payload = {
            "test": {
                "start_time": _to_utc(start),
                "end_time":   _to_utc(end),
            }
        }
        log.info(
            "PATCH %s  start=%s  end=%s",
            url, payload["test"]["start_time"], payload["test"]["end_time"],
        )
        resp = self._req("PATCH", url, referer=ref, json=payload)
        self._raise(resp, "update_hire_test_window")
        result = resp.json()

        # Read back immediately to verify
        verify = self._req("GET", url, referer=ref)
        if verify.ok:
            result["_readback"] = verify.json()
            log.debug("Hire Test %s read-back: %s", test_id, str(verify.json())[:200])
        else:
            log.warning("Could not read back hire test %s after update (HTTP %s)", test_id, verify.status_code)

        return result

    def verify_hire_test_window(self, readback: dict, start: datetime, end: datetime) -> bool:
        """
        Verify a hire test window from a read-back GET response.

        Compares the server's returned timestamps to what was requested.
        Scaler stores UTC internally; the UI shows IST (GMT+05:30). We convert
        UTC readback to IST before comparing so the log is timezone-explicit.

        Returns True only when both start and end match at hour level.
        """
        from datetime import timedelta as _td

        data = readback.get("test", readback)
        raw_start = data.get("start_time") or data.get("start_at") or ""
        raw_end   = data.get("end_time")   or data.get("end_at")   or ""

        def _parse(s: str) -> Optional[datetime]:
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    pass
            return None

        ps = _parse(raw_start)
        pe = _parse(raw_end)
        if not ps or not pe:
            log.warning(
                "Could not parse API readback dates: start=%r end=%r", raw_start, raw_end
            )
            return False

        # Convert UTC readback to IST (GMT+05:30) for comparison and logging.
        IST = _td(hours=5, minutes=30)
        ps_ist = ps + IST if raw_start.endswith("Z") else ps
        pe_ist = pe + IST if raw_end.endswith("Z") else pe

        # Compare at date+hour level (IST hours may differ by ±1 due to rounding)
        def _near(a: datetime, b: datetime) -> bool:
            return a.date() == b.date() and abs(a.hour - b.hour) <= 1

        start_ok = _near(ps_ist, start)
        end_ok   = _near(pe_ist, end)

        log.info(
            "Hire Test API verify (IST/GMT+05:30): "
            "requested start=%s → server %s UTC = %s IST: %s; "
            "requested end=%s → server %s UTC = %s IST: %s",
            start.strftime("%d %b %Y %H:%M"),
            raw_start, ps_ist.strftime("%d %b %Y %H:%M"), "✓" if start_ok else "✗",
            end.strftime("%d %b %Y %H:%M"),
            raw_end,   pe_ist.strftime("%d %b %Y %H:%M"), "✓" if end_ok else "✗",
        )

        if not (start_ok and end_ok):
            log.error(
                "Hire Test API window MISMATCH: "
                "requested %s→%s IST, server has %s→%s IST",
                start.strftime("%d %b %Y %H:%M"), end.strftime("%d %b %Y %H:%M"),
                ps_ist.strftime("%d %b %Y %H:%M"), pe_ist.strftime("%d %b %Y %H:%M"),
            )
        return start_ok and end_ok
