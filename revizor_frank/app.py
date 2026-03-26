"""ReviZoR FranK — Main Streamlit Application.

Run with:  streamlit run revizor_frank/app.py
"""

from __future__ import annotations

import io
import os
import tempfile
import time
import uuid
from pathlib import Path

import streamlit as st

from revizor_frank.config import (
    APP_NAME,
    APP_VERSION,
    EXPORTS_DIR,
    TEMPLATES,
    DEFAULT_TEMPLATE,
    ANTHROPIC_API_KEY,
)
from revizor_frank.i18n import STRINGS as S

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
        "stage":            "upload",      # upload | processing | results
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
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


_init_state()


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

        # Connection status
        online = _check_online()
        st.session_state.online = online
        if online:
            st.success(f"🟢 {S['status_online']}", icon=None)
        else:
            if ANTHROPIC_API_KEY:
                st.warning("🟡 API key found but no internet", icon=None)
            else:
                st.info(f"⚪ {S['status_offline']}", icon=None)

        st.divider()
        st.markdown("### Template")
        selected = st.session_state.selected_template
        for key, info in TEMPLATES.items():
            label = f"{'✓ ' if key == selected else '   '}{info['name']}"
            if st.button(label, key=f"tmpl_{key}", use_container_width=True):
                st.session_state.selected_template = key
                st.rerun()

        st.divider()
        if st.session_state.stage == "results":
            if st.button("🔄 Start Over", use_container_width=True):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()

        st.divider()
        st.caption("ReviZoR FranK — Part of the ReviZoR HR Platform")


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
        st.session_state.job_description = jd.strip()
        _run_pipeline(uploaded)


# ── Processing pipeline ───────────────────────────────────────────────────────

def _run_pipeline(uploaded_file):
    """Run the full parse → analyze → optimize → LinkedIn pipeline."""
    from revizor_frank.core import cv_parser, cv_analyzer, ats_engine
    from revizor_frank.core import linkedin_gen
    from revizor_frank.storage import database as db

    st.session_state.stage = "processing"
    st.session_state.error = None

    progress = st.progress(0, text="Starting...")
    status = st.empty()

    try:
        # 1. Parse
        status.info(f"⚙️ {S['parsing_cv']}")
        file_bytes = io.BytesIO(uploaded_file.getvalue())
        parsed = cv_parser.parse_cv(file_bytes, uploaded_file.name)
        st.session_state.parsed_cv = parsed
        progress.progress(20, text=S["parsing_cv"])

        # 2. Create DB session
        session_id = db.create_session(uploaded_file.name, parsed.get("raw_text", ""))
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
        if online:
            try:
                from revizor_frank.core import cv_optimizer
                status.info(f"🤖 {S['optimizing_ai']} (General ATS)...")
                general_cv = cv_optimizer.optimize_general(offline_cv)
                st.session_state.ai_cv_general = general_cv
                db.update_session(session_id, ai_cv_general=general_cv)
                progress.progress(75, text="General ATS optimization complete")

                jd_cv = None
                if st.session_state.job_description:
                    status.info(f"🤖 {S['optimizing_ai']} (JD-Tailored)...")
                    jd_cv = cv_optimizer.optimize_jd_tailored(
                        parsed, st.session_state.job_description, general_cv
                    )
                    st.session_state.ai_cv_jd = jd_cv
                    db.update_session(session_id, ai_cv_jd=jd_cv)
                progress.progress(85, text="AI optimization complete")

                # LinkedIn via Claude
                status.info(f"🤖 {S['generating_linkedin']}...")
                linkedin = cv_optimizer.generate_linkedin(
                    parsed, general_cv, st.session_state.job_description
                )
                st.session_state.linkedin_data = linkedin
                db.update_session(session_id, linkedin_data=linkedin,
                                  sync_status="synced", ai_enhanced=1)

            except Exception as e:
                st.session_state.error = f"{S['err_api_failed']} ({e})"
                # Fall through to offline LinkedIn
                online = False

        if not online:
            # Offline LinkedIn
            status.info(f"⚙️ {S['generating_linkedin']}...")
            linkedin = linkedin_gen.generate_offline(offline_cv)
            st.session_state.linkedin_data = linkedin
            db.update_session(session_id, linkedin_data=linkedin,
                              sync_status="queued")

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

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_labels = [S["tab_general"]]
    if has_jd:
        tab_labels.append(S["tab_jd_tailored"])
    tab_labels += [S["tab_linkedin"], "🔍 ATS Issues", S["tab_download"]]

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
                # Show keyword match highlights
                if ats.get("keyword_matches"):
                    with st.expander("✅ Keywords matched from JD"):
                        st.write(", ".join(ats["keyword_matches"]))
                if ats.get("missing_keywords"):
                    with st.expander("⚠️ Keywords still missing from JD"):
                        st.write(", ".join(ats["missing_keywords"][:30]))
            else:
                st.info("JD-tailored version requires internet connection. Will be generated automatically when connectivity returns.")

    # LinkedIn Tab
    with tabs[tab_idx]:
        tab_idx += 1
        _render_linkedin_tab()

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
            st.success(s.title(), icon="✓")
    with col2:
        st.markdown("**Sections Missing**")
        for s in ats.get("sections_missing", []):
            st.error(s.title(), icon="✗")

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
            st.error(f"{fmt.upper()} failed", icon="⚠️")


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
    render_sidebar()
    stage = st.session_state.stage
    if stage == "upload":
        render_upload()
    elif stage == "processing":
        render_upload()  # pipeline runs within upload render
    elif stage == "results":
        render_results()


if __name__ == "__main__":
    main()
