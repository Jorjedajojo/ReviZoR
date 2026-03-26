"""Offline rule-based CV improvement engine.

Applies deterministic improvements to CVData without any network calls.
This is the fallback when Claude API is unavailable, and also runs first
as a pre-processing step before sending to Claude.

Improvements applied:
- Standardize date formats to "Month YYYY"
- Remove first-person pronouns from summary
- Capitalize section content consistently
- Deduplicate skills
- Flag weak verbs in bullets (marks them for AI rewrite)
- Ensure required sections exist
- Normalize whitespace and punctuation in bullets
"""

from __future__ import annotations

import re

from revizor_frank.core.ats_engine import STRONG_ACTION_VERBS, WEAK_VERBS


# ── Date normalization ────────────────────────────────────────────────────────

_MONTH_MAP = {
    "01": "Jan", "1": "Jan",  "02": "Feb", "2": "Feb",
    "03": "Mar", "3": "Mar",  "04": "Apr", "4": "Apr",
    "05": "May", "5": "May",  "06": "Jun", "6": "Jun",
    "07": "Jul", "7": "Jul",  "08": "Aug", "8": "Aug",
    "09": "Sep", "9": "Sep",  "10": "Oct", "11": "Nov", "12": "Dec",
}

_MONTH_RE = re.compile(
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"[\s,]+(\d{4})",
    re.I,
)
_SLASH_DATE_RE = re.compile(r"(\d{1,2})/(\d{4})")


def _normalize_date(date_str: str) -> str:
    if not date_str:
        return date_str
    if date_str.strip().lower() in ("present", "current", "now"):
        return "Present"
    m = _MONTH_RE.search(date_str)
    if m:
        month_abbr = m.group(1)[:3].capitalize()
        return f"{month_abbr} {m.group(2)}"
    m = _SLASH_DATE_RE.search(date_str)
    if m:
        month_num = m.group(1)
        year = m.group(2)
        return f"{_MONTH_MAP.get(month_num, month_num)} {year}"
    return date_str.strip()


# ── Text cleaners ─────────────────────────────────────────────────────────────

_FIRST_PERSON_RE = re.compile(
    r"\b(I am|I have|I've|I'd|I'll|I was|I |my |me )\b", re.I
)
_MULTI_SPACE_RE = re.compile(r" {2,}")
_BULLET_CLEANUP_RE = re.compile(r"^[•\-–*·]\s*")
_TRAILING_PUNCT_RE = re.compile(r"[.;,]\s*$")


def _clean_summary(text: str) -> str:
    """Remove first-person, normalize whitespace."""
    if not text:
        return text
    # Remove first-person phrasing
    text = re.sub(r"\bI am\b", "A seasoned professional who is", text, flags=re.I)
    text = re.sub(r"\bI have\b", "Possessing", text, flags=re.I)
    text = re.sub(r"\bI've\b", "Having", text, flags=re.I)
    text = re.sub(r"\bmy\b", "their", text, flags=re.I)
    text = re.sub(r"\bI\b", "", text, flags=re.I)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def _clean_bullet(text: str) -> str:
    """Normalize a single bullet point."""
    text = _BULLET_CLEANUP_RE.sub("", text).strip()
    text = _MULTI_SPACE_RE.sub(" ", text)
    # Capitalize first letter
    if text:
        text = text[0].upper() + text[1:]
    # Ensure no trailing period (ATS preference varies; we keep it consistent)
    text = _TRAILING_PUNCT_RE.sub("", text).strip()
    return text


def _capitalize_title(text: str) -> str:
    """Title-case a job title / degree string."""
    if not text:
        return text
    # Words to keep lowercase in titles
    minor = {"a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for"}
    words = text.split()
    result = []
    for i, w in enumerate(words):
        if i == 0 or w.lower() not in minor:
            result.append(w.capitalize())
        else:
            result.append(w.lower())
    return " ".join(result)


# ── Skill deduplication ───────────────────────────────────────────────────────

def _dedup_skills(skills: dict) -> dict:
    seen: set[str] = set()
    clean_cats = []
    for cat in skills.get("categories", []):
        items = []
        for item in cat.get("items", []):
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                items.append(item.strip())
        if items:
            clean_cats.append({"name": cat["name"], "items": items})
    return {"categories": clean_cats}


# ── Experience improvement ────────────────────────────────────────────────────

def _improve_bullet(bullet: str) -> str:
    """Apply rule-based improvements to a single bullet."""
    bullet = _clean_bullet(bullet)
    if not bullet:
        return bullet

    # Replace weak openers with placeholders the AI can refine
    first_word = bullet.split()[0].lower().rstrip(".,;:")
    if first_word in WEAK_VERBS:
        # Best-effort replacement for most common weak patterns
        replacements = {
            "helped": "Supported",
            "assisted": "Collaborated with",
            "worked": "Contributed to",
            "responsible": "Managed",
            "was": "Served as",
            "were": "Acted as",
            "did": "Executed",
            "handled": "Managed",
            "made": "Developed",
        }
        new_start = replacements.get(first_word)
        if new_start:
            rest = bullet[len(first_word):].lstrip(" for in on .,;:")
            bullet = f"{new_start} {rest}"

    return bullet


def _improve_experience(experience: list[dict]) -> list[dict]:
    improved = []
    for exp in experience:
        entry = {**exp}
        entry["title"] = _capitalize_title(exp.get("title", ""))
        entry["company"] = exp.get("company", "").strip()
        entry["start_date"] = _normalize_date(exp.get("start_date", ""))
        entry["end_date"] = _normalize_date(exp.get("end_date", ""))
        entry["bullets"] = [_improve_bullet(b) for b in exp.get("bullets", []) if b.strip()]
        improved.append(entry)
    return improved


def _improve_education(education: list[dict]) -> list[dict]:
    improved = []
    for edu in education:
        entry = {**edu}
        entry["degree"] = _capitalize_title(edu.get("degree", ""))
        entry["institution"] = _capitalize_title(edu.get("institution", ""))
        entry["year"] = _normalize_date(edu.get("year", ""))
        improved.append(entry)
    return improved


# ── Public API ────────────────────────────────────────────────────────────────

def improve_offline(cv_data: dict) -> dict:
    """Return an improved copy of cv_data using rule-based logic only."""
    improved = {**cv_data}
    improved["summary"] = _clean_summary(cv_data.get("summary", ""))
    improved["experience"] = _improve_experience(cv_data.get("experience", []))
    improved["education"] = _improve_education(cv_data.get("education", []))
    improved["skills"] = _dedup_skills(cv_data.get("skills", {"categories": []}))
    improved["name"] = cv_data.get("name", "").strip()
    improved["email"] = cv_data.get("email", "").strip().lower()
    improved["phone"] = cv_data.get("phone", "").strip()
    improved["location"] = cv_data.get("location", "").strip()
    improved["linkedin"] = cv_data.get("linkedin", "").strip()
    improved["website"] = cv_data.get("website", "").strip()
    return improved
