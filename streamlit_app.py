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

from datetime import datetime, time

import streamlit as st

from config import APP_PASSWORD, DEFAULT_PROGRAM, PROGRAMS
from modules.orchestrator import create_contest

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
            "Library override (optional)", placeholder="Leave blank to use NV Contests"
        )
        end_date = st.date_input("Contest End Date")
        end_time = st.time_input("Contest End Time", value=time(21, 0))

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

    start_dt = datetime.combine(start_date, start_time)
    end_dt = datetime.combine(end_date, end_time)

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
        st.subheader("Attempt Windows")
        st.table(
            [
                {"Attempt": w.label, "Start": w.start, "End": w.end}
                for w in outcome.windows
            ]
        )
