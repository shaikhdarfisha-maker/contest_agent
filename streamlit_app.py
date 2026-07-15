"""
streamlit_app.py
================
Optional dashboard for the Contest Agent.

Run with:
    streamlit run streamlit_app.py

Provides the four operator inputs (Module, Contest Name, Start, End), a program
selector, safety toggles (skip browser / dry-run tracker), and a live progress
checklist that updates as each workflow step completes.
"""

from __future__ import annotations

from datetime import datetime, time

import streamlit as st

from config import DEFAULT_PROGRAM, PROGRAMS
from modules.orchestrator import create_contest

st.set_page_config(page_title="NV Contest Agent", page_icon="🎯", layout="centered")
st.title("🎯 Neovarsity Contest Creation Agent")
st.caption("Automates batch creation → CCT scheduling → Hire Test → tracker update.")

with st.form("contest_form"):
    col1, col2 = st.columns(2)
    with col1:
        module = st.text_input("Module Name", placeholder="Advanced DSA 4")
        program = st.selectbox(
            "Program", options=list(PROGRAMS.keys()), index=list(PROGRAMS.keys()).index(DEFAULT_PROGRAM)
        )
        start_date = st.date_input("Contest Start Date")
        start_time = st.time_input("Contest Start Time", value=time(21, 0))
    with col2:
        contest_name = st.text_input("Contest Name", placeholder="Advanced DSA 4 July Contest")
        library_override = st.text_input(
            "Library override (optional)", placeholder="Leave blank to auto-resolve"
        )
        end_date = st.date_input("Contest End Date")
        end_time = st.time_input("Contest End Time", value=time(21, 0))

    c1, c2 = st.columns(2)
    with c1:
        skip_browser = st.checkbox("Skip browser steps (Excel-only)", value=False)
    with c2:
        dry_run = st.checkbox("Dry-run tracker (don't write)", value=False)

    submitted = st.form_submit_button("Create Contest", type="primary")

if submitted:
    if not module or not contest_name:
        st.error("Module Name and Contest Name are required.")
        st.stop()

    start_dt = datetime.combine(start_date, start_time)
    end_dt = datetime.combine(end_date, end_time)

    # Live checklist scaffold.
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
            end=end_dt,
            program=program,
            library_name=library_override or None,
            browser=not skip_browser,
            dry_run_tracker=dry_run,
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
        st.subheader("Attempt Windows")
        st.table(
            [
                {"Attempt": w.label, "Start": w.start, "End": w.end}
                for w in outcome.windows
            ]
        )
