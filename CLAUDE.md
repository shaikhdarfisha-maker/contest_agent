# NV Contest Agent — Claude Context

Read this file at the start of every session. It replaces machine-local memory.

---

## Business / Domain Knowledge — READ THIS FIRST

### What is Neovarsity (NV)?
Neovarsity is Scaler's upskilling program for working professionals. Students are enrolled in one of several programs (Academy, DSML, AIML, DevOps). Each program has multiple modules taught sequentially (e.g. Advanced DSA 1 → 2 → 3 → 4).

### What is an "NV Contest event"?
An NV Contest event is a periodic assessment (monthly or quarterly) that runs **across multiple modules simultaneously**. For example, the "NV Contest June 2026" event might include:
- Advanced DSA 1, 2, 3, 4 (Academy program)
- Data Foundations, ML Coding (DSML program)
- Basics of GenAI and AI Agents (AIML program)
- …and more — potentially 15–20 modules in one event

**The tool is run once per module.** Each run creates one module's contest. To run an entire event, the operator runs the tool once for each participating module, back to back. There is no "run all" mode.

### What does one module's "contest" actually consist of?
One module's NV Contest = **4 linked hire tests** on Scaler's Hire Test platform:
- **Contest** (A1) — the main contest window, operator-supplied start/end
- **Re-attempt 1** (A2) — starts when A1 ends (snapped to midnight), runs **7 days**
- **Re-attempt 2** (A3) — starts when A2 ends, runs **9 days**
- **Re-attempt 3** (A4) — starts when A3 ends, runs **10 days**

These 4 tests are pre-linked in a "Group Contest Summary" on the `edit-sbat-group` page. The tool reads all 4 hire-test IDs from that page and sets each test's date window in order.

### Programs and their module libraries
| Program | Sheet in Library Excel | Notes |
|---|---|---|
| Academy | Academy Libraries | Largest program; DSA, Full-stack, etc. |
| DSML | DSML Libraries | Data Science & ML modules |
| AIML | AIML Libraries | AI/ML; GenAI and AI Agents modules carry `(AIML)` suffix |
| DevOps | DevOps Libraries | Cloud/infrastructure modules |

The `(AIML)` suffix (e.g. "Basics of GenAI and AI Agents (AIML)") is in the Excel/batch name to distinguish modules that appear in multiple programs. The suffix is stripped before CCT checkbox matching.

### The "NV Contests" CCT library
Most modules (especially in Academy) live in a single CCT library called **NV Contests**. This one library hosts 90+ contest classes, one per module (e.g. "Advanced DSA 4", "Full-stack LLD and Development 4"). The agent scrolls the full class list and matches by module name.

Modules with dedicated CCT libraries (e.g. DSML or AIML-specific ones) are mapped in the Excel sheet. If a module is not in the sheet, the fallback is **NV Contests**.

### Four systems the tool touches
1. **Admin V2** (`scaler.com/admin/academy/v2/batches/`) — creates a batch by cloning an NV template batch. Batch name: `"{Module}: NV Contest {Month} {Year}"`.
2. **CCT** (`scaler.com/scm/`) — schedules a class for that batch in the correct library, picks a slot (9 PM IST preferred), ticks the skill-eval checkbox for the module.
3. **Hire Test** (`scaler.com/hire/test/<id>/`) — sets start/end dates for all 4 hire tests (Contest + 3 Re-attempts) found in the Group Contest Summary.
4. **Google Sheets Tracker** — appends/updates one row per module with batch name, module, and all 4 start/end datetimes.

### Timing conventions
- Contests always start at **9 PM IST** on the contest date.
- CCT class scheduling also targets **9 PM IST slots** (MWF or TTHS depending on the day).
- The operator enters only the A1 (Contest) window; A2–A4 windows are derived automatically.

### What to do when a new module is added
1. Add a row to `data/Library__All_Programs.xlsx` in the correct program sheet: `Module Name | CCT Library Name`.
2. If the CCT class is in the NV Contests library (most Academy modules), use `NV Contests`.
3. If the module name has CamelCase in CCT (e.g. "MLCoding"), the tool normalises it automatically — no special handling needed.

### What does the operator actually do?
The operator (Scaler admin, typically 1–2 people per team) opens the Streamlit dashboard, enters 4 fields per module, and clicks "Run". They repeat this for each module in the current contest event. A full event of 15 modules ≈ 15 runs ≈ ~15 minutes total.

---

## What this tool does

End-to-end automation for creating Neovarsity contest classes on Scaler. One run does:
1. **Library resolution** — reads `data/Library__All_Programs.xlsx` for the correct CCT library
2. **Batch creation** — clones an existing NV batch in Scaler Admin V2
3. **CCT scheduling** — opens Classroom Creation Tool, picks batch/library/slot/date, confirms
4. **Hire Test discovery** — reads hire-test IDs from "Group Contest Summary" cards
5. **Window setting** — sets contest + re-attempt date windows in each hire test
6. **Tracker upsert** — writes/updates the row in Google Sheets (keyed on Module Name col A)

---

## How to run locally

```bash
cd ~/contest_agent
./start.sh        # starts Streamlit on :8501 + ngrok tunnel
```

Public URL: `https://shale-unfailing-backyard.ngrok-free.dev`

If ngrok isn't in PATH:
```bash
python3 -m streamlit run streamlit_app.py --server.port 8501 --server.headless true &
/opt/homebrew/Caskroom/ngrok/*/ngrok http --url=shale-unfailing-backyard.ngrok-free.dev 8501 &
```

## New machine setup (one-time)

Repo is public — no GitHub login/token needed to clone it.

**On the Mac that already works**, bundle the 4 gitignored secret files into one AirDrop-friendly file:
```bash
./bundle_secrets.sh   # creates secrets_bundle.zip
```
AirDrop that one file into the new Mac's Downloads folder.

**On the new Mac**, open Terminal and paste:
```bash
curl -fsSL https://raw.githubusercontent.com/shaikhdarfisha-maker/contest_agent/main/bootstrap.sh | bash
```
This installs Homebrew/python/ngrok/git if missing, clones the repo, installs Python deps + Playwright Chromium, unpacks the secrets bundle, and configures ngrok (it'll prompt for the authtoken from dashboard.ngrok.com).

Then refresh the Scaler session (always required — sessions don't transfer machine to machine):
```bash
cd ~/contest_agent
python3.11 capture_login.py   # opens browser, log in manually
```

**Gotcha (bit us during a migration):** `data/contest_agent.sqlite3` is the only record of `batch_exists()`/duplicate-detection history (`modules/metadata_store.py`) and is gitignored — it does NOT come from `git clone`. `bundle_secrets.sh` now includes it in the zip, but if a new machine ever ends up with its own fresh (near-empty) db from having run the app before the real history arrived, don't just overwrite — check row counts on both (`sqlite3 data/contest_agent.sqlite3 "SELECT COUNT(*) FROM contests"`) and merge the newer machine's rows into the fuller history before replacing the file, or duplicate-detection silently loses weeks of memory.

Prevent Mac sleep (so the app stays up during work hours):
```bash
sudo pmset -c sleep 0 disksleep 0 displaysleep 0
```

---

## Key files

| File | Purpose |
|---|---|
| `streamlit_app.py` | Streamlit UI entry point |
| `modules/orchestrator.py` | Top-level run loop |
| `modules/schedule_creator.py` | CCT browser automation (most complex, most fragile) |
| `modules/hire_test.py` | Hire Test date window setting |
| `modules/google_tracker.py` | Google Sheets upsert |
| `modules/library_reader.py` | Excel library resolution |
| `config.py` | Slot labels, column maps, constants |
| `data/Library__All_Programs.xlsx` | Per-program library mapping (sheet per program) |
| `data/storage_state.json` | Playwright saved auth (gitignored) |
| `data/service_account.json` | Google SA key (gitignored) |

---

## Session expiry

`data/storage_state.json` expires every ~2-4 weeks. When the agent starts failing with auth errors:
```bash
python3 capture_login.py   # log in manually, saves fresh session
```

---

## All bugs fixed (do NOT re-apply)

### 1. Hire Test ID discovery
**File:** `schedule_creator.py` → `_visit_sbat_and_collect_test_ids()`
Parse IDs from "Group Contest Summary" card headers using regex `/(Contest|Re-attempt\s+\d+)\s+(\d{5,8})/gi`. Section loads async — must `wait_for_selector("text=Group Contest Summary")` first.

### 2. CCT navigation
**File:** `schedule_creator.py` → `_read_sbat_ids_from_table()`
Use `a[href*='/scm/classes/edit-sbat-group/']` anchors on view-schedule page, not hire-test links.

### 3. Time mismatch guard
**File:** `schedule_creator.py` → `_validate_confirm_modal()`
After "Confirm Schedule" click, parse "Proposed Date & Time" from modal body and compare to `requested_start`. Abort if > 5 min difference. Slot hint regex must require `\d{1,2}:\d{2}` before AM/PM or it falsely matches "FundAMental".

### 4. Post-schedule outcome detection
**File:** `schedule_creator.py` → `_wait_for_schedule_outcome()`
Race `'View Scheduled Classes' in body OR /view-schedule/ in URL` — don't wait only for the button text.

### 5. Slot selection order
**File:** `schedule_creator.py` → `schedule_class()`
Order: same-pattern-9PM → same-pattern-7AM → other-pattern-9PM → other-pattern-7AM. Use `start.date()` not `today` to pick preferred pattern.

### 6. Google Sheets upsert
**File:** `google_tracker.py` → `_find_module_row()`
Search col A (Module Name) case-insensitively. UPDATE existing row. APPEND only if not found.

### 7. Google Sheets date format
**File:** `google_tracker.py` → `_fmt()`
Use `dt.strftime("%Y-%m-%d %H:%M:%S")` — ISO 8601. DD/MM format breaks in US-locale sheets.

### 8. Library defaults
`data/Library__All_Programs.xlsx` — prepend rows to control priority. Higher rows = higher priority.

### 9. Skill-eval checkbox matching — colon spacing + CamelCase + plural
**File:** `schedule_creator.py` → `_find_target()` + JS `tryClick()`
- Normalize colon spacing: `re.sub(r'\s*:\s*', ':', pref_lower)`
- Handle CamelCase: split `([A-Z]+)([A-Z][a-z])` and `([a-z\d])([A-Z])` before lowercasing
- Flexible spaces in regex: `.replace('\\ ', r'\s*')`
- JS: `rmSpace = s => s.replace(/\s+/g, '')` applied before `startsWith`
- Strip program suffix tags like `(AIML)` before matching: `re.sub(r'\s*\([^)]+\)\s*$', '', preferred_name)`

### 10. Hire test date injection
**File:** `hire_test.py` → `update_window()` → `_intercept_request`
Playwright LIFO route ordering meant a separate `_inject_dates_route` never fired. Fix: merged injection directly into `_intercept_request`. For every POST to `basic-settings`, parse JSON body, overwrite `start_time`/`end_time` with HTTP-date strings, call `route.continue_(post_data=...)`.

### 11. Clone button strict mode
**File:** `batch_creator.py` → clone step
Use `.first` on both the row locator and Clone button: `row.first` + `row.get_by_text("Clone").first.click()`.

### 12. #showChangedTestSettingsModal dismissal
**File:** `hire_test.py` → `_dismiss_tour_overlay()`
Use Playwright click (not JS click) on the close button — JS click skips AngularJS `$scope.$apply()`.

### 13. Skill-eval checkbox label can diverge from module name
**Files:** `config.py` (`SheetSpec.skill_eval_col`), `library_reader.py` (`LibraryMatch.skill_eval_label`), `schedule_creator.py` → skill-eval checkbox block
Shared libraries like NV Contests (338) hold many unrelated contest sessions. `_check_skill_eval_checkbox` matches by module name by default, which breaks when Scaler's checkbox label shares no words with the module (e.g. module "Linux Shell Scripting and Computer Systems 2" vs. checkbox "Linux Certification Contest") — it would silently tick the wrong contest instead of erroring. Fix: add an optional "Skill Eval Label" column per-sheet in the workbook; when set, it overrides the match target instead of the module name. Check this whenever a module is remapped to a shared/generic library — verify in Scaler's Schedule Classes flow (not the Edit Library admin page, which lists sessions but isn't the live checkbox screen) what the checkbox is actually labeled before assuming module-name matching will work.

### 14. A failed run could poison every future retry of that module (permanent fix: stopped trusting local DB for this)
**Files:** `orchestrator.py` → `_browser_steps_inner()`; `batch_creator.py` → `create_batch()` / `_find_existing_batch()`
First fix attempt (kept status tracking but added an intermediate `"batch_created"` state) still trusted a local SQLite flag to decide whether to skip real Admin V2 batch creation on retry. The exact same symptom recurred on a *brand-new* module ("Classical ML 1: NV Contest July 2026", never run before, single fresh DB row) — `_skip_batch` was still true somehow, CCT then timed out searching for a batch that never existed. Root cause was never fully pinned down (possibly a race/edge case in when the local flag gets trusted), but it didn't need to be: `BatchCreator.create_batch()` already does its own **live** check against Scaler's Admin V2 batch list (`_find_existing_batch`) and reuses an existing batch if found instead of re-cloning. The local `skip_batch` shortcut was therefore pure risk with no real benefit — removed entirely (along with `batch_was_previously_created()`). The batch step now **always** goes through `create_batch()`, which is self-verifying against Scaler (the actual source of truth) on every call, so a wrong/stale local DB state can no longer cause this failure mode. If a run still fails at CCT batch-selection with a timeout, the batch genuinely doesn't exist and something else is wrong (check Admin V2 directly, and check `_find_existing_batch`'s selectors haven't broken).

### 15. Hire Test date picker: generic selector fallback silently sets the wrong field
**File:** `hire_test.py` → `update_window()`, Path A JS event trigger
The `apply.daterangepicker` event-trigger path tries a list of selectors and fires on the first visible match, with `'input[type="text"]'` as a last-resort fallback. On the **Contest/A1** hire-test page layout specifically (not Re-attempts, which have a different layout and always worked), none of the real date-range-directive selectors match, so it fell through to "the first visible text input on the page" — not the actual date widget. The event fires, reports `ok:true`, the start date happens to apply correctly but the end date silently stays at whatever it was before (a stale, unrelated date) — verification correctly catches the mismatch, but `@retry` just reruns the same broken logic 3/3 times identically. Diagnosed by running `finish_hire_test.py` in isolation with its existing debug logging (`apply.daterangepicker event result`, per-field API verify readout) — the log line `'sel': 'input[type="text"]'` combined with `end=<wrong date> MISMATCH` was the direct proof. Fix: removed the generic fallback; when no real directive selector matches, `ok:false` now correctly falls through to Path B (actual picker-click logic via `_pick_day`/`_set_times`), which had never been exercised for Contest-type pages before because Path A always falsely "succeeded" first.

### 16. CCT class scheduling is NOT idempotent — don't re-run a whole contest from the UI to retry a later step
**Files:** `schedule_creator.py` → `schedule_class()`; contrast with `batch_creator.py` → `create_batch()` (which IS idempotent, see #14)
Unlike batch creation, CCT scheduling has no "already scheduled, reuse it" check — every full run schedules a brand-new class. If a run fails at the hire-test or tracker step (batch + CCT already succeeded), re-running the same module from the Streamlit UI creates a **second duplicate scheduled class** with a fresh set of 4 hire-test IDs, orphaning the first set. When only a later step failed, fix that step in isolation instead (`finish_hire_test.py <test_id> <start> <end>` for a hire-test date, a direct `_build_tracker(program).append_contest(...)` call for the tracker) — never just click Run again on the same module once CCT has already scheduled successfully.

### 17. Hire Test "Confirm & Apply Changes" — simulated clicks stopped reaching AngularJS entirely (call the function directly)
**File:** `hire_test.py` → `update_window()`, confirm-modal handling
The single biggest fix from a very long live-debugging session. Symptom: the Contest (first) hire-test window in every run consistently failed to save the correct end date, while every Re-attempt in the same run succeeded with identical code — across every fix attempt (Custom Range click, real vs JS-driven day-picking, force clicks, settle delays, retrying the click, removing the API fast-path as a contamination source, slowing the whole sequence down to human pacing). None of it worked. A real human click on the exact same button, at the exact moment automation was stuck, always worked immediately — even inside the same Playwright-launched browser/session, ruling out session/browser explanations.
**Root cause, proven via Chrome DevTools Network tab** (not guessed): a simulated Playwright click on `#save_setting` (`ng-click="saveTestBasicSettings(null, true)"`) produces **zero network requests** — the click event was landing on the correct, visible element but never reaching AngularJS's `ng-click` binding to invoke the handler at all. Not a payload issue, not a timing issue, not a session issue.
**Fix:** stopped simulating a click and instead call the Angular scope function directly via `page.evaluate()`: `angular.element(el).scope().saveTestBasicSettings(null, true); scope.$apply();` — the same call `ng-click` would have made, just invoked directly rather than hoping a simulated DOM click reaches it. Falls back to the old retry-click logic only if the direct call is unavailable.
**If this regresses again:** don't re-try click mechanics (force/delay/retry all already tried and failed) — go straight to DevTools Network tab inspection (`HIRE_TEST_DEBUG_PAUSE=1` env var pauses right before Apply Changes for exactly this) to check whether a request fires at all before assuming a payload/logic bug.

### 18. Don't put the project in ~/Downloads, ~/Desktop, or ~/Documents
**File:** `launchd/com.contestagent.app.plist`, `bootstrap.sh`
macOS blocks background/`launchd`-launched processes from accessing Desktop/Documents/Downloads without an explicit per-app permission grant — one that's awkward to give to a raw shell script (there's no simple GUI picker entry for it). Auto-start on login silently fails with `Operation not permitted` (visible in `logs/launchd.log`) if the project lives in one of those folders, even though running the identical script manually from Terminal works fine (Terminal.app itself already has the access). Fix: keep the project directly under `$HOME` (e.g. `~/contest_agent`) or anywhere else outside those three protected folders. `bootstrap.sh` now defaults new installs to `~/contest_agent`.

---

## Fragile areas — check first when things break

| Area | Selector/Signal | Risk |
|---|---|---|
| Group Contest Summary cards | text "Contest 1288152" regex | Scaler renames section |
| view-schedule pencil links | `a[href*='/scm/classes/edit-sbat-group/']` | Path changed 3+ times before |
| CCT slot dropdown | `#react-select-5-input` | React-select IDs shift if dropdowns added |
| CCT library dropdown | `#react-select-4-input` | Same risk |
| Slot label exact text | `"Mon 09:00 PM \| Wed 09:00 PM \| Fri 09:00 PM (GMT+05:30)"` | Spacing/timezone label changes |
| "View Scheduled Classes" | button text + `/view-schedule/` in URL | Button text change |

When a selector breaks: take a screenshot, inspect the live DOM, update the selector/regex.

---

## Security rules (never violate)

- `.streamlit/secrets.toml` — gitignored, never commit
- `data/storage_state.json`, `data/service_account.json` — gitignored, never commit
- `SESSION_SECRET`, `STORAGE_STATE_B64`, `SERVICE_ACCOUNT_B64` — never hardcode
- No raw logs with session tokens or JWTs committed
