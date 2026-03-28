"""DOCX exporter — builds an ATS-safe Word document using python-docx."""

from __future__ import annotations

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Inches
from lxml import etree


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _set_run_color(run, hex_color: str):
    r, g, b = _hex_to_rgb(hex_color)
    run.font.color.rgb = RGBColor(r, g, b)


def _add_horizontal_rule(para):
    """Add a bottom border to a paragraph (simulates a horizontal rule)."""
    pPr = para._p.get_or_add_pPr()
    pBdr = etree.SubElement(pPr, qn("w:pBdr"))
    bottom = etree.SubElement(pBdr, qn("w:bottom"))
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "auto")


def export_docx(cv_data: dict, template_name: str, output_path: str,
                template_color: str = "") -> str:
    """Build a .docx CV file. Returns output_path."""
    from revizor_frank.templates import get_template
    tmpl = get_template(template_name, primary_color=template_color)
    primary_hex = tmpl.style.docx_primary_hex
    accent_hex = tmpl.style.docx_accent_hex

    doc = Document()

    # ── Page margins ──────────────────────────────────────────────────────────
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    # ── Name ──────────────────────────────────────────────────────────────────
    name_para = doc.add_paragraph()
    name_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = name_para.add_run(cv_data.get("name", ""))
    run.bold = True
    run.font.size = Pt(22)
    _set_run_color(run, primary_hex)

    # ── Contact line ──────────────────────────────────────────────────────────
    contact_parts = []
    for field in ("email", "phone", "location", "linkedin", "website"):
        val = cv_data.get(field, "")
        if val:
            contact_parts.append(val)
    if cv_data.get("dob"):
        contact_parts.append(f"DOB: {cv_data['dob']}")
    if contact_parts:
        cp = doc.add_paragraph("  |  ".join(contact_parts))
        cp.runs[0].font.size = Pt(9)
        _set_run_color(cp.runs[0], "666666")

    def add_section_heading(title: str):
        p = doc.add_paragraph()
        run = p.add_run(title.upper())
        run.bold = True
        run.font.size = Pt(10)
        _set_run_color(run, primary_hex)
        _add_horizontal_rule(p)
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(3)

    def add_bullet(text: str):
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(text)
        p.runs[0].font.size = Pt(9.5)
        p.paragraph_format.space_after = Pt(1)

    def add_body(text: str, bold: bool = False, size: float = 9.5, color: str = "222222"):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        _set_run_color(run, color)
        p.paragraph_format.space_after = Pt(1)
        return p

    # ── Summary ───────────────────────────────────────────────────────────────
    if cv_data.get("summary"):
        add_section_heading("Professional Summary")
        add_body(cv_data["summary"])

    # ── Experience ────────────────────────────────────────────────────────────
    if cv_data.get("experience"):
        add_section_heading("Professional Experience")
        for exp in cv_data["experience"]:
            title_run_p = doc.add_paragraph()
            r = title_run_p.add_run(exp.get("title", ""))
            r.bold = True
            r.font.size = Pt(10)
            _set_run_color(r, primary_hex)
            title_run_p.paragraph_format.space_after = Pt(0)

            co_line = exp.get("company", "")
            if exp.get("location"):
                co_line += f"  —  {exp['location']}"
            date_str = ""
            if exp.get("start_date") or exp.get("end_date"):
                date_str = f"  |  {exp.get('start_date', '')} – {exp.get('end_date', 'Present')}"

            sub_p = doc.add_paragraph()
            r_co = sub_p.add_run(co_line)
            r_co.font.size = Pt(9)
            _set_run_color(r_co, "555555")
            if date_str:
                r_dt = sub_p.add_run(date_str)
                r_dt.font.size = Pt(9)
                _set_run_color(r_dt, accent_hex)
            sub_p.paragraph_format.space_after = Pt(2)

            for bullet in exp.get("bullets", []):
                add_bullet(bullet)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)

    # ── Education ─────────────────────────────────────────────────────────────
    if cv_data.get("education"):
        add_section_heading("Education")
        for edu in cv_data["education"]:
            p = doc.add_paragraph()
            r = p.add_run(edu.get("degree", ""))
            r.bold = True
            r.font.size = Pt(10)
            _set_run_color(r, primary_hex)

            sub = edu.get("institution", "")
            if edu.get("year"):
                sub += f"  |  {edu['year']}"
            add_body(sub, color="555555", size=9.0)
            if edu.get("honors"):
                add_body(edu["honors"], color="555555", size=9.0)
            if edu.get("gpa"):
                add_body(edu["gpa"], color="555555", size=9.0)

    # ── Skills ────────────────────────────────────────────────────────────────
    if cv_data.get("skills", {}).get("categories"):
        add_section_heading("Skills")
        for cat in cv_data["skills"]["categories"]:
            items = ", ".join(cat.get("items", []))
            if items:
                p = doc.add_paragraph()
                r_cat = p.add_run(f"{cat['name']}: ")
                r_cat.bold = True
                r_cat.font.size = Pt(9.5)
                r_items = p.add_run(items)
                r_items.font.size = Pt(9.5)

    # ── Certifications ────────────────────────────────────────────────────────
    if cv_data.get("certifications"):
        add_section_heading("Certifications")
        for cert in cv_data["certifications"]:
            line = cert.get("name", "")
            if cert.get("issuer"):
                line += f"  —  {cert['issuer']}"
            if cert.get("date"):
                line += f"  ({cert['date']})"
            add_bullet(line)

    # ── Projects ──────────────────────────────────────────────────────────────
    if cv_data.get("projects"):
        add_section_heading("Projects")
        for proj in cv_data["projects"]:
            p = doc.add_paragraph()
            r = p.add_run(proj.get("name", ""))
            r.bold = True
            r.font.size = Pt(10)
            if proj.get("description"):
                add_body(proj["description"])
            if proj.get("technologies"):
                add_body(f"Technologies: {', '.join(proj['technologies'])}", color="555555", size=9.0)

    # ── Languages ─────────────────────────────────────────────────────────────
    if cv_data.get("languages"):
        add_section_heading("Languages")
        add_body(", ".join(cv_data["languages"]))

    # Apply template color overrides
    tmpl.apply_docx_styles(doc)

    doc.save(output_path)
    return output_path
