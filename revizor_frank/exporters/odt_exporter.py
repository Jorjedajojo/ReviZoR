"""ODT exporter — OpenDocument Text format (LibreOffice compatible, replaces Pages)."""

from __future__ import annotations

from odf.opendocument import OpenDocumentText
from odf.style import (
    ParagraphProperties,
    Style,
    TextProperties,
)
from odf.text import H, List, ListItem, P, Span


def _make_style(doc, name: str, family: str = "paragraph", **props) -> Style:
    style = Style(name=name, family=family)
    if family == "paragraph":
        pp_attrs = {k: v for k, v in props.items() if k.startswith("margin") or k in
                    ("textalign", "breakbefore", "lineheight")}
        tp_attrs = {k: v for k, v in props.items() if k not in pp_attrs}
        if pp_attrs:
            style.addElement(ParagraphProperties(**pp_attrs))
        if tp_attrs:
            style.addElement(TextProperties(**tp_attrs))
    doc.styles.addElement(style)
    return style


def export_odt(cv_data: dict, template_name: str, output_path: str,
               template_color: str = "") -> str:
    """Build an .odt CV file. Returns output_path."""
    from revizor_frank.templates import get_template
    tmpl = get_template(template_name, primary_color=template_color)
    primary = f"#{tmpl.style.docx_primary_hex}"
    accent = f"#{tmpl.style.docx_accent_hex}"

    doc = OpenDocumentText()

    # ── Styles ────────────────────────────────────────────────────────────────
    _make_style(doc, "NameStyle",
                fontweight="bold", fontsize="22pt", color=primary,
                marginbottom="0.15cm")

    _make_style(doc, "ContactStyle",
                fontsize="9pt", color="#666666", marginbottom="0.3cm")

    _make_style(doc, "SectionHeading",
                fontweight="bold", fontsize="11pt", color=primary,
                margintop="0.4cm", marginbottom="0.1cm",
                borderbottom=f"0.5pt solid {accent}")

    _make_style(doc, "JobTitle",
                fontweight="bold", fontsize="10pt", color=primary,
                marginbottom="0cm")

    _make_style(doc, "SubText",
                fontsize="9pt", color="#555555", marginbottom="0.1cm")

    _make_style(doc, "BodyText",
                fontsize="9.5pt", color="#1a1a1a",
                margintop="0cm", marginbottom="0.1cm")

    _make_style(doc, "BulletText",
                fontsize="9.5pt", color="#1a1a1a",
                marginleft="0.5cm", marginbottom="0.05cm")

    # ── Helper ────────────────────────────────────────────────────────────────
    def add_para(text: str, style_name: str):
        p = P(stylename=style_name)
        p.addText(text)
        doc.text.addElement(p)

    def add_section(title: str):
        p = P(stylename="SectionHeading")
        p.addText(title.upper())
        doc.text.addElement(p)

    def add_bullet_item(text: str):
        p = P(stylename="BulletText")
        p.addText(f"• {text}")
        doc.text.addElement(p)

    # ── Name ─────────────────────────────────────────────────────────────────
    add_para(cv_data.get("name", ""), "NameStyle")

    # ── Contact ───────────────────────────────────────────────────────────────
    contact_parts = [
        cv_data.get(f, "")
        for f in ("email", "phone", "location", "linkedin", "website")
        if cv_data.get(f)
    ]
    if cv_data.get("dob"):
        contact_parts.append(f"DOB: {cv_data['dob']}")
    if contact_parts:
        add_para("  |  ".join(contact_parts), "ContactStyle")

    # ── Summary ───────────────────────────────────────────────────────────────
    if cv_data.get("summary"):
        add_section("Professional Summary")
        add_para(cv_data["summary"], "BodyText")

    # ── Experience ────────────────────────────────────────────────────────────
    if cv_data.get("experience"):
        add_section("Professional Experience")
        for exp in cv_data["experience"]:
            add_para(exp.get("title", ""), "JobTitle")
            co = exp.get("company", "")
            if exp.get("location"):
                co += f"  —  {exp['location']}"
            date_str = f"{exp.get('start_date', '')} – {exp.get('end_date', 'Present')}"
            add_para(f"{co}  |  {date_str}", "SubText")
            for b in exp.get("bullets", []):
                add_bullet_item(b)

    # ── Education ─────────────────────────────────────────────────────────────
    if cv_data.get("education"):
        add_section("Education")
        for edu in cv_data["education"]:
            add_para(edu.get("degree", ""), "JobTitle")
            sub = edu.get("institution", "")
            if edu.get("year"):
                sub += f"  |  {edu['year']}"
            add_para(sub, "SubText")
            if edu.get("honors"):
                add_para(edu["honors"], "SubText")

    # ── Skills ────────────────────────────────────────────────────────────────
    if cv_data.get("skills", {}).get("categories"):
        add_section("Skills")
        for cat in cv_data["skills"]["categories"]:
            items = ", ".join(cat.get("items", []))
            if items:
                add_para(f"{cat['name']}: {items}", "BodyText")

    # ── Certifications ────────────────────────────────────────────────────────
    if cv_data.get("certifications"):
        add_section("Certifications")
        for cert in cv_data["certifications"]:
            line = cert.get("name", "")
            if cert.get("issuer"):
                line += f"  —  {cert['issuer']}"
            if cert.get("date"):
                line += f"  ({cert['date']})"
            add_bullet_item(line)

    # ── Projects ──────────────────────────────────────────────────────────────
    if cv_data.get("projects"):
        add_section("Projects")
        for proj in cv_data["projects"]:
            add_para(proj.get("name", ""), "JobTitle")
            if proj.get("description"):
                add_para(proj["description"], "BodyText")
            if proj.get("technologies"):
                add_para(f"Technologies: {', '.join(proj['technologies'])}", "SubText")

    # ── Languages ─────────────────────────────────────────────────────────────
    if cv_data.get("languages"):
        add_section("Languages")
        add_para(", ".join(cv_data["languages"]), "BodyText")

    doc.save(output_path)
    return output_path
