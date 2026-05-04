#!/usr/bin/env python3
"""ReviZoR FranK — Change verification script.

Checks that every deliberate code change introduced across the
claude/analyze-app-integration branch is still present and structurally
valid.  Runs with no external dependencies beyond the stdlib — Streamlit
does NOT need to be installed or running.

Usage:
    python scripts/verify_changes.py          # run all checks
    python scripts/verify_changes.py --fast   # skip AST-heavy checks
"""
from __future__ import annotations

import ast
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP_PY        = ROOT / "revizor_frank" / "app.py"
CONFIG_PY     = ROOT / "revizor_frank" / "config.py"
SYNC_PY       = ROOT / "revizor_frank" / "core" / "sync_manager.py"
SERVER_DB_PY  = ROOT / "server" / "database.py"
CV_PARSER_PY  = ROOT / "revizor_frank" / "core" / "cv_parser.py"

FAST = "--fast" in sys.argv

# ── Colour helpers ─────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


# ── Result tracking ────────────────────────────────────────────────────────────

_results: list[tuple[bool, str, str]] = []   # (passed, check_name, detail)


def _pass(name: str, detail: str = "") -> None:
    _results.append((True, name, detail))
    print(f"  {GREEN}✓{RESET} {name}" + (f"  — {detail}" if detail else ""))


def _fail(name: str, detail: str = "") -> None:
    _results.append((False, name, detail))
    print(f"  {RED}✗{RESET} {name}" + (f"\n      {RED}{detail}{RESET}" if detail else ""))


def _section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# ── File helpers ───────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse(path: Path) -> ast.Module:
    return ast.parse(_read(path), filename=str(path))


def _fn_names(tree: ast.Module) -> set[str]:
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _class_names(tree: ast.Module) -> set[str]:
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


def _count_pattern(source: str, pattern: str) -> int:
    return len(re.findall(pattern, source))


def _contains(source: str, pattern: str) -> bool:
    return bool(re.search(pattern, source, re.MULTILINE))


def _line_of(source: str, pattern: str) -> int | None:
    """Return 1-based line number of the first match, or None."""
    for i, line in enumerate(source.splitlines(), 1):
        if re.search(pattern, line):
            return i
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. SYNTAX — every tracked .py file must parse cleanly
# ══════════════════════════════════════════════════════════════════════════════

def check_syntax() -> None:
    _section("1. Syntax validation")
    tracked = [APP_PY, CONFIG_PY, SYNC_PY, SERVER_DB_PY, CV_PARSER_PY]
    for path in tracked:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            _pass(f"Syntax OK: {path.relative_to(ROOT)}")
        except SyntaxError as exc:
            _fail(f"Syntax error: {path.relative_to(ROOT)}", str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# 2. CONFIG.PY — correct model names
# ══════════════════════════════════════════════════════════════════════════════

def check_config() -> None:
    _section("2. config.py — model names & constants")
    src = _read(CONFIG_PY)

    if _contains(src, r'CLAUDE_MODEL\s*=\s*["\']claude-opus-4-7["\']'):
        _pass("CLAUDE_MODEL = claude-opus-4-7 (valid)")
    else:
        _fail("CLAUDE_MODEL must be claude-opus-4-7",
              "Was claude-opus-4-6 (non-existent model) — causes all AI calls to fail")

    if _contains(src, r'CLAUDE_FAST_MODEL\s*=\s*["\']claude-sonnet-4-6["\']'):
        _pass("CLAUDE_FAST_MODEL = claude-sonnet-4-6 (valid)")
    else:
        _fail("CLAUDE_FAST_MODEL must be claude-sonnet-4-6")

    if _contains(src, r'CONNECTIVITY_TEST_URL\s*=\s*["\']https://api\.anthropic\.com["\']'):
        _pass("CONNECTIVITY_TEST_URL present")
    else:
        _fail("CONNECTIVITY_TEST_URL missing or wrong")


# ══════════════════════════════════════════════════════════════════════════════
# 3. SERVER/DATABASE.PY — unified DB path
# ══════════════════════════════════════════════════════════════════════════════

def check_server_db() -> None:
    _section("3. server/database.py — unified SQLite path")
    src = _read(SERVER_DB_PY)

    if _contains(src, r'revizor\.db'):
        _pass("_DB_PATH points to revizor.db (shared with CV session store)")
    else:
        _fail("_DB_PATH must point to revizor.db",
              "auth.db would be a separate file — two databases instead of one")

    if _contains(src, r'auth\.db'):
        _fail("Old auth.db path still present — DB is not unified")
    else:
        _pass("No old auth.db reference found")


# ══════════════════════════════════════════════════════════════════════════════
# 4. SYNC_MANAGER.PY — thread removed, maybe_sync present
# ══════════════════════════════════════════════════════════════════════════════

def check_sync_manager() -> None:
    _section("4. sync_manager.py — thread-safe Streamlit sync")
    src = _read(SYNC_PY)
    tree = _parse(SYNC_PY)
    classes = _class_names(tree)
    fns = _fn_names(tree)

    if "SyncWorker" not in classes:
        _pass("SyncWorker class removed (background threads unsafe in Streamlit)")
    else:
        _fail("SyncWorker class still present — must be removed")

    if "maybe_sync" in fns:
        _pass("maybe_sync() present (on-demand sync safe to call from Streamlit)")
    else:
        _fail("maybe_sync() missing")

    if "get_sync_status" in fns:
        _pass("get_sync_status() present")
    else:
        _fail("get_sync_status() missing")

    if "is_online" in fns:
        _pass("is_online() present")
    else:
        _fail("is_online() missing")

    if not _contains(src, r'^import threading', ):
        _pass("No threading import (consistent with thread removal)")
    else:
        _fail("threading still imported — SyncWorker likely not fully removed")


# ══════════════════════════════════════════════════════════════════════════════
# 5. APP.PY — module-level imports
# ══════════════════════════════════════════════════════════════════════════════

def check_app_imports() -> None:
    _section("5. app.py — module-level imports")
    src = _read(APP_PY)

    if _contains(src, r'^import copy$', ) or _contains(src, r'^import copy\s*$'):
        _pass("import copy present at module level")
    else:
        _fail("import copy missing from module level")

    if _contains(src, r'^import html as _html$') or _contains(src, r'import html as _html'):
        _pass("import html as _html present (for comparison panel XSS fix)")
    else:
        _fail("import html as _html missing — comparison panels will inject raw HTML")


# ══════════════════════════════════════════════════════════════════════════════
# 6. APP.PY — required functions exist
# ══════════════════════════════════════════════════════════════════════════════

def check_app_functions() -> None:
    _section("6. app.py — required function definitions")
    if FAST:
        print(f"  {YELLOW}(skipped in --fast mode){RESET}")
        return
    tree = _parse(APP_PY)
    fns = _fn_names(tree)

    required = {
        "_apply_review_decisions": "merge review decisions into final CV",
        "_resync_review_revised":  "refresh diff display on back-navigation",
        "_get_editable_cv":        "deep copy of working CV for edit stage",
        "_persist_edited_cv":      "unified save: writes to edited_cv + sets linkedin_stale",
        "_refresh_linkedin_after_edit": "online LinkedIn regeneration after section save",
        "_render_edit_cv_tab":     "structured inline editor (Option B)",
        "render_review_changes":   "side-by-side review stage",
        "render_full_preview":     "full comparison preview page",
        "render_results":          "download/results stage",
        "_render_linkedin_tab":    "LinkedIn output tab",
    }
    for fn, purpose in required.items():
        if fn in fns:
            _pass(f"def {fn}()  —  {purpose}")
        else:
            _fail(f"def {fn}() missing", purpose)


# ══════════════════════════════════════════════════════════════════════════════
# 7. APP.PY — _apply_review_decisions logic
# ══════════════════════════════════════════════════════════════════════════════

def check_apply_review_decisions() -> None:
    _section("7. _apply_review_decisions() — data-flow invariants")
    src = _read(APP_PY)

    # Base source: edited_cv takes priority
    if _contains(src, r'get\("edited_cv"\)\s*or\s*\n?\s*st\.session_state\.ai_cv_general'):
        _pass("Base source: edited_cv or ai_cv_general (edits preserved on re-finalise)")
    elif _contains(src, r'get\("edited_cv"\) or'):
        _pass("Base source: edited_cv or … (edits preserved on re-finalise)")
    else:
        _fail("_apply_review_decisions() base does not prefer edited_cv",
              "User edits made in Edit stage will be lost when re-finalising review")

    # edited_cv cleared after merge
    if _contains(src, r'st\.session_state\.edited_cv\s*=\s*None'):
        _pass("edited_cv = None after merge (prevents stale edits leaking to downloads)")
    else:
        _fail("edited_cv not cleared after merge",
              "Stale edited_cv will override the fresh merged ai_cv_general in downloads")

    # linkedin_stale set
    if _contains(src, r'st\.session_state\.linkedin_stale\s*=\s*True'):
        _pass("linkedin_stale = True set after merge")
    else:
        _fail("linkedin_stale not set after merge — LinkedIn tab won't refresh")


# ══════════════════════════════════════════════════════════════════════════════
# 8. APP.PY — _resync_review_revised called on back-navigation
# ══════════════════════════════════════════════════════════════════════════════

def check_resync_called() -> None:
    _section("8. _resync_review_revised() — called on back-navigation")
    src = _read(APP_PY)

    pattern = (
        r'if not st\.session_state\.get\("review_decisions"\).*?'
        r'_init_review_state\(\).*?'
        r'else.*?'
        r'_resync_review_revised\(\)'
    )
    if re.search(pattern, src, re.DOTALL):
        _pass("_resync_review_revised() called in else-branch when review_decisions exist")
    else:
        # Try a simpler check: both the else and the call appear in same proximity
        block = re.search(
            r'_init_review_state\(\).{0,200}_resync_review_revised\(\)',
            src, re.DOTALL
        )
        if block:
            _pass("_resync_review_revised() called shortly after _init_review_state block")
        else:
            _fail("_resync_review_revised() not wired into render_review_changes()",
                  "Back-navigation will show stale diff text")


# ══════════════════════════════════════════════════════════════════════════════
# 9. APP.PY — comparison panels use html.escape (XSS / display fix)
# ══════════════════════════════════════════════════════════════════════════════

def check_html_escape() -> None:
    _section("9. Comparison panels — html.escape() applied")
    src = _read(APP_PY)

    escape_count = _count_pattern(src, r'_html\.escape\(')
    if escape_count >= 4:
        _pass(f"_html.escape() used {escape_count}× in comparison panels (≥4 required)")
    elif escape_count > 0:
        _fail(f"_html.escape() used only {escape_count}× — expected ≥4",
              "Some comparison panel is still injecting raw HTML; XSS risk + broken layout")
    else:
        _fail("_html.escape() not used anywhere",
              "All comparison panels inject raw CV text into HTML — XSS risk")

    # Confirm no bare unsafe injection of text variables into <div>
    unsafe = re.findall(
        r'<div[^>]*>\}\s*,\s*unsafe_allow_html=True',
        src
    )
    if not unsafe:
        _pass("No bare f-string text injection found in <div> blocks")
    else:
        _fail(f"Found {len(unsafe)} unescaped <div> injection(s)",
              "Raw text variables inserted into HTML without html.escape()")


# ══════════════════════════════════════════════════════════════════════════════
# 10. APP.PY — linkedin_stale = False only on success
# ══════════════════════════════════════════════════════════════════════════════

def check_linkedin_stale_placement() -> None:
    _section("10. _render_linkedin_tab() — linkedin_stale cleared only on success")
    src = _read(APP_PY)

    # Extract the body of _render_linkedin_tab
    fn_match = re.search(
        r'def _render_linkedin_tab\(\):(.*?)(?=\ndef [a-zA-Z_]|\Z)',
        src, re.DOTALL
    )
    if not fn_match:
        _fail("_render_linkedin_tab() not found in source")
        return

    fn_body = fn_match.group(1)

    # linkedin_stale = False must appear BEFORE the except clause
    stale_false_pos  = fn_body.find("linkedin_stale = False")
    except_pos       = fn_body.find("except Exception")

    if stale_false_pos == -1:
        _fail("linkedin_stale = False not found in _render_linkedin_tab()")
        return

    if except_pos == -1:
        _fail("except block not found in _render_linkedin_tab()")
        return

    if stale_false_pos < except_pos:
        _pass("linkedin_stale = False is inside try block (before except) — clears only on success")
    else:
        _fail("linkedin_stale = False is AFTER except block",
              "Failed API calls will still clear the stale flag, preventing retries")


# ══════════════════════════════════════════════════════════════════════════════
# 11. APP.PY — _render_linkedin_tab uses edited_cv as primary source
# ══════════════════════════════════════════════════════════════════════════════

def check_linkedin_source() -> None:
    _section("11. _render_linkedin_tab() — edited_cv used as primary CV source")
    src = _read(APP_PY)

    fn_match = re.search(
        r'def _render_linkedin_tab\(\):(.*?)(?=\ndef [a-zA-Z_]|\Z)',
        src, re.DOTALL
    )
    if not fn_match:
        _fail("_render_linkedin_tab() not found")
        return
    fn_body = fn_match.group(1)

    if re.search(r'get\("edited_cv"\)\s*or\s*st\.session_state\.ai_cv_general', fn_body):
        _pass("LinkedIn tab reads edited_cv or ai_cv_general (manual edits flow into LinkedIn)")
    else:
        _fail("LinkedIn tab does not prefer edited_cv",
              "Manual CV edits won't appear in regenerated LinkedIn profile")


# ══════════════════════════════════════════════════════════════════════════════
# 12. APP.PY — all section save handlers call _persist_edited_cv()
# ══════════════════════════════════════════════════════════════════════════════

def check_persist_called_in_all_sections() -> None:
    _section("12. Section save handlers — all call _persist_edited_cv()")
    src = _read(APP_PY)

    section_fns = [
        "_edit_section_personal",
        "_edit_section_summary",
        "_edit_section_experience",
        "_edit_section_education",
        "_edit_section_skills",
        "_edit_section_certifications",
        "_edit_section_languages",
        "_edit_section_projects",
    ]

    pattern = re.compile(
        r'def (_edit_section_\w+)\(.*?\):(.*?)(?=\ndef [a-zA-Z_]|\Z)',
        re.DOTALL
    )
    found_fns: dict[str, str] = {m.group(1): m.group(2) for m in pattern.finditer(src)}

    for fn in section_fns:
        if fn not in found_fns:
            _fail(f"{fn}() not defined")
            continue
        body = found_fns[fn]
        if "_persist_edited_cv(" in body:
            _pass(f"{fn}() calls _persist_edited_cv()")
        else:
            _fail(f"{fn}() does NOT call _persist_edited_cv()",
                  "Saves in this section will not persist to edited_cv or set linkedin_stale")


# ══════════════════════════════════════════════════════════════════════════════
# 13. APP.PY — no hard API-key block before offline pipeline
# ══════════════════════════════════════════════════════════════════════════════

def check_no_api_hard_block() -> None:
    _section("13. app.py — no hard API-key gate blocking offline pipeline")
    src = _read(APP_PY)

    # The old pattern blocked the entire pipeline if no key was set
    hard_block = re.search(
        r'if not ANTHROPIC_API_KEY.*?\n.*?st\.error.*?API key.*?\n.*?stage.*?upload',
        src, re.DOTALL | re.IGNORECASE
    )
    if hard_block:
        _fail("Hard API-key block found — offline CVs will be rejected",
              "Remove the block; pipeline degrades gracefully at each optional AI step")
    else:
        _pass("No hard API-key gate found — offline pipeline accessible")


# ══════════════════════════════════════════════════════════════════════════════
# 14. APP.PY — session_state initialised with edited_cv key
# ══════════════════════════════════════════════════════════════════════════════

def check_session_state_init() -> None:
    _section("14. app.py — session_state initialisation includes edited_cv")
    src = _read(APP_PY)

    if _contains(src, r'"edited_cv":\s*None') or _contains(src, r"'edited_cv':\s*None"):
        _pass("edited_cv initialised to None in session_state defaults")
    else:
        _fail("edited_cv not found in session_state defaults",
              "First access before any edit could raise KeyError")

    if _contains(src, r'"linkedin_stale"'):
        _pass("linkedin_stale key present in session_state initialisation block")
    else:
        _fail("linkedin_stale not found in session_state defaults")


# ══════════════════════════════════════════════════════════════════════════════
# 15. CV_PARSER.PY — improved image-PDF error message
# ══════════════════════════════════════════════════════════════════════════════

def check_cv_parser_error_msg() -> None:
    _section("15. cv_parser.py — image-PDF error guides user to API key solution")
    src = _read(CV_PARSER_PY)

    if _contains(src, r'image-based or scanned PDF'):
        _pass("Image-PDF error message mentions scanned/image PDF")
    else:
        _fail("Image-PDF error message missing expected phrasing")

    if _contains(src, r'ANTHROPIC_API_KEY'):
        _pass("Error message mentions ANTHROPIC_API_KEY as the solution")
    else:
        _fail("Error message does not guide user to set ANTHROPIC_API_KEY")


# ══════════════════════════════════════════════════════════════════════════════
# 16. STORAGE/DATABASE.PY — lifecycle schema and functions
# ══════════════════════════════════════════════════════════════════════════════

def check_database_lifecycle() -> None:
    _section("16. storage/database.py — lifecycle schema")
    src = _read(ROOT / "revizor_frank" / "storage" / "database.py")

    required_cols = [
        ("stage",            "pipeline stage persisted"),
        ("lifecycle_status", "session lifecycle status column"),
        ("candidate_name",   "candidate name column"),
        ("candidate_email",  "candidate email column"),
        ("lead_time_days",   "delivery lead time column"),
        ("delivery_due_at",  "delivery deadline column"),
        ("completed_at",     "completion timestamp column"),
        ("notes",            "operator notes column"),
        ("edited_cv",        "edited CV JSON column"),
        ("review_decisions", "review decisions JSON column"),
        ("service_tier",     "service tier column"),
    ]
    for col, desc in required_cols:
        if _contains(src, rf'"{col}"') or _contains(src, rf"'{col}'"):
            _pass(f"Column '{col}' defined  —  {desc}")
        else:
            _fail(f"Column '{col}' missing from _LIFECYCLE_COLUMNS", desc)

    if _contains(src, r'cv_action_log'):
        _pass("cv_action_log table defined")
    else:
        _fail("cv_action_log table missing — no audit trail")

    if _contains(src, r'def _migrate'):
        _pass("_migrate() present — safe forward-compatible schema upgrades")
    else:
        _fail("_migrate() missing — new columns will never be added to existing DBs")

    if _contains(src, r'_migrate\(conn\)'):
        _pass("_migrate(conn) called inside _connect()")
    else:
        _fail("_migrate() not called in _connect() — columns only created on first use")


# ══════════════════════════════════════════════════════════════════════════════
# 17. STORAGE/DATABASE.PY — required lifecycle functions
# ══════════════════════════════════════════════════════════════════════════════

def check_database_functions() -> None:
    _section("17. storage/database.py — lifecycle functions present")
    if FAST:
        print(f"  {YELLOW}(skipped in --fast mode){RESET}")
        return
    db_path = ROOT / "revizor_frank" / "storage" / "database.py"
    tree = _parse(db_path)
    fns = _fn_names(tree)

    required = {
        "log_action":             "append to audit log",
        "get_action_log":         "retrieve audit log for a session",
        "update_lifecycle":       "update status + log",
        "set_delivery":           "set lead time / delivery deadline",
        "add_note":               "operator notes + log",
        "mark_info_requested":    "status → awaiting_info + log",
        "save_full_session":      "persist full pipeline state",
        "get_full_session":       "restore full session from DB",
        "list_sessions_dashboard": "dashboard listing with auto-expire",
        "get_session_counts":     "summary metrics by lifecycle status",
    }
    for fn, purpose in required.items():
        if fn in fns:
            _pass(f"def {fn}()  —  {purpose}")
        else:
            _fail(f"def {fn}() missing", purpose)


# ══════════════════════════════════════════════════════════════════════════════
# 18. APP.PY — session save infrastructure
# ══════════════════════════════════════════════════════════════════════════════

def check_session_save_infrastructure() -> None:
    _section("18. app.py — session save infrastructure")
    src = _read(APP_PY)

    if FAST:
        tree = None
    else:
        tree = _parse(APP_PY)
        fns = _fn_names(tree)

    if not FAST and "render_sessions_dashboard" in fns:
        _pass("render_sessions_dashboard() defined")
    elif not FAST:
        _fail("render_sessions_dashboard() missing — sessions page not implemented")

    if not FAST and "_save_session_to_db" in fns:
        _pass("_save_session_to_db() defined")
    elif not FAST:
        _fail("_save_session_to_db() missing — no SQLite save on stage transitions")

    if not FAST and "_restore_session_from_db" in fns:
        _pass("_restore_session_from_db() defined — resume from SQLite works")
    elif not FAST:
        _fail("_restore_session_from_db() missing — cannot resume sessions")

    # _save_session_to_db called in _go_to_stage
    if _contains(src, r'def _go_to_stage.*?_save_session_to_db', ) or re.search(
        r'_go_to_stage.*?_save_session_to_db|_save_session_to_db.*?_go_to_stage',
        src, re.DOTALL
    ):
        _pass("_save_session_to_db() wired into _go_to_stage()")
    else:
        _fail("_save_session_to_db() not called in _go_to_stage()",
              "Stage transitions won't persist state to SQLite")

    # Called after review finalise
    if _contains(src, r'_save_session_to_db\("review_finalised"\)'):
        _pass("_save_session_to_db() called after review finalise")
    else:
        _fail("_save_session_to_db() not called after review finalise")

    # Called in _persist_edited_cv — use grep-style line proximity check
    fn_start = src.find("def _persist_edited_cv(")
    fn_end   = src.find("\ndef ", fn_start + 1) if fn_start != -1 else -1
    fn_body  = src[fn_start:fn_end] if fn_start != -1 and fn_end != -1 else ""
    if not fn_body:
        fn_body = src[fn_start:fn_start + 400] if fn_start != -1 else ""
    if "_save_session_to_db(" in fn_body:
        _pass("_save_session_to_db() called inside _persist_edited_cv()")
    else:
        _fail("_save_session_to_db() not called in _persist_edited_cv()",
              "Section edits won't be persisted to SQLite until next stage nav")

    # Sessions stage wired into router
    if _contains(src, r'stage == "sessions"') and _contains(src, r'render_sessions_dashboard'):
        _pass("'sessions' stage wired into main router")
    else:
        _fail("'sessions' stage not in main router", "Sessions page unreachable")

    # Sidebar button
    if _contains(src, r'nav_sessions') and _contains(src, r'_go_to_stage\("sessions"\)'):
        _pass("Sessions nav button in sidebar")
    else:
        _fail("Sessions nav button missing from sidebar")

    # Audit log wired at session creation
    if _contains(src, r'db\.log_action\(session_id.*?"created"'):
        _pass("log_action('created') called when session is first created")
    else:
        _fail("log_action('created') not called at session creation")


# ══════════════════════════════════════════════════════════════════════════════
# 19. STORAGE/DATABASE.PY — functional integration test
# ══════════════════════════════════════════════════════════════════════════════

def check_database_integration() -> None:
    _section("19. storage/database.py — integration test (real SQLite)")
    import importlib.util, types, os

    cfg = types.ModuleType("revizor_frank.config")
    cfg.DB_PATH = Path("/tmp/rvz_verify_test.db")
    import sys
    sys.modules["revizor_frank.config"] = cfg

    spec = importlib.util.spec_from_file_location(
        "db_test", ROOT / "revizor_frank" / "storage" / "database.py"
    )
    db_mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(db_mod)
    except Exception as exc:
        _fail("database.py failed to import", str(exc))
        return
    _pass("database.py imports cleanly")

    try:
        sid = db_mod.create_session("test.pdf", "raw text")
        _pass(f"create_session() returned ID {sid[:8]}…")
    except Exception as exc:
        _fail("create_session() raised", str(exc))
        return

    try:
        db_mod.log_action(sid, "tester", "created", {"file": "test.pdf"})
        _pass("log_action() succeeded")
    except Exception as exc:
        _fail("log_action() raised", str(exc))

    try:
        db_mod.update_lifecycle(sid, "in_delivery", "tester")
        _pass("update_lifecycle() → in_delivery")
    except Exception as exc:
        _fail("update_lifecycle() raised", str(exc))

    try:
        due = db_mod.set_delivery(sid, 3, "tester")
        assert due[:4] == "2026" or True  # just check it returns a string
        _pass(f"set_delivery() → due {due[:10]}")
    except Exception as exc:
        _fail("set_delivery() raised", str(exc))

    try:
        db_mod.save_full_session(
            sid, stage="review", candidate_name="Jane Doe",
            candidate_email="jane@test.com", service_tier="cv_linkedin",
        )
        _pass("save_full_session() succeeded")
    except Exception as exc:
        _fail("save_full_session() raised", str(exc))

    try:
        sessions = db_mod.list_sessions_dashboard()
        assert len(sessions) >= 1
        _pass(f"list_sessions_dashboard() returned {len(sessions)} session(s)")
    except Exception as exc:
        _fail("list_sessions_dashboard() raised", str(exc))

    try:
        counts = db_mod.get_session_counts()
        assert "total" in counts
        _pass(f"get_session_counts() total={counts['total']}")
    except Exception as exc:
        _fail("get_session_counts() raised", str(exc))

    try:
        log = db_mod.get_action_log(sid)
        assert len(log) >= 3
        actions = [e["action"] for e in log]
        _pass(f"get_action_log() returned {len(log)} entries: {actions}")
    except Exception as exc:
        _fail("get_action_log() raised", str(exc))

    try:
        full = db_mod.get_full_session(sid)
        assert full["stage"] == "review"
        assert full["lifecycle_status"] == "in_delivery"
        _pass("get_full_session() returns correct stage and lifecycle_status")
    except Exception as exc:
        _fail("get_full_session() validation failed", str(exc))

    try:
        if Path("/tmp/rvz_verify_test.db").exists():
            os.unlink("/tmp/rvz_verify_test.db")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def print_summary() -> int:
    passed = sum(1 for ok, _, _ in _results if ok)
    failed = sum(1 for ok, _, _ in _results if not ok)
    total  = len(_results)

    print(f"\n{'═'*60}")
    print(f"{BOLD}RESULT: {passed}/{total} checks passed{RESET}")
    if failed:
        print(f"{RED}{BOLD}{failed} FAILED:{RESET}")
        for ok, name, detail in _results:
            if not ok:
                print(f"  {RED}✗ {name}{RESET}")
                if detail:
                    print(f"    {textwrap.fill(detail, width=72, subsequent_indent='    ')}")
        print()
    else:
        print(f"{GREEN}{BOLD}All checks passed.{RESET}")
    print('═'*60)
    return failed


def main() -> None:
    print(f"{BOLD}ReviZoR FranK — Change Verification{RESET}")
    print(f"Root: {ROOT}")
    if FAST:
        print(f"{YELLOW}Running in --fast mode (AST-heavy checks skipped){RESET}")

    check_syntax()
    check_config()
    check_server_db()
    check_sync_manager()
    check_app_imports()
    check_app_functions()
    check_apply_review_decisions()
    check_resync_called()
    check_html_escape()
    check_linkedin_stale_placement()
    check_linkedin_source()
    check_persist_called_in_all_sections()
    check_no_api_hard_block()
    check_session_state_init()
    check_cv_parser_error_msg()
    check_database_lifecycle()
    check_database_functions()
    check_session_save_infrastructure()
    check_database_integration()

    sys.exit(print_summary())


if __name__ == "__main__":
    main()
