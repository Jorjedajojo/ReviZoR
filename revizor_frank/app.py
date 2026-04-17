"""ReviZoR FranK — Main Streamlit Application.

Run with:  streamlit run revizor_frank/app.py

Auth modes:
- Local (no APP_USERNAME secret/env):  no login gate, single-user desktop use
- Deployed (APP_USERNAME + APP_PASSWORD set in secrets): standalone login gate
- Deployed (API_BASE_URL set in secrets): full JWT login against FastAPI server
"""

from __future__ import annotations

import hashlib
import hmac
import io
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

# ── Streamlit Cloud secrets bridge ────────────────────────────────────────────
# Pushes st.secrets into os.environ so the rest of the app is environment-agnostic.
try:
    for _k in ("ANTHROPIC_API_KEY", "SECRET_KEY", "API_BASE_URL",
               "APP_USERNAME", "APP_PASSWORD", "SESSION_TIMEOUT_HOURS",
               "ADMIN_USERNAME", "ADMIN_PASSWORD", "USD_TO_EGP_RATE",
               "SUPABASE_URL", "SUPABASE_ANON_KEY", "APP_URL"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

import httpx

from revizor_frank.config import (
    APP_NAME,
    APP_VERSION,
    EXPORTS_DIR,
    TEMPLATES,
    DEFAULT_TEMPLATE,
    ANTHROPIC_API_KEY,
)
from revizor_frank.i18n import STRINGS as S

# ── Auth config ───────────────────────────────────────────────────────────────
API_BASE_URL: str        = os.getenv("API_BASE_URL", "").rstrip("/")
_APP_USERNAME: str       = os.getenv("APP_USERNAME", "")
_APP_PASSWORD: str       = os.getenv("APP_PASSWORD", "")
_ADMIN_USERNAME: str     = os.getenv("ADMIN_USERNAME", "")
_ADMIN_PASSWORD: str     = os.getenv("ADMIN_PASSWORD", "")
SESSION_TIMEOUT_HOURS: int = int(os.getenv("SESSION_TIMEOUT_HOURS", "8"))
USD_TO_EGP_RATE: float   = float(os.getenv("USD_TO_EGP_RATE", "50"))
APP_URL: str             = os.getenv("APP_URL", "").rstrip("/")

# Pricing
TIER_PRICES = {
    "cv_only":     7.50,
    "cv_linkedin": 10.00,
}

# Auth mode resolution (priority order)
SIMPLE_AUTH: bool = bool(_APP_USERNAME and _APP_PASSWORD) and not API_BASE_URL
JWT_AUTH: bool    = bool(API_BASE_URL)
AUTH_ENABLED: bool = JWT_AUTH  # kept for JWT path compatibility


def _check_credentials(username: str, password: str) -> str | None:
    """Constant-time credential check. Returns 'admin', 'user', or None."""
    u = username.strip().lower()
    p_hash = hashlib.sha256(password.encode()).hexdigest()

    # Check admin credentials first (admin also has user access)
    if _ADMIN_USERNAME and _ADMIN_PASSWORD:
        a_u_ok = hmac.compare_digest(u, _ADMIN_USERNAME.strip().lower())
        a_p_ok = hmac.compare_digest(p_hash, hashlib.sha256(_ADMIN_PASSWORD.encode()).hexdigest())
        if a_u_ok and a_p_ok:
            return "admin"

    # Check regular user credentials
    if _APP_USERNAME and _APP_PASSWORD:
        u_ok = hmac.compare_digest(u, _APP_USERNAME.strip().lower())
        p_ok = hmac.compare_digest(p_hash, hashlib.sha256(_APP_PASSWORD.encode()).hexdigest())
        if u_ok and p_ok:
            return "user"

    return None


def _simple_auth_valid() -> bool:
    if not st.session_state.get("simple_auth_ok"):
        return False
    login_time = st.session_state.get("simple_auth_time")
    if not login_time:
        return False
    elapsed = datetime.now(timezone.utc) - login_time
    return elapsed < timedelta(hours=SESSION_TIMEOUT_HOURS)


def render_simple_login():
    """Standalone username/password login page — no external service required."""
    # Hide sidebar on login page
    st.markdown("<style>[data-testid='stSidebar']{display:none}</style>",
                unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown(
            f"<h1 style='text-align:center;margin-bottom:0'>📄 {APP_NAME}</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align:center;color:#888;margin-top:4px'>"
            "AI-Powered CV Optimization Engine</p>",
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)

        with st.form("simple_login", clear_on_submit=False):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

        if submitted:
            role = _check_credentials(username, password)
            if role:
                st.session_state.simple_auth_ok   = True
                st.session_state.simple_auth_time = datetime.now(timezone.utc)
                st.session_state.simple_auth_user = username.strip().lower()
                st.session_state.user_role        = role
                # Load session history for this user — show picker if sessions exist
                try:
                    from revizor_frank.storage import supabase_db as _sdb
                    _sessions = _sdb.list_sessions(username.strip().lower())
                except Exception:
                    _sessions = []

                if _sessions:
                    st.session_state.pending_session_list = _sessions
                    st.session_state.show_session_picker = True
                # If history exists go to queue; otherwise straight to upload
                st.session_state.stage = "queue" if _sessions else "upload"
                st.session_state.session_restored_banner = False
                st.rerun()
            else:
                # Small delay to further slow brute-force attempts
                time.sleep(1.5)
                st.error("Invalid username or password.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            "<p style='text-align:center;font-size:0.75rem;color:#bbb'>"
            "This tool is for authorized use only.</p>",
            unsafe_allow_html=True,
        )

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title=APP_NAME,
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS overrides ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main .block-container { max-width: 1100px; padding-top: 1.5rem; }
    .stAlert { border-radius: 8px; }
    .metric-card {
        background: #f8f9fa; border-radius: 10px;
        padding: 1rem; text-align: center;
        border: 1px solid #e9ecef;
    }
    .score-big { font-size: 3rem; font-weight: 800; line-height: 1; }
    .grade-badge {
        display: inline-block; padding: 0.2rem 0.7rem;
        border-radius: 20px; font-weight: 700; font-size: 1.1rem;
    }
    .badge-A { background: #d4edda; color: #155724; }
    .badge-B { background: #cce5ff; color: #004085; }
    .badge-C { background: #fff3cd; color: #856404; }
    .badge-D { background: #f8d7da; color: #721c24; }
    .badge-F { background: #f5c6cb; color: #491217; }
    .severity-critical { color: #dc3545; font-weight: 600; }
    .severity-warning  { color: #fd7e14; }
    .severity-info     { color: #0dcaf0; }
    .template-card {
        border: 2px solid #e9ecef; border-radius: 8px;
        padding: 0.6rem; cursor: pointer; text-align: center;
        transition: border-color 0.2s;
    }
    .template-card.selected { border-color: #0d6efd; }
    .linkedin-box {
        background: #f0f8ff; border: 1px solid #bee3f8;
        border-radius: 8px; padding: 1rem;
        font-family: monospace; font-size: 0.8rem;
        white-space: pre-wrap; max-height: 400px;
        overflow-y: auto;
    }
    footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Session state init ────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        # CV pipeline
        "stage":            "upload",  # upload|process|review|template|edit|download|queue|admin
        "session_id":       None,
        "parsed_cv":        None,
        "offline_cv":       None,
        "ai_cv_general":    None,
        "ai_cv_jd":         None,
        "ats_report":       None,
        "linkedin_data":    None,
        "job_description":  "",
        "selected_template": DEFAULT_TEMPLATE,
        "filename":         "",
        "online":           False,
        "error":            None,
        # Service & pricing
        "service_tier":     "",     # "cv_only" | "cv_linkedin"
        "coupon_code":      "",
        "total_input_tokens":  0,
        "total_output_tokens": 0,
        # Certificate / document upload
        "uploaded_cv_bytes":      None,
        "certificates":           [],   # confirmed cert dicts merged into CV
        "classified_files":       [],   # [{filename, type, data}] from detect_document_type
        "additional_cv_data":     [],   # cv_data dicts from extra CV uploads
        "cert_input_tokens":      0,
        "cert_output_tokens":     0,
        # Review stage
        "review_decisions":       {},   # {key: {label, original, revised, status, text}}
        "review_editing":         [],   # list of section keys currently in edit mode
        # Accomplishments questions workflow
        "questions_list":         [],   # [{id, section_key, source_bullet, text}]
        "questions_generated":    False,
        "questions_sent":         False,
        "questions_token":        "",
        # Mandatory fields detection
        "missing_fields":         [],
        "recommended_missing":    [],
        # Inline editor
        "edited_cv_text":   "",
        "edited_cv":        None,       # parsed CVData dict after user applies edits
        # Personal details
        "dob":              "",         # date of birth (extracted or entered by user)
        # Template + colour
        "template_color":   "",         # hex colour override for selected template
        # Auth — JWT mode
        "auth_token":       None,
        "refresh_token":    None,
        "auth_user":        None,
        "auth_expires_at":  None,
        "auth_error":       None,
        # Auth — simple mode
        "simple_auth_ok":   False,
        "simple_auth_time": None,
        "simple_auth_user": None,
        "user_role":        "user",  # "user" | "admin"
        # Session persistence
        "session_already_parsed":  False,  # True when parsed_cv was restored from Supabase
        "session_restored_banner": False,  # True when a previous session was loaded on login
        "last_autosave":           None,   # datetime of last timer-based autosave
        # Session picker (multi-session history)
        "show_session_picker":     False,
        "pending_session_list":    [],
        # Error log
        "error_log":          [],   # [{code, detail, stage, timestamp}]
        # Sidebar collapse state
        "sidebar_collapsed":  False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_state()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _api_login(username: str, password: str) -> dict | None:
    """POST to FastAPI /api/auth/login. Returns token dict or None on failure."""
    try:
        r = httpx.post(
            f"{API_BASE_URL}/api/auth/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        st.session_state.auth_error = r.json().get("detail", "Login failed")
        return None
    except Exception as e:
        st.session_state.auth_error = f"Cannot reach auth server: {e}"
        return None


def _api_logout():
    """POST to FastAPI /api/auth/logout with the current token."""
    token = st.session_state.auth_token
    if not token:
        return
    try:
        httpx.post(
            f"{API_BASE_URL}/api/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except Exception:
        pass  # Best-effort logout


def _api_refresh() -> bool:
    """Try to refresh the access token. Returns True on success."""
    refresh = st.session_state.refresh_token
    if not refresh:
        return False
    try:
        r = httpx.post(
            f"{API_BASE_URL}/api/auth/refresh",
            json={"refresh_token": refresh},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            st.session_state.auth_token = data["access_token"]
            st.session_state.refresh_token = data["refresh_token"]
            st.session_state.auth_expires_at = data["expires_at"]
            return True
    except Exception:
        pass
    return False


def _session_is_valid() -> bool:
    """Return True if the current session token is still valid."""
    expires_at = st.session_state.auth_expires_at
    if not expires_at or not st.session_state.auth_token:
        return False
    try:
        exp = datetime.fromisoformat(expires_at).replace(tzinfo=timezone.utc)
        remaining = (exp - datetime.now(timezone.utc)).total_seconds()
        # Auto-refresh when < 15 minutes remain
        if 0 < remaining < 900:
            _api_refresh()
        return remaining > 0
    except Exception:
        return False


def _session_remaining_str() -> str:
    expires_at = st.session_state.auth_expires_at
    if not expires_at:
        return ""
    try:
        exp = datetime.fromisoformat(expires_at).replace(tzinfo=timezone.utc)
        secs = int((exp - datetime.now(timezone.utc)).total_seconds())
        if secs <= 0:
            return "Expired"
        h, m = divmod(secs // 60, 60)
        if h:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return ""


def render_login():
    """Full-page login form. Only shown in AUTH_ENABLED mode."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"<h1 style='text-align:center'>📄 {APP_NAME}</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:#666'>Sign in to continue</p>",
                    unsafe_allow_html=True)
        st.divider()

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="your.username")
            password = st.text_input("Password", type="password", placeholder="••••••••••")
            submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

        if submitted:
            if not username or not password:
                st.error("Please enter your username and password.")
            else:
                with st.spinner("Signing in..."):
                    result = _api_login(username, password)
                if result:
                    st.session_state.auth_token = result["access_token"]
                    st.session_state.refresh_token = result["refresh_token"]
                    st.session_state.auth_expires_at = result["expires_at"]
                    # Fetch user info
                    try:
                        me = httpx.get(
                            f"{API_BASE_URL}/api/auth/me",
                            headers={"Authorization": f"Bearer {result['access_token']}"},
                            timeout=5,
                        ).json()
                        st.session_state.auth_user = me.get("user", {})
                    except Exception:
                        st.session_state.auth_user = {"username": username}
                    st.session_state.auth_error = None
                    st.rerun()

        if st.session_state.auth_error:
            st.error(st.session_state.auth_error)

        st.divider()
        st.caption("Protected by ReviZoR FranK — Unauthorized access is prohibited.")


# ── Online check ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def _check_online() -> bool:
    from revizor_frank.core.sync_manager import is_online
    return is_online()


# ── Session ID helpers ────────────────────────────────────────────────────────

def _make_upload_session_id(username: str, filename: str) -> str:
    """Return a short deterministic session ID derived from username + upload timestamp.

    Using current timestamp at minute precision: same user re-uploading the same
    file within the same minute gets the same ID (deduplication window), but a
    new upload the next minute gets a fresh ID.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    raw = f"{username.lower()}:{filename}:{ts}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Session save helper ───────────────────────────────────────────────────────

def _autosave_session() -> None:
    """Save current session to Supabase. Silent fail — never raises."""
    username = (st.session_state.get("simple_auth_user") or
                (st.session_state.get("auth_user") or {}).get("username", ""))
    if not username:
        return
    try:
        from revizor_frank.storage import supabase_db as _sdb
        _sdb.save_session(username, dict(st.session_state))
    except Exception:
        pass


# ── Stage navigation ─────────────────────────────────────────────────────────

def _go_to_stage(stage: str):
    """Navigate to a stage, push browser history, and auto-save session."""
    st.session_state.stage = stage
    st.query_params["stage"] = stage
    username = (st.session_state.get("simple_auth_user") or
                (st.session_state.get("auth_user") or {}).get("username", ""))
    if username:
        try:
            from revizor_frank.storage import supabase_db as _sdb
            _saved = _sdb.save_session(username, dict(st.session_state))
            if _saved:
                st.toast("Progress saved", icon="✅")
        except Exception:
            pass
    st.rerun()


# ── Navigation helpers ────────────────────────────────────────────────────────

_STAGE_ORDER = [
    "select_service",
    "upload",
    "upload_certs",
    "review_changes",
    "select_template",
    "results",
]

# Hardcoded per-stage back destinations (not inferred from _STAGE_ORDER).
# full_preview sits between review_changes and select_template in the back chain.
_PREV_STAGE: dict[str, str] = {
    "upload":          "select_service",
    "upload_certs":    "upload",
    "review_changes":  "upload_certs",
    "full_preview":    "review_changes",
    "select_template": "full_preview",
    "results":         "select_template",
}
_STAGE_LABELS = {
    "select_service": "Service",
    "upload": "Upload",
    "upload_certs": "Certificates",
    "review_changes": "Review",
    "select_template": "Template",
    "results": "Download",
}


def _can_advance_from(stage: str) -> bool:
    """Return True if the user can advance from this stage via the top nav."""
    if stage == "select_service":
        return bool(st.session_state.get("service_tier"))
    if stage == "upload":
        return bool(st.session_state.get("uploaded_cv_bytes"))
    if stage == "upload_certs":
        return True
    if stage == "review_changes":
        decisions = st.session_state.get("review_decisions", {})
        return bool(decisions) and all(
            d["status"] in ("approved", "edited") for d in decisions.values()
        )
    if stage == "select_template":
        return True
    return False


def _start_over():
    """Clear all CV state, preserve auth, go to select_service."""
    keep = (
        "auth_token", "refresh_token", "auth_user", "auth_expires_at", "auth_error",
        "simple_auth_ok", "simple_auth_time", "simple_auth_user", "user_role",
    )
    auth_keys = {k: st.session_state[k] for k in keep if k in st.session_state}
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.session_state.update(auth_keys)
    st.query_params["stage"] = "upload"
    st.rerun()


def _render_top_nav():
    """Navigation is now handled by the sidebar — this function is a no-op."""
    pass


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    """Persistent collapsible navigation sidebar."""
    _collapsed = st.session_state.get("sidebar_collapsed", False)

    with st.sidebar:
        # ── Collapse toggle ───────────────────────────────────────────────────
        _toggle_label = "◀" if not _collapsed else "▶"
        if st.button(_toggle_label, key="sidebar_toggle", help="Collapse / expand sidebar"):
            st.session_state.sidebar_collapsed = not _collapsed
            st.rerun()

        if not _collapsed:
            st.markdown(f"## 📄 {APP_NAME}")
            st.caption(f"v{APP_VERSION}")

        st.divider()

        # ── Auth info — simple mode ───────────────────────────────────────────
        if SIMPLE_AUTH and st.session_state.get("simple_auth_ok"):
            login_time = st.session_state.get("simple_auth_time")
            if login_time:
                elapsed   = datetime.now(timezone.utc) - login_time
                remaining = timedelta(hours=SESSION_TIMEOUT_HOURS) - elapsed
                rem_h, rem_m = divmod(int(remaining.total_seconds()) // 60, 60)
                rem_str = f"{rem_h}h {rem_m}m" if rem_h else f"{rem_m}m"
                color   = "green" if rem_h >= 1 else "orange"
            else:
                rem_str, color = "—", "grey"

            if not _collapsed:
                st.markdown(f"**{st.session_state.get('simple_auth_user', 'user')}**")
                st.caption(f"Session: :{color}[{rem_str}]")
            if st.button("⏏" if _collapsed else "Sign Out",
                         key="sidebar_signout", use_container_width=True):
                st.session_state.simple_auth_ok   = False
                st.session_state.simple_auth_time = None
                st.rerun()
            st.divider()

        # ── Auth info — JWT mode ──────────────────────────────────────────────
        elif AUTH_ENABLED and st.session_state.auth_user:
            user = st.session_state.auth_user
            remaining = _session_remaining_str()
            if not _collapsed:
                st.markdown(
                    f"**{user.get('username', '')}**  "
                    f"`{user.get('role', 'user').upper()}`"
                )
                if remaining:
                    color = ("red" if remaining == "Expired"
                             else "orange" if "m" in remaining and "h" not in remaining
                             else "green")
                    st.caption(f"Session: :{color}[{remaining}]")
            if st.button("⏏" if _collapsed else "Sign Out",
                         key="sidebar_signout_jwt", use_container_width=True):
                _api_logout()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
            st.divider()

        # ── Connection status ─────────────────────────────────────────────────
        online = _check_online()
        st.session_state.online = online
        if not _collapsed:
            if online:
                st.success(f"🟢 {S['status_online']}")
            elif ANTHROPIC_API_KEY:
                st.warning("🟡 API key found but no internet")
            else:
                st.info(f"⚪ {S['status_offline']}")

        # ── Active candidate card ─────────────────────────────────────────────
        if not _collapsed:
            _filename = st.session_state.get("filename") or "No file yet"
            _parsed   = bool(st.session_state.get("parsed_cv"))
            _ai       = bool(st.session_state.get("ai_cv_general"))
            _decisions = st.session_state.get("review_decisions", {})
            _rev_done  = (bool(_decisions) and
                          all(d["status"] in ("approved", "edited")
                              for d in _decisions.values()))
            _tmpl_set  = bool(st.session_state.get("selected_template"))
            _dl_done   = st.session_state.get("stage") in ("download", "results")
            _stages_n  = sum([_parsed, _ai, _rev_done, _tmpl_set, _dl_done])

            _fn_display = _filename[:28] + "…" if len(_filename) > 28 else _filename
            st.markdown(f"**{_fn_display}**")
            st.progress(_stages_n / 5)
            st.divider()

        # ── CANDIDATES section ────────────────────────────────────────────────
        if not _collapsed:
            st.markdown(
                "<p style='font-size:0.7rem;font-weight:700;color:#888;"
                "text-transform:uppercase;letter-spacing:0.08em;margin-bottom:2px'>"
                "CANDIDATES</p>",
                unsafe_allow_html=True,
            )

        _stage = st.session_state.get("stage", "upload")
        _session_count = len(st.session_state.get("pending_session_list", []))
        _queue_badge = f" ({_session_count})" if _session_count else ""
        _queue_label = "👥" if _collapsed else f"👥 Queue{_queue_badge}"
        if st.button(_queue_label, key="nav_queue", use_container_width=True,
                     type="primary" if _stage == "queue" else "secondary"):
            _go_to_stage("queue")

        # ── CURRENT CV section ────────────────────────────────────────────────
        if not _collapsed:
            st.markdown(
                "<p style='font-size:0.7rem;font-weight:700;color:#888;"
                "text-transform:uppercase;letter-spacing:0.08em;"
                "margin-top:8px;margin-bottom:2px'>CURRENT CV</p>",
                unsafe_allow_html=True,
            )

        # Recompute badges (collapsed mode shares same vars)
        _parsed  = bool(st.session_state.get("parsed_cv"))
        _ai      = bool(st.session_state.get("ai_cv_general"))
        _decisions = st.session_state.get("review_decisions", {})
        _rev_done  = (bool(_decisions) and
                      all(d["status"] in ("approved", "edited")
                          for d in _decisions.values()))

        # Upload
        _up_badge = " ✅" if _parsed else " ⏳"
        _up_label = "📤" if _collapsed else f"📤 Upload{_up_badge}"
        if st.button(_up_label, key="nav_upload", use_container_width=True,
                     type="primary" if _stage == "upload" else "secondary"):
            _go_to_stage("upload")

        # Processing
        if _stage == "process":
            _proc_badge = " 🔄"
        elif _ai:
            _proc_badge = " ✅"
        else:
            _proc_badge = " ⏳"
        _proc_label = "⚙️" if _collapsed else f"⚙️ Processing{_proc_badge}"
        if st.button(_proc_label, key="nav_process", use_container_width=True,
                     type="primary" if _stage == "process" else "secondary"):
            _go_to_stage("process")

        # Review
        if not _ai:
            _rev_badge = " 🔒"
        elif _decisions:
            _approved_n = sum(1 for d in _decisions.values()
                              if d["status"] in ("approved", "edited"))
            _rev_badge = f" {_approved_n}/{len(_decisions)} ✅"
        else:
            _rev_badge = " ⏳"
        _rev_label = "🔍" if _collapsed else f"🔍 Review{_rev_badge}"
        if st.button(_rev_label, key="nav_review", use_container_width=True,
                     type="primary" if _stage == "review" else "secondary"):
            _go_to_stage("review")

        # Template
        _tmpl_badge = " ✅" if st.session_state.get("selected_template") else " ⏳"
        _tmpl_label = "🎨" if _collapsed else f"🎨 Template{_tmpl_badge}"
        if st.button(_tmpl_label, key="nav_template", use_container_width=True,
                     type="primary" if _stage == "template" else "secondary"):
            _go_to_stage("template")

        # Edit
        _edit_badge = " ✅" if _ai else " ⏳"
        _edit_label = "✏️" if _collapsed else f"✏️ Edit{_edit_badge}"
        if st.button(_edit_label, key="nav_edit", use_container_width=True,
                     type="primary" if _stage == "edit" else "secondary"):
            _go_to_stage("edit")

        # Download & Send
        _dl_badge = " ✅" if _rev_done else " 🔒"
        _dl_label = "⬇️" if _collapsed else f"⬇️ Download & Send{_dl_badge}"
        if st.button(_dl_label, key="nav_download", use_container_width=True,
                     type="primary" if _stage in ("download", "results") else "secondary"):
            _go_to_stage("download")

        # ── Bottom actions ────────────────────────────────────────────────────
        st.divider()
        if not _collapsed:
            if st.button("📂 All CVs", use_container_width=True, key="sidebar_allcvs"):
                _go_to_stage("queue")
        if st.button("➕" if _collapsed else "➕ New CV",
                     key="sidebar_new_cv", use_container_width=True, type="primary"):
            _start_over()

        # ── Admin ─────────────────────────────────────────────────────────────
        if st.session_state.get("user_role") == "admin":
            st.divider()
            _adm_label = "🛠" if _collapsed else "🛠 Admin Dashboard"
            if st.button(_adm_label, key="sidebar_admin", use_container_width=True):
                _go_to_stage("admin")

        if not _collapsed:
            st.divider()
            st.caption("ReviZoR FranK — ReviZoR HR Platform")


# ── Upload stage (service tier + file upload + cert expander) ────────────────

def render_upload():
    st.markdown(f"# 📄 {APP_NAME}")
    st.markdown(f"*{S['app_tagline']}*")

    # ── Session-restored banner ───────────────────────────────────────────────
    if st.session_state.get("session_restored_banner"):
        _fn = st.session_state.get("filename", "your previous CV")
        st.info(
            f"👋 Welcome back — your previous session has been restored "
            f"(*{_fn}*). Start a new CV or continue below."
        )
        if st.button("Dismiss", key="dismiss_restore_banner"):
            st.session_state.session_restored_banner = False
            st.rerun()

    st.divider()

    # ── Service tier toggle ───────────────────────────────────────────────────
    st.markdown("### Select Service")
    _tier = st.session_state.get("service_tier", "")
    _t1, _t2 = st.columns(2)
    with _t1:
        if st.button(
            "📄 CV Only  ($7.50)",
            use_container_width=True,
            type="primary" if _tier == "cv_only" else "secondary",
            key="tier_toggle_cv",
        ):
            st.session_state.service_tier = "cv_only"
            st.rerun()
    with _t2:
        if st.button(
            "📄 + 🔗 CV + LinkedIn  ($10.00)",
            use_container_width=True,
            type="primary" if _tier == "cv_linkedin" else "secondary",
            key="tier_toggle_linkedin",
        ):
            st.session_state.service_tier = "cv_linkedin"
            st.rerun()

    st.divider()

    # ── CV file upload ────────────────────────────────────────────────────────
    col1, col2 = st.columns([3, 2], gap="large")

    with col1:
        st.markdown(f"### {S['upload_header']}")
        uploaded = st.file_uploader(
            S["upload_instruction"],
            type=["pdf", "docx", "txt"],
            label_visibility="visible",
            key="cv_file_uploader",
        )

        st.markdown(f"### {S['upload_jd_label']}")
        jd = st.text_area(
            S["upload_jd_help"],
            placeholder=S["upload_jd_placeholder"],
            height=200,
            label_visibility="visible",
            value=st.session_state.get("job_description", ""),
            key="upload_jd_area",
        )

        ready = uploaded is not None
        upload_btn = st.button(
            f"📥 {S['upload_btn']}",
            disabled=not ready,
            type="secondary",
            use_container_width=True,
            key="upload_save_btn",
        )
        if not ready:
            st.caption(S["err_no_file"])

    with col2:
        st.markdown("### How it works")
        st.markdown("""
**1. Upload** your CV in any format

**2. Analyze** — instant ATS score + issue report

**3. Optimize** — AI rewrites for maximum impact
*(requires internet + API key)*

**4. Download** in 6 formats:
- Word (.docx)
- OpenDocument (.odt)
- PDF (.pdf)
- Image (.png)
- Plain text (.txt)
- LinkedIn copy-paste (.txt)

**5. LinkedIn** — all profile sections ready to paste

---
**Offline mode:** Full ATS analysis and template-based
improvements work without internet.

**Online mode:** Claude AI rewrites every bullet, fixes
language, optimizes for your target role.
        """)

    if upload_btn and uploaded:
        st.session_state.filename = uploaded.name
        st.session_state.uploaded_cv_bytes = uploaded.getvalue()
        st.session_state.job_description = jd.strip()
        _upload_username = (
            st.session_state.get("simple_auth_user") or
            (st.session_state.get("auth_user") or {}).get("username", "anon")
        )
        st.session_state.session_id = _make_upload_session_id(_upload_username, uploaded.name)
        st.session_state.session_already_parsed = False
        st.session_state.certificates = []
        st.session_state.classified_files = []
        st.session_state.additional_cv_data = []
        st.session_state.cert_input_tokens = 0
        st.session_state.cert_output_tokens = 0
        st.session_state.review_decisions   = {}
        st.session_state.review_editing     = []
        st.session_state.edited_cv          = None
        st.session_state.edited_cv_text     = ""
        st.session_state.dob                = ""
        st.session_state.questions_list      = []
        st.session_state.questions_generated = False
        st.session_state.questions_sent      = False
        st.session_state.questions_token     = ""
        st.session_state.missing_fields      = []
        st.session_state.recommended_missing = []
        try:
            import io as _io
            from revizor_frank.core import cv_parser as _cvp
            _quick, _, _ = _cvp.parse_cv(
                _io.BytesIO(uploaded.getvalue()), uploaded.name,
                api_key="", check_doc_type=False,
            )
            basic_missing = _cvp.check_required_fields(_quick)
            st.session_state.missing_fields = basic_missing
        except Exception:
            pass
        st.rerun()  # Stay on upload page — show cert expander

    # ── Required-fields warning ───────────────────────────────────────────────
    _missing = st.session_state.get("missing_fields") or []
    if _missing:
        st.warning(
            "The following sections were not detected in the uploaded CV:\n\n"
            + "\n".join(f"- {f}" for f in _missing)
        )

    # ── Certificate & extras expander (shown once a CV is uploaded) ──────────
    if st.session_state.get("uploaded_cv_bytes"):
        st.info(f"✅ **CV loaded:** `{st.session_state.get('filename', '')}`")

        with st.expander("📜 Add certificates or extra pages (optional)", expanded=False):
            st.caption(
                "Upload any certificates or additional CV files. "
                "Claude will detect what each file is — certificates are added to your CV, "
                "extra CV pages are merged in automatically."
            )
            uploaded_files = st.file_uploader(
                "Files (PDF, JPG, PNG, DOCX, TXT)",
                type=["pdf", "jpg", "jpeg", "png", "docx", "txt"],
                accept_multiple_files=True,
                key="cert_uploader",
                label_visibility="collapsed",
            )
            if uploaded_files:
                if st.button("🔍 Classify & Extract", type="secondary",
                             use_container_width=True):
                    if not _check_online():
                        st.warning("File classification requires internet. "
                                   "You can still proceed without adding files.")
                    else:
                        _classified = []
                        _total_in, _total_out = 0, 0
                        with st.spinner(f"Classifying {len(uploaded_files)} file(s)…"):
                            try:
                                from revizor_frank.core import cert_extractor
                                for uf in uploaded_files:
                                    file_bytes = uf.getvalue()
                                    doc_type, dt_in, dt_out = cert_extractor.detect_document_type(
                                        file_bytes, uf.name
                                    )
                                    _total_in += dt_in; _total_out += dt_out
                                    if doc_type == "CV":
                                        cv_data, cv_in, cv_out = cert_extractor.extract_cv_data_from_file(
                                            file_bytes, uf.name
                                        )
                                        _total_in += cv_in; _total_out += cv_out
                                        _classified.append({"filename": uf.name, "type": "CV", "data": cv_data})
                                    else:
                                        cert, c_in, c_out = cert_extractor.extract_certificate(
                                            file_bytes, uf.name
                                        )
                                        cert["_filename"] = uf.name
                                        _total_in += c_in; _total_out += c_out
                                        _classified.append({"filename": uf.name, "type": "CERTIFICATE", "data": cert})
                            except Exception as e:
                                st.error(f"Classification failed: {e}")
                        if _classified:
                            st.session_state.classified_files = _classified
                            st.session_state.cert_input_tokens  = (
                                st.session_state.get("cert_input_tokens", 0) + _total_in
                            )
                            st.session_state.cert_output_tokens = (
                                st.session_state.get("cert_output_tokens", 0) + _total_out
                            )
                            st.rerun()

            classified = st.session_state.get("classified_files", [])
            if classified:
                st.divider()
                st.markdown("#### ✏️ Review Detected Files")
                cv_items   = [c for c in classified if c["type"] == "CV"]
                cert_items = [c for c in classified if c["type"] == "CERTIFICATE"]
                for item in cv_items:
                    st.success(f"📄 CV/Resume detected: **{item['filename']}**")
                    _cv = item["data"]
                    _name = _cv.get("name") or ""
                    _exp_count  = len(_cv.get("experience", []))
                    _edu_count  = len(_cv.get("education", []))
                    _skill_cats = len(_cv.get("skills", {}).get("categories", []))
                    st.caption(
                        f"{_name + ' · ' if _name else ''}"
                        f"{_exp_count} experience entr{'y' if _exp_count == 1 else 'ies'}, "
                        f"{_edu_count} education entr{'y' if _edu_count == 1 else 'ies'}, "
                        f"{_skill_cats} skill categor{'y' if _skill_cats == 1 else 'ies'} — "
                        "will be merged into your CV automatically."
                    )
                if cert_items:
                    st.markdown("**Edit certificate details if needed:**")
                    with st.form("cert_confirm_form"):
                        edited_certs = []
                        for i, item in enumerate(cert_items):
                            cert = item["data"]
                            label = cert.get("name") or item["filename"]
                            st.markdown(f"**📜 {label}** — `{item['filename']}`")
                            col_a, col_b = st.columns(2)
                            with col_a:
                                c_name   = st.text_input("Certificate Name",    value=cert.get("name", ""),          key=f"cname_{i}")
                                c_issuer = st.text_input("Issuing Organisation", value=cert.get("issuer", ""),        key=f"ciss_{i}")
                            with col_b:
                                c_date   = st.text_input("Issue Date",           value=cert.get("date", ""),          key=f"cdate_{i}")
                                c_id     = st.text_input("Credential ID (opt.)", value=cert.get("credential_id", ""), key=f"ccid_{i}")
                            edited_certs.append({"name": c_name, "issuer": c_issuer,
                                                 "date": c_date, "credential_id": c_id})
                            if i < len(cert_items) - 1:
                                st.divider()
                        col_ok, col_skip_btn = st.columns(2)
                        with col_ok:
                            confirmed = st.form_submit_button(
                                "✅ Confirm Certificates", type="primary", use_container_width=True
                            )
                        with col_skip_btn:
                            skipped_form = st.form_submit_button("Skip", use_container_width=True)
                    if confirmed:
                        st.session_state.certificates = [
                            {"name": c["name"], "issuer": c["issuer"],
                             "date": c["date"],  "credential_id": c.get("credential_id", "")}
                            for c in edited_certs if c.get("name")
                        ]
                        st.session_state.additional_cv_data = [item["data"] for item in cv_items]
                        st.session_state.classified_files = []
                        st.rerun()
                    elif skipped_form:
                        st.session_state.additional_cv_data = [item["data"] for item in cv_items]
                        st.session_state.classified_files = []
                        st.rerun()
                else:
                    if st.button("✅ Confirm Extra Pages", type="secondary", use_container_width=True):
                        st.session_state.additional_cv_data = [item["data"] for item in cv_items]
                        st.session_state.classified_files = []
                        st.rerun()

        # ── Proceed to optimization ───────────────────────────────────────────
        st.divider()
        if not st.session_state.get("service_tier"):
            st.warning("Please select a service tier above before optimizing.")
        else:
            if st.button("🚀 Optimize CV →", type="primary", use_container_width=True,
                         key="proceed_to_optimize"):
                st.session_state.job_description = st.session_state.get(
                    "upload_jd_area", st.session_state.get("job_description", "")
                ).strip()
                _go_to_stage("process")


# ── Processing pipeline ───────────────────────────────────────────────────────

def _run_pipeline():
    """Run the full parse → analyze → optimize → LinkedIn pipeline."""
    from revizor_frank.core import cv_parser, cv_analyzer, ats_engine
    from revizor_frank.core import linkedin_gen
    from revizor_frank.storage import database as db

    tier = st.session_state.get("service_tier", "cv_linkedin")
    include_linkedin = (tier != "cv_only")

    cv_bytes = st.session_state.get("uploaded_cv_bytes")
    filename = st.session_state.get("filename", "cv")

    if not cv_bytes:
        _go_to_stage("upload")
        return

    # Explicit API key check — required for image-based PDF vision fallback
    if not ANTHROPIC_API_KEY or not ANTHROPIC_API_KEY.strip():
        st.error(
            "**API key not found in secrets.** "
            "Add `ANTHROPIC_API_KEY` to your Streamlit secrets (Settings → Secrets). "
            "It is required to process CVs, including image-based PDFs."
        )
        st.session_state.stage = "upload"
        return

    st.session_state.error = None
    st.session_state.total_input_tokens = 0
    st.session_state.total_output_tokens = 0

    progress = st.progress(0, text="Starting...")
    status = st.empty()

    try:
        # 1. Parse
        # ── Skip-reparse guard: if session was restored from Supabase and the
        #    session_id matches the current upload, reuse the saved parsed_cv to
        #    avoid burning API tokens on a CV we have already processed.
        _saved_parsed = st.session_state.get("parsed_cv") if st.session_state.get("session_already_parsed") else None
        if _saved_parsed and st.session_state.get("session_id") and st.session_state.get("filename") == filename:
            status.info("⚙️ Reusing parsed CV from previous session (no re-parsing needed)…")
            parsed = _saved_parsed
            pdf_in_tok, pdf_out_tok = 0, 0
            st.session_state.session_already_parsed = False  # consume the flag
        else:
            status.info(f"⚙️ {S['parsing_cv']}")
            file_bytes = io.BytesIO(cv_bytes)
            from revizor_frank.core.cv_parser import NonCVDocumentError
            try:
                parsed, pdf_in_tok, pdf_out_tok = cv_parser.parse_cv(
                    file_bytes, filename, api_key=ANTHROPIC_API_KEY
                )
            except NonCVDocumentError:
                progress.empty()
                status.empty()
                st.error(
                    "⚠️ This file doesn't appear to be a CV or resume. "
                    "Please upload your CV file instead."
                )
                st.session_state.stage = "upload"
                return
        # Accumulate vision-extraction tokens into the cert bucket
        st.session_state.cert_input_tokens  = st.session_state.get("cert_input_tokens",  0) + pdf_in_tok
        st.session_state.cert_output_tokens = st.session_state.get("cert_output_tokens", 0) + pdf_out_tok

        # Merge user-confirmed certificates into parsed CV before any processing
        confirmed_certs = st.session_state.get("certificates", [])
        if confirmed_certs:
            existing_names = {c.get("name", "").lower() for c in parsed.get("certifications", [])}
            for cert in confirmed_certs:
                if cert.get("name", "").lower() not in existing_names:
                    parsed.setdefault("certifications", []).append({
                        "name": cert.get("name", ""),
                        "issuer": cert.get("issuer", ""),
                        "date": cert.get("date", ""),
                    })
        # DOB: prefer manually entered value from upload_certs stage
        user_dob = st.session_state.get("dob", "").strip()
        if user_dob:
            parsed["dob"] = user_dob
        elif parsed.get("dob"):
            st.session_state.dob = parsed["dob"]  # reflect extracted value back

        # Merge any additional CV files uploaded in the cert stage
        additional_cv_data = st.session_state.get("additional_cv_data", [])
        if additional_cv_data:
            from revizor_frank.core.cert_extractor import merge_cv_data
            for extra in additional_cv_data:
                parsed = merge_cv_data(parsed, extra)

        st.session_state.parsed_cv = parsed

        # Update missing_fields from the full parse (overrides pre-flight result)
        from revizor_frank.core import cv_parser as _cvp_full
        st.session_state.missing_fields = _cvp_full.check_required_fields(parsed)

        progress.progress(20, text=S["parsing_cv"])

        # 2. Create DB session
        session_id = db.create_session(filename, parsed.get("raw_text", ""))
        st.session_state.session_id = session_id
        db.update_session(session_id, parsed_data=parsed,
                          job_description=st.session_state.job_description,
                          template=st.session_state.selected_template)

        # 3. Offline improvement
        status.info(f"⚙️ {S['optimizing_offline']}")
        offline_cv = cv_analyzer.improve_offline(parsed)
        st.session_state.offline_cv = offline_cv
        db.update_session(session_id, offline_cv=offline_cv)
        progress.progress(40, text=S["optimizing_offline"])

        # 4. ATS analysis (run on offline-improved CV)
        status.info(f"⚙️ {S['analyzing_ats']}")
        ats_report = ats_engine.analyze(offline_cv, st.session_state.job_description)
        st.session_state.ats_report = ats_report
        db.update_session(session_id, ats_report=ats_report)
        progress.progress(60, text=S["analyzing_ats"])

        # 5. Claude AI optimization (online only)
        online = _check_online()
        total_in, total_out = 0, 0

        if online:
            try:
                from revizor_frank.core import cv_optimizer
                status.info(f"🤖 {S['optimizing_ai']} (General ATS)...")
                general_cv, in_tok, out_tok = cv_optimizer.optimize_general(offline_cv)
                total_in += in_tok; total_out += out_tok
                st.session_state.ai_cv_general = general_cv
                db.update_session(session_id, ai_cv_general=general_cv)
                progress.progress(75, text="General ATS optimization complete")

                jd_cv = None
                if st.session_state.job_description:
                    status.info(f"🤖 {S['optimizing_ai']} (JD-Tailored)...")
                    jd_cv, in_tok, out_tok = cv_optimizer.optimize_jd_tailored(
                        parsed, st.session_state.job_description, general_cv
                    )
                    total_in += in_tok; total_out += out_tok
                    st.session_state.ai_cv_jd = jd_cv
                    db.update_session(session_id, ai_cv_jd=jd_cv)
                progress.progress(85, text="AI optimization complete")

                if include_linkedin:
                    # LinkedIn via Claude
                    status.info(f"🤖 {S['generating_linkedin']}...")
                    linkedin, in_tok, out_tok = cv_optimizer.generate_linkedin(
                        parsed, general_cv, st.session_state.job_description
                    )
                    total_in += in_tok; total_out += out_tok
                    st.session_state.linkedin_data = linkedin
                    db.update_session(session_id, linkedin_data=linkedin,
                                      sync_status="synced", ai_enhanced=1)
                else:
                    db.update_session(session_id, sync_status="synced", ai_enhanced=1)

            except Exception as e:
                st.session_state.error = f"{S['err_api_failed']} ({e})"
                online = False

        if not online and include_linkedin:
            # Offline LinkedIn
            status.info(f"⚙️ {S['generating_linkedin']}...")
            linkedin = linkedin_gen.generate_offline(offline_cv)
            st.session_state.linkedin_data = linkedin
            db.update_session(session_id, linkedin_data=linkedin,
                              sync_status="queued")

        st.session_state.total_input_tokens = total_in
        st.session_state.total_output_tokens = total_out

        # 6. Save to Supabase
        try:
            from revizor_frank.storage import supabase_db
            from revizor_frank.exporters.txt_exporter import export_txt as _export_txt_fn
            import tempfile as _tmp

            general_cv_data = st.session_state.ai_cv_general or st.session_state.offline_cv or {}
            _txt_path = str(Path(_tmp.gettempdir()) / f"revizor_txt_{uuid.uuid4().hex}.txt")
            _export_txt_fn(general_cv_data, _txt_path)
            with open(_txt_path, "r", encoding="utf-8") as _f:
                revised_text = _f.read()
            if os.path.exists(_txt_path):
                os.unlink(_txt_path)

            supabase_db.save_cv_run(
                session_id=str(session_id),
                original_cv_text=parsed.get("raw_text", ""),
                revised_cv_text=revised_text,
                linkedin_output=st.session_state.linkedin_data,
                tier=tier,
                price_usd=TIER_PRICES.get(tier, 0.0),
                coupon_code=st.session_state.get("coupon_code", ""),
                input_tokens=total_in,
                output_tokens=total_out,
                certificates=st.session_state.get("certificates") or None,
                cert_input_tokens=st.session_state.get("cert_input_tokens", 0),
                cert_output_tokens=st.session_state.get("cert_output_tokens", 0),
                dob=st.session_state.get("dob", ""),
            )
        except Exception:
            pass  # Supabase save is best-effort; never break the main flow

        progress.progress(100, text=S["done"])
        time.sleep(0.5)
        status.empty()
        progress.empty()

        # ── Mandatory fields check (run on AI output) ──────────────────────────
        _check_mandatory_fields()

        # Route to review stage when AI ran, otherwise go to template selection
        if st.session_state.get("ai_cv_general"):
            _init_review_state()
            _go_to_stage("review")
        else:
            _go_to_stage("template")

    except Exception as e:
        progress.empty()
        status.empty()
        st.session_state.stage = "upload"
        _err_str = str(e)
        _err_code = _err_str[:10] if _err_str.startswith("[RVZ-") else "RVZ-U001"
        st.session_state.setdefault("error_log", []).append({
            "code": _err_code,
            "detail": _err_str,
            "stage": st.session_state.get("stage", "processing"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        st.error(f"**{_err_code}** — {_err_str}")


# ── Mandatory fields check ───────────────────────────────────────────────────

_MANDATORY_FIELDS = {
    "name":       "Full name",
    "email":      "Professional email address",
    "phone":      "Phone number",
    "summary":    "Personal profile / professional summary",
    "experience": "Work experience (at least one role)",
    "education":  "Education (at least one entry)",
    "skills":     "Skills (at least one skill listed)",
}

_RECOMMENDED_FIELDS = {
    "linkedin": "LinkedIn profile URL",
}

_MISSING_QUESTIONS = {
    "Full name": "Could you confirm your full legal name as it should appear on your CV?",
    "Professional email address": "What is your professional email address?",
    "Phone number": "What is the best phone number to reach you on?",
    "Personal profile / professional summary": "Could you describe your professional background and career goals in 3–4 sentences?",
    "Work experience (at least one role)": "Please list your work history: job title, company name, dates, and main responsibilities for each role.",
    "Education (at least one entry)": "Please provide your educational background: degree, institution, and graduation year.",
    "Skills (at least one skill listed)": "What are your key professional skills, tools, and software you use regularly?",
}


def _check_mandatory_fields():
    """Populate session_state.missing_fields and recommended_missing from ai_cv_general."""
    cv = st.session_state.get("ai_cv_general") or {}
    missing = []
    for field, label in _MANDATORY_FIELDS.items():
        if field == "name":
            val = cv.get("name", "")
            if not val or any(val.lower().startswith(p) for p in
                              ("address", "tel", "mobile", "phone", "email")):
                missing.append(label)
        elif field == "summary":
            val = cv.get("summary", "")
            if not val or len(val.split()) < 20:
                missing.append(label)
        elif field == "experience":
            if not cv.get("experience"):
                missing.append(label)
        elif field == "education":
            if not cv.get("education"):
                missing.append(label)
        elif field == "skills":
            cats = cv.get("skills", {}).get("categories", [])
            if not any(c.get("items") for c in cats):
                missing.append(label)
        elif field == "phone":
            # phones is the list; phone is the backward-compat joined string
            phones = cv.get("phones") or (
                [p.strip() for p in cv["phone"].split("|") if p.strip()]
                if cv.get("phone") else []
            )
            if not phones:
                missing.append(label)
        else:
            if not cv.get(field, "").strip():
                missing.append(label)

    recommended_missing = [
        label for field, label in _RECOMMENDED_FIELDS.items()
        if not cv.get(field, "").strip()
    ]
    st.session_state.missing_fields = missing
    st.session_state.recommended_missing = recommended_missing


# ── Review stage helpers ──────────────────────────────────────────────────────

def _diff_html(old: str, new: str) -> str:
    """Return HTML string with word-level diff: additions green, deletions red strikethrough."""
    import difflib
    old_words = old.split()
    new_words = new.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    parts = []
    _ADD = 'background:#d4edda;color:#155724;border-radius:3px;padding:0 3px'
    _DEL = 'background:#f8d7da;color:#721c24;text-decoration:line-through;border-radius:3px;padding:0 3px'
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(" ".join(old_words[i1:i2]))
        elif tag == "insert":
            parts.append(f'<span style="{_ADD}">{" ".join(new_words[j1:j2])}</span>')
        elif tag == "delete":
            parts.append(f'<span style="{_DEL}">{" ".join(old_words[i1:i2])}</span>')
        elif tag == "replace":
            parts.append(f'<span style="{_DEL}">{" ".join(old_words[i1:i2])}</span> '
                         f'<span style="{_ADD}">{" ".join(new_words[j1:j2])}</span>')
    return " ".join(parts)


def _cv_section_text(cv: dict, section: str, idx: int = -1) -> str:
    """Convert one CV section (or entry at idx) to a plain-text string for display/editing."""
    if section == "summary":
        return str(cv.get("summary") or "")

    if section == "experience":
        exps = cv.get("experience", [])
        if idx < 0 or idx >= len(exps):
            return ""
        e = exps[idx]
        parts = []
        if e.get("title"):
            parts.append(e["title"])
        if e.get("company"):
            parts.append(e["company"])
        dates = f"{e.get('start_date', '')} – {e.get('end_date', '')}".strip(" –")
        if dates:
            parts.append(dates)
        if e.get("location"):
            parts.append(e["location"])
        bullets = e.get("bullets", [])
        if bullets:
            parts.append("\n".join(f"• {b}" for b in bullets))
        return "\n".join(parts)

    if section == "education":
        edus = cv.get("education", [])
        if idx < 0 or idx >= len(edus):
            return ""
        e = edus[idx]
        parts = [str(v) for v in [e.get("degree"), e.get("institution"),
                                   e.get("year"), e.get("honors"), e.get("gpa")] if v]
        return "\n".join(parts)

    if section == "skills":
        cats = cv.get("skills", {}).get("categories", [])
        parts = []
        for cat in cats:
            if cat.get("items"):
                parts.append(f"{cat['name']}: {', '.join(str(i) for i in cat['items'])}")
        return "\n".join(parts)

    if section == "certifications":
        certs = cv.get("certifications", [])
        return "\n".join(
            f"{c.get('name', '')} — {c.get('issuer', '')} {c.get('date', '')}".strip(" —")
            for c in certs if c.get("name")
        )

    if section == "training":
        items = cv.get("training", [])
        return "\n".join(
            f"{t.get('name', '')} — {t.get('organisation', '')} {t.get('date', '')}".strip(" —")
            for t in items if t.get("name")
        )

    if section == "languages":
        langs = cv.get("languages", [])
        return ", ".join(str(l) for l in langs) if langs else ""

    return str(cv.get(section) or "")


# ── Accomplishments questions helpers ─────────────────────────────────────────

def _extract_approx_items(decisions: dict) -> list[tuple[str, str]]:
    """Return (section_key, text_fragment) pairs where the AI revised text has ≈."""
    results = []
    for key, dec in decisions.items():
        text = dec.get("text", dec.get("revised", ""))
        for fragment in re.split(r"[\n\u2022\-\u2013\u2014]", text):
            fragment = fragment.strip()
            if "≈" in fragment and len(fragment) > 10:
                results.append((key, fragment))
    return results


def _generate_questions_batch(items: list[tuple[str, str]]) -> list[str]:
    """Call Claude to turn ≈-bearing bullets into friendly questions. One API call per item."""
    questions: list[str] = []
    in_tok = 0
    out_tok = 0
    for _key, fragment in items:
        if not ANTHROPIC_API_KEY:
            questions.append(
                f"Can you confirm or provide the actual figure for: "
                f"{fragment.replace('≈', '').strip()}?"
            )
            continue
        try:
            import anthropic as _anthropic
            _client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = _client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": (
                        f"This is an estimated accomplishment added to a CV: '{fragment}'. "
                        "Write a short, friendly question to ask the CV owner to confirm "
                        "or provide the real figure. Max 1 sentence."
                    ),
                }],
            )
            questions.append(resp.content[0].text.strip())
            if resp.usage:
                in_tok += resp.usage.input_tokens
                out_tok += resp.usage.output_tokens
        except Exception:
            questions.append(
                f"Can you confirm or provide the actual figure for: "
                f"{fragment.replace('≈', '').strip()}?"
            )
    # Accumulate token usage into cert bucket
    if in_tok or out_tok:
        st.session_state.cert_input_tokens  = st.session_state.get("cert_input_tokens",  0) + in_tok
        st.session_state.cert_output_tokens = st.session_state.get("cert_output_tokens", 0) + out_tok
    return questions


def _ensure_questions_generated():
    """Generate questions from ≈-bearing content on first call; no-op after."""
    if st.session_state.get("questions_generated"):
        return
    decisions = st.session_state.get("review_decisions", {})
    items = _extract_approx_items(decisions)
    if items:
        with st.spinner("Generating questions from estimated accomplishments…"):
            generated = _generate_questions_batch(items)
    else:
        generated = []
    questions_list = [
        {
            "id": uuid.uuid4().hex[:8],
            "section_key": key,
            "source_bullet": fragment,
            "text": q_text,
        }
        for (key, fragment), q_text in zip(items, generated)
    ]
    st.session_state.questions_list = questions_list
    st.session_state.questions_generated = True


def _render_questions_for_section(section_key: str):
    """Show questions inline in the diff view — read-only, no widgets."""
    qs = [q for q in st.session_state.get("questions_list", [])
          if q["section_key"] == section_key]
    if not qs:
        st.caption("_No estimated figures._")
        return
    for q in qs:
        st.markdown(
            f'<div style="background:#fffbea;border:1px solid #f0e68c;'
            f'border-radius:6px;padding:0.5rem 0.75rem;font-size:0.82rem;'
            f'margin-bottom:0.4rem">'
            f'❓ {q["text"]}'
            f'</div>',
            unsafe_allow_html=True,
        )
    st.caption("_Edit or send below ↓_")


def _send_questions_email(
    to_email: str,
    candidate_name: str,
    questions: list[dict],
) -> tuple[bool, str]:
    """Send questions to the candidate via SMTP (configured in st.secrets["smtp"]).

    Returns (success, error_message).
    """
    import smtplib
    import ssl
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        smtp_cfg = st.secrets.get("smtp", {})
    except Exception:
        smtp_cfg = {}

    host     = smtp_cfg.get("host", "")
    port     = int(smtp_cfg.get("port", 587))
    username = smtp_cfg.get("username", "")
    password = smtp_cfg.get("password", "")
    from_addr = smtp_cfg.get("from_address", username)

    if not (host and username and password):
        return False, "SMTP credentials not configured in st.secrets['smtp']."

    subject = f"Further information needed — {candidate_name}"
    body_lines = ["Hi,\n", "We are reviewing your CV and have a few questions:\n"]
    for i, q in enumerate(questions, 1):
        text = q.get("text", "").strip()
        if text:
            body_lines.append(f"{i}. {text}")
    body_lines.append("\nPlease reply to this email at your earliest convenience.\n")
    body = "\n".join(body_lines)

    msg = MIMEMultipart()
    msg["From"]    = from_addr
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(username, password)
            server.sendmail(from_addr, to_email, msg.as_string())
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _render_questions_panel():
    """Bottom-of-review panel: add questions, send to CV owner."""
    st.divider()
    st.markdown("### 📬 Questions for CV Owner")

    questions_list: list[dict] = st.session_state.get("questions_list", [])

    # ── Add manual question ──────────────────────────────────────────────────
    if st.button("➕ Add question"):
        new_id = uuid.uuid4().hex[:8]
        questions_list.append({
            "id": new_id,
            "section_key": "manual",
            "source_bullet": "",
            "text": "",
        })
        st.session_state.questions_list = questions_list
        st.session_state[f"q_chk_{new_id}"] = True
        st.session_state[f"q_txt_{new_id}"] = ""
        st.rerun()

    # Render all questions (flat list)
    checked_questions = []
    for q in questions_list:
        qid = q["id"]
        chk_key = f"q_chk_{qid}"
        txt_key = f"q_txt_{qid}"
        if chk_key not in st.session_state:
            st.session_state[chk_key] = True
        if txt_key not in st.session_state:
            st.session_state[txt_key] = q["text"]
        col_chk, col_txt = st.columns([1, 9])
        with col_chk:
            st.checkbox("", key=chk_key, label_visibility="collapsed")
        with col_txt:
            st.text_area("", key=txt_key, height=68, label_visibility="collapsed")
        if st.session_state[chk_key]:
            checked_questions.append({
                "id": qid,
                "text": st.session_state[txt_key],
                "source_bullet": q.get("source_bullet", ""),
            })

    if not checked_questions:
        st.info("No questions selected. Check boxes above or add a question.")
        return

    st.caption(f"{len(checked_questions)} question(s) will be sent.")

    # ── Already sent — show link again ───────────────────────────────────────
    if st.session_state.get("questions_sent") and st.session_state.get("questions_token"):
        _render_send_channels(st.session_state.questions_token)
        return

    # ── Send button ──────────────────────────────────────────────────────────
    if st.button("📤 Send to CV owner", type="primary"):
        # ── Email send ───────────────────────────────────────────────────────
        candidate_email = (
            (st.session_state.get("original_cv") or {}).get("email", "")
            or (st.session_state.get("edited_cv") or {}).get("email", "")
        ).strip()
        if not candidate_email:
            st.error("No candidate email found — please check the original CV.")
        else:
            candidate_name = (
                (st.session_state.get("original_cv") or {}).get("name", "")
                or (st.session_state.get("edited_cv") or {}).get("name", "Candidate")
            ).strip()
            _email_ok, _email_err = _send_questions_email(
                to_email=candidate_email,
                candidate_name=candidate_name,
                questions=checked_questions,
            )
            if _email_ok:
                st.session_state.questions_email_sent_to = candidate_email
            else:
                st.session_state.questions_email_error = _email_err

            # ── Supabase save + share channels (unchanged) ───────────────────
            token = uuid.uuid4().hex
            expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            from revizor_frank.storage import supabase_db as _sdb
            session_id = str(st.session_state.get("session_id") or "")
            ok = _sdb.save_owner_questions(
                session_id=session_id,
                token=token,
                questions=checked_questions,
                expires_at=expires,
            )
            if not ok:
                st.warning(
                    "Supabase is not configured. The link below will not work until "
                    "SUPABASE_URL and SUPABASE_ANON_KEY are set."
                )
            st.session_state.questions_token = token
            st.session_state.questions_sent  = True
            st.rerun()

    # Show email send result (persists across rerun)
    if st.session_state.get("questions_email_sent_to"):
        st.success(f"Questions sent to {st.session_state.questions_email_sent_to}.")
    if st.session_state.get("questions_email_error"):
        st.warning(
            f"Email delivery failed: {st.session_state.questions_email_error} "
            "— use the share link below to reach the candidate."
        )


def _render_send_channels(token: str):
    """Show share channel buttons + copy-link for the owner form."""
    base = APP_URL or "http://localhost:8501"
    link = f"{base}/?token={token}"
    message = (
        "Hi, I'm reviewing your CV and have a few quick questions to make sure "
        "everything is accurate. Please click the link below to answer — it only "
        f"takes a minute: {link}"
    )
    import urllib.parse
    enc_msg  = urllib.parse.quote(message)
    enc_link = urllib.parse.quote(link)
    enc_subj = urllib.parse.quote("A few questions about your CV")

    st.success("Questions saved! Share via:")
    st.code(link, language=None)

    channels = {
        "WhatsApp":  f"https://wa.me/?text={enc_msg}",
        "Telegram":  f"https://t.me/share/url?url={enc_link}&text={enc_msg}",
        "Email":     f"mailto:?subject={enc_subj}&body={enc_msg}",
        "LinkedIn":  f"https://www.linkedin.com/messaging/compose?body={enc_msg}",
    }
    cols = st.columns(len(channels) + 1)
    for col, (label, url) in zip(cols, channels.items()):
        with col:
            st.link_button(label, url, use_container_width=True)
            # Record preferred channel on first click (best-effort)
    with cols[-1]:
        if st.button("📋 Copy link", use_container_width=True):
            st.write(
                f"<script>navigator.clipboard.writeText('{link}')</script>",
                unsafe_allow_html=True,
            )
            st.toast("Link copied!")


def _clean_for_display(text: str) -> str:
    """Remove personal info lines that leak into section text."""
    skip = re.compile(
        r"^\s*[\u2022\uf0b7•\-]?\s*"
        r"(date\s+of\s+birth|place\s+of\s+birth|nationality|marital|gender|"
        r"religion|تاريخ|جنسية|الحالة)[^\n]*",
        re.I | re.M,
    )
    return skip.sub("", text).strip()


def _init_review_state():
    """Populate review_decisions from parsed_cv (original) vs ai_cv_general (revised).

    parsed_cv is the raw-parsed upload — the most faithful representation of the
    candidate's original document.  offline_cv has light rule-based edits (date
    normalisation, de-duplication) but the same structural content, so it is used
    as fallback.  ai_cv_general is always the "revised" side.
    """
    # Use parsed_cv as "original" — it has the unmodified content from the upload.
    # Prefer parsed_cv whenever it has any useful content (name or raw_text is
    # sufficient — do not require summary/experience since those may be empty
    # for DOCX files that lack section headings).
    # Fall back to offline_cv only if parsed_cv is entirely absent.
    _parsed   = st.session_state.get("parsed_cv") or {}
    _offline  = st.session_state.offline_cv or {}
    original  = _parsed if (_parsed.get("name") or _parsed.get("raw_text") or
                            _parsed.get("summary") or _parsed.get("experience")) else _offline
    revised   = st.session_state.ai_cv_general or _offline or {}

    decisions: dict = {}

    def _add(key, label, section, idx=-1):
        orig = _clean_for_display(_cv_section_text(original, section, idx))
        # Last resort for summary: try raw_text first, then structured fallback
        if not orig and section == "summary":
            _rt = original.get("raw_text", "")
            if _rt and len(_rt.strip()) > 100 and _is_usable_text(_rt):
                _email_re = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
                for _para in re.split(r"\n{2,}", _rt):
                    _clean = _para.strip()
                    if len(_clean.split()) >= 10 and not _email_re.search(_clean):
                        orig = _clean[:400]
                        break
            if not orig:
                # raw_text absent or unusable — pull summary from structured fields
                _plain = _cv_to_plain_text(original)
                if _plain:
                    orig = _plain[:400]
        rev  = _cv_section_text(revised,  section, idx)
        if rev:  # only add sections that actually have content
            decisions[key] = {
                "label": label, "original": orig, "revised": rev,
                "status": "pending", "text": rev,
            }

    _add("summary", "Summary", "summary")

    for i, exp in enumerate(revised.get("experience", [])):
        label = f"Experience: {exp.get('title', '')} @ {exp.get('company', '')}"
        _add(f"exp_{i}", label, "experience", i)

    for i, edu in enumerate(revised.get("education", [])):
        label = f"Education: {edu.get('degree', '')} — {edu.get('institution', '')}"
        _add(f"edu_{i}", label, "education", i)

    _add("skills",         "Skills",         "skills")
    _add("certifications", "Certifications", "certifications")
    _add("training",       "Training",       "training")
    _add("languages",      "Languages",      "languages")

    st.session_state.review_decisions = decisions
    st.session_state.review_editing   = []


def _apply_review_decisions() -> dict:
    """Build final CV dict: start from ai_cv_general, apply any edited sections."""
    import copy
    from revizor_frank.core.cv_parser import (
        _parse_experience, _parse_education, _parse_skills,
        _parse_certifications, _parse_languages,
    )

    final = copy.deepcopy(st.session_state.ai_cv_general or st.session_state.offline_cv or {})
    for key, dec in st.session_state.get("review_decisions", {}).items():
        if dec["status"] != "edited":
            continue
        text = dec["text"]
        if key == "summary":
            final["summary"] = text
        elif key.startswith("exp_"):
            idx = int(key.split("_")[1])
            parsed = _parse_experience(text)
            if parsed and idx < len(final.get("experience", [])):
                final["experience"][idx] = parsed[0]
        elif key.startswith("edu_"):
            idx = int(key.split("_")[1])
            parsed = _parse_education(text)
            if parsed and idx < len(final.get("education", [])):
                final["education"][idx] = parsed[0]
        elif key == "skills":
            final["skills"] = _parse_skills(text)
        elif key == "certifications":
            final["certifications"] = _parse_certifications(text)
        elif key == "languages":
            final["languages"] = _parse_languages(text)
    return final


def render_review_changes():
    """Side-by-side tracked-changes review before final results."""
    _render_top_nav()
    if not st.session_state.get("review_decisions"):
        _init_review_state()

    _ensure_questions_generated()

    decisions: dict = st.session_state.review_decisions
    editing: list   = st.session_state.get("review_editing", [])
    total    = len(decisions)

    if total == 0:
        from revizor_frank.core.errors import raise_rvz as _raise_rvz
        _n2 = _raise_rvz("RVZ-N002", detail="Finalise reached with 0 sections — cv_data likely empty")
        st.error(
            f"[{_n2.code}] No sections to review. "
            "The CV may not have been parsed correctly. Please go back and re-upload."
        )
        st.stop()

    approved = sum(1 for d in decisions.values() if d["status"] in ("approved", "edited"))
    all_done = (approved == total)

    st.markdown(f"## 🔍 Review AI Changes — {approved}/{total} sections reviewed")
    st.caption(
        f"**{st.session_state.filename}**  ·  "
        "Approve each section or edit before finalising. "
        "Green = added, ~~red~~ = removed."
    )

    # ── Missing fields banners ────────────────────────────────────────────────
    if st.session_state.get("missing_fields"):
        st.warning(
            "⚠️ The following sections were not detected in the uploaded CV: "
            + ", ".join(st.session_state.missing_fields)
            + "."
        )
        if st.button("📤 Request missing info from client", key="req_missing"):
            auto_questions = [
                _MISSING_QUESTIONS[f]
                for f in st.session_state.missing_fields
                if f in _MISSING_QUESTIONS
            ]
            if auto_questions:
                existing_qs = st.session_state.get("questions_list", [])
                for q_text in auto_questions:
                    if not any(q.get("text") == q_text for q in existing_qs):
                        existing_qs.append({
                            "id": f"missing_{len(existing_qs)}",
                            "section_key": "missing_info",
                            "source_bullet": "",
                            "text": q_text,
                        })
                st.session_state.questions_list = existing_qs
                st.info("Questions added to the Questions panel below. Use 'Send to CV owner' to dispatch them.")
                st.rerun()

    if st.session_state.get("recommended_missing"):
        st.info(
            "💡 Recommended additions: "
            + ", ".join(st.session_state.recommended_missing)
        )

    # ── Progress / instruction banner (above buttons so it's never below the fold)
    st.info("Approve or edit each section below, then click **Finalise CV →** to continue.")

    top_left, top_mid, top_right = st.columns([2, 3, 2])
    with top_left:
        if st.button("✅ Approve All Changes", use_container_width=True):
            for dec in decisions.values():
                dec["status"] = "approved"
            st.session_state.review_editing = []
            st.session_state.review_decisions = decisions
            _autosave_session()
            st.rerun()
        st.caption("Accepts all AI suggestions without review.")
    with top_right:
        if st.button("Finalise CV →", type="primary", use_container_width=True,
                     disabled=not all_done, key="finalise_top"):
            st.session_state.ai_cv_general = _apply_review_decisions()
            _go_to_stage("template")
        st.caption(f"{approved}/{total} sections reviewed")

    st.divider()

    # Build per-section flag lookup from ai_cv_general["flags"]
    _ai_flags: list = (st.session_state.get("ai_cv_general") or {}).get("flags") or []
    _flags_rendered: set = set()

    for key, dec in decisions.items():
        status = dec["status"]
        icon = "✅" if status == "approved" else "✏️" if status == "edited" else "⏳"
        label = dec["label"]

        # Determine canonical section name for this decision key
        if key.startswith("exp"):
            _flag_section = "experience"
        elif key.startswith("edu"):
            _flag_section = "education"
        else:
            _flag_section = key  # summary, skills, certifications, training, languages

        # Show AI flags for this section once, before the expander
        if _ai_flags and _flag_section not in _flags_rendered:
            for _flag in _ai_flags:
                if (_flag.get("section") or "").lower() == _flag_section.lower():
                    st.info(f"ℹ️ **AI Note — {_flag['section']}:** {_flag['issue']}")
            _flags_rendered.add(_flag_section)

        with st.expander(f"{icon} {label}", expanded=(status == "pending")):
            if key in editing:
                # ── Edit mode ────────────────────────────────────────────────
                new_text = st.text_area(
                    "Edit the revised text:",
                    value=dec.get("text", dec["revised"]),
                    height=220,
                    key=f"ta_{key}",
                )
                c_save, c_cancel = st.columns(2)
                with c_save:
                    if st.button("💾 Save & Approve", key=f"save_{key}",
                                 type="primary", use_container_width=True):
                        dec["text"]   = new_text
                        dec["status"] = "edited"
                        editing.remove(key)
                        st.session_state.review_editing   = editing
                        st.session_state.review_decisions = decisions
                        _autosave_session()
                        st.rerun()
                with c_cancel:
                    if st.button("Cancel", key=f"cancel_{key}", use_container_width=True):
                        editing.remove(key)
                        st.session_state.review_editing = editing
                        st.rerun()
            else:
                # ── Diff view ────────────────────────────────────────────────
                c_orig, c_rev, c_q = st.columns(3)
                with c_orig:
                    st.caption("**Original**")
                    st.markdown(
                        f'<div style="background:#fff8f8;border:1px solid #e9ecef;'
                        f'border-radius:6px;padding:0.75rem;font-size:0.85rem;'
                        f'white-space:pre-wrap;min-height:60px">'
                        f'{dec["original"] or "<em>(empty)</em>"}</div>',
                        unsafe_allow_html=True,
                    )
                with c_rev:
                    st.caption("**AI Revised**")
                    diff = _diff_html(dec["original"], dec.get("text", dec["revised"]))
                    st.markdown(
                        f'<div style="background:#f8fff8;border:1px solid #e9ecef;'
                        f'border-radius:6px;padding:0.75rem;font-size:0.85rem;'
                        f'white-space:pre-wrap;min-height:60px">'
                        f'{diff or "<em>(empty)</em>"}</div>',
                        unsafe_allow_html=True,
                    )
                with c_q:
                    st.caption("**Questions**")
                    _render_questions_for_section(key)

                c_app, c_edit, _ = st.columns([1, 1, 3])
                with c_app:
                    if st.button("✅ Approve", key=f"app_{key}", use_container_width=True,
                                 type="primary" if status == "pending" else "secondary"):
                        dec["status"] = "approved"
                        st.session_state.review_decisions = decisions
                        _autosave_session()
                        st.rerun()
                with c_edit:
                    if st.button("✏️ Edit", key=f"edit_{key}", use_container_width=True):
                        if key not in editing:
                            editing.append(key)
                        st.session_state.review_editing = editing
                        st.rerun()

    # ── Bottom Finalise repeat (convenience) ─────────────────────────────────
    st.divider()
    _, _bot_mid, _ = st.columns([2, 3, 2])
    with _bot_mid:
        if st.button("Finalise CV →", type="primary", use_container_width=True,
                     disabled=not all_done, key="finalise_bottom"):
            st.session_state.ai_cv_general = _apply_review_decisions()
            _go_to_stage("template")
        st.caption(f"{approved}/{total} sections reviewed")

    _render_questions_panel()


# ── Template selection stage ─────────────────────────────────────────────────

_SAMPLE_CV: dict = {
    "name": "Alexandra Chen",
    "email": "alex.chen@example.com",
    "phone": "+1 (555) 123-4567",
    "location": "San Francisco, CA",
    "linkedin": "linkedin.com/in/alexchen",
    "website": "",
    "dob": "",
    "summary": (
        "Results-driven software engineer with 8+ years of experience building scalable "
        "web applications and leading cross-functional engineering teams."
    ),
    "experience": [
        {
            "title": "Senior Software Engineer",
            "company": "TechCorp Inc.",
            "location": "San Francisco, CA",
            "start_date": "Mar 2020",
            "end_date": "Present",
            "bullets": [
                "Led microservices platform migration reducing API latency by 40%",
                "Mentored team of 5 junior engineers and conducted weekly code reviews",
            ],
        },
        {
            "title": "Software Engineer",
            "company": "StartupXYZ",
            "location": "New York, NY",
            "start_date": "Jan 2018",
            "end_date": "Feb 2020",
            "bullets": ["Built RESTful APIs serving 2M+ daily requests"],
        },
    ],
    "education": [
        {
            "degree": "B.S. Computer Science",
            "institution": "Stanford University",
            "location": "Stanford, CA",
            "year": "2017",
            "gpa": "",
            "honors": "",
        }
    ],
    "skills": {
        "categories": [
            {"name": "Technical Competencies", "items": ["Python", "JavaScript", "React", "AWS", "Docker", "PostgreSQL"]},
            {"name": "Core Competencies",      "items": ["Leadership", "Communication", "Strategic Planning"]},
        ]
    },
    "certifications": [{"name": "AWS Solutions Architect", "issuer": "Amazon", "date": "2022"}],
    "languages": ["English (Native)", "Mandarin (Fluent)"],
    "projects": [],
    "raw_text": "",
}

_COLOR_PRESETS: list[dict] = [
    {"name": "Navy & White",          "hex": "#1a3a5c"},
    {"name": "Charcoal & Gold",       "hex": "#2c2c2c"},
    {"name": "Forest Green",          "hex": "#2d5a27"},
    {"name": "Burgundy",              "hex": "#722f37"},
    {"name": "Midnight Blue",         "hex": "#191970"},
    {"name": "Black & White",         "hex": "#000000"},
    {"name": "Teal",                  "hex": "#008080"},
    {"name": "Slate & Coral",         "hex": "#708090"},
]


@st.cache_data(ttl=3600, show_spinner=False)
def _generate_template_thumbnail(template_name: str) -> bytes:
    """Generate a small first-page PNG for a template using sample data. Cached for 1 h."""
    from revizor_frank.exporters.png_exporter import export_png
    import tempfile as _tmp
    _dir = Path(_tmp.gettempdir()) / "revizor_thumbs"
    _dir.mkdir(exist_ok=True)
    out = str(_dir / f"thumb_{template_name}.png")
    try:
        export_png(_SAMPLE_CV, template_name, out, dpi=72)
        with open(out, "rb") as f:
            return f.read()
    except Exception:
        return b""


def _render_cv_html_preview(cv: dict, color: str = ""):
    """Render CV as styled HTML in a scrollable preview panel.

    Uses st.components.v1.html — no PDF generation, no external libraries.
    Full content is always visible regardless of CV length.
    """
    import streamlit.components.v1 as _components

    primary = color or "#1a3a5c"

    def _esc(s: str) -> str:
        return (str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    parts: list[str] = [f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:1rem 2rem;
        color:#222;font-size:9.5pt;line-height:1.45;}}
  h1.nm{{color:{primary};font-size:22pt;margin:0 0 3px 0;}}
  h2.jt{{color:#555;font-size:11pt;font-weight:normal;font-style:italic;margin:0 0 4px 0;}}
  .ct{{font-size:8.5pt;color:#555;margin-bottom:12px;}}
  h3.sh{{color:{primary};font-size:10.5pt;text-transform:uppercase;
          border-bottom:1.5px solid {primary};margin:16px 0 5px 0;padding-bottom:2px;}}
  .eh{{font-weight:bold;color:{primary};font-size:10pt;margin-bottom:1px;}}
  .em{{color:#555;font-size:8.5pt;margin-bottom:4px;}}
  ul{{margin:3px 0 8px 0;padding-left:18px;}}
  li{{margin-bottom:2px;}}
  .tp{{display:inline-block;background:#eef2ff;border:1px solid #c7d2fe;
        border-radius:3px;padding:1px 5px;margin:2px 1px;font-size:8pt;}}
</style>
</head><body>"""]

    # ── Header
    parts.append(f'<h1 class="nm">{_esc(cv.get("name",""))}</h1>')
    if cv.get("title"):
        parts.append(f'<h2 class="jt">{_esc(cv["title"])}</h2>')
    _html_phones = cv.get("phones") or (
        [p.strip() for p in cv["phone"].split("|") if p.strip()]
        if cv.get("phone") else []
    )
    contact_items = []
    if cv.get("email"):
        contact_items.append(_esc(cv["email"]))
    if _html_phones:
        contact_items.append(_esc(" | ".join(_html_phones)))
    for _f in ("location", "linkedin", "website"):
        if cv.get(_f):
            contact_items.append(_esc(cv[_f]))
    if contact_items:
        parts.append(f'<div class="ct">{" | ".join(contact_items)}</div>')
    if cv.get("dob"):
        parts.append(f'<div class="ct">DOB: {_esc(cv["dob"])}</div>')

    # ── Summary
    if cv.get("summary"):
        parts.append('<h3 class="sh">Professional Summary</h3>')
        parts.append(f'<p>{_esc(cv["summary"])}</p>')

    # ── Experience
    if cv.get("experience"):
        parts.append('<h3 class="sh">Professional Experience</h3>')
        for exp in cv["experience"]:
            t = _esc(exp.get("title", ""))
            c = _esc(exp.get("company", ""))
            loc = _esc(exp.get("location", ""))
            sd = exp.get("start_date", "")
            ed = exp.get("end_date", "")
            dates = _esc(f"{sd} – {ed}".strip(" –")) if (sd or ed) else ""
            meta = " | ".join(p for p in [c, loc, dates] if p)
            if t:
                parts.append(f'<div class="eh">{t}</div>')
            if meta:
                parts.append(f'<div class="em">{meta}</div>')
            bullets = exp.get("bullets", [])
            if bullets:
                parts.append("<ul>" + "".join(f"<li>{_esc(b)}</li>" for b in bullets) + "</ul>")

    # ── Education
    if cv.get("education"):
        parts.append('<h3 class="sh">Education</h3>')
        for edu in cv["education"]:
            deg = _esc(edu.get("degree", ""))
            inst = _esc(edu.get("institution", ""))
            yr = _esc(edu.get("year", ""))
            honors = _esc(edu.get("honors", ""))
            meta = " | ".join(p for p in [inst, yr] if p)
            if deg:
                parts.append(f'<div class="eh">{deg}</div>')
            if meta:
                parts.append(f'<div class="em">{meta}</div>')
            if honors:
                parts.append(f'<div class="em">{honors}</div>')

    # ── Skills
    skill_cats = cv.get("skills", {}).get("categories", [])
    if skill_cats:
        parts.append('<h3 class="sh">Skills</h3>')
        for cat in skill_cats:
            items = cat.get("items", [])
            if not items:
                continue
            cat_name = _esc(cat.get("name", ""))
            if "technical" in cat.get("name", "").lower():
                pills = "".join(f'<span class="tp">{_esc(i)}</span>' for i in items)
                parts.append(f'<div><strong>{cat_name}:</strong><br>{pills}<br></div>')
            else:
                parts.append(f'<div><strong>{cat_name}:</strong> {_esc(", ".join(items))}</div>')

    # ── Certifications
    certs = cv.get("certifications", [])
    if certs:
        parts.append('<h3 class="sh">Certifications</h3><ul>')
        for cert in certs:
            n = _esc(cert.get("name", ""))
            iss = _esc(cert.get("issuer", ""))
            dt = _esc(cert.get("date", ""))
            meta = " | ".join(p for p in [iss, dt] if p)
            parts.append(f'<li><strong>{n}</strong>{(" — " + meta) if meta else ""}</li>')
        parts.append("</ul>")

    # ── Training
    training = cv.get("training", [])
    if training:
        parts.append('<h3 class="sh">Professional Training</h3><ul>')
        for tr in training:
            n = _esc(tr.get("name", ""))
            org = _esc(tr.get("organisation", ""))
            dt = _esc(tr.get("date", ""))
            meta = " | ".join(p for p in [org, dt] if p)
            parts.append(f'<li><strong>{n}</strong>{(" — " + meta) if meta else ""}</li>')
        parts.append("</ul>")

    # ── Languages
    langs = cv.get("languages", [])
    if langs:
        parts.append('<h3 class="sh">Languages</h3>')
        parts.append(f'<p>{_esc(", ".join(str(l) for l in langs))}</p>')

    # ── Projects
    projects = cv.get("projects", [])
    if projects:
        parts.append('<h3 class="sh">Projects</h3>')
        for proj in projects:
            pn = _esc(proj.get("name", ""))
            pd = _esc(proj.get("description", ""))
            if pn:
                parts.append(f'<div class="eh">{pn}</div>')
            if pd:
                parts.append(f'<p style="margin:2px 0 8px 0">{pd}</p>')

    parts.append("</body></html>")
    _components.html("".join(parts), height=700, scrolling=True)


def _is_usable_text(text: str) -> bool:
    """Return False if more than 20% of non-whitespace characters are cid-token garbage.

    pdfminer produces (cid:N) sequences for fonts it cannot decode. A high
    proportion of these renders the text useless for display.
    """
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return False
    cid_matches = re.findall(r"\(cid:\d+\)", text)
    # each match contributes its length in chars to the garbage count
    cid_chars = sum(len(m) for m in cid_matches)
    return cid_chars / len(non_ws) <= 0.20


def _cv_to_plain_text(cv: dict) -> str:
    """Build a readable plain-text representation from structured CV fields.

    Used as fallback when raw_text is absent or too short (< 100 chars).
    Order: name, title, contact, summary, experience, education, skills,
           training, languages.
    """
    lines: list[str] = []

    if cv.get("name"):
        lines.append(cv["name"])
    if cv.get("title"):
        lines.append(cv["title"])

    # Contact line
    contact_parts = []
    if cv.get("email"):
        contact_parts.append(cv["email"])
    _phones = cv.get("phones") or (
        [p.strip() for p in cv["phone"].split("|") if p.strip()]
        if cv.get("phone") else []
    )
    if _phones:
        contact_parts.append(" | ".join(_phones))
    for _cf in ("location", "linkedin", "website"):
        if cv.get(_cf):
            contact_parts.append(cv[_cf])
    if contact_parts:
        lines.append("  |  ".join(contact_parts))

    if cv.get("summary"):
        lines += ["", "SUMMARY", "-" * 40, cv["summary"]]

    if cv.get("experience"):
        lines += ["", "EXPERIENCE", "-" * 40]
        for exp in cv["experience"]:
            role = exp.get("title", "")
            company = exp.get("company", "")
            dates = f"{exp.get('start_date', '')} – {exp.get('end_date', 'Present')}".strip(" –")
            lines.append(f"{role}  |  {company}  |  {dates}".strip("  |  "))
            for b in exp.get("bullets", []):
                lines.append(f"  • {b}")
            lines.append("")

    if cv.get("education"):
        lines += ["", "EDUCATION", "-" * 40]
        for edu in cv["education"]:
            deg = edu.get("degree", "")
            inst = edu.get("institution", "")
            yr = edu.get("year", "")
            lines.append(f"{deg}  |  {inst}  |  {yr}".strip("  |  "))

    if cv.get("skills", {}).get("categories"):
        lines += ["", "SKILLS", "-" * 40]
        for cat in cv["skills"]["categories"]:
            items = ", ".join(cat.get("items", []))
            if items:
                lines.append(f"{cat.get('name', 'Skills')}: {items}")

    if cv.get("training"):
        lines += ["", "PROFESSIONAL TRAINING", "-" * 40]
        for tr in cv["training"]:
            line = tr.get("name", "")
            if tr.get("organisation"):
                line += f"  —  {tr['organisation']}"
            if tr.get("date"):
                line += f"  ({tr['date']})"
            lines.append(line)

    if cv.get("languages"):
        lines += ["", "LANGUAGES", "-" * 40, ", ".join(cv["languages"])]

    return "\n".join(lines).strip()


def render_full_preview():
    """Full CV preview — original vs revised, side by side."""
    _render_top_nav()
    st.markdown("## 📄 Full CV Preview — Original vs Revised")
    st.caption("Review both versions side by side before selecting your template and downloading.")

    original_cv = st.session_state.get("parsed_cv") or {}
    revised_cv = (
        st.session_state.get("edited_cv") or
        st.session_state.get("ai_cv_general") or {}
    )

    col_orig, col_rev = st.columns(2)

    with col_orig:
        st.markdown("### Original CV")
        raw = original_cv.get("raw_text", "")
        if raw and len(raw.strip()) > 100 and _is_usable_text(raw):
            orig_text = raw
        else:
            # raw_text absent, too short, or cid-garbage — build from structured fields
            orig_text = _cv_to_plain_text(original_cv)
        if orig_text:
            st.text_area("", value=orig_text, height=800, disabled=True,
                         label_visibility="collapsed", key="preview_orig")
        else:
            st.info("Original text not available.")

    with col_rev:
        st.markdown("### Revised CV")
        from revizor_frank.exporters.txt_exporter import export_txt
        import tempfile
        revised_text = ""
        if revised_cv:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as _f:
                _tmp = _f.name
            try:
                export_txt(revised_cv, _tmp)
                with open(_tmp) as _f:
                    revised_text = _f.read()
            except Exception:
                revised_text = ""
            finally:
                if os.path.exists(_tmp):
                    os.remove(_tmp)
        if revised_text:
            st.text_area("", value=revised_text, height=800, disabled=True,
                         label_visibility="collapsed", key="preview_rev")
        else:
            st.info("Revised CV not yet available.")


def render_select_template():
    """Template & colour selection stage — shown before the download results."""
    _render_top_nav()
    st.markdown(f"# 📄 {APP_NAME}")
    st.markdown("## Choose Your Template & Colour")
    st.caption("Pick any template, customise the colour, preview with your actual CV, then proceed to download.")
    st.divider()

    selected = st.session_state.get("selected_template", DEFAULT_TEMPLATE)
    current_color = st.session_state.get("template_color", "")

    # ── Colour picker ─────────────────────────────────────────────────────────
    st.markdown("### 🎨 Colour Scheme")
    preset_cols = st.columns(len(_COLOR_PRESETS))
    for i, preset in enumerate(_COLOR_PRESETS):
        with preset_cols[i]:
            is_active = current_color == preset["hex"]
            swatch = f'<div style="width:100%;height:24px;background:{preset["hex"]};' \
                     f'border-radius:4px;border:2px solid {"#0d6efd" if is_active else "#dee2e6"}"></div>'
            st.markdown(swatch, unsafe_allow_html=True)
            if st.button(preset["name"], key=f"color_preset_{i}",
                         use_container_width=True,
                         type="primary" if is_active else "secondary"):
                st.session_state.template_color = preset["hex"]
                st.rerun()

    custom_col, _ = st.columns([1, 2])
    with custom_col:
        new_color = st.color_picker(
            "Custom colour",
            value=current_color if current_color else "#1a3a5c",
            key="template_color_picker",
        )
    if new_color != current_color:
        st.session_state.template_color = new_color
        st.rerun()

    st.divider()

    # ── Template grid ─────────────────────────────────────────────────────────
    st.markdown("### 📐 Template")
    tmpl_list = list(TEMPLATES.items())
    COLS = 4
    for row_start in range(0, len(tmpl_list), COLS):
        row = tmpl_list[row_start: row_start + COLS]
        cols = st.columns(len(row))
        for j, (tkey, tcfg) in enumerate(row):
            with cols[j]:
                thumb = _generate_template_thumbnail(tkey)
                if thumb:
                    border = "3px solid #0d6efd" if tkey == selected else "2px solid #dee2e6"
                    st.markdown(
                        f'<div style="border:{border};border-radius:6px;overflow:hidden">',
                        unsafe_allow_html=True,
                    )
                    st.image(thumb, use_container_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                is_sel = tkey == selected
                if st.button(
                    f"{'✓ ' if is_sel else ''}{tcfg['name']}",
                    key=f"tmpl_btn_{tkey}",
                    use_container_width=True,
                    type="primary" if is_sel else "secondary",
                ):
                    st.session_state.selected_template = tkey
                    st.rerun()
                st.caption(tcfg.get("best_for", ""))

    st.divider()

    # ── Live preview with actual CV data ──────────────────────────────────────
    cv_source = (
        st.session_state.get("edited_cv") or
        st.session_state.get("ai_cv_general") or
        st.session_state.get("offline_cv") or {}
    )
    if cv_source:
        st.markdown("### 👁️ Live Preview")
        tcolor = st.session_state.get("template_color", "")
        _render_cv_html_preview(cv_source, tcolor)
        st.divider()

    if st.button("Use This Template — Download My CV →",
                 type="primary", use_container_width=True):
        _go_to_stage("download")


# ── Results stage ─────────────────────────────────────────────────────────────

def render_results():
    _render_top_nav()
    ats = st.session_state.ats_report or {}
    score = ats.get("score", 0)
    grade = ats.get("grade", "—")
    online = st.session_state.online
    has_jd = bool(st.session_state.job_description)
    has_ai = bool(st.session_state.ai_cv_general)

    # ── ATS score bar ─────────────────────────────────────────────────────────
    st.markdown(f"## Results — {st.session_state.filename}")
    if st.session_state.error:
        st.warning(st.session_state.error)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="metric-card">'
            f'<div style="font-size:0.8rem;color:#666">{S["ats_score_label"]}</div>'
            f'<div class="score-big" style="color:{"#28a745" if score>=75 else "#fd7e14" if score>=50 else "#dc3545"}">'
            f'{score}</div><div style="font-size:0.8rem;color:#666">/100</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        badge_class = f"badge-{grade}"
        st.markdown(
            f'<div class="metric-card">'
            f'<div style="font-size:0.8rem;color:#666">{S["ats_grade_label"]}</div>'
            f'<div class="score-big"><span class="grade-badge {badge_class}">{grade}</span></div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        issues = ats.get("issues", [])
        crit = sum(1 for i in issues if i["severity"] == "critical")
        warn = sum(1 for i in issues if i["severity"] == "warning")
        st.markdown(
            f'<div class="metric-card">'
            f'<div style="font-size:0.8rem;color:#666">{S["ats_issues_label"]}</div>'
            f'<div class="score-big" style="font-size:1.8rem">'
            f'<span style="color:#dc3545">{crit} critical</span><br>'
            f'<span style="color:#fd7e14">{warn} warnings</span></div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        kw_score = ats.get("keyword_score", 0)
        kw_label = f"{kw_score}%" if has_jd else "N/A"
        kw_color = "#28a745" if kw_score >= 70 else "#fd7e14" if kw_score >= 50 else "#dc3545"
        st.markdown(
            f'<div class="metric-card">'
            f'<div style="font-size:0.8rem;color:#666">{S["ats_keyword_label"]}</div>'
            f'<div class="score-big" style="color:{kw_color if has_jd else "#aaa"}">'
            f'{kw_label}</div>'
            f'<div style="font-size:0.8rem;color:#666">{"JD Match" if has_jd else "No JD provided"}</div></div>',
            unsafe_allow_html=True,
        )

    st.divider()

    tier = st.session_state.get("service_tier", "cv_linkedin")
    include_linkedin = (tier != "cv_only")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_labels = [S["tab_general"]]
    if has_jd:
        tab_labels.append(S["tab_jd_tailored"])
    if include_linkedin:
        tab_labels.append(S["tab_linkedin"])
    tab_labels += ["✏️ Edit CV", "🔍 ATS Issues", S["tab_download"]]

    # Owner answers tab — only when submitted answers exist for this session
    _owner_answers_row = None
    _session_id_str = str(st.session_state.get("session_id") or "")
    if _session_id_str:
        try:
            from revizor_frank.storage import supabase_db as _sdb
            _owner_answers_row = _sdb.get_submitted_answers(_session_id_str)
        except Exception:
            pass
    if _owner_answers_row:
        tab_labels.append("💬 Owner answers")

    tabs = st.tabs(tab_labels)
    tab_idx = 0

    # General ATS Tab
    with tabs[tab_idx]:
        tab_idx += 1
        cv_to_show = st.session_state.ai_cv_general or st.session_state.offline_cv
        label = "🤖 AI-Optimized" if has_ai else "📋 Rule-Optimized (Offline)"
        st.caption(label)
        _render_cv_preview(cv_to_show)

    # JD-Tailored Tab
    if has_jd:
        with tabs[tab_idx]:
            tab_idx += 1
            jd_cv = st.session_state.ai_cv_jd
            if jd_cv:
                st.caption("🎯 JD-Tailored AI Optimization")
                _render_cv_preview(jd_cv)
                if ats.get("keyword_matches"):
                    with st.expander("✅ Keywords matched from JD"):
                        st.write(", ".join(ats["keyword_matches"]))
                if ats.get("missing_keywords"):
                    with st.expander("⚠️ Keywords still missing from JD"):
                        st.write(", ".join(ats["missing_keywords"][:30]))
            else:
                st.info("JD-tailored version requires internet connection. Will be generated automatically when connectivity returns.")

    # LinkedIn Tab (cv_linkedin tier only)
    if include_linkedin:
        with tabs[tab_idx]:
            tab_idx += 1
            _render_linkedin_tab()

    # Edit CV Tab
    with tabs[tab_idx]:
        tab_idx += 1
        _render_edit_cv_tab(include_linkedin)

    # ATS Issues Tab
    with tabs[tab_idx]:
        tab_idx += 1
        _render_ats_issues(ats)

    # Download Tab
    with tabs[tab_idx]:
        tab_idx += 1
        _render_downloads()

    # Owner answers Tab (conditional)
    if _owner_answers_row:
        with tabs[tab_idx]:
            _render_owner_answers_tab(_owner_answers_row)


def _render_owner_answers_tab(row: dict):
    """Show CV owner's answers and allow co-worker to incorporate them into edited_cv."""
    st.markdown("### 💬 CV Owner Answers")
    questions = row.get("questions") or []
    answers   = {a["id"]: a["answer"] for a in (row.get("answers") or []) if a.get("id")}

    ai_cv = st.session_state.ai_cv_general or st.session_state.offline_cv or {}

    for q in questions:
        if not isinstance(q, dict):
            continue
        qid    = q.get("id", "")
        q_text = q.get("text", "")
        answer = answers.get(qid, "")
        bullet = q.get("source_bullet", "")

        st.markdown(f"**Q:** {q_text}")
        if answer:
            st.success(f"**A:** {answer}")
        else:
            st.caption("_(no answer provided)_")

        if bullet:
            edit_key = f"owner_edit_{qid}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = bullet
            st.text_area(
                "Edit the bullet to incorporate this answer:",
                key=edit_key,
                height=80,
            )
            if st.button("✅ Save edit", key=f"owner_save_{qid}"):
                # Inject the edited bullet into edited_cv
                new_text = st.session_state[edit_key]
                _apply_owner_bullet_edit(bullet, new_text, ai_cv)
                st.success("Saved!")
        st.divider()


def _apply_owner_bullet_edit(original_bullet: str, new_bullet: str, ai_cv: dict):
    """Replace original_bullet with new_bullet in edited_cv (or ai_cv_general)."""
    import copy
    base = copy.deepcopy(st.session_state.get("edited_cv") or ai_cv or {})
    for exp in base.get("experience", []):
        bullets = exp.get("bullets", [])
        for i, b in enumerate(bullets):
            if original_bullet.replace("≈", "").strip() in b:
                bullets[i] = new_bullet
    st.session_state.edited_cv = base


def _render_cv_preview(cv: dict):
    if not cv:
        st.warning("No optimized CV data available.")
        return

    st.markdown(f"### {cv.get('name', '')}")
    contact_parts = [cv.get(f, "") for f in ("email", "phone", "location", "linkedin") if cv.get(f)]
    st.caption("  |  ".join(contact_parts))
    st.divider()

    if cv.get("summary"):
        st.markdown("**Professional Summary**")
        st.write(cv["summary"])
        st.divider()

    if cv.get("experience"):
        st.markdown("**Professional Experience**")
        for exp in cv["experience"]:
            col_a, col_b = st.columns([3, 1])
            with col_a:
                st.markdown(f"**{exp.get('title', '')}** — {exp.get('company', '')}")
            with col_b:
                st.caption(f"{exp.get('start_date', '')} – {exp.get('end_date', 'Present')}")
            for b in exp.get("bullets", []):
                st.write(f"• {b}")
            st.write("")
        st.divider()

    if cv.get("education"):
        st.markdown("**Education**")
        for edu in cv["education"]:
            st.markdown(f"**{edu.get('degree', '')}** — {edu.get('institution', '')} {edu.get('year', '')}")
        st.divider()

    if cv.get("skills", {}).get("categories"):
        st.markdown("**Skills**")
        for cat in cv["skills"]["categories"]:
            items = ", ".join(cat.get("items", []))
            if items:
                st.markdown(f"**{cat['name']}:** {items}")

    if cv.get("certifications"):
        st.divider()
        st.markdown("**Certifications**")
        for cert in cv["certifications"]:
            st.write(f"• {cert.get('name', '')} — {cert.get('issuer', '')}")

    if cv.get("training"):
        st.divider()
        st.markdown("**Professional Training**")
        for tr in cv["training"]:
            line = tr.get("name", "")
            if tr.get("organisation"):
                line += f"  —  {tr['organisation']}"
            if tr.get("date"):
                line += f"  ({tr['date']})"
            st.write(f"• {line}")

    if cv.get("languages"):
        st.divider()
        st.markdown("**Languages**")
        st.write(", ".join(cv["languages"]))


def _render_linkedin_tab():
    li = st.session_state.linkedin_data
    if not li:
        st.info("LinkedIn profile will appear here after processing.")
        return

    quality = "🤖 AI-Generated" if st.session_state.ai_cv_general else "📋 Rule-Generated (Offline)"
    st.caption(quality)
    st.info(S["li_copy_hint"])

    def li_section(label: str, content: str, char_limit: int = 0):
        st.markdown(f"**{label}**")
        if char_limit:
            count = len(content)
            color = "red" if count > char_limit else "green"
            st.caption(f"Character count: :{color}[{count}/{char_limit}]")
        st.text_area(label=label, value=content, height=120, label_visibility="collapsed", key=f"li_{label}")

    li_section(S["li_headline"], li.get("headline", ""), char_limit=220)
    li_section(S["li_about"], li.get("about", ""), char_limit=2600)

    st.markdown(f"**{S['li_experience']}**")
    for i, exp in enumerate(li.get("experience", []), 1):
        with st.expander(f"{exp.get('title', '')} @ {exp.get('company', '')} — {exp.get('dates', '')}"):
            st.text_area("Description", value=exp.get("description", ""),
                         height=150, key=f"li_exp_{i}")
            desc = exp.get("description", "")
            st.caption(f"Character count: {len(desc)}/2000")

    skills_text = "\n".join(li.get("skills", []))
    li_section(S["li_skills"], skills_text)

    if li.get("certifications"):
        st.markdown(f"**{S['li_certifications']}**")
        for cert in li.get("certifications", []):
            st.write(f"• {cert.get('name', '')} — {cert.get('issuer', '')}")

    li_section("Summary Tagline (for InMail / connection notes)", li.get("summary_tagline", ""))


def _cv_to_text(cv: dict) -> str:
    """Convert a CVData dict to a plain-text string using txt_exporter."""
    import tempfile as _tmp
    _path = str(Path(_tmp.gettempdir()) / f"revizor_edit_{uuid.uuid4().hex}.txt")
    try:
        from revizor_frank.exporters.txt_exporter import export_txt
        export_txt(cv, _path)
        with open(_path, "r", encoding="utf-8") as _f:
            return _f.read()
    except Exception:
        return ""
    finally:
        if os.path.exists(_path):
            os.unlink(_path)


def _render_edit_cv_tab(include_linkedin: bool):
    st.markdown("### ✏️ Edit Your CV Text")
    st.caption("Edit the optimized CV below. Click **Apply edits** to save changes"
               + (" and regenerate your LinkedIn profile." if include_linkedin else "."))

    cv_source = st.session_state.ai_cv_general or st.session_state.offline_cv
    if not cv_source:
        st.warning("No CV available to edit yet.")
        return

    # Passive DOB note — only show when DOB was not extracted from the CV
    if not cv_source.get("dob") and not st.session_state.get("dob"):
        st.info(
            "ℹ️ Date of birth not found in your CV. "
            "Add it manually in the text below if needed, e.g. "
            "**Date of Birth: 1 January 1990**"
        )

    # Initialize edit buffer from CV if not already set
    if not st.session_state.get("edited_cv_text"):
        st.session_state.edited_cv_text = _cv_to_text(cv_source)

    btn_label = "✅ Apply edits & refresh LinkedIn" if include_linkedin else "✅ Apply edits"

    def _do_apply_edits(edited_text: str) -> None:
        """Shared handler for both top and bottom Apply Edits buttons."""
        st.session_state.edited_cv_text = edited_text

        _edit_ok = False
        try:
            import copy
            _base = st.session_state.get("ai_cv_general") or st.session_state.get("offline_cv") or {}
            merged = copy.deepcopy(_base)

            _summary_lines: list[str] = []
            _heading_re = re.compile(
                r"^\s*(SUMMARY|PROFILE|OBJECTIVE|EXPERIENCE|EDUCATION|SKILLS|"
                r"CERTIFICATIONS?|TRAINING|LANGUAGES?|PROJECTS?|PUBLICATIONS?|"
                r"AWARDS?|VOLUNTEER|PROFESSIONAL\s+SUMMARY|PROFESSIONAL\s+TRAINING)\s*$",
                re.I,
            )
            _collecting = False
            for _line in edited_text.splitlines():
                if not _line.strip():
                    if _collecting:
                        break
                    continue
                if _heading_re.match(_line):
                    if _collecting:
                        break
                    break
                _collecting = True
                _summary_lines.append(_line.strip())

            _extracted_summary = " ".join(_summary_lines).strip()
            if _extracted_summary:
                merged["summary"] = _extracted_summary

            for _field in ("title", "dob", "linkedin", "website", "phones", "phone", "email", "raw_text"):
                if not merged.get(_field) and _base.get(_field):
                    merged[_field] = _base[_field]

            st.session_state.edited_cv = merged
            _edit_ok = True
        except Exception as _merge_err:
            st.session_state.edited_cv = None
            st.error(f"Could not save edits: {_merge_err}.")

        if _edit_ok and include_linkedin and st.session_state.online and st.session_state.ai_cv_general:
            with st.spinner("Regenerating LinkedIn profile from edited CV…"):
                try:
                    from revizor_frank.core import cv_optimizer
                    base_cv = st.session_state.get("edited_cv") or st.session_state.ai_cv_general
                    linkedin, in_tok, out_tok = cv_optimizer.generate_linkedin(
                        base_cv,
                        st.session_state.ai_cv_general,
                        st.session_state.job_description,
                    )
                    st.session_state.linkedin_data = linkedin
                    st.session_state.total_input_tokens = (
                        st.session_state.get("total_input_tokens", 0) + in_tok
                    )
                    st.session_state.total_output_tokens = (
                        st.session_state.get("total_output_tokens", 0) + out_tok
                    )
                    st.success("Edits saved — LinkedIn profile refreshed.")
                except Exception as e:
                    st.error(f"Could not regenerate LinkedIn: {e}")
        elif _edit_ok and include_linkedin and not st.session_state.online:
            st.success("Edits saved — downloads will use your edited CV.")
            st.info("LinkedIn refresh requires internet connection.")
        elif _edit_ok:
            st.success("Edits saved — downloads will use your edited CV.")

    # ── Top Apply Edits button (reads current text area value from session state)
    if st.button(btn_label, type="primary", key="apply_edits_top"):
        _current = st.session_state.get("cv_text_editor",
                                        st.session_state.get("edited_cv_text", ""))
        _do_apply_edits(_current)

    edited = st.text_area(
        "CV Text",
        value=st.session_state.edited_cv_text,
        height=500,
        key="cv_text_editor",
        label_visibility="collapsed",
    )

    # ── Bottom Apply Edits button (convenience repeat)
    if st.button(btn_label, type="primary", key="apply_edits_bottom"):
        _do_apply_edits(edited)


_TC_TEXT = """SERVICE TERMS — ReviZoR CV Revision Service

1. SCOPE OF SERVICE
   The Service Provider will revise and optimise the submitted CV using AI-assisted tools.
   The final output depends on the quality and completeness of information provided by the Client.

2. CLIENT RESPONSIBILITIES
   The Client is responsible for providing all required CV information including:
   full name, professional email, phone number, work experience, education, and skills.
   Missing information must be supplied within 14 days of being notified,
   or the service will be considered rendered at the level possible.

3. RESPONSE WINDOW
   Once notified of missing information, the Client has 14 days to respond.
   Failure to respond within this window will result in the service being closed.

4. REFUND & DEPOSIT POLICY
   If the Client fails to provide required information within the 14-day window,
   50% of the service fee will be retained by the Service Provider to cover
   administrative costs and AI processing already performed.
   The remaining 50% will be refunded to the Client.
   No refund is issued once the final revised CV has been delivered and approved.

5. CONFIDENTIALITY
   All CV data is processed securely and is not shared with third parties.
   Data is retained only for the duration of service delivery.

6. ACCEPTANCE
   By proceeding with the service, the Client implicitly agrees to these terms.
"""


def render_admin_dashboard():
    import csv
    from io import StringIO

    st.markdown("# 🛠 Admin Dashboard")
    st.divider()

    tab_pl, tab_pending, tab_incomplete, tab_errors, tab_tc = st.tabs([
        "📊 P&L / Runs", "⏰ Pending Responses", "⚠️ Incomplete CVs", "🔴 Error Log", "📋 T&C Draft"
    ])

    with tab_pl:
        # ── Month selector ────────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        col_y, col_m, _ = st.columns([1, 1, 2])
        with col_y:
            year = st.selectbox("Year", list(range(now.year - 2, now.year + 1)), index=2)
        with col_m:
            month = st.selectbox("Month", list(range(1, 13)), index=now.month - 1,
                                 format_func=lambda m: datetime(2000, m, 1).strftime("%B"))

        st.divider()

        try:
            from revizor_frank.storage import supabase_db
            from revizor_frank.storage.supabase_db import calculate_cost
            runs = supabase_db.get_monthly_runs(year, month)
        except Exception as e:
            st.error(f"Could not load Supabase data: {e}")
            runs = []

        egp_rate = USD_TO_EGP_RATE

        # ── P&L Summary ───────────────────────────────────────────────────────
        st.markdown("### Monthly P&L")
        if runs:
            total_rev_usd = sum(float(r.get("price_usd") or 0) for r in runs)
            total_cost_usd = sum(float(r.get("cost_usd") or 0) for r in runs)
            profit_usd = total_rev_usd - total_cost_usd

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Sessions", len(runs))
            c2.metric("Revenue (USD)", f"${total_rev_usd:,.2f}",
                      delta=f"EGP {total_rev_usd * egp_rate:,.0f}")
            c3.metric("AI Cost (USD)", f"${total_cost_usd:,.4f}")
            c4.metric("Profit (USD)", f"${profit_usd:,.2f}",
                      delta=f"EGP {profit_usd * egp_rate:,.0f}")

            st.divider()
            st.markdown("**Sessions by Tier**")
            tier_counts: dict[str, int] = {}
            for r in runs:
                t = r.get("tier", "unknown")
                tier_counts[t] = tier_counts.get(t, 0) + 1
            for t, cnt in tier_counts.items():
                st.write(f"• {t}: **{cnt}** sessions")
        else:
            st.info("No data for the selected period.")

        st.divider()

        # ── Coupon Manager ────────────────────────────────────────────────────
        st.markdown("### Coupon Usage")
        try:
            coupon_stats = supabase_db.get_coupon_stats()
        except Exception:
            coupon_stats = []

        if coupon_stats:
            import pandas as pd  # type: ignore
            df_coupons = pd.DataFrame(coupon_stats)
            df_coupons["profit_usd"] = df_coupons["total_revenue_usd"] - df_coupons["total_cost_usd"]
            st.dataframe(df_coupons, use_container_width=True, hide_index=True)
        else:
            st.info("No coupon usage found.")

        st.divider()

        # ── CSV Export ────────────────────────────────────────────────────────
        st.markdown("### Export Data")
        col_exp1, col_exp2 = st.columns(2)

        with col_exp1:
            if runs:
                buf = StringIO()
                writer = csv.DictWriter(buf, fieldnames=runs[0].keys())
                writer.writeheader()
                writer.writerows(runs)
                st.download_button(
                    "⬇️ Export This Month (CSV)",
                    data=buf.getvalue().encode("utf-8"),
                    file_name=f"revizor_runs_{year}_{month:02d}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        with col_exp2:
            if st.button("Export All Runs (CSV)", use_container_width=True):
                try:
                    all_runs = supabase_db.get_all_runs_for_export()
                    if all_runs:
                        buf_all = StringIO()
                        writer_all = csv.DictWriter(buf_all, fieldnames=all_runs[0].keys())
                        writer_all.writeheader()
                        writer_all.writerows(all_runs)
                        st.download_button(
                            "⬇️ Download All Runs CSV",
                            data=buf_all.getvalue().encode("utf-8"),
                            file_name="revizor_all_runs.csv",
                            mime="text/csv",
                            use_container_width=True,
                            key="dl_all_csv",
                        )
                    else:
                        st.info("No data to export.")
                except Exception as e:
                    st.error(f"Export failed: {e}")

    with tab_pending:
        st.markdown("### Pending CV Owner Responses")
        st.caption("Deposit policy: 50% retained if client does not respond within 14 days.")
        try:
            from revizor_frank.storage import supabase_db as _sdb_admin
            pending_rows = _sdb_admin.get_pending_responses()
        except Exception as e:
            st.error(f"Could not load pending responses: {e}")
            pending_rows = []

        if not pending_rows:
            st.info("No pending responses.")
        else:
            _now = datetime.now(timezone.utc)
            for row in pending_rows:
                status = row.get("status", "pending")
                created_str = row.get("created_at", "")
                try:
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    days_elapsed = (_now - created_dt).days
                    days_remaining = max(0, 14 - days_elapsed)
                except Exception:
                    days_elapsed = 0
                    days_remaining = 14

                if status == "submitted":
                    badge = "✅ Submitted"
                elif days_remaining == 0:
                    badge = "🔴 Expired"
                elif status == "pending":
                    badge = "🟡 Pending"
                else:
                    badge = "⚫ Closed"

                n_questions = len(row.get("questions") or [])
                with st.expander(
                    f"{badge} — Session {str(row.get('session_id', ''))[:8]}… "
                    f"| {n_questions} question(s) | {days_elapsed}d elapsed / {days_remaining}d remaining"
                ):
                    st.progress(min(days_elapsed / 14, 1.0))
                    st.caption(f"Created: {created_str[:10]}  |  Deposit policy: 50% retained if unresponded")
                    qs = row.get("questions") or []
                    for i, q in enumerate(qs, 1):
                        st.write(f"{i}. {q.get('text', q) if isinstance(q, dict) else q}")
                    if status not in ("submitted", "closed"):
                        if st.button("Mark as closed", key=f"close_{row['id']}"):
                            try:
                                _sdb_admin.close_owner_questions(row["id"])
                                st.success("Marked as closed.")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Failed: {ex}")

            # Export pending as CSV
            if pending_rows:
                buf_p = StringIO()
                fieldnames = ["session_id", "status", "created_at", "expires_at",
                              "submitted_at", "token"]
                w_p = csv.DictWriter(buf_p, fieldnames=fieldnames, extrasaction="ignore")
                w_p.writeheader()
                w_p.writerows(pending_rows)
                st.download_button(
                    "⬇️ Export Pending Responses (CSV)",
                    data=buf_p.getvalue().encode("utf-8"),
                    file_name="revizor_pending_responses.csv",
                    mime="text/csv",
                )

    with tab_incomplete:
        st.markdown("### Candidates with Incomplete CVs")
        st.caption(
            "Sessions where required fields are missing from the parsed CV. "
            "Flag: **Incomplete — awaiting info.**"
        )
        try:
            from revizor_frank.storage import supabase_db as _sdb_inc
            incomplete_rows = _sdb_inc.get_incomplete_sessions()
        except Exception as _inc_e:
            st.error(f"Could not load incomplete sessions: {_inc_e}")
            incomplete_rows = []

        if not incomplete_rows:
            st.info("No incomplete CV records found.")
        else:
            for row in incomplete_rows:
                username   = row.get("username", "—")
                filename   = row.get("filename", "—")
                updated    = (row.get("updated_at") or "")[:10]
                missing    = row.get("missing_fields") or []
                with st.expander(
                    f"⚠️ Incomplete — awaiting info.  |  {username}  |  {filename}  |  {updated}"
                ):
                    st.warning("Incomplete — awaiting info.")
                    st.markdown("**Missing fields:**")
                    for mf in missing:
                        st.write(f"• {mf}")

    with tab_errors:
        st.markdown("### 🔴 Error Log")
        st.caption("Sessions that produced at least one classified error during this deployment.")
        try:
            from revizor_frank.storage import supabase_db as _sdb_err
            _err_rows = _sdb_err.get_sessions_with_errors()
        except Exception as _e:
            st.error(f"Could not load error log: {_e}")
            _err_rows = []
        if not _err_rows:
            st.success("No errors recorded.")
        else:
            for _erow in _err_rows:
                _eu = _erow.get("username", "—")
                _ef = _erow.get("filename", "—")
                _es = _erow.get("stage", "—")
                _et = (_erow.get("updated_at") or "")[:19]
                _elog = _erow.get("error_log") or []
                with st.expander(f"🔴 {_eu}  |  {_ef}  |  {_et}"):
                    for _entry in _elog:
                        _col1, _col2, _col3 = st.columns([1, 2, 5])
                        with _col1:
                            st.code(_entry.get("code", "?"), language=None)
                        with _col2:
                            st.caption(_entry.get("timestamp", "")[:19])
                            st.caption(f"Stage: {_entry.get('stage', '—')}")
                        with _col3:
                            st.markdown(_entry.get("detail", ""))
                        st.divider()

    with tab_tc:
        st.markdown("### T&C Reference Draft")
        st.caption("For reference when the service goes public. Not shown to clients yet.")
        st.code(_TC_TEXT, language=None)

    st.divider()
    if st.button("← Back to App", use_container_width=False):
        _go_to_stage("upload")


def _render_ats_issues(ats: dict):
    issues = ats.get("issues", [])
    if not issues:
        st.success("No ATS issues detected! Your CV is well-optimized.")
        return

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    sorted_issues = sorted(issues, key=lambda i: severity_order.get(i["severity"], 9))

    for issue in sorted_issues:
        sev = issue["severity"]
        icon = "🔴" if sev == "critical" else "🟡" if sev == "warning" else "🔵"
        with st.expander(f"{icon} [{sev.upper()}] {issue['category']} — {issue['message']}"):
            st.markdown(f"**Fix:** {issue['fix']}")

    # Sections summary
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Sections Found**")
        for s in ats.get("sections_found", []):
            st.success(s.title())
    with col2:
        st.markdown("**Sections Missing**")
        for s in ats.get("sections_missing", []):
            st.error(s.title())

    # Quality scores
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        av = ats.get("action_verb_score", 0)
        st.metric("Action Verb Score", f"{av}%",
                  delta=f"{'Good' if av>=70 else 'Needs work'}")
    with c2:
        qs = ats.get("quantification_score", 0)
        st.metric("Quantification Score", f"{qs}%",
                  delta=f"{'Good' if qs>=40 else 'Add metrics'}")


def _render_downloads():
    st.markdown(f"### {S['download_header']}")
    template = st.session_state.selected_template
    template_color = st.session_state.get("template_color", "")
    template_name = TEMPLATES.get(template, {}).get("name", template)
    cv_used = "edited_cv ✏️" if st.session_state.get("edited_cv") else "ai_cv_general"
    st.caption(f"Downloads using: **{cv_used}**")
    color_note = f"  ·  colour: <span style='color:{template_color};font-weight:bold'>{template_color}</span>" if template_color else ""
    st.caption(
        f"Template: **{template_name}**  ·  All formats are ATS-safe{color_note}",
        unsafe_allow_html=True,
    )

    # ── Colour adjustment expander ────────────────────────────────────────────
    _PRESET_COLORS = {
        "Navy (default)": "#002147",
        "Charcoal & Gold": "#2c2c2c",
        "Forest Green": "#1a4731",
        "Burgundy": "#6b1a2a",
        "Slate Blue": "#2d4a7a",
        "Dark Teal": "#1a4a4a",
    }
    with st.expander("Adjust CV colours", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            preset = st.selectbox(
                "Preset palette",
                list(_PRESET_COLORS.keys()),
                key="dl_color_preset",
            )
        with col2:
            current = st.session_state.get("template_color") or _PRESET_COLORS[preset]
            custom = st.color_picker("Custom colour", value=current, key="dl_color_picker")
        if st.button("Apply colour", key="dl_apply_color"):
            chosen = custom if custom != current else _PRESET_COLORS[preset]
            st.session_state.template_color = chosen
            st.rerun()

    has_general = bool(st.session_state.ai_cv_general or st.session_state.offline_cv)
    has_jd_cv = bool(st.session_state.ai_cv_jd)
    has_li = bool(st.session_state.linkedin_data)

    def get_cv(variant: str) -> dict:
        if variant == "jd":
            return st.session_state.ai_cv_jd or st.session_state.offline_cv
        # Prefer edited_cv (user's manual edits) over ai_cv_general
        return (st.session_state.get("edited_cv") or
                st.session_state.ai_cv_general or
                st.session_state.offline_cv)

    def make_download_row(variant_label: str, cv_key: str):
        cv = get_cv(cv_key)
        if not cv:
            st.info(f"No {variant_label} output available.")
            return
        # Show edit badge if user edits are active
        if cv_key != "jd" and st.session_state.get("edited_cv"):
            variant_label = f"{variant_label} ✏️"
        st.markdown(f"#### {variant_label}")
        fname_base = (cv.get("name", "cv") or "cv").replace(" ", "_")
        suffix = "_JD" if cv_key == "jd" else "_General"
        cols = st.columns(6)

        _format_download_btn(cols[0], cv, "docx", template, f"{fname_base}{suffix}.docx", template_color)
        _format_download_btn(cols[1], cv, "odt",  template, f"{fname_base}{suffix}.odt",  template_color)
        _format_download_btn(cols[2], cv, "pdf",  template, f"{fname_base}{suffix}.pdf",  template_color)
        _format_download_btn(cols[3], cv, "png",  template, f"{fname_base}{suffix}.png",  template_color)
        _format_download_btn(cols[4], cv, "txt",  template, f"{fname_base}{suffix}.txt",  template_color)

    if has_general:
        make_download_row("📄 General ATS-Optimized CV", "general")
    if has_jd_cv:
        make_download_row("🎯 JD-Tailored CV", "jd")

    if has_li:
        st.markdown("#### 🔗 LinkedIn Copy-Paste File")
        li_bytes = _build_linkedin_bytes(st.session_state.linkedin_data)
        fname_base = (get_cv("general").get("name", "cv") or "cv").replace(" ", "_")
        st.download_button(
            label="⬇️ Download LinkedIn (.txt)",
            data=li_bytes,
            file_name=f"{fname_base}_LinkedIn.txt",
            mime="text/plain",
            use_container_width=False,
        )

    # ── Send to candidate ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("Send to candidate")
    email_to = st.text_input("Candidate email", placeholder="candidate@email.com", key="send_email_to")
    col1, col2 = st.columns(2)
    with col1:
        send_pdf = st.button("Send PDF", use_container_width=True, key="send_pdf_btn")
    with col2:
        send_all = st.button("Send all formats", use_container_width=True, key="send_all_btn")
    if send_pdf and email_to:
        ok, err = _send_cv_email(to=email_to, formats=["pdf"])
        if ok:
            st.success(f"PDF sent to {email_to}")
        else:
            st.error(f"Failed to send: {err}")
    if send_all and email_to:
        ok, err = _send_cv_email(to=email_to, formats=["pdf", "docx", "txt"])
        if ok:
            st.success(f"All formats sent to {email_to}")
        else:
            st.error(f"Failed to send: {err}")
    if (send_pdf or send_all) and not email_to:
        st.warning("Please enter a candidate email address.")


def _format_download_btn(col, cv: dict, fmt: str, template: str, filename: str,
                         template_color: str = ""):
    LABELS = {
        "docx": "⬇️ Word",
        "odt":  "⬇️ ODT",
        "pdf":  "⬇️ PDF",
        "png":  "⬇️ PNG",
        "txt":  "⬇️ Text",
    }
    MIMES = {
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "odt":  "application/vnd.oasis.opendocument.text",
        "pdf":  "application/pdf",
        "png":  "image/png",
        "txt":  "text/plain",
    }
    try:
        data = _build_export_bytes(cv, fmt, template, template_color)
        with col:
            st.download_button(
                label=LABELS.get(fmt, fmt),
                data=data,
                file_name=filename,
                mime=MIMES.get(fmt, "application/octet-stream"),
                use_container_width=True,
                key=f"dl_{fmt}_{filename}_{template_color}",
            )
    except Exception as e:
        with col:
            st.error(f"{fmt.upper()} failed")


def _build_export_bytes(cv: dict, fmt: str, template: str,
                        template_color: str = "") -> bytes:
    """Build export bytes for the given CV dict and format."""
    import sys
    _exp_count = len(cv.get("experience", []))
    _edu_count = len(cv.get("education", []))
    _skills_cats = len(cv.get("skills", {}).get("categories", []))
    print(
        f"[export] fmt={fmt} template={template} "
        f"keys={sorted(k for k,v in cv.items() if v and k != 'raw_text')} "
        f"exp={_exp_count} edu={_edu_count} skills_cats={_skills_cats} "
        f"certs={len(cv.get('certifications', []))} langs={len(cv.get('languages', []))}",
        file=sys.stderr,
    )

    tmp_dir = Path(tempfile.gettempdir()) / "revizor_frank"
    tmp_dir.mkdir(exist_ok=True)
    out_path = str(tmp_dir / f"export_{uuid.uuid4().hex}.{fmt}")

    try:
        if fmt == "pdf":
            from revizor_frank.exporters.pdf_exporter import export_pdf
            export_pdf(cv, template, out_path, template_color=template_color)
        elif fmt == "png":
            from revizor_frank.exporters.png_exporter import export_png
            export_png(cv, template, out_path, template_color=template_color)
        elif fmt == "docx":
            from revizor_frank.exporters.docx_exporter import export_docx
            export_docx(cv, template, out_path, template_color=template_color)
        elif fmt == "odt":
            from revizor_frank.exporters.odt_exporter import export_odt
            export_odt(cv, template, out_path, template_color=template_color)
        elif fmt == "txt":
            from revizor_frank.exporters.txt_exporter import export_txt
            export_txt(cv, out_path)

        with open(out_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


def _build_linkedin_bytes(linkedin_data: dict) -> bytes:
    tmp_dir = Path(tempfile.gettempdir()) / "revizor_frank"
    tmp_dir.mkdir(exist_ok=True)
    out_path = str(tmp_dir / f"linkedin_{uuid.uuid4().hex}.txt")
    try:
        from revizor_frank.exporters.linkedin_exporter import export_linkedin
        export_linkedin(linkedin_data, out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


# ── CV owner response form (public — no auth) ────────────────────────────────

def render_owner_form(token: str):
    """Public form for CV owner to answer co-worker questions. No login required."""
    from revizor_frank.storage import supabase_db as _sdb

    st.markdown("## A few questions about your CV")
    st.caption("Please answer these quick questions to help your CV editor get everything right.")

    row = _sdb.get_owner_questions(token)
    if not row:
        st.error("This link has expired or is invalid.")
        return

    expires_at = row.get("expires_at")
    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                st.error("This link has expired or is invalid.")
                return
        except Exception:
            pass

    if row.get("status") == "submitted":
        st.success("You've already submitted your answers. Thank you!")
        return

    questions = row.get("questions") or []
    if not questions:
        st.info("No questions found for this link.")
        return

    with st.form("owner_answers_form"):
        answers = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            q_text = q.get("text", "")
            if not q_text:
                continue
            answer = st.text_area(q_text, key=f"owner_ans_{q.get('id', '')}", height=80)
            answers.append({"id": q.get("id", ""), "question": q_text, "answer": answer})

        submitted = st.form_submit_button("✅ Submit answers", type="primary")
        if submitted:
            ok = _sdb.submit_owner_answers(token, answers)
            if ok:
                st.success(
                    "Thank you! Your answers have been sent to your CV editor."
                )
                st.rerun()
            else:
                st.error("Could not save answers — please try again.")


# ── Send CV by email ─────────────────────────────────────────────────────────

def _send_cv_email(to: str, formats: list) -> tuple:
    """Send revised CV to candidate via SMTP. Returns (success: bool, error: str)."""
    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders as _encoders

    smtp_host  = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port  = int(os.getenv("SMTP_PORT", "465"))
    smtp_user  = os.getenv("SMTP_USER", "")
    smtp_pass  = os.getenv("SMTP_PASS", "")
    from_name  = os.getenv("SMTP_FROM_NAME", "ReviZoR FranK")

    if not smtp_user or not smtp_pass:
        st.error(
            "SMTP not configured. Add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS "
            "to Streamlit secrets."
        )
        return False, "SMTP credentials not set."

    cv = (
        st.session_state.get("edited_cv") or
        st.session_state.get("ai_cv_general") or
        st.session_state.get("offline_cv")
    )
    if not cv:
        return False, "No CV available to send."

    template       = st.session_state.get("selected_template", DEFAULT_TEMPLATE)
    template_color = st.session_state.get("template_color", "")
    fname_base     = (cv.get("name", "cv") or "cv").replace(" ", "_")
    cand_name      = cv.get("name", "Candidate")

    msg = MIMEMultipart()
    msg["From"]    = f"{from_name} <{smtp_user}>"
    msg["To"]      = to
    msg["Subject"] = f"Your Optimized CV — {cand_name}"
    msg.attach(MIMEText(
        f"Hi,\n\nPlease find your optimized CV attached.\n\nBest regards,\n{from_name}",
        "plain",
    ))

    for fmt in formats:
        try:
            data = _build_export_bytes(cv, fmt, template, template_color)
            part = MIMEBase("application", "octet-stream")
            part.set_payload(data)
            _encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", "attachment",
                filename=f"{fname_base}_General.{fmt}",
            )
            msg.attach(part)
        except Exception as e:
            return False, f"Could not build {fmt} export: {e}"

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to, msg.as_string())
        return True, ""
    except Exception as exc:
        return False, str(exc)


# ── Queue stage ───────────────────────────────────────────────────────────────

def render_queue():
    """Candidate queue — list all sessions, filter, resume or start new."""
    st.markdown("# 👥 Candidate Queue")
    st.caption("All CV sessions saved for this account.")
    st.divider()

    username = (
        st.session_state.get("simple_auth_user") or
        (st.session_state.get("auth_user") or {}).get("username", "")
    )
    sessions: list = []
    if username:
        try:
            from revizor_frank.storage import supabase_db as _sdb
            sessions = _sdb.list_sessions(username) or []
            # Cache locally so sidebar badge is up-to-date
            st.session_state.pending_session_list = sessions
        except Exception:
            st.warning("Could not load sessions from database.")

    right_col, _ = st.columns([1, 3])
    with right_col:
        if st.button("➕ New CV", type="primary", key="queue_new_cv",
                     use_container_width=True):
            _start_over()

    if not sessions:
        st.info("No previous sessions found for this account.")
        return

    # ── Filter pills ──────────────────────────────────────────────────────────
    filter_opt = st.radio(
        "Show",
        ["All", "In Progress", "Completed"],
        horizontal=True,
        key="queue_filter",
    )

    def _queue_status(s: dict) -> str:
        if s.get("is_complete"):
            return "Completed"
        if s.get("parsed_cv") is not None or s.get("stage") not in (None, "upload"):
            return "In Progress"
        return "Incomplete"

    if filter_opt == "In Progress":
        sessions = [s for s in sessions if _queue_status(s) == "In Progress"]
    elif filter_opt == "Completed":
        sessions = [s for s in sessions if _queue_status(s) == "Completed"]

    if not sessions:
        st.info(f"No '{filter_opt}' sessions found.")
        return

    st.divider()

    for s in sessions:
        _label   = s.get("display_name") or s.get("filename") or "Untitled CV"
        _stage   = (s.get("stage") or "unknown").replace("_", " ").title()
        _updated = (s.get("updated_at") or "")[:16].replace("T", " ")
        _status  = "✅ Complete" if s.get("is_complete") else f"⏸ {_stage}"

        # Initials avatar
        _words = _label.split()
        _initials = "".join(w[0].upper() for w in _words[:2]) if _words else "?"

        col_av, col_info, col_btn = st.columns([1, 6, 2])
        with col_av:
            st.markdown(
                f'<div style="width:40px;height:40px;border-radius:50%;'
                f'background:#0d6efd;color:white;display:flex;'
                f'align-items:center;justify-content:center;'
                f'font-weight:700;font-size:1rem">{_initials}</div>',
                unsafe_allow_html=True,
            )
        with col_info:
            st.markdown(f"**{_label}**")
            st.caption(f"{_status}  ·  Last saved: {_updated}")
        with col_btn:
            if st.button("Resume", key=f"q_resume_{s['session_id']}",
                         use_container_width=True):
                try:
                    from revizor_frank.storage import supabase_db as _sdb2
                    _saved = _sdb2.load_session(username, session_id=s["session_id"])
                    if _saved:
                        _restorable = [
                            "parsed_cv", "ai_cv_general", "ai_cv_jd", "offline_cv",
                            "linkedin_data", "job_description", "service_tier",
                            "selected_template", "template_color", "filename",
                            "ats_report", "session_id", "review_decisions",
                            "questions_list", "missing_fields", "edited_cv",
                        ]
                        for _key in _restorable:
                            if _saved.get(_key):
                                st.session_state[_key] = _saved[_key]
                        _sd = _saved.get("session_data") or {}
                        for _key in ("missing_fields", "questions_list", "selected_template"):
                            if _sd.get(_key):
                                st.session_state[_key] = _sd[_key]
                        if _saved.get("parsed_cv"):
                            st.session_state.session_already_parsed = True
                        st.session_state.session_restored_banner = True
                        st.session_state.show_session_picker = False
                        # Route to the saved stage (with migration)
                        _raw = _saved.get("stage", "upload")
                        _MIGRATE = {
                            "select_service": "upload", "upload_certs": "upload",
                            "processing": "process", "review_changes": "review",
                            "full_preview": "template", "select_template": "template",
                            "results": "download",
                        }
                        st.session_state.stage = _MIGRATE.get(_raw, _raw)
                        st.rerun()
                except Exception:
                    st.error("Could not load that session. Please try again.")
        st.divider()


# ── Edit stage ────────────────────────────────────────────────────────────────

def render_edit():
    """Standalone Edit CV section between Template and Download."""
    st.markdown("# ✏️ Edit CV")
    st.divider()

    if not st.session_state.get("ai_cv_general") and not st.session_state.get("offline_cv"):
        st.warning(
            "AI optimisation hasn't run yet — no CV to edit. "
            "Go to **Processing** to run it first."
        )

    tier = st.session_state.get("service_tier", "cv_linkedin")
    include_linkedin = (tier != "cv_only")
    _render_edit_cv_tab(include_linkedin)

    st.divider()
    col_back, _, col_fwd = st.columns([2, 3, 2])
    with col_back:
        if st.button("← Template", use_container_width=True, key="edit_back"):
            _go_to_stage("template")
    with col_fwd:
        if st.button("Download →", type="primary", use_container_width=True,
                     key="edit_to_download"):
            _go_to_stage("download")


# ── Main router ───────────────────────────────────────────────────────────────

def main():
    # ── CV owner response form — public, no auth ──────────────────────────────
    token = st.query_params.get("token")
    if token:
        render_owner_form(token)
        return

    # ── Auth gate: simple username/password mode ──────────────────────────────
    if SIMPLE_AUTH:
        if not _simple_auth_valid():
            _autosave_session()  # save before session is dropped
            render_simple_login()
            return

    # ── Auth gate: JWT / FastAPI mode ─────────────────────────────────────────
    elif AUTH_ENABLED:
        if not _session_is_valid():
            st.session_state.auth_token = None
            render_login()
            return

    # ── Timer-based autosave (every 60 s, regardless of stage) ───────────────
    _now_as = datetime.now(timezone.utc)
    _last_as = st.session_state.get("last_autosave")
    if _last_as is None or (_now_as - _last_as).total_seconds() > 60:
        _autosave_session()
        st.session_state.last_autosave = _now_as

    # URL stage sync intentionally removed — reading the browser URL to set
    # session state caused browser back to re-route into login. Navigation is
    # now handled exclusively by _go_to_stage() and the top nav bar buttons.

    # ── Stage migration — backward compat with saved sessions ────────────────
    _STAGE_MIGRATION = {
        "select_service": "upload",
        "upload_certs":   "upload",
        "processing":     "process",
        "review_changes": "review",
        "full_preview":   "template",
        "select_template": "template",
        "results":        "download",
    }
    _raw_stage = st.session_state.get("stage", "upload")
    if _raw_stage in _STAGE_MIGRATION:
        st.session_state.stage = _STAGE_MIGRATION[_raw_stage]

    render_sidebar()
    stage = st.session_state.stage
    # Keep URL in sync with current stage
    st.query_params["stage"] = stage

    if stage == "upload":
        render_upload()
    elif stage == "process":
        _run_pipeline()
    elif stage == "review":
        render_review_changes()
    elif stage == "template":
        render_select_template()
    elif stage == "edit":
        render_edit()
    elif stage == "download":
        render_results()
    elif stage == "queue":
        render_queue()
    elif stage == "admin":
        if st.session_state.get("user_role") == "admin":
            render_admin_dashboard()
        else:
            st.error("Access denied.")
            _go_to_stage("upload")


if __name__ == "__main__":
    main()
