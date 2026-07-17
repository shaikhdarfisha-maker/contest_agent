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

### Dashboard

```bash
streamlit run streamlit_app.py
```

### Public URL via ngrok

To share the dashboard externally (e.g. for the ops team), run:

```bash
./start.sh
```

This starts Streamlit on port 8501 and opens a permanent ngrok tunnel at:

**https://shale-unfailing-backyard.ngrok-free.dev/**

Both services stop together when you press `Ctrl+C`. The domain is static —
the URL never changes between restarts.

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

- **Headless:** set `HEADLESS=true` in `.env`. Run under cron or a CI job.
  Persist `data/storage_state.json` as a secret/volume so SSO isn't re-scripted.
- **Re-auth:** the session cookie expires periodically. Re-run `setup_auth.py`
  when the agent starts logging in redirects.
- **Streamlit Cloud:** set all `.env` variables as Streamlit secrets. The
  `data/` workbooks must be present in the repo or mounted as a volume.
