"""
streamlit_app.py — NV Contest Agent dashboard (Scaler-themed).
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import os
import re
import secrets as _secrets
import time as _time
from collections import OrderedDict
from datetime import datetime, time
from pathlib import Path
from typing import Optional

import streamlit as st
from streamlit_cookies_controller import CookieController as _CookieCtrl

from config import (
    APP_PASSWORD, BROWSER, DEFAULT_PROGRAM, GOOGLE_SHEET_ID,
    PROGRAMS, next_slot_datetime,
)
from modules.library_reader import LibraryReader
from modules.metadata_store import MetadataStore
from modules.orchestrator import create_contest
from modules.tracker import ContestTracker
from modules.utils import (
    AmbiguousLibraryError,
    LibraryNotFoundError,
    derive_attempt_windows_by_count,
)

# ─────────────────────────────────────────────────────────────────────────────
# Page config (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NV Contest Agent",
    page_icon="https://www.scaler.com/favicon.ico",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# Global Scaler-themed CSS (injected on every rerun before any widgets)
# ─────────────────────────────────────────────────────────────────────────────
st.html("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
      rel="stylesheet">
<style>
  html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"],
  [data-testid="stMain"], input, select, textarea, button, label, p {
    font-family: 'Inter', sans-serif !important;
  }
  /* Restore Material Symbols ligature font — must come after the broad rule */
  [data-testid="stIconMaterial"],
  [class*="material-symbols"],
  [class*="Material-Symbols"] {
    font-family: "Material Symbols Rounded" !important;
    font-weight: normal !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    font-feature-settings: "liga" !important;
    -webkit-font-feature-settings: "liga" !important;
    font-style: normal !important;
    display: inline-block !important;
  }
  [data-testid="stHeader"], [data-testid="stToolbar"],
  [data-testid="stDecoration"], #MainMenu, footer {
    visibility: hidden !important; height: 0 !important;
  }
  [data-testid="stApp"], [data-testid="stAppViewContainer"],
  [data-testid="stMain"] > div:first-child { background-color: #F5F6FA !important; }

  /* ── Nav bar ── */
  .scaler-nav {
    background: #1A1A2E; padding: 12px 32px; display: flex;
    align-items: center; justify-content: space-between;
    margin: -1rem -1rem 1.5rem -1rem; border-bottom: 3px solid #FF6B2B;
  }
  .scaler-nav img { height: 30px; }
  .scaler-nav-title { color:#fff; font-size:16px; font-weight:600; letter-spacing:0.3px; }

  /* ── Auth banner ── */
  .auth-banner {
    background:#FFF7ED; border:1px solid #FED7AA; border-radius:8px;
    padding:10px 16px; margin-bottom:16px; font-size:13px; color:#9A3412;
    display:flex; align-items:center; gap:8px;
  }

  /* ── Cards / badges ── */
  .scaler-card {
    background:#fff; border-radius:12px; border:1px solid #E2E8F0;
    padding:24px 28px; margin-bottom:16px;
    box-shadow:0 1px 3px rgba(0,0,0,0.06);
  }
  .scaler-card-title {
    font-size:13px; font-weight:600; color:#64748B; text-transform:uppercase;
    letter-spacing:0.8px; margin-bottom:14px; padding-bottom:10px;
    border-bottom:1px solid #F1F5F9;
  }
  .section-badge {
    display:inline-block; background:#FFF0E8; color:#FF6B2B; font-size:11px;
    font-weight:700; padding:3px 10px; border-radius:20px;
    letter-spacing:0.5px; text-transform:uppercase; margin-bottom:10px;
  }

  /* ── Buttons ── */
  button[kind="primary"], [data-testid="stBaseButton-primary"] {
    background-color:#FF6B2B !important; border:none !important;
    border-radius:8px !important; color:#fff !important;
    font-weight:600 !important; font-size:14px !important;
    transition:background-color 0.2s !important;
  }
  button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {
    background-color:#E85D20 !important;
  }
  button[kind="secondary"], [data-testid="stBaseButton-secondary"] {
    border-radius:8px !important; font-size:14px !important; font-weight:500 !important;
  }

  /* ── Inputs ── */
  [data-testid="stTextInput"] input, [data-testid="stDateInput"] input {
    border-radius:8px !important; border-color:#CBD5E1 !important;
    font-size:14px !important; color:#1A1A2E !important; background:#fff !important;
  }
  [data-testid="stSelectbox"] [data-baseweb="select"] > div:first-child {
    border-radius:8px !important; border-color:#CBD5E1 !important;
    font-size:14px !important; background:#fff !important;
  }
  [data-testid="stTextInput"] label, [data-testid="stSelectbox"] label,
  [data-testid="stDateInput"] label, [data-testid="stRadio"] label,
  [data-testid="stRadio"] span, [data-testid="stForm"] label {
    color:#1A1A2E !important; font-size:14px !important; font-weight:500 !important;
  }

  /* ── Tabs ── */
  [data-baseweb="tab-list"] {
    background:transparent !important; border-bottom:2px solid #E2E8F0 !important; gap:0 !important;
  }
  [data-baseweb="tab"] {
    font-weight:500 !important; font-size:14px !important; color:#64748B !important;
    padding:10px 24px !important; border-radius:0 !important; background:transparent !important;
  }
  [data-baseweb="tab"][aria-selected="true"] {
    color:#FF6B2B !important; border-bottom:2px solid #FF6B2B !important; font-weight:600 !important;
  }

  /* ── Step rows ── */
  .step-row {
    display:flex; align-items:center; gap:10px;
    padding:8px 4px; font-size:14px; color:#475569;
    border-bottom:1px solid #F8FAFC;
  }
  .step-row:last-child { border-bottom:none; }
  .step-label-pending { color:#94A3B8; }
  .step-label-running { color:#1D4ED8; font-weight:600; }
  .step-label-ok      { color:#166534; }
  .step-label-fail    { color:#991B1B; }

  /* ── Status chips ── */
  .chip { padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
  .chip-success { background:#DCFCE7; color:#166534; }
  .chip-fail    { background:#FEE2E2; color:#991B1B; }
  .chip-planned { background:#FEF9C3; color:#854D0E; }

  /* ── Preview plan table ── */
  .preview-row { display:flex; gap:8px; padding:5px 0; font-size:14px; border-bottom:1px solid #F1F5F9; }
  .preview-row:last-child { border-bottom:none; }
  .preview-label { color:#64748B; min-width:130px; font-weight:500; }
  .preview-value { color:#1A1A2E; font-weight:600; }

  /* ── History empty state ── */
  .empty-state {
    text-align:center; padding:60px 20px; color:#94A3B8;
  }
  .empty-state .empty-icon { font-size:40px; margin-bottom:12px; }
  .empty-state p { font-size:15px; margin:0; }

  /* ── Login card (injected separately when on login page) ── */
  .login-wrap { display:flex; flex-direction:column; align-items:center; padding-top:60px; }
  .login-logo-area {
    text-align:center; margin-bottom:20px;
  }
  .login-logo-area img { height:34px; margin-bottom:14px; display:block; margin-left:auto; margin-right:auto; }
  .login-logo-area h2 { font-size:22px; font-weight:700; color:#1A1A2E; margin:0; }
  .login-logo-area p  { font-size:14px; color:#64748B; margin:4px 0 0; }

  /* ── Misc ── */
  [data-testid="stDataFrame"] { border-radius:8px !important; overflow:hidden !important; }
  hr { border-color:#E2E8F0; margin:16px 0; }
</style>
""")

# ─────────────────────────────────────────────────────────────────────────────
# Cookie-based auth (must render before any st.stop() so the hidden component
# is present on both login and app pages, allowing the browser to respond)
# ─────────────────────────────────────────────────────────────────────────────
_cookies = _CookieCtrl()

_COOKIE_NAME = "nv_agent_session"
_COOKIE_TTL  = 7 * 24 * 3600  # 7 days in seconds
try:
    _SESSION_SECRET: str = st.secrets.get("SESSION_SECRET", "") or ""
except Exception:
    _SESSION_SECRET = ""
_SESSION_SECRET = _SESSION_SECRET or os.getenv("SESSION_SECRET", "")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
_SCALER_LOGO = (
    "https://www.scaler.com/storyblok-assets/f/290352327034910"
    "/190x40/762eb27df8/scaler-logo.svg"
)
_DEFAULT_LIB = "— NV Contests (default) —"

# Step order mirrors orchestrator emit() calls
_STEPS: OrderedDict[str, str] = OrderedDict([
    ("library",     "Reading Library"),
    ("plan",        "Planning Windows"),
    ("batch",       "Admin V2 — Creating Batch"),
    ("schedule",    "CCT — Scheduling Class"),
    ("hire_update", "Hire Test — Setting Windows"),
    ("tracker",     "Updating Tracker"),
    ("done",        "Complete"),
])
_STEP_KEYS = list(_STEPS.keys())

_ERROR_HINTS: dict[str, str] = {
    "LibraryNotFoundError":  "Module not found in the library Excel — add it to the sheet or pick a Library Override.",
    "AmbiguousLibraryError": "Module maps to multiple libraries — use the Library Override field to pick one.",
    "session expired":       "Scaler session expired. Run `python capture_login.py` locally to refresh auth, then upload the new storage_state.json via the panel below.",
    "BrowserStepError":      "Browser automation failed. Scaler session may have expired — run `python capture_login.py` to refresh it.",
    "DuplicateContestError": "A contest with this batch name already exists in the tracker.",
    "TrackerUpdateError":    "Google Sheet tracker could not be updated — check service account credentials.",
    "past":                  "Start time is in the past — pick a future date and time.",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def _is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def _email_to_display_name(email: str) -> str:
    """'darfisha.shaikh@scaler.com' → 'Darfisha Shaikh'"""
    prefix = email.split("@")[0]
    parts = re.split(r"[._\-+]+", prefix)
    return " ".join(p.title() for p in parts if p)


def _bootstrap_storage_state() -> None:
    """Write storage_state.json from STORAGE_STATE_B64 secret when file absent.

    On Streamlit Community Cloud the filesystem is ephemeral, so the file
    won't survive a reboot.  The base64 secret is the durable source of truth.
    """
    path = Path(BROWSER.storage_state) if BROWSER.storage_state else None
    if path is None or path.exists():
        return
    b64: str = ""
    try:
        b64 = st.secrets.get("STORAGE_STATE_B64", "") or ""
    except Exception:
        pass
    b64 = b64 or os.getenv("STORAGE_STATE_B64", "")
    if b64:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(b64.strip()))
        except Exception:
            pass


def _bootstrap_cloud_config() -> None:
    """Inject Streamlit secrets into env vars and write credential files.

    config.py reads all settings via os.getenv() at module-import time, so
    those values are frozen.  _build_tracker() re-reads env at call time, so
    injecting here before the first run is enough to reach Google Sheets.
    """
    from config import DATA_DIR

    # Simple string secrets → env vars (safe to call os.environ.setdefault
    # so local .env values already present are not overwritten).
    for key in ("GOOGLE_SHEET_ID", "APP_PASSWORD", "SESSION_SECRET"):
        try:
            val = str(st.secrets.get(key, "") or "")
            if val:
                os.environ.setdefault(key, val)
        except Exception:
            pass

    # Service account JSON from base64 secret.
    svc_b64: str = ""
    try:
        svc_b64 = str(st.secrets.get("SERVICE_ACCOUNT_B64", "") or "")
    except Exception:
        pass
    svc_b64 = svc_b64 or os.getenv("SERVICE_ACCOUNT_B64", "")
    if svc_b64:
        svc_path = DATA_DIR / "service_account.json"
        if not svc_path.exists():
            try:
                svc_path.parent.mkdir(parents=True, exist_ok=True)
                svc_path.write_bytes(base64.b64decode(svc_b64.strip()))
            except Exception:
                pass


def _session_expired() -> bool:
    """Return True if no usable auth state exists (file absent AND no secret)."""
    path = Path(BROWSER.storage_state) if BROWSER.storage_state else None
    if path is not None and path.exists():
        return False
    try:
        return not bool(st.secrets.get("STORAGE_STATE_B64", ""))
    except Exception:
        return True


def _error_hint(msg: str) -> str:
    for key, hint in _ERROR_HINTS.items():
        if key.lower() in msg.lower():
            return hint
    return ""


def _latest_screenshot() -> Optional[Path]:
    shots = sorted(
        Path("screenshots").glob("*.png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return shots[0] if shots else None


def _chip(status: str) -> str:
    cls = {"created": "chip-success", "failed": "chip-fail", "planned": "chip-planned"}.get(
        status, "chip-planned"
    )
    label = status.title()
    return f'<span class="chip {cls}">{label}</span>'


def _make_auth_cookie(email: str) -> str:
    """Return a signed HMAC-SHA256 token: base64(expiry:sid:email:sig)."""
    expiry = int(_time.time()) + _COOKIE_TTL
    sid = _secrets.token_hex(8)
    payload = f"{expiry}:{sid}:{email}"
    sig = _hmac.new(_SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _verify_auth_cookie(token: str) -> Optional[str]:
    """Return the email if the cookie token is valid and unexpired, else None."""
    if not _SESSION_SECRET:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = raw.rsplit(":", 1)
        expected = _hmac.new(
            _SESSION_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            return None
        expiry_str, _sid, email = payload.split(":", 2)
        if _time.time() > int(expiry_str):
            return None
        return email
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Cached loaders
# ─────────────────────────────────────────────────────────────────────────────
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


@st.cache_data
def _resolve_library_preview(module: str, program: str, override: Optional[str]) -> tuple[str, Optional[str]]:
    """Returns (resolved_name, error_or_None) without raising."""
    if override:
        return override, None
    if not module:
        return "NV Contests (default)", None
    try:
        match = LibraryReader().resolve(program, module)
        return match.library_name, None
    except LibraryNotFoundError:
        return "NV Contests (default — module not in Excel)", None
    except AmbiguousLibraryError as exc:
        return "", str(exc)
    except Exception:
        return "NV Contests (default)", None


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap from secrets (Community Cloud: env vars and files are ephemeral)
# ─────────────────────────────────────────────────────────────────────────────
_bootstrap_cloud_config()   # env vars + service_account.json
_bootstrap_storage_state()  # data/storage_state.json

# ─────────────────────────────────────────────────────────────────────────────
# Restore session from cookie (before login gate and sign-out handler).
# On the very first render the cookie controller returns None while the hidden
# component loads; it triggers one extra rerun, after which the value is real.
# ─────────────────────────────────────────────────────────────────────────────
if not st.session_state.get("authenticated") and _SESSION_SECRET:
    _raw_token = _cookies.get(_COOKIE_NAME)
    if _raw_token:
        _cookie_email = _verify_auth_cookie(_raw_token)
        if _cookie_email:
            st.session_state["authenticated"] = True
            st.session_state["user"] = {
                "email": _cookie_email,
                "display_name": _email_to_display_name(_cookie_email),
            }

# ─────────────────────────────────────────────────────────────────────────────
# Sign-out handler (runs before login gate so ?signout=1 always works)
# ─────────────────────────────────────────────────────────────────────────────
if st.query_params.get("signout") == "1":
    for _k in ("authenticated", "user", "pending"):
        st.session_state.pop(_k, None)
    _cookies.remove(_COOKIE_NAME)
    st.query_params.clear()
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Login gate
# ─────────────────────────────────────────────────────────────────────────────
if APP_PASSWORD and not st.session_state.get("authenticated"):
    # Extra CSS: style stForm as the login card (safe — st.stop() below
    # prevents this from bleeding into the main-app form)
    st.html("""<style>
      [data-testid="stForm"] {
        background:#FFFFFF; border-radius:12px; border:1px solid #E2E8F0;
        box-shadow:0 4px 20px rgba(0,0,0,0.09) !important; padding:4px 4px 8px !important;
      }
    </style>""")

    _, col, _ = st.columns([1, 1.3, 1])
    with col:
        st.markdown(f"""
        <div class="login-logo-area" style="margin-top:56px;">
          <img src="{_SCALER_LOGO}" onerror="this.style.display='none'">
          <h2>NV Contest Agent</h2>
          <p>Sign in with your work email</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form", border=False):
            email_in = st.text_input("Work email", placeholder="name@scaler.com")
            pwd_in = st.text_input("Password", type="password", placeholder="Password")
            sign_in = st.form_submit_button(
                "Sign in →", type="primary", use_container_width=True
            )

        if sign_in:
            e = email_in.strip()
            if not e:
                st.error("Email is required.")
            elif not _is_valid_email(e):
                st.error("Enter a valid email address.")
            elif pwd_in != APP_PASSWORD:
                st.error("Incorrect password.")
            else:
                if not e.endswith("@scaler.com"):
                    st.warning(f"{e} is not a @scaler.com address — proceed with caution.")
                st.session_state["authenticated"] = True
                st.session_state["user"] = {
                    "email": e,
                    "display_name": _email_to_display_name(e),
                }
                if _SESSION_SECRET:
                    _cookies.set(_COOKIE_NAME, _make_auth_cookie(e), max_age=_COOKIE_TTL)
                st.rerun()

    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Nav bar (shown on every authenticated page)
# ─────────────────────────────────────────────────────────────────────────────
_user: dict = st.session_state.get("user", {})
_display_name = _user.get("display_name", "")
_right_html = (
    f'<span style="display:flex;align-items:center;gap:12px;">'
    f'<span style="color:#CBD5E1;font-size:13px;">{_display_name}</span>'
    f'<a href="?signout=1" style="color:#FF6B2B;text-decoration:none;font-size:13px;">Sign out</a>'
    f'</span>'
    if APP_PASSWORD else ""
)
_NAV_LOGO_SVG = """
<svg width="114" height="24" viewBox="0 0 190 40" fill="none" xmlns="http://www.w3.org/2000/svg">
<g clip-path="url(#clip0_nav)">
<path d="M163.971 32.7039C163.939 32.5947 163.918 32.4828 163.907 32.3697C163.907 27.9482 163.907 23.5264 163.907 19.104C163.907 18.884 163.896 18.6625 163.907 18.4439C163.926 18.1682 164.052 17.911 164.259 17.728C165.162 16.8394 166.07 15.9565 166.968 15.0623C168.751 13.2815 170.531 11.497 172.308 9.70871C172.975 9.04113 173.646 8.3782 174.319 7.71991C174.419 7.637 174.525 7.56247 174.638 7.49707H189.015C189.057 7.61083 189.085 7.72908 189.1 7.84943C189.1 12.3303 189.1 16.8102 189.1 21.2892C189.106 21.3831 189.121 21.4763 189.143 21.5677V22.0092C188.994 22.1763 188.853 22.3518 188.696 22.5106C188.079 23.1327 187.46 23.752 186.838 24.3685C186.047 25.1498 185.246 25.9214 184.459 26.7055C182.59 28.568 180.724 30.4319 178.86 32.2973C178.721 32.4449 178.548 32.5758 178.392 32.7151L163.971 32.7039ZM178.482 31.1288L178.586 31.2026C178.883 30.8753 179.167 30.5341 179.477 30.2207C180.733 28.9626 181.992 27.7092 183.256 26.4604C183.325 26.396 183.38 26.3173 183.415 26.2297C183.451 26.1421 183.467 26.0478 183.462 25.9534C183.456 21.856 183.456 17.7591 183.462 13.6626C183.462 13.6181 183.462 13.5735 183.462 13.5234C183.47 13.3228 183.41 13.2309 183.174 13.2309C179.031 13.2393 174.888 13.2393 170.745 13.2309C170.65 13.2283 170.555 13.246 170.467 13.2827C170.379 13.3194 170.3 13.3744 170.235 13.444C168.756 14.9296 167.276 16.4096 165.795 17.884C165.747 17.9327 165.703 17.987 165.621 18.079H178.486L178.482 31.1288ZM174.164 25.342V22.7989C174.164 22.4382 174.15 22.4229 173.795 22.4229H168.731C168.664 22.4229 168.592 22.4312 168.532 22.4229C168.323 22.4229 168.254 22.5231 168.254 22.7251C168.259 24.4651 168.259 26.2041 168.254 27.9422C168.254 28.1623 168.344 28.2556 168.552 28.2514C168.809 28.2514 169.065 28.2319 169.323 28.2319C170.843 28.2319 172.362 28.2319 173.88 28.2319C174.159 28.2319 174.159 28.2319 174.159 27.945C174.159 27.0759 174.159 26.2064 174.159 25.3364" fill="#0041CA"/>
<path d="M7.56694 14.1933C7.56694 15.3576 8.32737 16.0135 12.8593 16.8255H12.8621C21.9008 18.448 23.7114 21.1666 23.7114 25.0286C23.7114 27.3893 22.5735 32.8836 12.039 32.8836C8.06414 32.8836 1.22728 31.8488 0.0615682 24.9228L0.00585938 24.5913H6.42212L6.48619 24.7863C7.23547 27.0411 9.11704 28.0466 12.5877 28.0466C16.6725 28.0466 17.1447 26.6651 17.1447 25.6261C17.1447 24.1846 16.2213 23.2961 11.1769 22.4396C2.26207 20.9145 1.03369 17.8478 1.03369 14.7615C1.03369 10.1613 5.20906 7.18787 11.6727 7.18787C21.3061 7.18787 22.6041 12.7964 22.7755 14.515L22.8061 14.8269H16.4079L16.348 14.6208C15.9832 13.3381 15.1197 12.029 11.4916 12.029C9.70059 12.029 7.56694 12.4036 7.56694 14.1933Z" fill="white"/>
<path fill-rule="evenodd" clip-rule="evenodd" d="M71.4761 32.7039H78.7308L69.2631 7.48729H60.819L51.3109 32.7039H58.4012L60.3274 27.0118H69.5904L71.4761 32.7039ZM64.9596 12.3409L68.2798 22.537H61.6393L64.9596 12.3409Z" fill="white"/>
<path d="M88.9366 27.6219H102.503V32.7039H81.8867V7.48729H88.9366V27.6219Z" fill="white"/>
<path d="M105.797 7.48729V32.7039H126.826V27.6219H112.846V22.4646H125.958V17.6876H112.846V12.5679H126.863V7.48729H105.797Z" fill="white"/>
<path fill-rule="evenodd" clip-rule="evenodd" d="M143.038 7.48729C146.263 7.48729 148.77 8.19386 150.559 9.60701C152.348 11.0202 153.243 12.8989 153.243 15.2433C153.243 17.8162 152.355 19.7776 150.578 21.1276C149.794 21.7235 148.869 22.1879 147.803 22.5207L154.851 32.7039H147.063L141.288 23.4966H137.058V32.7039H130.131V7.48729H143.038ZM142.063 18.8352C143.429 18.8352 144.454 18.5803 145.137 18.0706C145.82 17.5608 146.162 16.7456 146.162 15.625C146.162 14.5303 145.82 13.7281 145.137 13.2183C144.454 12.7086 143.429 12.4537 142.063 12.4537H137.063V18.8352H142.063Z" fill="white"/>
<path d="M31.8685 20.1485C31.8685 24.3643 34.7919 27.2584 38.6135 27.2584C41.424 27.2584 43.5883 25.3782 44.488 22.4535H50.5296C49.4906 29.7875 44.7178 32.7387 38.6135 32.7387C30.8853 32.7387 25.5734 27.5954 25.5734 20.1485C25.5734 12.6724 30.8853 7.55692 38.6135 7.55692C43.3265 7.55692 48.1007 9.35771 49.9293 14.6793L44.261 16.5999C43.2554 14.1515 41.2123 13.0373 38.6135 13.0373C34.7919 13.0373 31.8685 15.9327 31.8685 20.1485Z" fill="white"/>
</g>
<defs>
<clipPath id="clip0_nav">
<rect width="189.143" height="40" fill="white"/>
</clipPath>
</defs>
</svg>"""

st.markdown(f"""
<div class="scaler-nav">
  <div style="display:flex;align-items:center;gap:16px;">
    {_NAV_LOGO_SVG}
    <span class="scaler-nav-title">NV Contest Agent</span>
  </div>
  {_right_html}
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Auth session banner + admin upload panel
# ─────────────────────────────────────────────────────────────────────────────
if _session_expired():
    st.markdown(
        '<div class="auth-banner">⚠️ &nbsp;'
        '<strong>Scaler session missing or expired.</strong>&nbsp; '
        'Run <code>python capture_login.py</code> locally, then upload '
        'the generated <code>storage_state.json</code> below.</div>',
        unsafe_allow_html=True,
    )
    _state_path = Path(BROWSER.storage_state) if BROWSER.storage_state else None
    if _state_path is not None:
        with st.expander("Upload auth state"):
            _up = st.file_uploader(
                "storage_state.json", type="json", label_visibility="collapsed"
            )
            if _up is not None:
                _state_path.parent.mkdir(parents=True, exist_ok=True)
                _state_path.write_bytes(_up.read())
                st.success("Auth state installed — ready to run contests.")
                st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────
tab_create, tab_history = st.tabs(["  Create Contest  ", "  Run History  "])


# ═════════════════════════════════════════════════════════════════════════════
# Tab 1 — Create Contest
# ═════════════════════════════════════════════════════════════════════════════
with tab_create:
    pending = st.session_state.get("pending")

    # ── PREVIEW / CONFIRM ────────────────────────────────────────────────────
    if pending:
        windows = derive_attempt_windows_by_count(pending["start_dt"], num_attempts=4)

        st.markdown('<div class="section-badge">Review Plan</div>', unsafe_allow_html=True)
        st.markdown('<div class="scaler-card"><div class="scaler-card-title">What will be created</div>',
                    unsafe_allow_html=True)

        col_info, col_windows = st.columns([1, 1])
        with col_info:
            rows = [
                ("Batch Name",   pending["contest_name"]),
                ("Module",       pending["module"]),
                ("Program",      pending["program"].upper()),
                ("Library",      pending["library_resolved"]),
                ("Start",        pending["start_dt"].strftime("%d %b %Y, %I:%M %p")),
            ]
            html_rows = "".join(
                f'<div class="preview-row">'
                f'<span class="preview-label">{label}</span>'
                f'<span class="preview-value">{value}</span>'
                f'</div>'
                for label, value in rows
            )
            st.markdown(f'<div style="margin-top:4px;">{html_rows}</div>', unsafe_allow_html=True)

        with col_windows:
            st.markdown("**Attempt Windows**")
            st.table([{
                "Attempt":  w.label,
                "Start":    w.start.strftime("%d %b %Y"),
                "End":      w.end.strftime("%d %b %Y"),
                "Days":     str((w.end - w.start).days),
            } for w in windows])
            st.markdown(
                '<p style="font-size:11px;color:#94A3B8;margin-top:-8px;">'
                '* Actual attempts depend on the CCT library — may be fewer than shown.'
                '</p>',
                unsafe_allow_html=True,
            )

        if pending.get("duplicate_warning"):
            st.warning(f"⚠️ A contest named **{pending['contest_name']}** already exists in history — it will be overwritten.")

        st.markdown("</div>", unsafe_allow_html=True)

        btn_confirm, btn_edit, _ = st.columns([1.2, 1, 5])
        confirmed = btn_confirm.button("Confirm & Create →", type="primary")
        cancelled = btn_edit.button("← Edit")

        if cancelled:
            st.session_state.pop("pending", None)
            st.rerun()

        if confirmed:
            # ── LIVE PROGRESS ────────────────────────────────────────────────
            prog_header = st.empty()
            prog_header.markdown(
                '<div class="scaler-card-title" style="margin-top:16px;">Running</div>',
                unsafe_allow_html=True,
            )
            placeholders = {k: st.empty() for k in _STEPS}
            for k, label in _STEPS.items():
                placeholders[k].markdown(
                    f'<div class="step-row">⬜ &nbsp;<span class="step-label-pending">{label}</span></div>',
                    unsafe_allow_html=True,
                )

            log_exp = st.expander("Run logs", expanded=False)
            log_ph = log_exp.empty()
            log_lines: list[str] = []

            step_states: dict[str, str] = {k: "pending" for k in _STEPS}

            def _mark_running(key: str) -> None:
                if key in placeholders and step_states[key] == "pending":
                    step_states[key] = "running"
                    label = _STEPS[key]
                    placeholders[key].markdown(
                        f'<div class="step-row">🔄 &nbsp;<span class="step-label-running">{label}</span></div>',
                        unsafe_allow_html=True,
                    )

            def progress(step: str, msg: str, ok: bool) -> None:
                # Resolve hire_nav → hire_update for display
                display_step = "hire_update" if step == "hire_nav" else step
                if display_step in placeholders:
                    icon = "✅" if ok else "❌"
                    cls = "step-label-ok" if ok else "step-label-fail"
                    label = _STEPS[display_step]
                    step_states[display_step] = "ok" if ok else "fail"
                    placeholders[display_step].markdown(
                        f'<div class="step-row">{icon} &nbsp;<span class="{cls}">{label}</span>'
                        f'<span style="color:#94A3B8;font-size:12px;margin-left:auto;">{msg[:80]}</span></div>',
                        unsafe_allow_html=True,
                    )
                    # Mark next step as running
                    if ok and display_step in _STEP_KEYS:
                        idx = _STEP_KEYS.index(display_step)
                        if idx + 1 < len(_STEP_KEYS):
                            _mark_running(_STEP_KEYS[idx + 1])

                # Append to log
                tag = "✅" if ok else "❌"
                log_lines.append(f"{datetime.now().strftime('%H:%M:%S')} {tag} [{step}] {msg}")
                log_ph.code("\n".join(log_lines), language=None)

            # Mark first step as running
            _mark_running("library")

            with st.spinner("Running automation — this takes 2–4 minutes…"):
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
                    created_by=_user.get("email", "Unknown"),
                )

            st.session_state.pop("pending", None)
            _suggest_name.clear()

            # ── OUTCOME ──────────────────────────────────────────────────────
            if outcome.success:
                st.success("Contest created successfully.")
            else:
                hint = _error_hint(outcome.error or "")
                st.error(f"**Failed:** {outcome.error}")
                if hint:
                    st.info(f"💡 {hint}")
                shot = _latest_screenshot()
                if shot:
                    with st.expander("Error screenshot"):
                        st.image(str(shot))

            c1, c2 = st.columns(2)
            with c1:
                st.markdown('<div class="scaler-card"><div class="scaler-card-title">Run Summary</div>',
                            unsafe_allow_html=True)
                st.json({
                    "batch_name":       outcome.batch_name or "—",
                    "library_used":     outcome.library_used or "—",
                    "contest_id":       outcome.contest_id or "—",
                    "test_ids":         outcome.test_ids or [],
                    "tracker_row":      outcome.tracker_row,
                    "execution_s":      outcome.execution_seconds,
                })
                st.markdown("</div>", unsafe_allow_html=True)
            with c2:
                if outcome.windows:
                    st.markdown('<div class="scaler-card"><div class="scaler-card-title">Attempt Windows</div>',
                                unsafe_allow_html=True)
                    st.table([{
                        "Attempt": w.label,
                        "Start":   w.start.strftime("%d %b %Y"),
                        "End":     w.end.strftime("%d %b %Y"),
                    } for w in outcome.windows])
                    st.markdown("</div>", unsafe_allow_html=True)

    # ── INPUT FORM ──────────────────────────────────────────────────────────
    else:
        st.markdown('<div class="section-badge">New Contest</div>', unsafe_allow_html=True)
        st.markdown('<div class="scaler-card"><div class="scaler-card-title">Contest Details</div>',
                    unsafe_allow_html=True)

        r1c1, r1c2 = st.columns(2)
        with r1c1:
            program = st.selectbox(
                "Program",
                options=list(PROGRAMS.keys()),
                index=list(PROGRAMS.keys()).index(DEFAULT_PROGRAM),
                key="form_program",
            )
        with r1c2:
            module_options = _load_module_names(program)
            module = st.selectbox(
                "Module Name",
                options=module_options,
                index=None,
                placeholder="Type to search…",
                key="form_module",
            )

        suggested_name = _suggest_name(module, program) if module else ""
        if suggested_name and module:
            st.markdown(
                f'<div style="font-size:12px;color:#64748B;margin:-6px 0 8px;">'
                f'Suggested: <strong style="color:#FF6B2B;">{suggested_name}</strong></div>',
                unsafe_allow_html=True,
            )

        with st.form("contest_form", border=False):
            fc1, fc2 = st.columns(2)
            with fc1:
                contest_name = st.text_input(
                    "Contest / Batch Name",
                    value=suggested_name,
                    placeholder="e.g. Advanced DSA 4: NV Contest July 2026",
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
                start_time_val = time(21, 0) if time_choice == "9:00 PM" else time(7, 0)
            with fc2:
                lib_options = [_DEFAULT_LIB] + _load_library_names()
                library_sel = st.selectbox("Library Override (optional)", options=lib_options)
                library_override = None if library_sel == _DEFAULT_LIB else library_sel

                st.markdown("<br>", unsafe_allow_html=True)
                _preview_dt = datetime.combine(start_date, start_time_val)
                st.markdown(
                    f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;'
                    f'border-radius:8px;padding:12px 16px;font-size:13px;color:#475569;">'
                    f'📅 &nbsp;<strong>Contest A1 starts:</strong><br>'
                    f'<span style="color:#1A1A2E;font-size:15px;font-weight:600;">'
                    f'{_preview_dt.strftime("%d %b %Y, %I:%M %p")}</span></div>',
                    unsafe_allow_html=True,
                )

            st.markdown("<br>", unsafe_allow_html=True)
            form_submitted = st.form_submit_button(
                "Preview Plan →", type="primary"
            )

        st.markdown("</div>", unsafe_allow_html=True)

        if form_submitted:
            # Pre-flight validation — catch errors before any browser opens
            errors: list[str] = []
            warnings: list[str] = []

            if not module:
                errors.append("Module Name is required.")
            if not contest_name:
                errors.append("Contest / Batch Name is required.")

            start_dt = datetime.combine(start_date, start_time_val)
            if start_dt <= datetime.now():
                errors.append(
                    f"Start time **{start_dt.strftime('%d %b %Y %I:%M %p')}** "
                    "is in the past — pick a future date."
                )

            lib_resolved, lib_err = _resolve_library_preview(
                module or "", program, library_override
            )
            if lib_err:
                warnings.append(
                    f"Library ambiguity: {lib_err}. Use the Library Override field to pick one explicitly."
                )

            if not errors and module and contest_name:
                if MetadataStore().batch_exists(program, contest_name):
                    warnings.append(
                        f"A contest named **{contest_name}** already exists in history — it will be overwritten."
                    )

            if errors:
                for e in errors:
                    st.error(e)
            else:
                for w in warnings:
                    st.warning(w)
                st.session_state["pending"] = {
                    "module":            module,
                    "contest_name":      contest_name,
                    "program":           program,
                    "library_override":  library_override,
                    "library_resolved":  lib_resolved or library_override or "NV Contests (default)",
                    "start_dt":          start_dt,
                    "duplicate_warning": bool(
                        not errors and module and contest_name
                        and MetadataStore().batch_exists(program, contest_name)
                    ),
                }
                st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# Tab 2 — Run History
# ═════════════════════════════════════════════════════════════════════════════
with tab_history:
    hc1, hc2 = st.columns([8, 1])
    with hc1:
        st.markdown('<div class="section-badge">Run History</div>', unsafe_allow_html=True)
    with hc2:
        if st.button("Refresh", key="refresh_history"):
            st.cache_data.clear()
            st.rerun()

    rows = MetadataStore().recent_contests(limit=200)

    if not rows:
        st.markdown("""
        <div class="scaler-card">
          <div class="empty-state">
            <div class="empty-icon">📋</div>
            <p>No contests have been created yet.<br>Use the <strong>Create Contest</strong> tab to get started.</p>
          </div>
        </div>""", unsafe_allow_html=True)
    else:
        # Filters
        f1, f2, f3 = st.columns(3)
        with f1:
            prog_filter = st.multiselect("Program", options=sorted({r["program"] for r in rows}))
        with f2:
            status_filter = st.multiselect("Status", options=sorted({r["status"] for r in rows}))
        with f3:
            search = st.text_input("Search", placeholder="Batch name or module…")

        filtered = rows
        if prog_filter:
            filtered = [r for r in filtered if r["program"] in prog_filter]
        if status_filter:
            filtered = [r for r in filtered if r["status"] in status_filter]
        if search:
            s = search.lower()
            filtered = [r for r in filtered
                        if s in r["batch_name"].lower() or s in r["module"].lower()]

        st.markdown(
            f'<div style="font-size:13px;color:#94A3B8;margin:4px 0 12px;">'
            f'Showing {len(filtered)} of {len(rows)} runs</div>',
            unsafe_allow_html=True,
        )

        for r in filtered:
            created_at = r["created_at"][:16].replace("T", " ")
            created_by_email = r.get("created_by", "Unknown")
            created_by_name = (
                _email_to_display_name(created_by_email)
                if "@" in created_by_email
                else created_by_email
            )
            status_chip = _chip(r["status"])
            expander_label = (
                f"{r['batch_name']}  ·  {r['program'].upper()}  ·  {created_at}"
            )

            with st.expander(expander_label):
                st.markdown(
                    f'{status_chip} &nbsp; '
                    f'<span style="font-size:12px;color:#64748B;">by {created_by_name}</span>',
                    unsafe_allow_html=True,
                )
                st.markdown("---")

                d1, d2, d3 = st.columns(3)
                with d1:
                    st.markdown(f"**Module:** {r['module']}")
                    st.markdown(f"**Program:** {r['program'].upper()}")
                    st.markdown(f"**Library:** {r['library_name'] or '—'}")
                    st.markdown(f"**Created:** {created_at}")
                with d2:
                    st.markdown(f"**Contest ID:** {r['contest_id'] or '—'}")
                    test_ids = json.loads(r.get("test_ids_json") or "[]")
                    st.markdown(f"**Test IDs:** {', '.join(test_ids) or '—'}")
                    st.markdown(f"**Tracker Row:** {r['tracker_row'] or '—'}")
                    st.markdown(
                        f"**Created by:** {created_by_name}"
                        + (f" ({created_by_email})" if created_by_email != created_by_name else "")
                    )
                with d3:
                    windows = json.loads(r.get("windows_json") or "[]")
                    if windows:
                        st.markdown("**Attempt Windows:**")
                        for w in windows:
                            st.markdown(f"- {w['label']}: {w['start'][:10]} → {w['end'][:10]}")
                    else:
                        st.markdown("**Attempt Windows:** —")
