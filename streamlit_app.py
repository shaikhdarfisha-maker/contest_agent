"""
streamlit_app.py
================
Dashboard for the Contest Agent with a shared-password login gate.

Run with:
    streamlit run streamlit_app.py

Set APP_PASSWORD in .env (or environment) to enable the login screen.
If APP_PASSWORD is empty, the login screen is skipped.
"""

from __future__ import annotations

from datetime import datetime, date, time

import streamlit as st

from config import APP_PASSWORD, ATTEMPT_DURATIONS, DEFAULT_PROGRAM, PROGRAMS
from modules.orchestrator import create_contest
from modules.utils import derive_attempt_windows_by_count

st.set_page_config(page_title="NV Contest Agent", page_icon="🎯", layout="centered")


# --------------------------------------------------------------------------- #
# Login gate
# --------------------------------------------------------------------------- #
def _login_screen() -> None:
    st.title("🎯 NV Contest Agent")
    st.subheader("Sign in")
    with st.form("login_form"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        if password == APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")


if APP_PASSWORD and not st.session_state.get("authenticated"):
    _login_screen()
    st.stop()


# --------------------------------------------------------------------------- #
# Main app
# --------------------------------------------------------------------------- #
col_title, col_logout = st.columns([6, 1])
with col_title:
    st.title("🎯 Neovarsity Contest Creation Agent")
    st.caption("Automates batch creation → CCT scheduling → Hire Test → tracker update.")
with col_logout:
    if APP_PASSWORD and st.button("Sign out"):
        st.session_state["authenticated"] = False
        st.rerun()

# --------------------------------------------------------------------------- #
# Live windows preview (outside form so it re-renders on widget change)
# --------------------------------------------------------------------------- #
_DURATION_LABELS = {
    1: "1 attempt — contest only (30 days)",
    2: "2 attempts — contest + 1 re-attempt (15 days each)",
    3: "3 attempts — contest + 2 re-attempts (7 days each)",
    4: "4 attempts — contest + 3 re-attempts (7 days each)",
}

col_a, col_b = st.columns(2)
with col_a:
    num_attempts = st.selectbox(
        "Number of Attempts",
        options=[1, 2, 3, 4],
        index=3,
        format_func=lambda n: _DURATION_LABELS[n],
    )
    preview_start_date = st.date_input(
        "Contest Start Date", value=date.today(), key="preview_date"
    )
with col_b:
    preview_start_time = st.time_input(
        "Contest Start Time", value=time(21, 0), key="preview_time"
    )

preview_dt = datetime.combine(preview_start_date, preview_start_time)
preview_windows = derive_attempt_windows_by_count(preview_dt, num_attempts)

st.caption("**Computed windows** (auto-calculated from start date + attempt count):")
st.table(
    [
        {
            "Attempt": w.label,
            "Start": w.start.strftime("%d %b %Y %H:%M"),
            "End": w.end.strftime("%d %b %Y %H:%M"),
            "Duration": f"{(w.end - w.start).days} days",
        }
        for w in preview_windows
    ]
)

st.divider()

# --------------------------------------------------------------------------- #
# Contest form
# --------------------------------------------------------------------------- #
with st.form("contest_form"):
    col1, col2 = st.columns(2)
    with col1:
        module = st.text_input("Module Name", placeholder="Advanced DSA 4")
        program = st.selectbox(
            "Program", options=list(PROGRAMS.keys()), index=list(PROGRAMS.keys()).index(DEFAULT_PROGRAM)
        )
    with col2:
        contest_name = st.text_input("Contest Name", placeholder="Advanced DSA 4 July Contest")
        library_override = st.text_input(
            "Library override (optional)", placeholder="Leave blank to use NV Contests"
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        skip_browser = st.checkbox("Skip browser steps (Excel-only)", value=False)
    with c2:
        dry_run = st.checkbox("Dry-run tracker (don't write)", value=False)
    with c3:
        overwrite = st.checkbox("Overwrite tracker row", value=False)

    submitted = st.form_submit_button("Create Contest", type="primary")

if submitted:
    if not module or not contest_name:
        st.error("Module Name and Contest Name are required.")
        st.stop()

    start_dt = datetime.combine(preview_start_date, preview_start_time)

    steps = {
        "library": "Reading Library",
        "plan": "Planning Windows",
        "batch": "Creating Batch",
        "schedule": "Scheduling Class",
        "hire_update": "Updating Hire Test",
        "tracker": "Updating Tracker",
        "done": "Completed",
    }
    placeholders = {k: st.empty() for k in steps}
    for k, label in steps.items():
        placeholders[k].markdown(f"⬜ {label}")

    def progress(step: str, msg: str, ok: bool) -> None:
        if step in placeholders:
            icon = "✅" if ok else "❌"
            placeholders[step].markdown(f"{icon} {steps[step]}")

    with st.spinner("Running workflow..."):
        outcome = create_contest(
            module=module,
            contest_name=contest_name,
            start=start_dt,
            end=None,
            num_attempts=num_attempts,
            program=program,
            library_name=library_override or None,
            batch_name_override=contest_name,
            browser=not skip_browser,
            dry_run_tracker=dry_run,
            overwrite_tracker=overwrite,
            progress=progress,
        )

    if outcome.success:
        st.success("Contest Successfully Created")
    else:
        st.error(f"Failed: {outcome.error}")

    st.subheader("Summary")
    st.json(
        {
            "Batch Name": outcome.batch_name,
            "Library Used": outcome.library_used,
            "Contest ID": outcome.contest_id,
            "Test IDs": outcome.test_ids,
            "Tracker Row": outcome.tracker_row,
            "Execution Time (s)": outcome.execution_seconds,
        }
    )

    if outcome.windows:
        st.subheader("Attempt Windows (actual)")
        st.table(
            [
                {
                    "Attempt": w.label,
                    "Start": w.start.strftime("%d %b %Y %H:%M"),
                    "End": w.end.strftime("%d %b %Y %H:%M"),
                    "Duration": f"{(w.end - w.start).days} days",
                }
                for w in outcome.windows
            ]
        )
