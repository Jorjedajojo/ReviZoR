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
               "SUPABASE_URL", "SUPABASE_ANON_KEY"):
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
        "stage":            "select_service",  # select_service | upload | processing | results
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
        # Certificate upload
        "uploaded_cv_bytes":      None,
        "certificates":           [],   # confirmed cert dicts merged into CV
        "pending_cert_results":   [],   # extracted but not yet confirmed
        "cert_input_tokens":      0,
        "cert_output_tokens":     0,
        # Inline editor
        "edited_cv_text":   "",
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


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
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

            st.markdown(f"**{st.session_state.get('simple_auth_user', 'user')}**")
            st.caption(f"Session expires in: :{color}[{rem_str}]")
            if st.button("Sign Out", use_container_width=True):
                st.session_state.simple_auth_ok   = False
                st.session_state.simple_auth_time = None
                st.rerun()
            st.divider()

        # ── Auth info — JWT mode ──────────────────────────────────────────────
        elif AUTH_ENABLED and st.session_state.auth_user:
            user = st.session_state.auth_user
            remaining = _session_remaining_str()
            st.markdown(
                f"**{user.get('username', '')}**  "
                f"`{user.get('role', 'user').upper()}`"
            )
            if remaining:
                color = "red" if remaining in ("Expired",) else "orange" if "m" in remaining and "h" not in remaining else "green"
                st.caption(f"Session expires in: :{color}[{remaining}]")
            if st.button("Sign Out", use_container_width=True):
                _api_logout()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
            st.divider()

        # Connection status
        online = _check_online()
        st.session_state.online = online
        if online:
            st.success(f"🟢 {S['status_online']}")
        else:
            if ANTHROPIC_API_KEY:
                st.warning("🟡 API key found but no internet")
            else:
                st.info(f"⚪ {S['status_offline']}")

        st.divider()
        st.markdown("### Template")
        selected = st.session_state.selected_template
        for key, info in TEMPLATES.items():
            label = f"{'✓ ' if key == selected else '   '}{info['name']}"
            if st.button(label, key=f"tmpl_{key}", use_container_width=True):
                st.session_state.selected_template = key
                st.rerun()

        st.divider()
        if st.session_state.stage in ("upload", "results"):
            if st.button("🔄 Start Over", use_container_width=True):
                # Preserve auth + role state
                keep = ("auth_token", "refresh_token", "auth_user", "auth_expires_at", "auth_error",
                        "simple_auth_ok", "simple_auth_time", "simple_auth_user", "user_role")
                auth_keys = {k: st.session_state[k] for k in keep if k in st.session_state}
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.session_state.update(auth_keys)
                st.rerun()

        # Admin dashboard button (only for admin role)
        if st.session_state.get("user_role") == "admin":
            st.divider()
            if st.button("🛠 Admin Dashboard", use_container_width=True):
                st.session_state.stage = "admin"
                st.rerun()

        st.divider()
        st.caption("ReviZoR FranK — Part of the ReviZoR HR Platform")


# ── Service selection stage ───────────────────────────────────────────────────

def render_select_service():
    st.markdown(f"# 📄 {APP_NAME}")
    st.markdown("*Choose your service before uploading your CV.*")
    st.divider()

    col_l, col_m, col_r = st.columns([1, 3, 1])
    with col_m:
        st.markdown("## Select Your Service")
        st.markdown("<br>", unsafe_allow_html=True)

        tier_col1, tier_col2 = st.columns(2, gap="large")

        with tier_col1:
            st.markdown("""
<div style="border:2px solid #0d6efd;border-radius:12px;padding:1.5rem;text-align:center">
<h3 style="margin:0">📄 CV Revision</h3>
<p style="font-size:2rem;font-weight:800;color:#0d6efd;margin:0.5rem 0">$7.50</p>
<ul style="text-align:left;margin-top:1rem">
<li>ATS score &amp; issue report</li>
<li>AI-optimized CV rewrite</li>
<li>JD-tailored version (if JD provided)</li>
<li>Plain text (.txt) output</li>
</ul>
</div>""", unsafe_allow_html=True)
            if st.button("Select CV Revision", key="tier_cv_only",
                         use_container_width=True, type="primary"):
                st.session_state.service_tier = "cv_only"
                st.session_state.stage = "upload"
                st.rerun()

        with tier_col2:
            st.markdown("""
<div style="border:2px solid #198754;border-radius:12px;padding:1.5rem;text-align:center">
<h3 style="margin:0">📄 + 🔗 CV + LinkedIn</h3>
<p style="font-size:2rem;font-weight:800;color:#198754;margin:0.5rem 0">$10.00</p>
<ul style="text-align:left;margin-top:1rem">
<li>Everything in CV Revision</li>
<li>Full LinkedIn profile generator</li>
<li>All 6 download formats</li>
<li>Inline CV editor</li>
</ul>
</div>""", unsafe_allow_html=True)
            if st.button("Select CV + LinkedIn", key="tier_cv_linkedin",
                         use_container_width=True, type="primary"):
                st.session_state.service_tier = "cv_linkedin"
                st.session_state.stage = "upload"
                st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        st.divider()
        st.markdown("**Have a coupon code?**")
        coupon = st.text_input("Coupon Code (optional)", placeholder="Enter code",
                               value=st.session_state.get("coupon_code", ""),
                               key="coupon_input")
        if coupon != st.session_state.get("coupon_code", ""):
            st.session_state.coupon_code = coupon.strip()


# ── Upload stage ──────────────────────────────────────────────────────────────

def render_upload():
    st.markdown(f"# 📄 {APP_NAME}")
    st.markdown(f"*{S['app_tagline']}*")
    st.divider()

    col1, col2 = st.columns([3, 2], gap="large")

    with col1:
        st.markdown(f"### {S['upload_header']}")
        uploaded = st.file_uploader(
            S["upload_instruction"],
            type=["pdf", "docx", "txt"],
            label_visibility="visible",
        )

        st.markdown(f"### {S['upload_jd_label']}")
        jd = st.text_area(
            S["upload_jd_help"],
            placeholder=S["upload_jd_placeholder"],
            height=200,
            label_visibility="visible",
        )

        ready = uploaded is not None
        btn = st.button(
            f"🚀 {S['upload_btn']}",
            disabled=not ready,
            type="primary",
            use_container_width=True,
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

    if btn and uploaded:
        st.session_state.filename = uploaded.name
        st.session_state.uploaded_cv_bytes = uploaded.getvalue()
        st.session_state.job_description = jd.strip()
        st.session_state.certificates = []
        st.session_state.pending_cert_results = []
        st.session_state.cert_input_tokens = 0
        st.session_state.cert_output_tokens = 0
        st.session_state.stage = "upload_certs"
        st.rerun()


# ── Certificate upload stage ──────────────────────────────────────────────────

def render_upload_certs():
    st.markdown(f"# 📄 {APP_NAME}")
    st.markdown(f"**CV uploaded:** `{st.session_state.filename}`")
    st.divider()

    col_left, col_right = st.columns([2, 1], gap="large")

    with col_left:
        st.markdown("### 📜 Add Certificates (Optional)")
        st.caption(
            "Upload certificate files — Claude will extract the details automatically. "
            "Certificates are added to your CV before AI optimisation so they appear in all outputs."
        )

        cert_files = st.file_uploader(
            "Certificate files (PDF, JPG, PNG)",
            type=["pdf", "jpg", "jpeg", "png"],
            accept_multiple_files=True,
            key="cert_uploader",
            label_visibility="collapsed",
        )

        if cert_files:
            if st.button("🔍 Extract Certificate Details", type="secondary",
                         use_container_width=True):
                if not _check_online():
                    st.warning("Certificate extraction requires internet. "
                               "You can still proceed — add certs manually below.")
                else:
                    results = []
                    total_in, total_out = 0, 0
                    with st.spinner(f"Extracting details from {len(cert_files)} file(s)…"):
                        try:
                            from revizor_frank.core import cert_extractor
                            for cf in cert_files:
                                cert, in_tok, out_tok = cert_extractor.extract_certificate(
                                    cf.getvalue(), cf.name
                                )
                                cert["_filename"] = cf.name
                                results.append(cert)
                                total_in += in_tok
                                total_out += out_tok
                        except Exception as e:
                            st.error(f"Extraction failed: {e}")
                    if results:
                        st.session_state.pending_cert_results = results
                        st.session_state.cert_input_tokens += total_in
                        st.session_state.cert_output_tokens += total_out
                        st.rerun()

        # ── Editable form for extracted certs ─────────────────────────────────
        pending = st.session_state.get("pending_cert_results", [])
        if pending:
            st.divider()
            st.markdown("#### ✏️ Review & Edit Extracted Details")
            st.caption("Correct any errors, then click **Confirm** to add to your CV.")

            with st.form("cert_confirm_form"):
                edited = []
                for i, cert in enumerate(pending):
                    label = cert.get("name") or cert.get("_filename", f"Certificate {i + 1}")
                    st.markdown(f"**📜 {label}**")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        c_name   = st.text_input("Certificate Name",    value=cert.get("name", ""),          key=f"cname_{i}")
                        c_issuer = st.text_input("Issuing Organisation", value=cert.get("issuer", ""),        key=f"ciss_{i}")
                    with col_b:
                        c_date   = st.text_input("Issue Date",           value=cert.get("date", ""),          key=f"cdate_{i}")
                        c_id     = st.text_input("Credential ID (opt.)", value=cert.get("credential_id", ""), key=f"ccid_{i}")
                    edited.append({"name": c_name, "issuer": c_issuer,
                                   "date": c_date,  "credential_id": c_id})
                    if i < len(pending) - 1:
                        st.divider()

                col_ok, col_skip_certs = st.columns(2)
                with col_ok:
                    confirmed = st.form_submit_button(
                        "✅ Confirm & Optimize CV", type="primary", use_container_width=True
                    )
                with col_skip_certs:
                    skipped_certs = st.form_submit_button(
                        "Skip Certificates", use_container_width=True
                    )

            if confirmed:
                st.session_state.certificates = [
                    {"name": c["name"], "issuer": c["issuer"],
                     "date": c["date"],  "credential_id": c.get("credential_id", "")}
                    for c in edited if c.get("name")
                ]
                st.session_state.pending_cert_results = []
                st.session_state.stage = "processing"
                st.rerun()
            elif skipped_certs:
                st.session_state.pending_cert_results = []
                st.session_state.stage = "processing"
                st.rerun()

        # ── Skip entirely ──────────────────────────────────────────────────────
        if not pending:
            st.markdown("<br>", unsafe_allow_html=True)
            col_proc, col_back = st.columns([2, 1])
            with col_proc:
                if st.button("⏭️ No certificates — Proceed to Optimization",
                             type="primary", use_container_width=True):
                    st.session_state.stage = "processing"
                    st.rerun()
            with col_back:
                if st.button("← Back to Upload", use_container_width=True):
                    st.session_state.stage = "upload"
                    st.rerun()

    with col_right:
        st.markdown("### Why add certificates?")
        st.markdown("""
Adding certificates helps Claude write a stronger CV:

- **ATS scoring** — certifications are a key scoring factor
- **All sections** — appear in PDF, DOCX, and LinkedIn outputs
- **Context** — Claude references them when rewriting your summary

**Supported formats:**
- PDF certificates
- JPG / PNG images of certificates

Certificate extraction is a separate, lightweight API call — it does not inflate your main optimisation cost.
        """)


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
        st.session_state.stage = "upload"
        st.rerun()
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
        status.info(f"⚙️ {S['parsing_cv']}")
        file_bytes = io.BytesIO(cv_bytes)
        parsed, pdf_in_tok, pdf_out_tok = cv_parser.parse_cv(
            file_bytes, filename, api_key=ANTHROPIC_API_KEY
        )
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
        st.session_state.parsed_cv = parsed
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
            )
        except Exception:
            pass  # Supabase save is best-effort; never break the main flow

        progress.progress(100, text=S["done"])
        time.sleep(0.5)
        status.empty()
        progress.empty()
        st.session_state.stage = "results"
        st.rerun()

    except Exception as e:
        progress.empty()
        status.empty()
        st.session_state.stage = "upload"
        st.error(f"{S['err_parse_failed']} — {e}")


# ── Results stage ─────────────────────────────────────────────────────────────

def render_results():
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
        _render_downloads()


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

    # Initialize edit buffer from CV if not already set
    if not st.session_state.get("edited_cv_text"):
        st.session_state.edited_cv_text = _cv_to_text(cv_source)

    edited = st.text_area(
        "CV Text",
        value=st.session_state.edited_cv_text,
        height=500,
        key="cv_text_editor",
        label_visibility="collapsed",
    )

    btn_label = "✅ Apply edits & refresh LinkedIn" if include_linkedin else "✅ Apply edits"
    if st.button(btn_label, type="primary"):
        st.session_state.edited_cv_text = edited

        if include_linkedin and st.session_state.online and st.session_state.ai_cv_general:
            with st.spinner("Regenerating LinkedIn profile from edited CV…"):
                try:
                    from revizor_frank.core import cv_optimizer
                    # Build a minimal CVData dict from the edited text
                    from revizor_frank.core.cv_parser import parse_cv as _parse_cv
                    import io as _io
                    raw_bytes = _io.BytesIO(edited.encode("utf-8"))
                    raw_bytes.name = "edited_cv.txt"
                    edited_parsed, _, _ = _parse_cv(raw_bytes, "edited_cv.txt")
                    linkedin, in_tok, out_tok = cv_optimizer.generate_linkedin(
                        edited_parsed,
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
                    st.success("LinkedIn profile refreshed from your edits.")
                except Exception as e:
                    st.error(f"Could not regenerate LinkedIn: {e}")
        elif include_linkedin and not st.session_state.online:
            st.info("LinkedIn refresh requires internet connection.")
        else:
            st.success("Edits saved.")


def render_admin_dashboard():
    import csv
    from io import StringIO

    st.markdown("# 🛠 Admin Dashboard")
    st.divider()

    # ── Month selector ────────────────────────────────────────────────────────
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

    # ── P&L Summary ───────────────────────────────────────────────────────────
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

        # Tier breakdown
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

    # ── Coupon Manager ────────────────────────────────────────────────────────
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

    # ── CSV Export ────────────────────────────────────────────────────────────
    st.markdown("### Export Data")
    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        # Monthly export
        if runs:
            buf = StringIO()
            if runs:
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

    st.divider()
    if st.button("← Back to App", use_container_width=False):
        st.session_state.stage = "select_service"
        st.rerun()


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
    template_name = TEMPLATES.get(template, {}).get("name", template)
    st.caption(f"Template: **{template_name}**  ·  All formats are ATS-safe")

    has_general = bool(st.session_state.ai_cv_general or st.session_state.offline_cv)
    has_jd_cv = bool(st.session_state.ai_cv_jd)
    has_li = bool(st.session_state.linkedin_data)

    def get_cv(variant: str) -> dict:
        if variant == "jd":
            return st.session_state.ai_cv_jd or st.session_state.offline_cv
        return st.session_state.ai_cv_general or st.session_state.offline_cv

    def make_download_row(variant_label: str, cv_key: str):
        cv = get_cv(cv_key)
        if not cv:
            st.info(f"No {variant_label} output available.")
            return
        st.markdown(f"#### {variant_label}")
        fname_base = (cv.get("name", "cv") or "cv").replace(" ", "_")
        suffix = "_JD" if cv_key == "jd" else "_General"
        cols = st.columns(6)

        _format_download_btn(cols[0], cv, "docx", template, f"{fname_base}{suffix}.docx")
        _format_download_btn(cols[1], cv, "odt",  template, f"{fname_base}{suffix}.odt")
        _format_download_btn(cols[2], cv, "pdf",  template, f"{fname_base}{suffix}.pdf")
        _format_download_btn(cols[3], cv, "png",  template, f"{fname_base}{suffix}.png")
        _format_download_btn(cols[4], cv, "txt",  template, f"{fname_base}{suffix}.txt")

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


def _format_download_btn(col, cv: dict, fmt: str, template: str, filename: str):
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
        data = _build_export_bytes(cv, fmt, template)
        with col:
            st.download_button(
                label=LABELS.get(fmt, fmt),
                data=data,
                file_name=filename,
                mime=MIMES.get(fmt, "application/octet-stream"),
                use_container_width=True,
                key=f"dl_{fmt}_{filename}",
            )
    except Exception as e:
        with col:
            st.error(f"{fmt.upper()} failed")


@st.cache_data(ttl=300, show_spinner=False)
def _build_export_bytes(cv: dict, fmt: str, template: str) -> bytes:
    """Build export bytes. Cached to avoid re-generating on every rerun."""
    # Use a stable temp dir tied to the session
    tmp_dir = Path(tempfile.gettempdir()) / "revizor_frank"
    tmp_dir.mkdir(exist_ok=True)
    out_path = str(tmp_dir / f"export_{uuid.uuid4().hex}.{fmt}")

    try:
        if fmt == "pdf":
            from revizor_frank.exporters.pdf_exporter import export_pdf
            export_pdf(cv, template, out_path)
        elif fmt == "png":
            from revizor_frank.exporters.png_exporter import export_png
            export_png(cv, template, out_path)
        elif fmt == "docx":
            from revizor_frank.exporters.docx_exporter import export_docx
            export_docx(cv, template, out_path)
        elif fmt == "odt":
            from revizor_frank.exporters.odt_exporter import export_odt
            export_odt(cv, template, out_path)
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


# ── Main router ───────────────────────────────────────────────────────────────

def main():
    # ── Auth gate: simple username/password mode ──────────────────────────────
    if SIMPLE_AUTH:
        if not _simple_auth_valid():
            render_simple_login()
            return

    # ── Auth gate: JWT / FastAPI mode ─────────────────────────────────────────
    elif AUTH_ENABLED:
        if not _session_is_valid():
            st.session_state.auth_token = None
            render_login()
            return

    render_sidebar()
    stage = st.session_state.stage
    if stage == "select_service":
        render_select_service()
    elif stage == "upload":
        render_upload()
    elif stage == "upload_certs":
        render_upload_certs()
    elif stage == "processing":
        _run_pipeline()
    elif stage == "results":
        render_results()
    elif stage == "admin":
        if st.session_state.get("user_role") == "admin":
            render_admin_dashboard()
        else:
            st.error("Access denied.")
            st.session_state.stage = "select_service"
            st.rerun()


if __name__ == "__main__":
    main()
