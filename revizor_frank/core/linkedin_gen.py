"""Offline LinkedIn profile generator.

Produces a structured LinkedInProfile from CVData using template-based rules.
Quality is lower than the Claude-generated version but works fully offline.
"""

from __future__ import annotations

import re


def _first_sentence(text: str) -> str:
    if not text:
        return ""
    m = re.match(r"[^.!?]+[.!?]", text)
    return m.group(0).strip() if m else text.split("\n")[0].strip()


def _top_skills(skills: dict, limit: int = 10) -> list[str]:
    items = []
    for cat in skills.get("categories", []):
        items.extend(cat.get("items", []))
    return items[:limit]


def _build_headline(cv: dict) -> str:
    parts = []
    # Latest title
    exp = cv.get("experience", [])
    if exp:
        title = exp[0].get("title", "")
        company = exp[0].get("company", "")
        if title:
            parts.append(title)
        if company:
            parts.append(f"@ {company}")

    # Top 2 skills
    skills = _top_skills(cv.get("skills", {}), 2)
    parts.extend(skills[:2])

    headline = " | ".join(parts)
    return headline[:220]


def _build_about(cv: dict) -> str:
    summary = cv.get("summary", "")
    exp = cv.get("experience", [])
    skills = _top_skills(cv.get("skills", {}), 5)
    name = cv.get("name", "").split()[0] if cv.get("name") else "I"

    lines = []
    if summary:
        lines.append(summary)
    elif exp:
        latest = exp[0]
        lines.append(
            f"Experienced {latest.get('title', 'professional')} with a track record of "
            f"delivering results at {latest.get('company', 'leading organizations')}."
        )

    if skills:
        lines.append(f"\nCore expertise: {', '.join(skills)}.")

    if exp:
        years = len(exp)
        lines.append(f"\nWith {years}+ roles across my career, {name} bring a broad perspective to every challenge.")

    lines.append("\nFeel free to connect — always open to meaningful conversations.")
    return "\n".join(lines)[:2600]


def _build_experience(cv: dict) -> list[dict]:
    result = []
    for exp in cv.get("experience", []):
        start = exp.get("start_date", "")
        end = exp.get("end_date", "Present")
        dates = f"{start} – {end}" if start else end
        bullets = exp.get("bullets", [])
        description = "\n".join(f"• {b}" for b in bullets[:6])
        result.append({
            "title": exp.get("title", ""),
            "company": exp.get("company", ""),
            "dates": dates,
            "description": description,
        })
    return result


def _build_skills(cv: dict) -> list[str]:
    return _top_skills(cv.get("skills", {}), 50)


def _build_education(cv: dict) -> list[dict]:
    result = []
    for edu in cv.get("education", []):
        result.append({
            "degree": edu.get("degree", ""),
            "school": edu.get("institution", ""),
            "dates": edu.get("year", ""),
        })
    return result


def _build_tagline(cv: dict) -> str:
    exp = cv.get("experience", [])
    if exp:
        title = exp[0].get("title", "professional")
        return f"{title} passionate about driving meaningful impact — let's connect."
    return "Open to new opportunities and meaningful conversations — feel free to connect."


def generate_offline(cv_data: dict) -> dict:
    """Generate a LinkedIn profile dict from CVData without internet."""
    return {
        "headline":       _build_headline(cv_data),
        "about":          _build_about(cv_data),
        "experience":     _build_experience(cv_data),
        "skills":         _build_skills(cv_data),
        "education":      _build_education(cv_data),
        "certifications": cv_data.get("certifications", []),
        "summary_tagline": _build_tagline(cv_data),
    }
