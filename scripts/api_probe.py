"""
scripts/api_probe.py
====================
THROWAWAY investigation script for API endpoint capture.
DO NOT commit the output log — it is gitignored (data/api_probe_log.json).

Two modes:

  --interactive (recommended)
      Opens a HEADED browser with your stored session.
      Navigate manually to CCT and Hire Test, complete a THROWAWAY test flow,
      then press Enter in this terminal to save the log and exit.
      Every request/response is recorded.

  (no flag) automatic read-only probe
      Navigates read-only pages automatically and intercepts/aborts write POSTs
      before they do anything. Session must be fresh (run capture_login.py first).

Run:
  cd /path/to/contest_agent
  python3 capture_login.py          # refresh session FIRST
  python3 scripts/api_probe.py --interactive

After running:
  - Check data/api_probe_log.json for captured endpoints
  - Look for POST/PATCH/PUT entries in "intercepted_write_requests" and "all_traffic"
  - Update SCALER_CCT_API and SCALER_HIRE_API in .env with confirmed paths
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STORAGE_STATE = Path("data/storage_state.json")
LOG_PATH      = Path("data/api_probe_log.json")

_SKIP_FRAGS = (
    ".js", ".css", ".png", ".jpg", ".svg", ".ico", ".woff",
    "google-analytics", "hotjar", "mixpanel", "segment", "sentry",
    "cloudfront", "cdn.", "fonts.googleapis", "intercom",
)
_SENSITIVE = ("cookie", "authorization", "x-csrf-token", "set-cookie")
_SCALER    = "scaler.com"


def _interesting(url: str) -> bool:
    lo = url.lower()
    return _SCALER in lo and not any(f in lo for f in _SKIP_FRAGS)


def _redact(headers: dict) -> dict:
    return {
        k: ("[REDACTED]" if k.lower() in _SENSITIVE else v)
        for k, v in headers.items()
    }


def _trunc(text: str, n: int = 1200) -> str:
    if not text:
        return ""
    return text[:n] + (" …[truncated]" if len(text) > n else "")


# ── Shared listener factory ───────────────────────────────────────────────────

def attach_listeners(page, log: list, writes: list) -> None:
    """Attach request/response listeners to record all Scaler traffic."""

    def on_request(req):
        if not _interesting(req.url):
            return
        try:
            post = req.post_data or None
        except Exception:
            post = None
        entry = {
            "ev": "request",
            "ts": datetime.now().isoformat(),
            "method": req.method,
            "url": req.url,
            "headers": _redact(dict(req.headers)),
            "post_data": _trunc(post or ""),
        }
        log.append(entry)
        if req.method in ("POST", "PUT", "PATCH", "DELETE"):
            writes.append({**entry, "note": "write — check url + post_data"})
            print(f"  ✏️  {req.method} {req.url}")

    def on_response(resp):
        if not _interesting(resp.url):
            return
        try:
            body = _trunc(resp.text())
        except Exception:
            body = "[binary/unreadable]"
        log.append({
            "ev": "response",
            "ts": datetime.now().isoformat(),
            "status": resp.status,
            "url": resp.url,
            "body_preview": body,
        })

    page.on("request", on_request)
    page.on("response", on_response)


def _section(log: list, label: str) -> None:
    log.append({"ev": "section", "label": label, "ts": datetime.now().isoformat()})


# ── Interactive mode ──────────────────────────────────────────────────────────

def run_interactive() -> None:
    """
    Opens a headed browser with the stored session.
    User performs the contest creation flow on a THROWAWAY module.
    All traffic is recorded. Press Enter when done to save.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed — run: pip3 install playwright")
        sys.exit(1)

    if not STORAGE_STATE.exists():
        print(f"ERROR: {STORAGE_STATE} not found — run capture_login.py first")
        sys.exit(1)

    traffic: list[dict] = []
    writes:  list[dict] = []

    print("\n" + "="*60)
    print("API PROBE — INTERACTIVE MODE")
    print("="*60)
    print("""
Steps to complete in the browser that will open:

  1. Go to: https://www.scaler.com/scm/classes/schedule-classes
     Select ANY batch, ANY library, tick skill-eval checkbox,
     select a slot, pick a date. Click 'Confirm Schedule'.
     READ the time in the confirm modal (don't click yet).
     Then click 'Confirm & Schedule'. [this is the KEY POST to capture]

  2. On the view-schedule page, click the pencil (edit) icon
     next to your newly scheduled class. Note the edit-sbat-group ID in the URL.

  3. On the edit-sbat-group page, wait for 'Group Contest Summary' to load.
     Note the hire-test IDs shown in the card headers.

  4. Go to: https://www.scaler.com/hire/test/<one_of_those_ids>/#/basic-settings
     Open Test Settings, change the start/end dates, click 'Apply Changes'
     then 'Confirm & Apply Changes'. [this is the KEY PATCH/PUT to capture]

Press Ctrl+C at any time to abort without saving.
""")
    input(">>> Press Enter to open the browser...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=0)
        ctx = browser.new_context(storage_state=str(STORAGE_STATE))
        page = ctx.new_page()
        attach_listeners(page, traffic, writes)

        _section(traffic, "PROBE START — interactive mode")
        print("\n📡 Recording all Scaler traffic...")
        print("    Complete the steps in the browser, then come back here.\n")

        # Open CCT as the starting point
        page.goto(
            "https://www.scaler.com/scm/classes/schedule-classes",
            wait_until="domcontentloaded", timeout=45_000,
        )
        print(f"Opened: {page.url}")

        try:
            input("\n>>> Press Enter AFTER completing all steps to save the log...")
        except KeyboardInterrupt:
            print("\nAborted.")
            browser.close()
            return

        _section(traffic, "PROBE END — user signalled done")
        browser.close()

    _write_log(traffic, writes)


# ── Automatic read-only probe ─────────────────────────────────────────────────

def run_auto(sbat_id: str | None, hire_test_id: str | None) -> None:
    """
    Automatic read-only probe. Navigates pages; intercepts + aborts write POSTs.
    Session must be fresh (run capture_login.py first) or JWT calls will 401.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed")
        sys.exit(1)

    if not STORAGE_STATE.exists():
        print(f"ERROR: {STORAGE_STATE} not found — run capture_login.py first")
        sys.exit(1)

    traffic: list[dict] = []
    writes:  list[dict] = []

    def intercept_writes(route, request):
        if request.method in ("POST", "PUT", "PATCH") and _SCALER in request.url:
            try:
                post = request.post_data or ""
            except Exception:
                post = ""
            entry = {
                "intercepted": "write_aborted",
                "method": request.method,
                "url": request.url,
                "headers": _redact(dict(request.headers)),
                "post_data": _trunc(post),
            }
            writes.append(entry)
            print(f"  INTERCEPTED & ABORTED: {request.method} {request.url}")
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, slow_mo=150)
        ctx = browser.new_context(storage_state=str(STORAGE_STATE))
        page = ctx.new_page()
        attach_listeners(page, traffic, writes)

        # ── CCT schedule-classes ──────────────────────────────────────────────
        _section(traffic, "CCT schedule-classes (GET)")
        print("[1] CCT schedule-classes")
        page.route("**", intercept_writes)
        try:
            page.goto("https://www.scaler.com/scm/classes/schedule-classes",
                      wait_until="networkidle", timeout=45_000)
            print(f"   Landed: {page.url}")
            # Trigger batch search API call
            try:
                page.locator(".css-32j6ly").first.click()
                page.keyboard.type("Backend LLD", delay=30)
                page.wait_for_timeout(1500)
                opt = page.locator("[id*='-option-']").first
                if opt.is_visible():
                    opt.click()
                    page.wait_for_timeout(1200)
            except Exception as exc:
                print(f"   (batch select: {exc})")
        finally:
            page.unroute("**", intercept_writes)

        # ── edit-sbat-group (Group Contest Summary) ───────────────────────────
        if sbat_id:
            _section(traffic, f"edit-sbat-group/{sbat_id}")
            print(f"[2] edit-sbat-group/{sbat_id}")
            page.goto(
                f"https://www.scaler.com/scm/classes/edit-sbat-group/{sbat_id}",
                wait_until="networkidle", timeout=45_000,
            )
            print(f"   Landed: {page.url}")
            try:
                page.wait_for_selector("text=Group Contest Summary", timeout=20_000)
                page.wait_for_timeout(1500)
                print("   'Group Contest Summary' section found")
            except Exception as exc:
                print(f"   (Group Contest Summary: {exc})")

        # ── Hire Test settings ────────────────────────────────────────────────
        if hire_test_id:
            _section(traffic, f"Hire Test {hire_test_id} settings")
            print(f"[3] Hire Test {hire_test_id}")
            page.route("**", intercept_writes)
            try:
                page.goto(
                    f"https://www.scaler.com/hire/test/{hire_test_id}/#/basic-settings",
                    wait_until="networkidle", timeout=45_000,
                )
                print(f"   Landed: {page.url}")
                try:
                    page.get_by_role("link", name="Test Settings").click()
                    page.wait_for_load_state("networkidle", timeout=15_000)
                    print("   'Test Settings' tab opened")
                except Exception as exc:
                    print(f"   (Test Settings: {exc})")
            finally:
                page.unroute("**", intercept_writes)

        browser.close()

    _write_log(traffic, writes)


# ── Output ────────────────────────────────────────────────────────────────────

def _write_log(traffic: list, writes: list) -> None:
    output = {
        "probe_run_at": datetime.now().isoformat(),
        "note": "Sensitive headers/cookies redacted. This file is gitignored.",
        "summary": {
            "total_events": len(traffic),
            "write_requests_captured": len(writes),
            "jwt_calls": sum(
                1 for e in traffic
                if e.get("ev") == "request" and "/generate-jwt" in e.get("url", "")
            ),
            "api_calls": [
                {"method": e["method"], "url": e["url"], "post_data": e.get("post_data")}
                for e in traffic
                if e.get("ev") == "request"
                and e.get("method") in ("POST", "PUT", "PATCH")
                and "/api/" in e.get("url", "")
            ],
        },
        "write_requests": writes,
        "all_traffic": traffic,
    }
    LOG_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n✓ Log saved → {LOG_PATH}")
    print(f"  {len(traffic)} events  |  {len(writes)} write requests captured")
    if output["summary"]["api_calls"]:
        print("\nAPI write calls captured:")
        for call in output["summary"]["api_calls"]:
            print(f"  {call['method']} {call['url']}")
            if call.get("post_data"):
                print(f"    payload: {call['post_data'][:200]}")
    else:
        print("\nNo /api/ write calls captured. Try --interactive with a fresh session.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scaler API endpoint probe")
    parser.add_argument("--interactive", action="store_true",
                        help="Open a headed browser for manual capture (recommended)")
    parser.add_argument("--sbat-id", default=None,
                        help="Existing edit-sbat-group ID to probe automatically")
    parser.add_argument("--hire-test-id", default=None,
                        help="Existing Hire Test ID to probe automatically")
    args = parser.parse_args()

    if args.interactive:
        run_interactive()
    else:
        run_auto(sbat_id=args.sbat_id, hire_test_id=args.hire_test_id)
