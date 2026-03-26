"""Plain text exporter — 100% ATS-safe, encoding-safe output."""

from __future__ import annotations


def _divider(char: str = "=", width: int = 60) -> str:
    return char * width


def export_txt(cv_data: dict, output_path: str) -> str:
    """Build a plain .txt CV file. Returns output_path."""
    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines.append(cv_data.get("name", "").upper())
    lines.append(_divider())
    contact_parts = []
    for field in ("email", "phone", "location", "linkedin", "website"):
        val = cv_data.get(field, "")
        if val:
            contact_parts.append(val)
    if contact_parts:
        lines.append(" | ".join(contact_parts))
    lines.append("")

    # ── Summary ───────────────────────────────────────────────────────────────
    if cv_data.get("summary"):
        lines.append("PROFESSIONAL SUMMARY")
        lines.append(_divider("-"))
        lines.append(cv_data["summary"])
        lines.append("")

    # ── Experience ────────────────────────────────────────────────────────────
    if cv_data.get("experience"):
        lines.append("PROFESSIONAL EXPERIENCE")
        lines.append(_divider("-"))
        for exp in cv_data["experience"]:
            title = exp.get("title", "")
            company = exp.get("company", "")
            location = exp.get("location", "")
            start = exp.get("start_date", "")
            end = exp.get("end_date", "Present")
            header = title
            if company:
                header += f"  |  {company}"
            if location:
                header += f",  {location}"
            if start or end:
                header += f"  |  {start} - {end}"
            lines.append(header)
            for b in exp.get("bullets", []):
                lines.append(f"  * {b}")
            lines.append("")

    # ── Education ─────────────────────────────────────────────────────────────
    if cv_data.get("education"):
        lines.append("EDUCATION")
        lines.append(_divider("-"))
        for edu in cv_data["education"]:
            line = edu.get("degree", "")
            if edu.get("institution"):
                line += f"  |  {edu['institution']}"
            if edu.get("year"):
                line += f"  |  {edu['year']}"
            lines.append(line)
            if edu.get("honors"):
                lines.append(f"  {edu['honors']}")
            if edu.get("gpa"):
                lines.append(f"  {edu['gpa']}")
            lines.append("")

    # ── Skills ────────────────────────────────────────────────────────────────
    if cv_data.get("skills", {}).get("categories"):
        lines.append("SKILLS")
        lines.append(_divider("-"))
        for cat in cv_data["skills"]["categories"]:
            items = ", ".join(cat.get("items", []))
            if items:
                lines.append(f"{cat['name']}: {items}")
        lines.append("")

    # ── Certifications ────────────────────────────────────────────────────────
    if cv_data.get("certifications"):
        lines.append("CERTIFICATIONS")
        lines.append(_divider("-"))
        for cert in cv_data["certifications"]:
            line = cert.get("name", "")
            if cert.get("issuer"):
                line += f"  —  {cert['issuer']}"
            if cert.get("date"):
                line += f"  ({cert['date']})"
            lines.append(f"  * {line}")
        lines.append("")

    # ── Projects ──────────────────────────────────────────────────────────────
    if cv_data.get("projects"):
        lines.append("PROJECTS")
        lines.append(_divider("-"))
        for proj in cv_data["projects"]:
            lines.append(proj.get("name", ""))
            if proj.get("description"):
                lines.append(f"  {proj['description']}")
            if proj.get("technologies"):
                lines.append(f"  Technologies: {', '.join(proj['technologies'])}")
            lines.append("")

    # ── Languages ─────────────────────────────────────────────────────────────
    if cv_data.get("languages"):
        lines.append("LANGUAGES")
        lines.append(_divider("-"))
        lines.append(", ".join(cv_data["languages"]))
        lines.append("")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path
