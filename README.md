# Neovarsity Contest Creation Agent

An AI operations agent that automates the end-to-end Neovarsity contest
creation workflow across four systems — Admin V2, the Classroom Creation Tool
(CCT), Hire Test, and the NV Contest Tracker — from four operator inputs.

The operator supplies only:

- **Module Name** (e.g. `Advanced DSA 4`)
- **Contest Name**
- **Contest Start Date/Time**
- **Contest End Date/Time**

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
 ┌────────────────┐  System 2: CCT       → schedule class,
 │schedule_creator│   View Schedule → Add Questions (→ Hire Test)
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
 │ metadata_store│   (kept OUT of the production tracker)
 └───────────────┘
```

The `orchestrator` wires these together; `app.py` (CLI) and `streamlit_app.py`
(dashboard) are thin front-ends over it.

### Key business rules (inferred from the supplied files)

- **Naming convention:** `"{Module}: NV Contest {Month} {Year}"`
  (e.g. `Advanced DSA 4: NV Contest June 2026`), confirmed against both the CCT
  screenshot and existing tracker rows.
- **Library lookup is program-scoped.** The operator picks the program
  (`academy` / `devops` / …); the reader uses the matching sheet. When a module
  still maps to multiple libraries, a non-deprecated ("Live") row is preferred,
  otherwise the run stops and asks for an explicit `--library-name`.
- **A "contest" is four linked tests** (Contest + Re-attempt 1/2/3). The
  operator enters only the **A1** window; the rest are derived:
  - A2: starts when A1 ends (snapped to 00:00), runs **7 days**
  - A3: starts when A2 ends, runs **9 days**
  - A4: starts when A3 ends, runs **10 days**

  These durations are config (`REATTEMPT_A*_DAYS`). The defaults reproduce the
  `Advanced DSA 4` Group Contest Summary exactly (25 May → 4 Jun → 11 Jun →
  20 Jun → 30 Jun).
- **The tracker is treated as the source of truth.** The agent appends a row
  using only the manually-entered columns (Module, Batch Name, the four
  start/end datetimes), mirrors the existing `CONCATENATE` batch-name formula
  style, and replicates the K–N formula columns re-pointed to the new row. It
  **never** adds columns or overwrites formulas, and it backs the workbook up
  before every write. All internal IDs/timestamps/errors go to SQLite instead.

---

## Project structure

```
contest_agent/
├── app.py                 # CLI entrypoint
├── streamlit_app.py       # Optional dashboard
├── setup_auth.py          # One-time SSO session capture
├── smoke_test.py          # Non-browser core tests (run against real data)
├── config.py              # All settings (env-overridable)
├── modules/
│   ├── browser.py         # Playwright lifecycle, auth reuse, error screenshots
│   ├── library_reader.py  # module → library resolution
│   ├── batch_creator.py   # System 1: Admin V2
│   ├── schedule_creator.py# System 2: CCT + reach Hire Test
│   ├── hire_test.py       # System 3: date update + verify
│   ├── tracker.py         # System 4: schema-preserving append
│   ├── metadata_store.py  # SQLite bookkeeping
│   ├── orchestrator.py    # End-to-end coordination
│   ├── logger.py          # Console + per-run file logging
│   └── utils.py           # Exceptions, retry, datetime + window derivation
├── logs/                  # Per-run log files
├── screenshots/           # Error screenshots
├── data/                  # Workbooks + SQLite + auth state
├── requirements.txt
├── .env.example
└── README.md
```

---

## Installation

```bash
cd contest_agent
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium                            # browser binaries
cp .env.example .env                                   # then edit paths/URLs
```

Place (or point `.env` at) the two workbooks:
`Library__All_Programs.xlsx` and `NV_contests_Tracker_Q2-2026_.xlsx`.

---

## Usage

### Verify the core first (no browser, no writes)

```bash
python smoke_test.py
```

### One-time auth

```bash
python setup_auth.py        # log in to Scaler, press Enter to save the session
```

### CLI

```bash
# Full run
python app.py --module "Advanced DSA 4" \
              --contest-name "Advanced DSA 4 July Contest" \
              --start "2026-07-20 21:00" --end "2026-07-30 21:00"

# Safe rehearsal: resolve + plan + tracker dry-run, no browser
python app.py --module "Advanced DSA 4" --contest-name x \
              --start "2026-07-20 21:00" --end "2026-07-30 21:00" \
              --no-browser --dry-run-tracker

# DevOps program
python app.py --module "AWS 1" --program devops --contest-name "AWS 1 Contest" \
              --start "2026-07-01 21:00" --end "2026-07-15 21:00"
```

Accepted date formats include `2026-07-20 21:00`, `2026-07-20T21:00`,
`Jul 20 2026 09:00 PM`, and `20 Jul 2026, Mon, 9:00 pm`.

### Dashboard

```bash
streamlit run streamlit_app.py
```

---

## Completing the browser selectors

The supplied screenshots cover the CCT edit page and the Hire Test settings
page, so those flows are built concretely. The exact form selectors on the
**Admin V2 create-batch** form and the **CCT Schedule Classes** form are only
visible in the workflow video, so they are left as clearly-marked
`# TODO[selector]` placeholders with notes on what to capture.

To fill them in:

```bash
playwright codegen https://www.scaler.com/admin/academy/v2/batches
playwright codegen https://www.scaler.com/scm/classes/schedule-classes
```

Search the codebase for `TODO[selector]` and replace each placeholder locator
with the recorded one. No other code needs to change.

---

## Error handling

Handled with typed exceptions, retries (linear backoff, `MAX_RETRIES`), and an
auto screenshot on browser failure:

- Library not found / ambiguous → `LibraryNotFoundError` / `AmbiguousLibraryError`
- Duplicate batch/contest → `DuplicateContestError` (checked in both SQLite and
  the tracker, formula-aware)
- Browser step failures (session expired, dropdown not loaded, nav timeout) →
  `BrowserStepError`, retried, screenshot captured
- Tracker write issues → `TrackerUpdateError`, workbook backed up pre-write

---

## Deployment suggestions

- **Scheduled / headless:** set `HEADLESS=true`, run `app.py` under cron or a CI
  job; persist `storage_state.json` as a secret/volume so SSO isn't re-scripted.
- **Containerise** with the official Playwright image
  (`mcr.microsoft.com/playwright/python`) to get browser deps preinstalled.
- **Tracker concurrency:** the tracker is last-write-wins on a file; run a
  single agent instance, or migrate the tracker to Google Sheets API and swap
  the `tracker` module if multiple writers are needed.
- **Secrets** via environment, never committed `.env`.

## Future enhancements (architecture already supports)

- **Bulk creation** — `orchestrator.run` is per-request; wrap a list of
  `ContestRequest`s for "Create all July contests."
- **Recreate expired contests** — read the tracker's `Contest Status` column,
  filter `Expired`, and re-run those modules.
- **Expiry monitoring + reminders** — a scheduled job over the tracker/SQLite.
- **Duplicate detection** — already implemented; extendable to fuzzy matches.
- **Natural-language commands** — map intents like "Create Advanced DSA 4
  contest" onto `create_contest(...)`.
