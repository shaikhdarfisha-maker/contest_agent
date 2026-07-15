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

from config import APP_PASSWORD, DEFAULT_PROGRAM, PROGRAMS
from modules.orchestrator import create_contest
from modules.library_reader import LibraryReader
from modules.tracker import ContestTracker

_DEFAULT_LIB = "— NV Contests (default) —"


@st.cache_data
def _load_library_names() -> list[str]:
    try:
        return LibraryReader().all_library_names()
    except Exception:
        return []

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

# Program + module selectors live outside the form so the module list
# updates immediately when the program is changed.
sel_col1, sel_col2 = st.columns(2)
with sel_col1:
    program = st.selectbox(
        "Program",
        options=list(PROGRAMS.keys()),
        index=list(PROGRAMS.keys()).index(DEFAULT_PROGRAM),
    )
with sel_col2:
    @st.cache_data
    def _load_module_names(prog: str) -> list[str]:
        try:
            return LibraryReader().all_module_names(prog)
        except Exception:
            return []

    module_options = _load_module_names(program)
    module = st.selectbox(
        "Module Name",
        options=module_options,
        index=None,
        placeholder="Type to search…",
    )

# Suggest next contest name based on tracker history
@st.cache_data
def _suggest_name(mod: str) -> str:
    try:
        return ContestTracker().suggest_next_name(mod)
    except Exception:
        return mod

suggested_name = _suggest_name(module) if module else ""
if suggested_name:
    st.caption(f"Suggested contest name: **{suggested_name}**")

with st.form("contest_form"):
    col1, col2 = st.columns(2)
    with col1:
        contest_name = st.text_input(
            "Contest Name",
            value=suggested_name,
            placeholder="Advanced DSA 4 July Contest",
        )
        start_date = st.date_input("Contest Start Date", value=date.today())
        start_time = st.time_input("Contest Start Time", value=time(21, 0))
    with col2:
        lib_options = [_DEFAULT_LIB] + _load_library_names()
        library_sel = st.selectbox("Library override (optional)", options=lib_options)
        library_override = None if library_sel == _DEFAULT_LIB else library_sel

    submitted = st.form_submit_button("Create Contest", type="primary")

if submitted:
    if not module or not contest_name:
        st.error("Module Name and Contest Name are required.")
        st.stop()

    start_dt = datetime.combine(start_date, start_time)

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
            program=program,
            library_name=library_override,
            batch_name_override=contest_name,
            browser=True,
            dry_run_tracker=False,
            overwrite_tracker=True,
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
                {
                    "Attempt": w.label,
                    "Start": w.start.strftime("%d %b %Y %H:%M"),
                    "End": w.end.strftime("%d %b %Y %H:%M"),
                    "Duration": f"{(w.end - w.start).days} days",
                }
                for w in outcome.windows
            ]
        )
