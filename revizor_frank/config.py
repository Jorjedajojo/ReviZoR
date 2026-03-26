"""Central configuration for ReviZoR FranK."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file)
_root = Path(__file__).parent.parent
load_dotenv(_root / ".env")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STORAGE_DIR = BASE_DIR / "storage" / "data"
EXPORTS_DIR = BASE_DIR / "exports"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ── App identity ───────────────────────────────────────────────────────────────
APP_NAME = "ReviZoR FranK"
APP_VERSION = "1.0.0"
APP_TAGLINE = "AI-Powered CV Optimization Engine"

# ── Claude API ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
# Use the most capable model for best CV output quality
CLAUDE_MODEL = "claude-opus-4-6"
MAX_TOKENS = 8192
# Fallback to Sonnet for faster/cheaper secondary calls
CLAUDE_FAST_MODEL = "claude-sonnet-4-6"

# ── Mode detection ────────────────────────────────────────────────────────────
# Online = API key present AND internet reachable (checked at runtime)
ONLINE_MODE: bool = bool(ANTHROPIC_API_KEY)

# ── Sync ──────────────────────────────────────────────────────────────────────
SYNC_CHECK_INTERVAL = 30      # seconds between connectivity checks
CONNECTIVITY_TEST_URL = "https://api.anthropic.com"
CONNECTIVITY_TIMEOUT = 5       # seconds

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = STORAGE_DIR / "revizor.db"

# ── Templates ─────────────────────────────────────────────────────────────────
TEMPLATES: dict[str, dict] = {
    "classic":    {"name": "Classic Professional",     "ats_safe": True,  "best_for": "General, Finance, Law"},
    "modern":     {"name": "Modern Minimalist",        "ats_safe": True,  "best_for": "Marketing, Design, Startups"},
    "executive":  {"name": "Executive",                "ats_safe": True,  "best_for": "C-Suite, Senior Management"},
    "creative":   {"name": "Creative (ATS-Safe)",      "ats_safe": True,  "best_for": "Media, Advertising, UX"},
    "technical":  {"name": "Technical / Engineering",  "ats_safe": True,  "best_for": "Software, Engineering, IT"},
    "academic":   {"name": "Academic",                 "ats_safe": True,  "best_for": "Research, Academia, Science"},
    "healthcare": {"name": "Healthcare",               "ats_safe": True,  "best_for": "Medical, Nursing, Allied Health"},
    "graduate":   {"name": "Graduate / Entry-Level",   "ats_safe": True,  "best_for": "Students, Career Changers"},
}

DEFAULT_TEMPLATE = "modern"

# ── Supported upload formats ───────────────────────────────────────────────────
UPLOAD_FORMATS = ["pdf", "docx", "txt"]

# ── Export formats ────────────────────────────────────────────────────────────
EXPORT_FORMATS = ["docx", "odt", "pdf", "png", "txt", "linkedin"]

# ── ATS scoring thresholds ────────────────────────────────────────────────────
ATS_GRADE_THRESHOLDS = {
    "A": 90,
    "B": 75,
    "C": 60,
    "D": 45,
}

# ── i18n ──────────────────────────────────────────────────────────────────────
DEFAULT_LANGUAGE = "en"
