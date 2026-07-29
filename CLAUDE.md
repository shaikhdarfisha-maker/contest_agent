# NV Contest Agent — Claude Context

Read this file at the start of every session. It replaces machine-local memory.

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
cd ~/Downloads/contest_agent
./start.sh        # starts Streamlit on :8501 + ngrok tunnel
```

Public URL: `https://shale-unfailing-backyard.ngrok-free.dev`

If ngrok isn't in PATH:
```bash
python3 -m streamlit run streamlit_app.py --server.port 8501 --server.headless true &
/opt/homebrew/Caskroom/ngrok/*/ngrok http --url=shale-unfailing-backyard.ngrok-free.dev 8501 &
```

## New machine setup (one-time)

```bash
brew install python@3.11 ngrok
git clone https://<TOKEN>@github.com/shaikhdarfisha-maker/contest_agent.git ~/Downloads/contest_agent
cd ~/Downloads/contest_agent
pip3 install -r requirements.txt
playwright install chromium
ngrok config add-authtoken <NGROK_TOKEN>   # from dashboard.ngrok.com
```

Transfer these files from old Mac (gitignored, never committed):
- `data/storage_state.json` — Scaler browser session
- `data/service_account.json` — Google Sheets service account key
- `.env` — local env vars
- `.streamlit/secrets.toml` — Streamlit secrets

Then refresh the Scaler session:
```bash
python3 capture_login.py   # opens browser, log in manually
```

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
