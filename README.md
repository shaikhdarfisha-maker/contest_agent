# Neovarsity Contest Creation Agent

An AI operations agent that automates the end-to-end Neovarsity contest
creation workflow across four systems — Admin V2, the Classroom Creation Tool
(CCT), Hire Test, and the NV Contest Tracker — from four operator inputs.

The operator supplies only:

- **Module Name** (e.g. `Advanced DSA 4`)
- **Contest Name**
- **Contest Start Date/Time**
- **Contest End Date/Time** (or number of attempts)

…and the agent resolves the library, generates the batch name, creates the
batch, schedules the class, drives the Hire Test date update, and appends a row
to the tracker — logging every step and capturing a screenshot on any failure.

---

## How it works

```
 operator inputs
       │
       ▼
 ┌───────────────┐   resolve module → library (per program)
 │ library_reader│   from Library__All_Programs.xlsx
 └───────┬───────┘
         ▼
 ┌───────────────┐   build "Module: NV Contest Month Year"
 │  config/utils │   derive 4 attempt windows from the A1 window
 └───────┬───────┘
         ▼
 ┌───────────────┐   System 1: Admin V2  → create batch
 │ batch_creator │
 └───────┬───────┘
         ▼
 ┌────────────────┐  System 2: CCT       → select library, tick skill-eval
 │schedule_creator│   checkbox, schedule class, open Add Questions links
 └───────┬────────┘
         ▼
 ┌───────────────┐   System 3: Hire Test → set start/end, Apply, verify
 │   hire_test   │
 └───────┬───────┘
         ▼
 ┌───────────────┐   System 4: Tracker  → append row (schema-preserving)
 │    tracker    │
 └───────┬───────┘
         ▼
 ┌───────────────┐   SQLite: ids, timestamps, status, errors
 │ metadata_store│
 └───────────────┘
```

The `orchestrator` wires these together; `app.py` (CLI) and `streamlit_app.py`
(dashboard) are thin front-ends over it.

### Key business rules

- **Naming convention:** `"{Module}: NV Contest {Month} {Year}"`
  (e.g. `Advanced DSA 4: NV Contest June 2026`)
- **Library lookup is program-scoped.** The module → CCT library mapping lives
  in `data/Library__All_Programs.xlsx`, one sheet per program. When a module is
  not in the sheet the fallback is **NV Contests**.
- **Schedule slot selection is automatic.** The agent picks the slot based on
  the current day, then falls back through all available options if the preferred
  slot is unavailable (e.g. today's 9 PM has already passed):
  1. MWF 9 PM *(preferred on Mon/Wed/Fri)*
  2. TTHS 9 PM *(preferred on Tue/Thu/Sat)*
  3. MWF 7 AM
  4. TTHS 7 AM
- **Past start times are rejected early.** If the contest start datetime has
  already passed when the agent runs, it fails immediately with a clear message
  before opening any browser.
- **A "contest" is four linked tests** (Contest + Re-attempt 1/2/3). The
  operator enters only the **A1** window; the rest are derived:
  - A2: starts when A1 ends (snapped to 00:00), runs **7 days**
  - A3: starts when A2 ends, runs **9 days**
  - A4: starts when A3 ends, runs **10 days**
- **The tracker is treated as the source of truth.** The agent appends a row
  using only the manually-entered columns (Module, Batch Name, the four
  start/end datetimes). It never adds columns or overwrites formulas.

---

## Project structure

```
contest_agent/
├── app.py                 # CLI entrypoint
├── streamlit_app.py       # Dashboard
├── setup_auth.py          # One-time SSO session capture
├── test_runner.py         # Full regression test suite
├── config.py              # All settings (env-overridable)
├── modules/
│   ├── browser.py         # Playwright lifecycle, auth reuse, error screenshots
│   ├── library_reader.py  # module → library resolution
│   ├── batch_creator.py   # System 1: Admin V2
│   ├── schedule_creator.py# System 2: CCT + reach Hire Test
│   ├── hire_test.py       # System 3: date update + verify
│   ├── tracker.py         # System 4: schema-preserving append
│   ├── google_tracker.py  # Google Sheets tracker variant
│   ├── metadata_store.py  # SQLite bookkeeping
│   ├── orchestrator.py    # End-to-end coordination
│   ├── logger.py          # Console + per-run file logging
│   └── utils.py           # Exceptions, retry, datetime + window derivation
├── data/
│   ├── Library__All_Programs.xlsx   # Module → CCT library mapping
│   └── NV_contests_Tracker_Q2-2026_.xlsx
├── logs/                  # Per-run log files
├── screenshots/           # Error screenshots (captured automatically on failure)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env        # edit paths/URLs/credentials
```

---

## Usage

### One-time auth

```bash
python setup_auth.py        # log in to Scaler, press Enter to save the session
```

The session is saved to `data/storage_state.json` and reused for all subsequent
runs. Re-run `setup_auth.py` if the agent starts getting login redirects.

### CLI

```bash
# Full run
python app.py --module "Advanced DSA 4" \
              --contest-name "Advanced DSA 4 July Contest" \
              --start "2026-07-20 21:00" --end "2026-07-30 21:00"

# Dry run: resolve + plan, no browser, no tracker write
python app.py --module "Advanced DSA 4" --contest-name x \
              --start "2026-07-20 21:00" --end "2026-07-30 21:00" \
              --no-browser --dry-run-tracker

# DevOps program
python app.py --module "AWS 1" --program devops \
              --contest-name "AWS 1 Contest" \
              --start "2026-07-01 21:00" --end "2026-07-15 21:00"
```

Accepted date formats: `2026-07-20 21:00`, `2026-07-20T21:00`,
`Jul 20 2026 09:00 PM`, `20 Jul 2026, Mon, 9:00 pm`.

### Dashboard (local only)

```bash
streamlit run streamlit_app.py
```

### Production: Mac + ngrok (primary setup)

See the **Deployment** section below for the full picture.

---

## Library mapping

The CCT library a module uses is looked up from
`data/Library__All_Programs.xlsx`. Each program has its own sheet:

| Sheet | Program |
|---|---|
| Academy Libraries | `academy` |
| DevOps Libraries | `devops` |
| DSML Libraries | `dsml` |
| AIML Libraries | `aiml` |

Each sheet has two columns: **Module Name** (col A) and **CCT Library Name** (col B).

**Resolution order:**
1. If the operator passes `--library-name`, that is used directly.
2. Otherwise, the Excel sheet is checked. If the module is found, that library
   is used.
3. If the module is not in the sheet, the fallback is **NV Contests**.

### NV Contests library

Most modules resolve to **NV Contests** — a single CCT library that hosts 90+
contest classes. The agent scrolls the full class list and matches by the module
name. Class names in NV Contests match module names exactly (e.g. `Advanced DSA 1`,
`Full-stack LLD and Development 4`).

**Currently mapped to NV Contests (Academy):**
- Data Structure Algorithms 1, 2, 3, 4
- Advanced DSA 1, 2, 3, 4
- DSA 4.2
- DSA for Competitive Programming
- Full-stack LLD and Development 4
- Introduction to Problem Solving (Intermediate) 1
- Data Engineering
- Backend Project (fallback)

**Currently mapped to NV Contests (DSML):**
- Data Analytics and Visualisation - Fundamentals
- Data Analytics and Visualisation - Probability and Stats
- Data Analytics and Visualisation - Python Libraries

### Adding a new module

1. Open `data/Library__All_Programs.xlsx`.
2. Find the sheet for the program.
3. Add a row: `Module Name | CCT Library Name`.
   - Use `NV Contests` if the class is in the NV Contests library.
   - Use the exact CCT library name otherwise.
4. Run a quick test (see below) to confirm.

---

## Test runner

`test_runner.py` runs the full contest creation flow (without Hire Test, without
tracker writes) across all modules in the Excel sheet and records results to the
`agent testing` tab in the Google Sheet.

```bash
# All programs, all modules
python3 test_runner.py

# Specific program only
python3 test_runner.py --programs academy

# Single module
python3 test_runner.py --programs academy --module "Advanced DSA 1"

# Re-run only modules that failed in the last test run
python3 test_runner.py --failed-only

# Skip browser (library/config validation only)
python3 test_runner.py --no-browser
```

---

## Error handling

| Error | Cause | Fix |
|---|---|---|
| `LibraryNotFoundError` | Module not in Excel and not in CCT dropdown | Add to Excel or use `--library-name` |
| `AmbiguousLibraryError` | Module has duplicate rows in Excel | Remove duplicate rows |
| `BrowserStepError: class not found` | Class name in CCT doesn't match module name | Check exact class name in CCT, update Excel preferred name |
| `BrowserStepError: library not found` | Library name in Excel no longer exists in CCT | Update Excel to correct library name |
| `BrowserStepError: Confirm & Schedule timeout` | CCT page load issue | Retry — usually transient |
| `DuplicateContestError` | Batch already exists | Use `--overwrite-tracker` or rename |

On any browser failure, a screenshot is saved to `screenshots/` automatically.

---

## Deployment

### Primary: Mac + ngrok static domain

The app runs on a Mac and is exposed to the ~15-person team via a permanent
ngrok tunnel. The URL never changes between restarts.

**One-time setup**

```bash
# 1. Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env                         # edit APP_PASSWORD, GOOGLE_SHEET_ID
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# secrets.toml needs: APP_PASSWORD + SESSION_SECRET (see file for instructions)

# 3. Capture Scaler session
python3 capture_login.py
# A headed browser opens → confirm admin batches page is visible → Enter
# Confirm CCT page loads → Enter
# Session saved to data/storage_state.json
```

**Daily start**

```bash
./start.sh
```

Starts Streamlit on port 8501 and the ngrok tunnel. Both processes log to
`logs/streamlit.log` and `logs/ngrok.log`. Press `Ctrl+C` to stop both.

```
Public URL:  https://shale-unfailing-backyard.ngrok-free.dev/
Local URL:   http://localhost:8501
```

**Share with teammates:** give them the public URL and the `APP_PASSWORD`.
The 7-day login cookie persists through page refreshes. No Scaler account needed.

**Keep the Mac awake:** use Amphetamine (free, App Store) or
`System Settings → Battery → Prevent automatic sleeping` so the tunnel
stays up while the Mac is plugged in but idle.

**Auto-start on Mac login (optional)**

```bash
# Update the path in the plist if your project is in a different location
cp launchd/com.contestagent.app.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.contestagent.app.plist
```

To stop auto-start: `launchctl unload ~/Library/LaunchAgents/com.contestagent.app.plist`

**Session refresh routine**

The Scaler session cookie (`data/storage_state.json`) is valid for weeks but
will eventually expire. The app shows "Auth: last refreshed X ago" below the
nav bar. When runs start failing with "session expired":

```bash
python3 capture_login.py   # browser opens, confirm pages, Enter twice
./start.sh                 # restart the app (picks up the new session)
```

**Config reference (`.env`):**

| Variable | Default | Purpose |
|---|---|---|
| `NGROK_DOMAIN` | `shale-unfailing-backyard.ngrok-free.dev` | ngrok static domain |
| `STREAMLIT_PORT` | `8501` | local port |
| `APP_PASSWORD` | _(none)_ | login gate password |
| `GOOGLE_SHEET_ID` | _(none)_ | Google Sheet tracker (optional) |
| `HEADLESS` | `true` | run browser in background |

---

### Dormant alternative: Streamlit Community Cloud

> **Not currently in use.** Scaler invalidates session cookies when they are
> replayed from a second network location — cookies captured locally work fine
> locally but die within seconds when used from Cloud's Linux servers. Until
> Scaler supports service-account or API-based auth, Cloud hosting is not viable.
>
> The bootstrap code (`_bootstrap_storage_state`, `_bootstrap_cloud_config`,
> `_build_credentials`) is kept in the codebase and is harmless locally. It
> activates automatically if `STORAGE_STATE_B64` / `GOOGLE_CREDS_B64` secrets
> are set — so if an internal VM becomes available, pointing to it should work.

If you ever retry Community Cloud deployment:
1. Run `capture_login.py`, copy the printed `STORAGE_STATE_B64 = "eyJ..."` line
2. In Streamlit Cloud → Settings → Secrets, add all keys from `secrets.toml.example`
3. Be aware that sessions will likely expire immediately due to Scaler's
   IP-based session binding

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Scaler session expired" | `storage_state.json` is stale | `python3 capture_login.py` → restart app |
| "Session limit reached" — auto-recovers | Scaler's 2-session limit hit | Usually self-resolves; if not, log out an old browser tab at scaler.com |
| App unreachable at public URL | Mac asleep or ngrok tunnel down | Wake Mac, check `./start.sh` is running |
| `ERR_NGROK_334` on start | Previous ngrok process still alive (local or cloud-side) | `./start.sh` now runs `killall ngrok` + 5 s wait; if it still fails, `killall ngrok && sleep 5 && ./start.sh` |
| "run in progress" banner | Previous run didn't finish | Wait 15 min (stale-lock timeout) or `rm data/run.lock` |
| `LibraryNotFoundError` | Module not in Library Excel | Add a row to `data/Library__All_Programs.xlsx` or use Library Override |
| `AmbiguousLibraryError` | Module has duplicate rows | Remove duplicate from Excel |
| `TrackerUpdateError` | Google Sheets credentials missing | Check `data/service_account.json` exists and is shared on the Sheet |
