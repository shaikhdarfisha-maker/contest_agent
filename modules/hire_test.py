"""
hire_test.py
============
System 3 - Hire Test test settings (opened as a popup from CCT "Add Questions").

The date control is a bootstrap-daterangepicker with TWO month panels shown
side by side (.drp-calendar.left = earlier month, .drp-calendar.right = later
month) plus start/end time dropdowns and a Confirm button (.applyBtn).

Correct flow (confirmed from live screenshots):
  1. Remove the onboarding "tour-backdrop" overlay (it intercepts clicks).
  2. Open Test Settings.
  3. Click the date field (the "<Month> DD, YYYY ..." span) to open the picker.
  4. Click the START day in whichever panel shows the start month.
  5. Click the END day in whichever panel shows the end month.
  6. Set start and end time dropdowns (hour / minute / AM-PM).
  7. Click Confirm, then Apply Changes -> Confirm & Apply Changes.
  8. Verify the field text now reflects the requested start AND end dates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from playwright.sync_api import Page

from modules.logger import get_logger
from modules.utils import AttemptWindow, BrowserStepError, retry

log = get_logger(__name__)


@dataclass
class HireTestResult:
    test_id: str
    applied: bool
    start: datetime
    end: datetime
    verified: bool


class HireTest:
    """Page object for updating a Hire Test's start/end window (popup page)."""

    # Confirmed via DevTools: POST https://www.scaler.com/hire/test/{id}/basic-settings
    # Payload was meant to be: GET current settings, patch start_time/end_time,
    # POST full object back — but update_window_via_fetch actually sends only
    # {start_time, end_time}, not the full merged object. That's had a 100%
    # HTTP 500 failure rate (every hire test, every module, all day) AND a
    # confirmed harmful side effect: the failed POST still appears to trigger
    # a server-side password regeneration, which then contaminates the
    # UI-fallback confirm modal with an extra unrelated "Password" change a
    # real human never sees, causing that confirm to silently fail too.
    # Disabled (default None) until update_window_via_fetch is rewritten to
    # actually do the GET-merge-POST the comment above describes.
    _api_endpoint: Optional[str] = None
    _api_method:   str = "POST"

    def __init__(self, page: Page) -> None:
        self.page = page

    @retry(exceptions=(BrowserStepError,))
    def update_window(self, window: AttemptWindow) -> HireTestResult:
        """Set and apply the start/end date+time for the main Contest window."""
        import time as _time
        _t0 = _time.perf_counter()

        def _lap(label: str) -> None:
            log.debug("Hire Test timing [%s]: %.1fs", label, _time.perf_counter() - _t0)

        import json as _json

        test_id = self._test_id_from_url()
        log.info(
            "Updating Hire Test %s: %s -> %s",
            test_id,
            window.start,
            window.end,
        )

        # Pre-compute HTTP-date strings for date injection inside _intercept_request.
        # The "Apply Changes" POST sends start_time/end_time from the AngularJS scope
        # (which may hold stale/default values); we overwrite them mid-flight.
        _IST = timedelta(hours=5, minutes=30)
        _want_start_http = (window.start - _IST).strftime("%a, %d %b %Y %H:%M:%S GMT")
        _want_end_http   = (window.end   - _IST).strftime("%a, %d %b %Y %H:%M:%S GMT")

        self._dismiss_tour_overlay()
        _lap("dismiss-overlay")

        # Open Test Settings tab.  The tour overlay often blocks the click on
        # the FIRST hire-test attempt (before localStorage marks it as seen).
        # Retry up to 5 times, dismissing overlays between attempts.
        try:
            settings_link = self.page.get_by_role("link", name="Test Settings")
            clicked = False
            for _attempt in range(5):
                self._dismiss_tour_overlay()
                try:
                    settings_link.click(timeout=4_000)
                    clicked = True
                    break
                except Exception:  # noqa: BLE001
                    self.page.wait_for_timeout(800)
            if not clicked:
                settings_link.click(timeout=10_000)  # final attempt — let it raise
            # Wait for the settings content to load — but don't fail hard if
            # the text selector times out (can happen when the element is in
            # the DOM but Playwright can't confirm visibility).
            try:
                self.page.wait_for_selector(
                    "text=/[A-Z][a-z]+ \\d{1,2}, \\d{4}/", timeout=15000
                )
            except Exception:  # noqa: BLE001
                pass  # proceed — picker click will raise if page not ready
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not open Test Settings: {exc}")
        _lap("settings-tab-open")

        # --- Path A: trigger apply.daterangepicker event directly (no picker UI) ---
        # Triggering the event with a moment-backed fake picker updates the
        # AngularJS directive's ngModel without needing to open the picker,
        # bypassing all visibility / selector issues.
        fmt = "%m/%d/%Y %H:%M"
        _start_s = window.start.strftime(fmt)
        _end_s   = window.end.strftime(fmt)
        _event_ok = False
        try:
            _ev_result = self.page.evaluate(f"""() => {{
                try {{
                    if (typeof moment === 'undefined') return {{ok: false, reason: 'no moment'}};
                    const s = moment('{_start_s}', 'MM/DD/YYYY HH:mm');
                    const e = moment('{_end_s}',   'MM/DD/YYYY HH:mm');
                    if (!s.isValid() || !e.isValid()) return {{ok: false, reason: 'invalid dates'}};
                    const fakePicker = {{startDate: s, endDate: e, chosenLabel: 'Custom Range'}};
                    // NOTE: do not add a generic fallback like 'input[type="text"]' here.
                    // On some hire-test page layouts (observed on Contest/A1 pages,
                    // not Re-attempts) it grabs the wrong text input, silently
                    // reports ok:true, and the real date-range widget never updates
                    // its end date — verified failing 3/3 retries identically before
                    // this was found (see CLAUDE.md bug #15). Only trust selectors
                    // that are actually the date-range directive; if none match,
                    // ok:false correctly falls through to the real picker-click path.
                    const sels = ['[daterangepicker]', '[drp-field]', '[date-range-picker]',
                                  '[ng-daterangepicker]'];
                    for (const sel of sels) {{
                        const $el = jQuery(sel).filter(':visible').first();
                        if ($el.length) {{
                            $el.trigger('apply.daterangepicker', [fakePicker]);
                            return {{ok: true, sel: sel}};
                        }}
                    }}
                    return {{ok: false, reason: 'no visible directive element'}};
                }} catch(ex) {{
                    return {{ok: false, reason: ex.message}};
                }}
            }}""")
            log.info("apply.daterangepicker event result: %s", _ev_result)
            _event_ok = bool(_ev_result and _ev_result.get("ok"))

            # Diagnostic: dump AngularJS scope date-related keys after event
            if _event_ok:
                try:
                    _scope_info = self.page.evaluate("""() => {
                        try {
                            const el = document.querySelector('[ng-controller]') || document.body;
                            let scope = angular.element(el).scope();
                            const found = {};
                            for (let i = 0; i < 6 && scope; i++) {
                                Object.keys(scope).filter(k =>
                                    !k.startsWith('$') && (
                                        k.toLowerCase().includes('start') ||
                                        k.toLowerCase().includes('end') ||
                                        k.toLowerCase().includes('date') ||
                                        k.toLowerCase().includes('time') ||
                                        k.toLowerCase().includes('window')
                                    )
                                ).forEach(k => {
                                    const v = scope[k];
                                    const s = (v && v._isAMomentObject) ? v.format()
                                            : (v instanceof Date) ? v.toISOString()
                                            : (typeof v === 'string' || typeof v === 'number') ? String(v)
                                            : (v && typeof v === 'object') ? JSON.stringify(v).substring(0,100)
                                            : typeof v;
                                    found[k + '@' + (scope.$id||'?')] = s;
                                });
                                scope = scope.$parent;
                            }
                            return found;
                        } catch(e) { return {error: e.message}; }
                    }""")
                    log.info("AngularJS scope date-keys after event: %s", _scope_info)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _ev_exc:  # noqa: BLE001
            log.warning("apply.daterangepicker event eval failed: %s", _ev_exc)
        _lap("event-trigger-attempted")

        if not _event_ok:
            # --- Path B: open the picker UI and set dates ---
            # Try [daterangepicker] directive selector first (avoids text-matching
            # ambiguity with invisible ng-if display spans that share the same date).
            # Falls back to regex text search with single-digit hour support (\d{1,2}).
            try:
                _picker_opened = False

                # B1: directive-attribute selector
                try:
                    self.page.wait_for_selector(
                        "[daterangepicker], [drp-field]", timeout=8000
                    )
                    drp_loc = self.page.locator("[daterangepicker], [drp-field]").first
                    drp_loc.click(timeout=5000)
                    _picker_opened = True
                    log.info("Opened picker via directive attribute selector")
                except Exception:  # noqa: BLE001
                    pass

                # B2: JS jQuery trigger on directive element. Must check whether
                # an element was actually found and clicked before claiming
                # success — a prior version set _picker_opened=True unconditionally
                # whenever the JS eval didn't throw, even when the loop matched
                # nothing and clicked nothing, which incorrectly skipped B3 (the
                # actually-reliable fallback) on pages where none of these
                # selectors match anything (observed on Contest/A1 pages).
                if not _picker_opened:
                    try:
                        _b2_found = self.page.evaluate("""() => {
                            const sels = ['[daterangepicker]','[drp-field]','[date-range-picker]'];
                            for (const s of sels) {
                                const $el = jQuery(s).first();
                                if ($el.length) { $el.trigger('click'); return true; }
                            }
                            return false;
                        }""")
                        if _b2_found:
                            _picker_opened = True
                            log.info("Opened picker via JS jQuery trigger")
                    except Exception:  # noqa: BLE001
                        pass

                # B3: visible text-match (single-digit hour fix: \d{1,2})
                if not _picker_opened:
                    date_matches = self.page.get_by_text(
                        re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4} \d{1,2}:\d{2} (AM|PM)")
                    )
                    n = date_matches.count()
                    log.info("Date text candidates: %d", n)
                    for _di in range(min(n, 8)):
                        _el = date_matches.nth(_di)
                        try:
                            if _el.is_visible():
                                _el.click(timeout=5000)
                                _picker_opened = True
                                break
                        except Exception:  # noqa: BLE001
                            continue
                    if not _picker_opened:
                        date_matches.first.click()  # last resort

                self.page.wait_for_selector(".daterangepicker", timeout=10000)
            except Exception as exc:  # noqa: BLE001
                raise BrowserStepError(f"Could not open date-range picker: {exc}")
            _lap("picker-open")

            # If the picker has a preset-ranges sidebar ("Today", "Next 7
            # Days", "Custom Range", ...), it must be switched to "Custom
            # Range" before setting dates — confirmed live: without this a
            # manual human click on the calendar still silently saved a
            # stale/default value instead of what was picked.
            try:
                custom_range = self.page.locator(".ranges li").filter(has_text="Custom Range")
                _cr_count = custom_range.count()
                log.info("Custom Range sidebar option count: %d", _cr_count)
                if _cr_count > 0:
                    custom_range.first.click(timeout=3000)
                    self.page.wait_for_timeout(200)
                    log.info("Clicked 'Custom Range' in the ranges sidebar")
            except Exception as _cr_exc:  # noqa: BLE001
                log.warning("Could not click 'Custom Range': %s", _cr_exc)

            # Set dates via REAL clicks on the calendar (_pick_day), not
            # _set_picker_dates_js's direct picker.setStartDate()/setEndDate()
            # JS calls. The JS approach updates the widget's own internal
            # state correctly (verified: picker.startDate/endDate end up
            # right, "ok: true" is returned) but never reaches AngularJS's
            # $scope — it's not listening for a state mutation, only for the
            # real click/apply events a genuine user interaction fires. That
            # made "Apply Changes" report success while silently saving a
            # stale end date. Confirmed live: switching to real clicks (this
            # path) after clicking "Custom Range" above is what actually
            # persists correctly server-side.
            try:
                self._pick_day(window.start)
                self.page.wait_for_timeout(200)
                self._pick_day(window.end)
            except Exception as exc:  # noqa: BLE001
                raise BrowserStepError(f"Could not pick start/end days: {exc}")
            try:
                self._set_times(window.start, window.end)
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not set time dropdowns precisely: %s", exc)
            _lap("days-picked")

            # Confirm inside the picker
            try:
                confirm = self.page.locator(".applyBtn")
                confirm.wait_for(state="visible", timeout=10000)
                try:
                    self.page.wait_for_function(
                        "() => { const b = document.querySelector('.applyBtn'); "
                        "return b && !b.disabled; }",
                        timeout=5000,
                    )
                except Exception:  # noqa: BLE001
                    pass
                confirm.click()
                _lap("applyBtn-clicked")
            except Exception as exc:  # noqa: BLE001
                raise BrowserStepError(f"Could not click picker apply button: {exc}")

        # -- Both Path A (event trigger) and Path B (picker UI) arrive here --
        try:
            # Wait for Apply Changes to become visible rather than sleeping
            apply_btn = self.page.get_by_text("Apply Changes", exact=True)
            apply_btn.first.wait_for(state="visible", timeout=8000)
            apply_btn.first.scroll_into_view_if_needed()
            _lap("apply-changes-visible")

            # Dual-layer save interception:
            #  1. page.route() catches any HTTP PATCH/PUT/POST (fast path)
            #  2. WebSocket.prototype.send patch catches WS frames (likely path)
            # Both run concurrently; whichever fires first wins.
            _captured: dict = {}

            def _intercept_request(route, request):  # noqa: E306
                try:
                    if request.method in ("PATCH", "PUT", "POST"):
                        log.info(
                            "Hire Test HTTP intercepted: %s %s",
                            request.method, request.url,
                        )
                        if not _captured:
                            _captured["url"]    = request.url
                            _captured["method"] = request.method
                except Exception as exc:  # noqa: BLE001
                    log.warning("HTTP intercept error: %s", exc)

                # Date injection: overwrite start_time/end_time for basic-settings POSTs.
                # Done here (not a separate route) to avoid Playwright chain-ordering issues.
                if request.method == "POST" and "basic-settings" in request.url:
                    try:
                        body = _json.loads(request.post_data or "{}")
                        old_start = body.get("start_time", "?")
                        old_end   = body.get("end_time",   "?")
                        body["start_time"] = _want_start_http
                        body["end_time"]   = _want_end_http
                        log.info(
                            "Date injection for %s: start %s→%s, end %s→%s",
                            test_id, old_start, _want_start_http, old_end, _want_end_http,
                        )
                        route.continue_(post_data=_json.dumps(body))
                        return
                    except Exception as _inj_exc:  # noqa: BLE001
                        log.warning("Date injection error (falling through): %s", _inj_exc)

                try:
                    route.continue_()
                except Exception:  # noqa: BLE001
                    pass

            # Intercept WS, fetch(), and XHR BEFORE clicking "Apply Changes".
            # fetch() patching is page-level (before Service Worker) so it
            # captures calls that page.route() (network-level) would miss.
            try:
                self.page.evaluate("""() => {
                    window.__wsCapture = [];
                    if (!window.__wsPatched) {
                        window.__wsPatched = true;

                        // WebSocket
                        const _origWS = WebSocket.prototype.send;
                        WebSocket.prototype.send = function(data) {
                            try {
                                window.__wsCapture.push({
                                    type: 'ws', url: this.url,
                                    data: typeof data === 'string'
                                        ? data.substring(0, 2000) : '(binary)'
                                });
                            } catch(_e) {}
                            return _origWS.call(this, data);
                        };

                        // fetch() — captured before SW interception
                        const _origFetch = window.fetch;
                        window.fetch = function(input, init) {
                            try {
                                const url = typeof input === 'string'
                                    ? input : (input && input.url) || '?';
                                const method = (init && init.method) || 'GET';
                                const body = (init && init.body)
                                    ? String(init.body).substring(0, 2000) : '';
                                window.__wsCapture.push(
                                    {type: 'fetch', method: method, url: url, data: body}
                                );
                            } catch(_e) {}
                            return _origFetch.apply(this, arguments);
                        };

                        // XMLHttpRequest
                        const _origOpen = XMLHttpRequest.prototype.open;
                        const _origSend = XMLHttpRequest.prototype.send;
                        XMLHttpRequest.prototype.open = function(method, url) {
                            this.__capM = method; this.__capU = url;
                            return _origOpen.apply(this, arguments);
                        };
                        XMLHttpRequest.prototype.send = function(body) {
                            try {
                                window.__wsCapture.push({
                                    type: 'xhr',
                                    method: this.__capM || '?',
                                    url: this.__capU || '?',
                                    data: body ? String(body).substring(0, 2000) : ''
                                });
                            } catch(_e) {}
                            return _origSend.apply(this, arguments);
                        };
                    }
                }""")
            except Exception:  # noqa: BLE001
                pass

            _lap("net-patch-injected")
            self.page.route("**/*", _intercept_request)
            _lap("route-set")
            try:
                # HIRE_TEST_DEBUG_PAUSE=1 → freeze here so you can open Chrome
                # DevTools → Network tab → clear → then resume in Playwright
                # Inspector to watch what fires on Apply Changes.
                import os as _os
                if _os.getenv("HIRE_TEST_DEBUG_PAUSE"):
                    log.info("PAUSED before Apply Changes — open DevTools Network tab, then resume")
                    self.page.pause()

                # Normal click — Playwright waits ~30s for the button to become
                # actionable after the picker closes (server processing during that
                # window). force=True was tried but triggered a confirm modal and
                # timed out — the 30s wait IS the save; it cannot be bypassed.
                apply_btn.first.click()
                _lap("apply-btn-clicked")

                # Check for a confirmation modal ("Please review the recent
                # changes...") that shows a computed old-vs-new diff table —
                # some hire tests save directly with no modal, others require
                # this extra confirmation. A prior version waited only 300ms
                # for #save_setting, then fell back to a synchronous (non-
                # waiting) .count() check on the text locator — if the modal's
                # diff table took even slightly longer than that to render
                # (plausible, it has to compute what changed), the code gave
                # up before it appeared and never clicked it at all, silently
                # leaving the change unconfirmed. Now both paths properly wait.
                final = None
                try:
                    final = self.page.locator("#save_setting")
                    final.first.wait_for(state="visible", timeout=5000)
                except Exception:  # noqa: BLE001
                    final = self.page.get_by_text("Confirm & Apply Changes")
                    try:
                        final.first.wait_for(state="visible", timeout=5000)
                    except Exception:  # noqa: BLE001
                        final = None  # genuinely no modal appeared

                try:
                    if final is not None and final.count() > 0:
                        final.first.scroll_into_view_if_needed()
                        # Confirmed live: a real human click on this exact
                        # button, at this exact moment, works — so the button
                        # itself is fine and force=True wasn't the issue.
                        # Leading theory now: a timing race. The modal has to
                        # compute a diff table (old vs new values) before it's
                        # fully interactive; the button is visible in the DOM
                        # slightly before AngularJS finishes binding its click
                        # handler. A force click at that instant technically
                        # dispatches an event, but nothing is listening yet —
                        # indistinguishable from "froze". Give the digest
                        # cycle a moment to settle before clicking for real.
                        self.page.wait_for_timeout(1200)
                        final.first.click(timeout=5000)
                        _lap("confirm-modal-clicked")
                        try:
                            self.page.locator("#save_setting").wait_for(
                                state="hidden", timeout=3_000
                            )
                        except Exception:  # noqa: BLE001
                            pass
                except Exception:  # noqa: BLE001
                    log.debug("No 'Confirm & Apply Changes' modal to click.")
                _lap("apply-sequence-done")
            finally:
                self.page.unroute("**/*", _intercept_request)

            # Read all intercepted network activity during the apply sequence.
            try:
                net_frames = self.page.evaluate("() => window.__wsCapture || []") or []
                for f in net_frames:
                    log.info(
                        "Hire Test net [%s] %s %s : %s",
                        f.get("type", "?"), f.get("method", ""),
                        f.get("url", "?"), f.get("data", "")[:2000],
                    )
                # Only use fetch/XHR mutating requests for endpoint discovery —
                # WS notification-channel frames (wss://scaler.com/cable) are
                # not the save mechanism and would corrupt _api_endpoint.
                for f in net_frames:
                    if (
                        f.get("type") in ("fetch", "xhr")
                        and f.get("method", "GET").upper() not in ("GET", "HEAD")
                        and not _captured
                    ):
                        _captured["url"]    = f.get("url", "")
                        _captured["method"] = f.get("method", "POST").upper()
                        break
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not read net captures: %s", exc)

            if _captured.get("url"):
                import re as _re
                base = _re.sub(r"/\d+$", "", _captured["url"])
                HireTest._api_endpoint = base
                HireTest._api_method   = _captured.get("method", "PATCH")
                log.info(
                    "Hire Test save mechanism discovered: %s %s",
                    _captured["method"], _captured["url"],
                )
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Could not apply changes: {exc}")

        verified = self._verify(window, test_id=test_id)
        _lap("verified")
        if not verified:
            raise BrowserStepError(
                "Applied, but verification failed: the date field does not show "
                "the requested start AND end dates."
            )
        log.info("Hire Test %s applied and verified", test_id)
        return HireTestResult(
            test_id=test_id,
            applied=True,
            start=window.start,
            end=window.end,
            verified=verified,
        )

    # ------------------------------------------------------------------ #
    def update_window_via_fetch(
        self, test_id: str, window: AttemptWindow
    ) -> HireTestResult:
        """
        Update a hire test window via the page's own browser fetch (page.evaluate).
        Runs inside the browser context — uses all cookies (including HttpOnly),
        same-origin headers, and the live CSRF token automatically.
        """
        import json as _json

        _IST = timedelta(hours=5, minutes=30)

        def _to_hire_utc(dt: datetime) -> str:
            utc = (dt - _IST) if not dt.tzinfo else dt.astimezone(timezone.utc).replace(tzinfo=None)
            return utc.strftime("%a, %d %b %Y %H:%M:%S GMT")

        def _parse_hire_ist(s: str) -> datetime:
            s = s.strip().rstrip("Z")
            if "T" in s:
                s = s.split(".")[0]
                utc = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            else:
                utc = datetime.strptime(s, "%a, %d %b %Y %H:%M:%S GMT")
            return utc + _IST

        url = f"https://www.scaler.com/hire/test/{test_id}/basic-settings"
        start_utc = _to_hire_utc(window.start)
        end_utc   = _to_hire_utc(window.end)

        # Use AngularJS $http service — it auto-adds X-XSRF-TOKEN from cookie,
        # correct Accept header, and all session cookies. This matches exactly
        # what the daterangepicker's applyBtn handler sends.
        log.info("Hire Test $http POST %s start=%s end=%s", test_id, start_utc, end_utc)
        try:
            resp = self.page.evaluate(f"""() => {{
                try {{
                    const $http = angular.element(document.body).injector().get('$http');
                    return $http.post(
                        '/hire/test/{test_id}/basic-settings',
                        {{ start_time: '{start_utc}', end_time: '{end_utc}' }}
                    ).then(
                        r => ({{ status: r.status, body: JSON.stringify(r.data).substring(0, 500) }}),
                        e => ({{ status: e.status || 0, body: JSON.stringify(e.data || e.message || '').substring(0, 500) }})
                    );
                }} catch(e) {{
                    return {{ status: 0, body: 'angular error: ' + e.message }};
                }}
            }}""")
        except Exception as exc:  # noqa: BLE001
            raise BrowserStepError(f"Browser-fetch eval error for {test_id}: {exc}")

        log.info("Hire Test browser-fetch %s → HTTP %d body=%r", test_id, resp.get("status"), resp.get("body", "")[:200])
        if resp.get("status") != 200:
            raise BrowserStepError(
                f"Hire Test browser-fetch POST failed for {test_id}: "
                f"HTTP {resp.get('status')} — {resp.get('body', '')[:200]}"
            )
        try:
            result = _json.loads(resp["body"])
        except Exception:
            raise BrowserStepError(f"Hire Test browser-fetch response not JSON for {test_id}: {resp.get('body','')[:200]}")
        if not result.get("success"):
            raise BrowserStepError(f"Hire Test browser-fetch save failed for {test_id}: {str(result)[:300]}")
        log.info("Hire Test browser-fetch %s → success", test_id)

        url = f"https://www.scaler.com/hire/test/{test_id}/basic-settings"
        hdrs = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        req_ctx = self.page.context.request

        # Verify via GET readback
        rb_resp = req_ctx.fetch(url, method="GET", headers=hdrs)
        rb_env  = rb_resp.json() if rb_resp.ok else {}
        rb = rb_env.get("current_test") or rb_env  # start_time lives inside current_test

        def _trunc(dt: datetime) -> datetime:
            return dt.replace(second=0, microsecond=0)

        verified = False
        try:
            got_start = _parse_hire_ist(rb.get("start_time", ""))
            got_end   = _parse_hire_ist(rb.get("end_time",   ""))
            verified  = (
                _trunc(got_start) == _trunc(window.start)
                and _trunc(got_end) == _trunc(window.end)
            )
            if verified:
                log.info(
                    "Hire Test API verified: start=%s IST, end=%s IST",
                    got_start, got_end,
                )
            else:
                log.warning(
                    "Hire Test API verify mismatch: got %s/%s, want %s/%s",
                    got_start, got_end, window.start, window.end,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not parse API readback timestamps: %s", exc)

        log.info("Hire Test %s updated via API (verified=%s)", test_id, verified)
        return HireTestResult(
            test_id=test_id, applied=True,
            start=window.start, end=window.end, verified=verified,
        )

    # ------------------------------------------------------------------ #
    def _pick_day(self, dt: datetime) -> None:
        """
        Click the day cell for `dt` in whichever calendar panel currently shows
        that month/year. Navigates the picker (prev/next arrows) if needed.
        """
        target_month = dt.strftime("%b %Y")  # e.g. "Jun 2026"
        day = str(dt.day)

        for _ in range(24):  # up to 24 nav steps (2 years) to bring the month into view
            left_hdr = self._panel_header(".drp-calendar.left")
            right_hdr = self._panel_header(".drp-calendar.right")

            if target_month in (left_hdr or ""):
                panel = ".drp-calendar.left"
            elif target_month in (right_hdr or ""):
                panel = ".drp-calendar.right"
            else:
                # Navigate: if target is before left header, go prev; else next.
                if self._month_is_before(target_month, left_hdr):
                    self.page.locator(".drp-calendar.left .prev").click()
                else:
                    self.page.locator(".drp-calendar.right .next").click()
                self.page.wait_for_timeout(80)
                continue

            # Click the day cell that is "available" (not off-month/disabled).
            cell = self.page.locator(
                f"{panel} td.available:not(.off)"
            ).filter(has_text=re.compile(rf"^{day}$"))
            log.info("_pick_day %s day=%s panel=%s cell_count=%d", target_month, day, panel, cell.count())
            cell.first.click()
            return
        raise BrowserStepError(f"Could not bring {target_month} into the picker.")

    def _panel_header(self, panel_sel: str) -> Optional[str]:
        try:
            return self.page.locator(
                f"{panel_sel} .month"
            ).first.inner_text(timeout=3000).strip()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _month_is_before(target: str, header: Optional[str]) -> bool:
        """True if target month/year is earlier than the header month/year."""
        if not header:
            return False
        try:
            t = datetime.strptime(target, "%b %Y")
            h = datetime.strptime(header, "%b %Y")
            return t < h
        except Exception:  # noqa: BLE001
            return False

    def _set_times(self, start: datetime, end: datetime) -> None:
        """Set the hour/minute/AM-PM dropdowns for start and end."""
        selects = self.page.locator(".daterangepicker select")
        # Expected order: [startHour, startMin, startAmPm, endHour, endMin, endAmPm]
        if selects.count() < 6:
            return
        values = [
            start.strftime("%I").lstrip("0") or "12",
            start.strftime("%M"),
            start.strftime("%p"),
            end.strftime("%I").lstrip("0") or "12",
            end.strftime("%M"),
            end.strftime("%p"),
        ]
        for i, val in enumerate(values):
            try:
                selects.nth(i).select_option(label=val)
            except Exception:  # noqa: BLE001
                try:
                    selects.nth(i).select_option(value=val)
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ #
    def _dismiss_tour_overlay(self) -> None:
        # JS pass: dismiss tour overlays only (NOT the AngularJS modal — see below).
        try:
            self.page.evaluate("""
                () => {
                    // Dismiss tour popups
                    const names = ['Skip','Close','Got it','Next','Done'];
                    for (const btn of document.querySelectorAll('button')) {
                        if (names.includes((btn.textContent || '').trim())
                                && btn.offsetParent !== null) {
                            btn.click();
                            break;
                        }
                    }
                    // Remove tour overlay elements
                    const sels = ['.tour-backdrop','.introjs-overlay',
                                  '.introjs-helperLayer','[class*="tour"]'];
                    for (const s of sels)
                        document.querySelectorAll(s).forEach(el => el.remove());
                }
            """)
        except Exception:  # noqa: BLE001
            log.debug("Tour overlay removal script did not run cleanly.")

        # Dismiss #showChangedTestSettingsModal via PLAYWRIGHT click, not JS.
        # JS close.click() skips AngularJS's $scope.$apply(), leaving the
        # scope's modal-open state as true — which prevents .applyBtn save
        # from firing. Playwright click triggers the full event chain properly.
        try:
            modal = self.page.locator("#showChangedTestSettingsModal.in")
            if modal.count() > 0:
                log.info("Dismissing #showChangedTestSettingsModal via Playwright click")
                close_btn = modal.locator('[data-dismiss="modal"], .close, button').first
                if close_btn.count() > 0:
                    close_btn.click(timeout=2000)
                    self.page.wait_for_timeout(300)
                else:
                    # No button — force-hide as last resort (state may be imperfect)
                    self.page.evaluate("""() => {
                        const m = document.getElementById('showChangedTestSettingsModal');
                        if (m) {
                            angular.element(m).scope().$apply(function(s) {
                                s.showChangedTestSettingsModal = false;
                            });
                            m.classList.remove('in');
                            m.style.display = 'none';
                            document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
                            document.body.classList.remove('modal-open');
                        }
                    }""")
        except Exception:  # noqa: BLE001
            pass

    def _test_id_from_url(self) -> str:
        match = re.search(r"/hire/test/(\d+)", self.page.url)
        return match.group(1) if match else "unknown"

    def _verify(self, window: AttemptWindow, test_id: Optional[str] = None) -> bool:
        """
        Verify by reading back from the server API (GET basic-settings).
        The page DOM is NOT used — it still shows whatever was entered in the
        picker and cannot confirm that the server actually saved the values.
        Falls back to DOM check if the GET fails.

        test_id must be passed explicitly — do not re-derive from URL here,
        because the page may have navigated after Apply Changes was clicked.
        """
        _IST = timedelta(hours=5, minutes=30)

        def _parse_hire_ist(s: str) -> datetime:
            """Parse server timestamp → naive IST. Handles both formats:
            - HTTP date: 'Mon, 27 Jul 2026 01:30:00 GMT'
            - ISO 8601:  '2026-07-27T01:30:00.000Z'
            """
            s = s.strip().rstrip("Z")
            if "T" in s:
                # ISO 8601 — strip trailing milliseconds if present
                s = s.split(".")[0]
                utc = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            else:
                utc = datetime.strptime(s, "%a, %d %b %Y %H:%M:%S GMT")
            return utc + _IST

        if not test_id:
            test_id = self._test_id_from_url()
        url = f"https://www.scaler.com/hire/test/{test_id}/basic-settings"
        try:
            rb = self.page.context.request.fetch(
                url,
                method="GET",
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            if not rb.ok:
                log.warning(
                    "Hire Test verify GET returned %d for %s — falling back to DOM",
                    rb.status, test_id,
                )
                return self._verify_dom(window)
            envelope = rb.json()
            # start_time/end_time live inside "current_test", not at top level
            data = envelope.get("current_test") or envelope
            log.debug("Hire Test verify GET keys: %s", list(data.keys())[:10])
            if "start_time" not in data:
                log.warning(
                    "Hire Test verify GET for %s missing start_time — "
                    "envelope keys=%s data keys=%s body=%r — falling back to DOM",
                    test_id, list(envelope.keys())[:10],
                    list(data.keys())[:10], rb.text()[:300],
                )
                return self._verify_dom(window)
            server_start = _parse_hire_ist(data["start_time"])
            server_end   = _parse_hire_ist(data["end_time"])
            start_ok = abs((server_start - window.start).total_seconds()) < 120
            end_ok   = abs((server_end   - window.end  ).total_seconds()) < 120
            log.info(
                "Hire Test verify (API): start=%s IST want=%s %s | end=%s IST want=%s %s",
                server_start, window.start, "OK" if start_ok else "MISMATCH",
                server_end,   window.end,   "OK" if end_ok   else "MISMATCH",
            )
            if not (start_ok and end_ok):
                log.warning("Hire Test verify FAILED via API: server times don't match window")
            return start_ok and end_ok
        except Exception as exc:  # noqa: BLE001
            log.warning("Hire Test API verify error (%s) — falling back to DOM", exc)
            return self._verify_dom(window)

    def _verify_dom(self, window: AttemptWindow) -> bool:
        """DOM fallback: check that both date strings appear in the page body."""
        try:
            body = self.page.locator("body").inner_text(timeout=5000)
        except Exception:  # noqa: BLE001
            return False

        def date_s(d: datetime) -> str:
            return f"{d.strftime('%B')} {d.day}, {d.year}"

        start_ok = date_s(window.start) in body
        end_ok   = date_s(window.end)   in body
        if start_ok and end_ok:
            log.info("Hire Test verify (DOM fallback): dates present in page body")
        else:
            log.warning(
                "Hire Test verify FAILED (DOM): start=%r present=%s, end=%r present=%s",
                date_s(window.start), start_ok, date_s(window.end), end_ok,
            )
        return start_ok and end_ok
