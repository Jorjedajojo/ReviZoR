"""ATS scoring engine — fully offline, rule-based.

Checks a CVData dict against a comprehensive set of ATS best-practice rules
and returns an ATSReport.

ATSReport schema:
{
    "score":             int,        # 0-100
    "grade":             str,        # A / B / C / D / F
    "issues":            [{
        "category":  str,
        "severity":  str,            # critical | warning | info
        "message":   str,
        "fix":       str,
    }],
    "keyword_matches":   [str],      # populated when JD is provided
    "missing_keywords":  [str],
    "keyword_score":     int,        # 0-100, JD match percentage
    "sections_found":    [str],
    "sections_missing":  [str],
    "action_verb_score": int,        # % of bullets starting with action verb
    "quantification_score": int,     # % of bullets containing numbers
}
"""

from __future__ import annotations

import re

from revizor_frank.config import ATS_GRADE_THRESHOLDS


# ── Word lists ────────────────────────────────────────────────────────────────

STRONG_ACTION_VERBS: set[str] = {
    "achieved", "accelerated", "administered", "advised", "advocated",
    "analyzed", "architected", "automated", "awarded", "built",
    "championed", "coached", "collaborated", "compiled", "conducted",
    "coordinated", "created", "cultivated", "delivered", "designed",
    "developed", "directed", "drove", "elevated", "engineered",
    "established", "evaluated", "exceeded", "executed", "expanded",
    "facilitated", "forecasted", "forged", "generated", "grew",
    "guided", "implemented", "improved", "increased", "initiated",
    "innovated", "integrated", "launched", "led", "leveraged",
    "managed", "mentored", "modernized", "negotiated", "optimized",
    "orchestrated", "oversaw", "partnered", "pioneered", "planned",
    "presented", "prioritized", "produced", "proposed", "reduced",
    "reformed", "reorganized", "resolved", "restructured", "revamped",
    "scaled", "secured", "shaped", "simplified", "spearheaded",
    "standardized", "streamlined", "strengthened", "supported",
    "transformed", "trained", "upgraded", "utilized", "validated",
}

WEAK_VERBS: set[str] = {
    "assisted", "helped", "worked", "tried", "handled", "did", "made",
    "got", "was", "were", "am", "is", "are", "been", "responsible",
    "duties", "tasks",
}

REQUIRED_SECTIONS: list[str] = ["summary", "experience", "education", "skills"]
RECOMMENDED_SECTIONS: list[str] = ["certifications", "languages", "projects"]

SECTION_ALIASES: dict[str, list[str]] = {
    "summary": [
        "summary", "profile", "professional summary", "career profile",
        "personal profile", "objective", "career objective", "about me",
        "about", "overview", "executive summary", "brief", "introduction",
        "خلاصة", "ملخص", "الهدف", "نبذة",
    ],
    "experience": [
        "experience", "work experience", "professional experience",
        "employment history", "career history", "work history",
        "employment", "career experience", "relevant experience",
        "الخبرة", "الخبرات", "تاريخ العمل",
    ],
    "education": [
        "education", "educational background", "academic background",
        "qualifications", "academic qualifications", "academic history",
        "التعليم", "المؤهلات",
    ],
    "skills": [
        "skills", "core skills", "key skills", "technical skills",
        "competencies", "core competencies", "areas of expertise",
        "expertise", "skill set", "technical competencies",
        "المهارات", "الكفاءات",
    ],
}

# Patterns that indicate ATS-hostile formatting artifacts
_TABLE_ARTIFACT_RE = re.compile(r"\t{3,}|[ ]{10,}")
_GRAPHICS_RE = re.compile(r"\[(?:image|photo|figure|logo)\]", re.I)
_HEADER_FOOTER_RE = re.compile(r"page \d+ of \d+", re.I)
_ALL_CAPS_RE = re.compile(r"\b[A-Z]{5,}\b")
_NUMBER_RE = re.compile(r"\d+[%$]?|\$\d+|\d+[kKmMbB]")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _first_word(text: str) -> str:
    words = text.strip().split()
    return words[0].lower().rstrip(".,;:") if words else ""


def _get_all_bullets(cv: dict) -> list[str]:
    bullets = []
    for exp in cv.get("experience", []):
        bullets.extend(exp.get("bullets", []))
    for proj in cv.get("projects", []):
        desc = proj.get("description", "")
        if desc:
            bullets.append(desc)
    return bullets


def _extract_keywords_from_jd(jd_text: str) -> set[str]:
    """Extract meaningful keywords from a job description (offline, rule-based)."""
    # Remove stop words
    stop_words = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "shall", "can",
        "not", "no", "nor", "so", "yet", "both", "either", "neither",
        "we", "our", "you", "your", "they", "their", "this", "that",
        "these", "those", "such", "more", "most", "also", "as", "if",
        "than", "then", "about", "into", "through", "during", "including",
    }
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9+#.\-]{2,}\b", jd_text)
    keywords = set()
    for w in words:
        w_lower = w.lower()
        if w_lower not in stop_words and len(w_lower) > 2:
            keywords.add(w_lower)
    return keywords


def _cv_text_blob(cv: dict) -> str:
    """Flatten all CV text into one string for keyword matching."""
    parts = [
        cv.get("summary", ""),
        " ".join(b for exp in cv.get("experience", []) for b in exp.get("bullets", [])),
        " ".join(exp.get("title", "") for exp in cv.get("experience", [])),
        " ".join(
            i for cat in cv.get("skills", {}).get("categories", [])
            for i in cat.get("items", [])
        ),
        " ".join(c.get("name", "") for c in cv.get("certifications", [])),
        cv.get("raw_text", ""),
    ]
    return " ".join(parts).lower()


# ── Issue factory ─────────────────────────────────────────────────────────────

def _issue(category: str, severity: str, message: str, fix: str) -> dict:
    return {"category": category, "severity": severity, "message": message, "fix": fix}


# ── ATS checks ────────────────────────────────────────────────────────────────

def _check_sections(cv: dict) -> tuple[list[dict], list[str], list[str]]:
    issues = []
    found = []
    missing = []
    raw = cv.get("raw_text", "").lower()

    for section, aliases in SECTION_ALIASES.items():
        if section == "skills":
            has_data = bool(cv.get("skills", {}).get("categories") and
                            any(c.get("items") for c in cv["skills"]["categories"]))
        else:
            has_data = bool(cv.get(section))
        found_in_raw = any(alias in raw for alias in aliases)
        if has_data or found_in_raw:
            found.append(section)
        else:
            missing.append(section)
            issues.append(_issue(
                "Sections", "critical",
                f'Required section "{section.title()}" is missing or empty.',
                f'Add a clearly labeled "{section.title()}" section with relevant content.',
            ))

    for section in RECOMMENDED_SECTIONS:
        if cv.get(section):
            found.append(section)

    return issues, found, missing


def _check_contact(cv: dict) -> list[dict]:
    issues = []
    if not cv.get("email"):
        issues.append(_issue("Contact", "critical", "No email address found.",
                              "Add your professional email address near the top of your CV."))
    if not cv.get("phone"):
        issues.append(_issue("Contact", "warning", "No phone number found.",
                              "Add your phone number in a standard international format."))
    if not cv.get("name"):
        issues.append(_issue("Contact", "warning", "Your name could not be detected.",
                              "Ensure your full name appears prominently at the top of your CV."))
    if not cv.get("linkedin"):
        issues.append(_issue("Contact", "info", "No LinkedIn URL detected.",
                              "Add your LinkedIn profile URL (linkedin.com/in/yourname)."))
    return issues


def _check_length(cv: dict) -> list[dict]:
    issues = []
    raw = cv.get("raw_text", "")
    word_count = len(raw.split())
    exp_count = len(cv.get("experience", []))
    # Rough page estimate: ~500 words per page
    estimated_pages = max(1, round(word_count / 500))
    if exp_count <= 5 and estimated_pages > 2:
        issues.append(_issue(
            "Length", "warning",
            f"CV appears to be ~{estimated_pages} pages (est. {word_count} words). Most ATS prefer 1-2 pages.",
            "Trim older roles to 1-2 bullet points each. Remove irrelevant early-career positions.",
        ))
    if word_count < 150:
        issues.append(_issue(
            "Length", "warning",
            "CV appears very short (under ~150 words). ATS may flag sparse CVs.",
            "Expand your experience bullets with quantified achievements and skills.",
        ))
    return issues


def _check_action_verbs(cv: dict) -> tuple[list[dict], int]:
    bullets = _get_all_bullets(cv)
    if not bullets:
        return [], 0
    strong_count = 0
    weak_bullets = []
    for b in bullets:
        fw = _first_word(b)
        if fw in STRONG_ACTION_VERBS:
            strong_count += 1
        elif fw in WEAK_VERBS:
            weak_bullets.append(b[:60])

    score = int((strong_count / len(bullets)) * 100) if bullets else 0
    issues = []
    if weak_bullets:
        sample = "; ".join(f'"{w}"' for w in weak_bullets[:3])
        issues.append(_issue(
            "Language", "warning",
            f"Weak verbs detected in {len(weak_bullets)} bullet(s). Examples: {sample}",
            "Replace weak/passive verbs with strong action verbs (e.g. 'Responsible for X' → 'Managed X').",
        ))
    if score < 50:
        issues.append(_issue(
            "Language", "warning",
            f"Only {score}% of experience bullets begin with a strong action verb.",
            "Start every bullet point with a past-tense action verb (e.g. Led, Built, Reduced).",
        ))
    return issues, score


def _check_quantification(cv: dict) -> tuple[list[dict], int]:
    bullets = _get_all_bullets(cv)
    if not bullets:
        return [], 0
    quantified = sum(1 for b in bullets if _NUMBER_RE.search(b))
    score = int((quantified / len(bullets)) * 100) if bullets else 0
    issues = []
    if score < 30:
        issues.append(_issue(
            "Impact", "warning",
            f"Only {score}% of bullets contain measurable results (numbers, %, $).",
            "Add metrics: 'Reduced load time by 40%', 'Managed $2M budget', 'Led team of 8'.",
        ))
    return issues, score


def _check_formatting_artifacts(cv: dict) -> list[dict]:
    issues = []
    raw = cv.get("raw_text", "")
    if _TABLE_ARTIFACT_RE.search(raw):
        issues.append(_issue(
            "Formatting", "critical",
            "Table or multi-column formatting detected. Many ATS cannot parse columns.",
            "Convert to single-column layout. Remove all tables.",
        ))
    if _GRAPHICS_RE.search(raw):
        issues.append(_issue(
            "Formatting", "critical",
            "Images or graphics detected. ATS systems ignore image content.",
            "Remove all images, photos, logos, and icons from your CV.",
        ))
    if _HEADER_FOOTER_RE.search(raw):
        issues.append(_issue(
            "Formatting", "warning",
            "Page headers/footers detected. Critical info in headers may be missed by ATS.",
            "Move all important information (name, contact) into the main body.",
        ))
    all_caps_matches = _ALL_CAPS_RE.findall(raw)
    if len(all_caps_matches) > 5:
        issues.append(_issue(
            "Formatting", "info",
            "Excessive ALL-CAPS text detected. This can hurt readability and some ATS parsers.",
            "Use title case for headings instead of ALL CAPS.",
        ))
    return issues


def _check_dates(cv: dict) -> list[dict]:
    issues = []
    inconsistent = False
    date_formats_seen = set()
    date_re_mmyyyy = re.compile(r"\d{1,2}/\d{4}")
    date_re_monthyyyy = re.compile(
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{4}", re.I
    )
    for exp in cv.get("experience", []):
        for d in (exp.get("start_date", ""), exp.get("end_date", "")):
            if date_re_mmyyyy.match(d or ""):
                date_formats_seen.add("MM/YYYY")
            elif date_re_monthyyyy.match(d or ""):
                date_formats_seen.add("Month YYYY")
    if len(date_formats_seen) > 1:
        inconsistent = True
        issues.append(_issue(
            "Formatting", "warning",
            "Inconsistent date formats detected (e.g. mixing '01/2020' and 'January 2020').",
            "Use a single consistent date format throughout. Recommended: 'Month YYYY' (e.g. Jan 2020).",
        ))
    return issues


def _check_summary(cv: dict) -> list[dict]:
    issues = []
    summary = cv.get("summary", "")
    if not summary:
        return issues
    words = summary.split()
    if len(words) < 30:
        issues.append(_issue(
            "Content", "info",
            "Professional summary is very short (under 30 words).",
            "Expand your summary to 50-100 words covering your role, years of experience, and top value propositions.",
        ))
    if len(words) > 120:
        issues.append(_issue(
            "Content", "info",
            "Professional summary is too long (over 120 words). Recruiters spend ~6 seconds on first scan.",
            "Trim your summary to 50-100 words. Save detail for your experience bullets.",
        ))
    first_person_re = re.compile(r"\b(I |I'm |I've |my |me )\b", re.I)
    if first_person_re.search(summary):
        issues.append(_issue(
            "Language", "info",
            "First-person pronouns (I, my, me) detected in summary.",
            "Write in third-person implied style. Instead of 'I led...' write 'Led...'",
        ))
    return issues


# ── Keyword matching ──────────────────────────────────────────────────────────

def _check_keywords(cv: dict, jd_text: str) -> tuple[list[dict], list[str], list[str], int]:
    if not jd_text:
        return [], [], [], 0
    jd_keywords = _extract_keywords_from_jd(jd_text)
    cv_blob = _cv_text_blob(cv)
    matched = sorted(kw for kw in jd_keywords if re.search(r"\b" + re.escape(kw) + r"\b", cv_blob))
    missing = sorted(kw for kw in jd_keywords if kw not in matched)
    score = int((len(matched) / len(jd_keywords)) * 100) if jd_keywords else 0
    issues = []
    if score < 50:
        sample = ", ".join(missing[:10])
        issues.append(_issue(
            "Keywords", "critical",
            f"Only {score}% keyword match with the job description. Missing: {sample}",
            "Incorporate the missing keywords naturally into your summary, bullets, and skills section.",
        ))
    elif score < 70:
        sample = ", ".join(missing[:5])
        issues.append(_issue(
            "Keywords", "warning",
            f"{score}% keyword match. Could be stronger. Missing: {sample}",
            "Add missing keywords where they genuinely reflect your experience.",
        ))
    return issues, matched, missing, score


# ── Grade calculator ──────────────────────────────────────────────────────────

def _calculate_grade(score: int) -> str:
    for grade, threshold in ATS_GRADE_THRESHOLDS.items():
        if score >= threshold:
            return grade
    return "F"


# ── Score calculator ──────────────────────────────────────────────────────────

def _calculate_score(issues: list[dict], action_score: int, quant_score: int,
                     kw_score: int, has_jd: bool) -> int:
    score = 100
    for issue in issues:
        if issue["severity"] == "critical":
            score -= 15
        elif issue["severity"] == "warning":
            score -= 7
        elif issue["severity"] == "info":
            score -= 2

    # Factor in quality scores
    score += (action_score - 50) * 0.1  # ±5 points
    score += (quant_score - 30) * 0.1   # ±3 points

    if has_jd:
        score += (kw_score - 60) * 0.15  # ±6 points for JD match

    return max(0, min(100, round(score)))


# ── Public API ────────────────────────────────────────────────────────────────

def analyze(cv_data: dict, job_description: str = "") -> dict:
    """Run full ATS analysis and return an ATSReport dict."""
    all_issues: list[dict] = []

    section_issues, sections_found, sections_missing = _check_sections(cv_data)
    all_issues.extend(section_issues)

    all_issues.extend(_check_contact(cv_data))
    all_issues.extend(_check_length(cv_data))
    all_issues.extend(_check_formatting_artifacts(cv_data))
    all_issues.extend(_check_dates(cv_data))
    all_issues.extend(_check_summary(cv_data))

    verb_issues, action_verb_score = _check_action_verbs(cv_data)
    all_issues.extend(verb_issues)

    quant_issues, quant_score = _check_quantification(cv_data)
    all_issues.extend(quant_issues)

    kw_issues, kw_matches, kw_missing, kw_score = _check_keywords(cv_data, job_description)
    all_issues.extend(kw_issues)

    score = _calculate_score(all_issues, action_verb_score, quant_score,
                             kw_score, bool(job_description))
    grade = _calculate_grade(score)

    return {
        "score":               score,
        "grade":               grade,
        "issues":              all_issues,
        "keyword_matches":     kw_matches,
        "missing_keywords":    kw_missing,
        "keyword_score":       kw_score,
        "sections_found":      sections_found,
        "sections_missing":    sections_missing,
        "action_verb_score":   action_verb_score,
        "quantification_score": quant_score,
    }
