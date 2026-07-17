"""
streamlit_app.py
================
Dashboard for the Contest Agent — Scaler-themed UI.
"""

from __future__ import annotations

import json
from datetime import datetime, date, time

import streamlit as st

from config import APP_PASSWORD, DEFAULT_PROGRAM, GOOGLE_SHEET_ID, PROGRAMS, next_slot_datetime
from modules.library_reader import LibraryReader
from modules.metadata_store import MetadataStore
from modules.orchestrator import create_contest
from modules.tracker import ContestTracker
from modules.utils import derive_attempt_windows_by_count

st.set_page_config(
    page_title="NV Contest Agent",
    page_icon="https://www.scaler.com/favicon.ico",
    layout="wide",
)

# --------------------------------------------------------------------------- #
# Scaler-themed CSS
# --------------------------------------------------------------------------- #
st.html("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
  #MainMenu, footer, header { visibility: hidden; }
  .stApp { background-color: #F5F6FA; }
  .scaler-nav {
    background: #1A1A2E; padding: 12px 32px; display: flex;
    align-items: center; justify-content: space-between;
    margin: -1rem -1rem 2rem -1rem; border-bottom: 3px solid #FF6B2B;
  }
  .scaler-nav img { height: 32px; }
  .scaler-nav-title { color: #FFF; font-size: 16px; font-weight: 600; letter-spacing: 0.3px; }
  .scaler-nav-right { color: #94A3B8; font-size: 13px; }
  .scaler-card {
    background: #FFF; border-radius: 12px; border: 1px solid #E2E8F0;
    padding: 24px 28px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }
  .scaler-card-title {
    font-size: 14px; font-weight: 600; color: #64748B; text-transform: uppercase;
    letter-spacing: 0.8px; margin-bottom: 16px; padding-bottom: 10px;
    border-bottom: 1px solid #F1F5F9;
  }
  .section-badge {
    display: inline-block; background: #FFF0E8; color: #FF6B2B; font-size: 11px;
    font-weight: 700; padding: 3px 10px; border-radius: 20px; letter-spacing: 0.5px;
    text-transform: uppercase; margin-bottom: 12px;
  }
  .stButton > button[kind="primary"] {
    background: #FF6B2B !important; border: none !important; border-radius: 8px !important;
    color: white !important; font-weight: 600 !important; font-family: 'Inter', sans-serif !important;
    padding: 10px 24px !important; font-size: 14px !important; transition: background 0.2s !important;
  }
  .stButton > button[kind="primary"]:hover { background: #E85D20 !important; }
  .stButton > button {
    border-radius: 8px !important; font-family: 'Inter', sans-serif !important;
    font-size: 14px !important; font-weight: 500 !important;
  }
  .stTextInput > div > div > input, .stSelectbox > div > div, .stDateInput > div > div > input {
    border-radius: 8px !important; border-color: #CBD5E1 !important;
    font-family: 'Inter', sans-serif !important; font-size: 14px !important;
  }
  .stTabs [data-baseweb="tab-list"] { background: transparent; border-bottom: 2px solid #E2E8F0; gap: 0; }
  .stTabs [data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important; font-weight: 500; font-size: 14px;
    color: #64748B; padding: 10px 24px; border-radius: 0;
  }
  .stTabs [aria-selected="true"] { color: #FF6B2B !important; border-bottom: 2px solid #FF6B2B !important; font-weight: 600 !important; }
  .step-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; font-size: 14px; color: #475569; border-bottom: 1px solid #F8FAFC; }
  .chip-success { background:#DCFCE7; color:#166534; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
  .chip-fail    { background:#FEE2E2; color:#991B1B; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
  .chip-planned { background:#FEF9C3; color:#854D0E; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
  .stDataFrame { border-radius: 8px; overflow: hidden; }
  thead tr th { background: #F8FAFC !important; font-size: 12px !important; color: #64748B !important; font-weight: 600 !important; }
  hr { border-color: #E2E8F0; margin: 20px 0; }
</style>
""")

_DEFAULT_LIB = "— NV Contests (default) —"
_SCALER_LOGO = "https://www.scaler.com/storyblok-assets/f/290352327034910/190x40/762eb27df8/scaler-logo.svg"


# --------------------------------------------------------------------------- #
# Cached loaders
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
# Nav bar
# --------------------------------------------------------------------------- #
def _nav(show_signout: bool = False) -> None:
    signout_html = ""
    if show_signout and APP_PASSWORD:
        signout_html = '<span class="scaler-nav-right">NV Contest Agent &nbsp;|&nbsp; <a href="?signout=1" style="color:#FF6B2B;text-decoration:none;">Sign out</a></span>'

    st.markdown(f"""
    <div class="scaler-nav">
      <div style="display:flex;align-items:center;gap:16px;">
        <img src="{_SCALER_LOGO}" alt="Scaler" onerror="this.style.display='none'">
        <span class="scaler-nav-title">NV Contest Agent</span>
      </div>
      {signout_html}
    </div>
    """, unsafe_allow_html=True)

# Handle sign-out via query param
if st.query_params.get("signout") == "1":
    st.session_state["authenticated"] = False
    st.query_params.clear()
    st.rerun()

# --------------------------------------------------------------------------- #
# Login gate
# --------------------------------------------------------------------------- #
if APP_PASSWORD and not st.session_state.get("authenticated"):
    _nav()
    st.markdown("""
    <div style="max-width:400px;margin:60px auto;">
      <div class="scaler-card">
        <div style="text-align:center;margin-bottom:24px;">
          <div style="font-size:22px;font-weight:700;color:#1A1A2E;">Sign in</div>
          <div style="color:#64748B;font-size:14px;margin-top:4px;">NV Contest Agent</div>
        </div>
    """, unsafe_allow_html=True)
    with st.form("login_form"):
        password = st.text_input("Password", type="password", label_visibility="collapsed",
                                 placeholder="Enter password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    st.markdown("</div></div>", unsafe_allow_html=True)
    if submitted:
        if password == APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

_nav(show_signout=True)

# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #
tab_create, tab_history = st.tabs(["  Create Contest  ", "  Run History  "])


# --------------------------------------------------------------------------- #
# Tab 1 — Create Contest
# --------------------------------------------------------------------------- #
with tab_create:
    pending = st.session_state.get("pending")

    # ── CONFIRMATION PREVIEW ────────────────────────────────────────────────
    if pending:
        windows = derive_attempt_windows_by_count(pending["start_dt"], num_attempts=4)

        st.markdown('<div class="section-badge">Review</div>', unsafe_allow_html=True)
        st.markdown('<div class="scaler-card"><div class="scaler-card-title">Contest Details</div>',
                    unsafe_allow_html=True)

        p1, p2 = st.columns([1, 1])
        with p1:
            st.markdown(f"**Batch Name** &nbsp; {pending['contest_name']}")
            st.markdown(f"**Module** &nbsp; {pending['module']}")
            st.markdown(f"**Program** &nbsp; {pending['program'].upper()}")
            st.markdown(f"**Library** &nbsp; {pending['library_override'] or 'NV Contests (default)'}")
            st.markdown(f"**Start** &nbsp; {pending['start_dt'].strftime('%d %b %Y, %I:%M %p')}")
        with p2:
            st.markdown("**Attempt Windows**")
            st.table([{
                "Attempt":  w.label,
                "Start":    w.start.strftime("%d %b %Y"),
                "End":      w.end.strftime("%d %b %Y"),
                "Duration": f"{(w.end - w.start).days}d",
            } for w in windows])

        st.markdown("</div>", unsafe_allow_html=True)

        btn_confirm, btn_edit, _ = st.columns([1, 1, 5])
        confirmed = btn_confirm.button("Confirm & Create", type="primary")
        cancelled = btn_edit.button("Edit")

        if cancelled:
            st.session_state.pop("pending", None)
            st.rerun()

        if confirmed:
            steps = {
                "library":     "Reading Library",
                "plan":        "Planning Windows",
                "batch":       "Creating Batch",
                "schedule":    "Scheduling Class",
                "hire_update": "Updating Hire Test",
                "tracker":     "Updating Tracker",
                "done":        "Completed",
            }
            placeholders = {k: st.empty() for k in steps}
            for k, label in steps.items():
                placeholders[k].markdown(
                    f'<div class="step-row">⬜ &nbsp; {label}</div>', unsafe_allow_html=True
                )

            def progress(step: str, msg: str, ok: bool) -> None:
                if step in placeholders:
                    icon = "✅" if ok else "❌"
                    color = "#166534" if ok else "#991B1B"
                    placeholders[step].markdown(
                        f'<div class="step-row">{icon} &nbsp; <span style="color:{color}">{steps[step]}</span></div>',
                        unsafe_allow_html=True,
                    )

            with st.spinner("Running automation…"):
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
                st.markdown("""
                <div style="background:#DCFCE7;border:1px solid #86EFAC;border-radius:10px;
                            padding:16px 20px;margin:16px 0;color:#166534;font-weight:600;font-size:15px;">
                  ✅ &nbsp; Contest Successfully Created
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="background:#FEE2E2;border:1px solid #FCA5A5;border-radius:10px;
                            padding:16px 20px;margin:16px 0;color:#991B1B;font-size:14px;">
                  ❌ &nbsp; <strong>Failed:</strong> {outcome.error}
                </div>""", unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="scaler-card"><div class="scaler-card-title">Summary</div>',
                            unsafe_allow_html=True)
                st.json({
                    "Batch Name":         outcome.batch_name,
                    "Library Used":       outcome.library_used,
                    "Contest ID":         outcome.contest_id,
                    "Test IDs":           outcome.test_ids,
                    "Tracker Row":        outcome.tracker_row,
                    "Execution Time (s)": outcome.execution_seconds,
                })
                st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                if outcome.windows:
                    st.markdown('<div class="scaler-card"><div class="scaler-card-title">Attempt Windows</div>',
                                unsafe_allow_html=True)
                    st.table([{
                        "Attempt":  w.label,
                        "Start":    w.start.strftime("%d %b %Y %H:%M"),
                        "End":      w.end.strftime("%d %b %Y %H:%M"),
                        "Duration": f"{(w.end - w.start).days}d",
                    } for w in outcome.windows])
                    st.markdown("</div>", unsafe_allow_html=True)

            _suggest_name.clear()

    # ── INPUT FORM ──────────────────────────────────────────────────────────
    else:
        st.markdown('<div class="section-badge">New Contest</div>', unsafe_allow_html=True)
        st.markdown('<div class="scaler-card"><div class="scaler-card-title">Contest Details</div>',
                    unsafe_allow_html=True)

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
            st.markdown(
                f'<div style="font-size:12px;color:#64748B;margin:-8px 0 8px;">Suggested: '
                f'<strong style="color:#FF6B2B">{suggested_name}</strong></div>',
                unsafe_allow_html=True,
            )

        with st.form("contest_form"):
            col1, col2 = st.columns(2)
            with col1:
                contest_name = st.text_input(
                    "Contest / Batch Name",
                    value=suggested_name,
                    placeholder="Advanced DSA 4 July Contest",
                )
                _next_slot = next_slot_datetime()
                _default_time = "9:00 PM" if _next_slot.hour == 21 else "7:00 AM"
                start_date = st.date_input("Contest Start Date", value=_next_slot.date())
                time_choice = st.radio(
                    "Contest Start Time",
                    options=["9:00 PM", "7:00 AM"],
                    index=0 if _default_time == "9:00 PM" else 1,
                    horizontal=True,
                )
                start_time = time(21, 0) if time_choice == "9:00 PM" else time(7, 0)
            with col2:
                lib_options = [_DEFAULT_LIB] + _load_library_names()
                library_sel = st.selectbox("Library Override (optional)", options=lib_options)
                library_override = None if library_sel == _DEFAULT_LIB else library_sel

                st.markdown("<br>", unsafe_allow_html=True)
                next_dt = datetime.combine(start_date, start_time)
                st.markdown(
                    f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;'
                    f'padding:12px 16px;font-size:13px;color:#475569;">'
                    f'📅 &nbsp; <strong>Contest A1 starts:</strong><br>'
                    f'<span style="color:#1A1A2E;font-size:15px;font-weight:600;">'
                    f'{next_dt.strftime("%d %b %Y, %I:%M %p")}</span></div>',
                    unsafe_allow_html=True,
                )

            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("Preview & Confirm →", type="primary",
                                              use_container_width=False)

        st.markdown("</div>", unsafe_allow_html=True)

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
# Tab 2 — Run History
# --------------------------------------------------------------------------- #
with tab_history:
    st.markdown('<div class="section-badge">History</div>', unsafe_allow_html=True)

    hcol1, hcol2 = st.columns([6, 1])
    with hcol2:
        if st.button("Refresh", key="refresh_history"):
            st.cache_data.clear()

    rows = MetadataStore().recent_contests(limit=100)

    if not rows:
        st.markdown("""
        <div class="scaler-card" style="text-align:center;color:#94A3B8;padding:48px;">
          No contests have been created yet.
        </div>""", unsafe_allow_html=True)
    else:
        f1, f2, f3 = st.columns(3)
        with f1:
            prog_filter = st.multiselect("Program", options=sorted({r["program"] for r in rows}))
        with f2:
            status_filter = st.multiselect("Status", options=sorted({r["status"] for r in rows}))
        with f3:
            search = st.text_input("Search batch name", placeholder="DSA…")

        filtered = rows
        if prog_filter:
            filtered = [r for r in filtered if r["program"] in prog_filter]
        if status_filter:
            filtered = [r for r in filtered if r["status"] in status_filter]
        if search:
            filtered = [r for r in filtered if search.lower() in r["batch_name"].lower()]

        st.markdown(
            f'<div style="font-size:13px;color:#94A3B8;margin:8px 0 16px;">'
            f'Showing {len(filtered)} of {len(rows)} runs</div>',
            unsafe_allow_html=True,
        )

        for r in filtered:
            chip = {
                "created": '<span class="chip-success">Created</span>',
                "planned": '<span class="chip-planned">Planned</span>',
                "failed":  '<span class="chip-fail">Failed</span>',
            }.get(r["status"], r["status"])
            created_at = r["created_at"][:16].replace("T", " ")

            with st.expander(f"{r['batch_name']}  ·  {r['program'].upper()}  ·  {created_at}"):
                st.markdown(chip, unsafe_allow_html=True)
                d1, d2, d3 = st.columns(3)
                with d1:
                    st.markdown(f"**Module:** {r['module']}")
                    st.markdown(f"**Program:** {r['program'].upper()}")
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
                            st.markdown(f"- {w['label']}: {w['start'][:10]} → {w['end'][:10]}")
