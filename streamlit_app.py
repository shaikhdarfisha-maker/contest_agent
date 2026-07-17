"""
streamlit_app.py
================
Dashboard for the Contest Agent with a shared-password login gate.

Run with:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
from datetime import datetime, date, time

import streamlit as st

from config import APP_PASSWORD, DEFAULT_PROGRAM, GOOGLE_SHEET_ID, PROGRAMS
from modules.library_reader import LibraryReader
from modules.metadata_store import MetadataStore
from modules.orchestrator import create_contest
from modules.tracker import ContestTracker
from modules.utils import derive_attempt_windows_by_count

st.set_page_config(page_title="NV Contest Agent", page_icon="🎯", layout="wide")

_DEFAULT_LIB = "— NV Contests (default) —"


# --------------------------------------------------------------------------- #
# Cached data loaders
# --------------------------------------------------------------------------- #
@st.cache_data
def _load_library_names() -> list[str]:
    try:
        return LibraryReader().all_library_names()
    except Exception:
        return []


@st.cache_data
def _load_module_names(prog: str) -> list[str]:
    try:
        return LibraryReader().all_module_names(prog)
    except Exception:
        return []


@st.cache_data
def _suggest_name(mod: str, prog: str) -> str:
    try:
        if GOOGLE_SHEET_ID:
            from modules.google_tracker import GoogleContestTracker
            return GoogleContestTracker(program=prog).suggest_next_name(mod)
        return ContestTracker().suggest_next_name(mod)
    except Exception:
        return mod


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
# Header
# --------------------------------------------------------------------------- #
col_title, col_logout = st.columns([8, 1])
with col_title:
    st.title("🎯 Neovarsity Contest Creation Agent")
    st.caption("Automates batch creation → CCT scheduling → Hire Test → tracker update.")
with col_logout:
    if APP_PASSWORD and st.button("Sign out"):
        st.session_state["authenticated"] = False
        st.rerun()

tab_create, tab_history = st.tabs(["Create Contest", "Run History"])


# --------------------------------------------------------------------------- #
# Tab 1: Create Contest
# --------------------------------------------------------------------------- #
with tab_create:
    pending = st.session_state.get("pending")

    # ---- CONFIRMATION PREVIEW -------------------------------------------- #
    if pending:
        st.subheader("Review before creating")
        st.caption("Check the details below, then confirm to start the automation.")

        windows = derive_attempt_windows_by_count(
            pending["start_dt"], num_attempts=4
        )

        p1, p2 = st.columns(2)
        with p1:
            st.markdown(f"**Batch Name:** {pending['contest_name']}")
            st.markdown(f"**Module:** {pending['module']}")
            st.markdown(f"**Program:** {pending['program'].upper()}")
            st.markdown(f"**Library:** {pending['library_override'] or 'NV Contests (default)'}")
            st.markdown(f"**Start:** {pending['start_dt'].strftime('%d %b %Y %H:%M')}")
        with p2:
            st.markdown("**Attempt Windows:**")
            st.table([
                {
                    "Attempt":  w.label,
                    "Start":    w.start.strftime("%d %b %Y"),
                    "End":      w.end.strftime("%d %b %Y"),
                    "Duration": f"{(w.end - w.start).days}d",
                }
                for w in windows
            ])

        st.divider()
        btn_confirm, btn_edit = st.columns([1, 5])
        confirmed = btn_confirm.button("Confirm & Create", type="primary")
        cancelled = btn_edit.button("Edit")

        if cancelled:
            st.session_state.pop("pending", None)
            st.rerun()

        if confirmed:
            steps = {
                "library":    "Reading Library",
                "plan":       "Planning Windows",
                "batch":      "Creating Batch",
                "schedule":   "Scheduling Class",
                "hire_update":"Updating Hire Test",
                "tracker":    "Updating Tracker",
                "done":       "Completed",
            }
            placeholders = {k: st.empty() for k in steps}
            for k, label in steps.items():
                placeholders[k].markdown(f"⬜ {label}")

            def progress(step: str, msg: str, ok: bool) -> None:
                if step in placeholders:
                    icon = "✅" if ok else "❌"
                    placeholders[step].markdown(f"{icon} {steps[step]}")

            with st.spinner("Running workflow…"):
                outcome = create_contest(
                    module=pending["module"],
                    contest_name=pending["contest_name"],
                    start=pending["start_dt"],
                    program=pending["program"],
                    library_name=pending["library_override"],
                    batch_name_override=pending["contest_name"],
                    browser=True,
                    dry_run_tracker=False,
                    overwrite_tracker=True,
                    progress=progress,
                )

            st.session_state.pop("pending", None)

            if outcome.success:
                st.success("Contest Successfully Created")
            else:
                st.error(f"Failed: {outcome.error}")

            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Summary")
                st.json({
                    "Batch Name":         outcome.batch_name,
                    "Library Used":       outcome.library_used,
                    "Contest ID":         outcome.contest_id,
                    "Test IDs":           outcome.test_ids,
                    "Tracker Row":        outcome.tracker_row,
                    "Execution Time (s)": outcome.execution_seconds,
                })
            with c2:
                if outcome.windows:
                    st.subheader("Attempt Windows")
                    st.table([
                        {
                            "Attempt":  w.label,
                            "Start":    w.start.strftime("%d %b %Y %H:%M"),
                            "End":      w.end.strftime("%d %b %Y %H:%M"),
                            "Duration": f"{(w.end - w.start).days}d",
                        }
                        for w in outcome.windows
                    ])

            _suggest_name.clear()

    # ---- INPUT FORM ------------------------------------------------------- #
    else:
        # Program + module outside form so module list refreshes on program change
        sel_col1, sel_col2 = st.columns(2)
        with sel_col1:
            program = st.selectbox(
                "Program",
                options=list(PROGRAMS.keys()),
                index=list(PROGRAMS.keys()).index(DEFAULT_PROGRAM),
                key="form_program",
            )
        with sel_col2:
            module_options = _load_module_names(program)
            module = st.selectbox(
                "Module Name",
                options=module_options,
                index=None,
                placeholder="Type to search…",
                key="form_module",
            )

        suggested_name = _suggest_name(module, program) if module else ""
        if suggested_name:
            st.caption(f"Suggested: **{suggested_name}**")

        with st.form("contest_form"):
            col1, col2 = st.columns(2)
            with col1:
                contest_name = st.text_input(
                    "Contest Name",
                    value=suggested_name,
                    placeholder="Advanced DSA 4 July Contest",
                )
                start_date = st.date_input("Contest Start Date", value=date.today())
                time_choice = st.radio(
                    "Contest Start Time",
                    options=["9:00 PM", "7:00 AM"],
                    horizontal=True,
                )
                start_time = time(21, 0) if time_choice == "9:00 PM" else time(7, 0)
            with col2:
                lib_options = [_DEFAULT_LIB] + _load_library_names()
                library_sel = st.selectbox("Library override (optional)", options=lib_options)
                library_override = None if library_sel == _DEFAULT_LIB else library_sel

            submitted = st.form_submit_button("Preview & Confirm", type="primary")

        if submitted:
            if not module or not contest_name:
                st.error("Module Name and Contest Name are required.")
            else:
                st.session_state["pending"] = {
                    "module":           module,
                    "contest_name":     contest_name,
                    "program":          program,
                    "library_override": library_override,
                    "start_dt":         datetime.combine(start_date, start_time),
                }
                st.rerun()


# --------------------------------------------------------------------------- #
# Tab 2: Run History
# --------------------------------------------------------------------------- #
with tab_history:
    st.subheader("Run History")

    if st.button("Refresh", key="refresh_history"):
        st.cache_data.clear()

    rows = MetadataStore().recent_contests(limit=100)

    if not rows:
        st.info("No contests have been created yet.")
    else:
        # Filters
        f1, f2, f3 = st.columns(3)
        with f1:
            prog_filter = st.multiselect(
                "Program", options=sorted({r["program"] for r in rows})
            )
        with f2:
            status_filter = st.multiselect(
                "Status", options=sorted({r["status"] for r in rows})
            )
        with f3:
            search = st.text_input("Search batch name", placeholder="DSA…")

        filtered = rows
        if prog_filter:
            filtered = [r for r in filtered if r["program"] in prog_filter]
        if status_filter:
            filtered = [r for r in filtered if r["status"] in status_filter]
        if search:
            filtered = [r for r in filtered if search.lower() in r["batch_name"].lower()]

        st.caption(f"Showing {len(filtered)} of {len(rows)} runs")

        for r in filtered:
            status_icon = {"created": "✅", "planned": "🕐", "failed": "❌"}.get(r["status"], "•")
            created_at = r["created_at"][:16].replace("T", " ")

            with st.expander(
                f"{status_icon}  {r['batch_name']}   —   {r['program'].upper()}   —   {created_at}"
            ):
                d1, d2, d3 = st.columns(3)
                with d1:
                    st.markdown(f"**Module:** {r['module']}")
                    st.markdown(f"**Program:** {r['program'].upper()}")
                    st.markdown(f"**Status:** {r['status']}")
                    st.markdown(f"**Library:** {r['library_name'] or '—'}")
                with d2:
                    st.markdown(f"**Contest ID:** {r['contest_id'] or '—'}")
                    test_ids = json.loads(r["test_ids_json"] or "[]")
                    st.markdown(f"**Test IDs:** {', '.join(test_ids) or '—'}")
                    st.markdown(f"**Tracker Row:** {r['tracker_row'] or '—'}")
                    st.markdown(f"**Created:** {created_at}")
                with d3:
                    windows = json.loads(r["windows_json"] or "[]")
                    if windows:
                        st.markdown("**Attempt Windows:**")
                        for w in windows:
                            start = w["start"][:10]
                            end = w["end"][:10]
                            st.markdown(f"- {w['label']}: {start} → {end}")
