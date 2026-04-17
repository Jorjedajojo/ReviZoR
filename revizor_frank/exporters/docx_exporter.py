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
    layout = getattr(tmpl, "layout", "single_column")

    if layout in ("two_column_left_sidebar", "two_column_right_sidebar",
                  "consultant", "healthcare", "executive", "sidebar"):
        return _export_docx_two_column(cv_data, tmpl, output_path)
    if layout == "header_banner":
        return _export_docx_header_banner(cv_data, tmpl, output_path)
    return _export_docx_single_column(cv_data, tmpl, output_path)


def _export_docx_single_column(cv_data: dict, tmpl, output_path: str) -> str:
    """Standard single-column DOCX (original implementation)."""
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

    # ── Professional title line (below name) ─────────────────────────────────
    if cv_data.get("title"):
        title_para = doc.add_paragraph()
        title_run = title_para.add_run(cv_data["title"])
        title_run.bold = False
        title_run.italic = True
        title_run.font.size = Pt(11)
        _set_run_color(title_run, "444444")

    # ── Contact line ──────────────────────────────────────────────────────────
    contact_parts = []
    if cv_data.get("email"):
        contact_parts.append(cv_data["email"])
    # phones: prefer list; fall back to splitting the joined string
    _phones = cv_data.get("phones") or (
        [p.strip() for p in cv_data["phone"].split("|") if p.strip()]
        if cv_data.get("phone") else []
    )
    if _phones:
        contact_parts.append(" | ".join(_phones))
    if cv_data.get("location"):
        contact_parts.append(cv_data["location"])
    if cv_data.get("linkedin"):
        contact_parts.append("LinkedIn")
    if cv_data.get("website"):
        contact_parts.append(cv_data["website"])
    if contact_parts:
        cp = doc.add_paragraph("  |  ".join(contact_parts))
        cp.runs[0].font.size = Pt(9)
        _set_run_color(cp.runs[0], "666666")
    if cv_data.get("dob"):
        dob_p = doc.add_paragraph(f"Date of Birth: {cv_data['dob']}")
        dob_p.runs[0].font.size = Pt(9)
        _set_run_color(dob_p.runs[0], "666666")

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

    # ── Skills ────────────────────────────────────────────────────────────────
    if cv_data.get("skills", {}).get("categories"):
        add_section_heading("Core & Technical Competencies")
        for cat in cv_data["skills"]["categories"]:
            items = cat.get("items", [])
            if not items:
                continue
            cat_name = cat.get("name", "Skills")
            p = doc.add_paragraph()
            r_cat = p.add_run(f"{cat_name}: ")
            r_cat.bold = True
            r_cat.font.size = Pt(9.5)
            r_items = p.add_run(", ".join(items))
            r_items.font.size = Pt(9.5)

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

    # ── Training ──────────────────────────────────────────────────────────────
    if cv_data.get("training"):
        add_section_heading("Professional Training")
        for item in cv_data["training"]:
            line = item.get("name", "")
            if item.get("organisation"):
                line += f"  —  {item['organisation']}"
            if item.get("date"):
                line += f"  ({item['date']})"
            add_bullet(line)
            if item.get("description"):
                add_body(item["description"], color="555555", size=9.0)

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


def _export_docx_header_banner(cv_data: dict, tmpl, output_path: str) -> str:
    """DOCX with shaded header banner containing name/title/contact."""
    from docx.oxml import OxmlElement
    primary_hex = tmpl.style.docx_primary_hex
    accent_hex  = tmpl.style.docx_accent_hex
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    def _shade_para(para, hex_color: str):
        """Apply solid background shading to a paragraph via XML."""
        pPr = para._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        pPr.append(shd)

    # Banner: name
    p_name = doc.add_paragraph()
    _shade_para(p_name, primary_hex)
    r = p_name.add_run(cv_data.get("name", ""))
    r.bold = True
    r.font.size = Pt(22)
    r.font.color.rgb = RGBColor(255, 255, 255)

    # Banner: title
    if cv_data.get("title"):
        p_title = doc.add_paragraph()
        _shade_para(p_title, primary_hex)
        r = p_title.add_run(cv_data["title"])
        r.font.size = Pt(11)
        r.font.color.rgb = RGBColor(220, 220, 220)

    # Banner: contact
    _phones = cv_data.get("phones") or (
        [p.strip() for p in cv_data.get("phone", "").split("|") if p.strip()])
    contact_parts = []
    if cv_data.get("email"):
        contact_parts.append(cv_data["email"])
    if _phones:
        contact_parts.append(" | ".join(_phones))
    for f in ("location", "linkedin"):
        if cv_data.get(f):
            contact_parts.append(str(cv_data[f]))
    if contact_parts:
        p_ct = doc.add_paragraph("  |  ".join(contact_parts))
        _shade_para(p_ct, primary_hex)
        p_ct.runs[0].font.size = Pt(8.5)
        p_ct.runs[0].font.color.rgb = RGBColor(200, 200, 200)

    # Spacer paragraph after banner
    doc.add_paragraph()

    # Reuse single-column section helpers
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

    if cv_data.get("summary"):
        add_section_heading("Professional Summary")
        add_body(cv_data["summary"])

    if cv_data.get("skills", {}).get("categories"):
        add_section_heading("Core & Technical Competencies")
        for cat in cv_data["skills"]["categories"]:
            items = cat.get("items", [])
            if not items:
                continue
            p = doc.add_paragraph()
            r_cat = p.add_run(f"{cat.get('name','Skills')}: ")
            r_cat.bold = True
            r_cat.font.size = Pt(9.5)
            r_items = p.add_run(", ".join(items))
            r_items.font.size = Pt(9.5)

    if cv_data.get("experience"):
        add_section_heading("Professional Experience")
        for exp in cv_data["experience"]:
            p = doc.add_paragraph()
            r = p.add_run(exp.get("title", ""))
            r.bold = True
            r.font.size = Pt(10)
            _set_run_color(r, primary_hex)
            co_line = exp.get("company", "")
            if exp.get("location"):
                co_line += f"  —  {exp['location']}"
            if exp.get("start_date") or exp.get("end_date"):
                co_line += f"  |  {exp.get('start_date','')} – {exp.get('end_date','Present')}"
            add_body(co_line, color="555555", size=9.0)
            for b in exp.get("bullets", []):
                add_bullet(b)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)

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

    if cv_data.get("certifications"):
        add_section_heading("Certifications")
        for cert in cv_data["certifications"]:
            line = cert.get("name", "")
            if cert.get("issuer"):
                line += f"  —  {cert['issuer']}"
            if cert.get("date"):
                line += f"  ({cert['date']})"
            add_bullet(line)

    if cv_data.get("training"):
        add_section_heading("Professional Training")
        for item in cv_data["training"]:
            line = item.get("name", "")
            if item.get("organisation"):
                line += f"  —  {item['organisation']}"
            if item.get("date"):
                line += f"  ({item['date']})"
            add_bullet(line)

    if cv_data.get("languages"):
        add_section_heading("Languages")
        add_body(", ".join(cv_data["languages"]))

    tmpl.apply_docx_styles(doc)
    doc.save(output_path)
    return output_path


def _export_docx_two_column(cv_data: dict, tmpl, output_path: str) -> str:
    """DOCX with a 2-column table: dark sidebar on left, main content on right."""
    from docx.oxml import OxmlElement
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ROW_HEIGHT_RULE

    primary_hex = tmpl.style.docx_primary_hex
    accent_hex  = tmpl.style.docx_accent_hex
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    # Use a 2-column table spanning the full page width
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"
    # Remove all borders from the table itself; we'll color the cells
    tbl = table._tbl
    tblPr = tbl.tblPr
    # Set column widths: left 33%, right 67%
    total_w = Inches(7.7)  # 8.5 - 0.9 left - 0.9 right margins (in EMU)
    left_w_emu  = int(total_w * 0.33)
    right_w_emu = int(total_w * 0.67)
    for i, width in enumerate([left_w_emu, right_w_emu]):
        table.columns[i].width = width

    left_cell  = table.cell(0, 0)
    right_cell = table.cell(0, 1)

    # ── Shade left cell with primary color ───────────────────────────────────
    def _shade_cell(cell, hex_color: str):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_color)
        tcPr.append(shd)

    _shade_cell(left_cell, primary_hex)

    def _white_run(para, text: str, sz: float = 9, bold: bool = False):
        r = para.add_run(text)
        r.bold = bold
        r.font.size = Pt(sz)
        r.font.color.rgb = RGBColor(255, 255, 255)
        return r

    def _grey_run(para, text: str, sz: float = 8):
        r = para.add_run(text)
        r.font.size = Pt(sz)
        r.font.color.rgb = RGBColor(200, 200, 200)
        return r

    # Left column content
    lc = left_cell
    # Clear default empty paragraph
    p = lc.paragraphs[0]
    _white_run(p, cv_data.get("name", ""), sz=14, bold=True)
    if cv_data.get("title"):
        p2 = lc.add_paragraph()
        _grey_run(p2, cv_data["title"], sz=9)

    lc.add_paragraph()  # spacer

    def _left_section(title: str):
        p = lc.add_paragraph()
        _white_run(p, title.upper(), sz=8.5, bold=True)
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(2)

    def _left_body(text: str):
        p = lc.add_paragraph()
        _grey_run(p, text, sz=8)
        p.paragraph_format.space_after = Pt(1)

    # Contact
    _left_section("Contact")
    _phones = cv_data.get("phones") or (
        [ph.strip() for ph in cv_data.get("phone", "").split("|") if ph.strip()])
    for ph in _phones:
        _left_body(ph)
    for fld in ("email", "location", "linkedin", "website"):
        if cv_data.get(fld):
            _left_body(str(cv_data[fld]))

    # Skills in sidebar
    if cv_data.get("skills", {}).get("categories"):
        for cat in cv_data["skills"]["categories"]:
            its = cat.get("items", [])
            if its:
                _left_section(cat.get("name", "Skills"))
                for item in its:
                    _left_body(f"• {item}")

    # Languages in sidebar
    if cv_data.get("languages"):
        _left_section("Languages")
        for lang in cv_data["languages"]:
            _left_body(f"• {lang}")

    # Right column content
    rc = right_cell
    rp = rc.paragraphs[0]

    def _right_heading(title: str):
        p = rc.add_paragraph()
        run = p.add_run(title.upper())
        run.bold = True
        run.font.size = Pt(10)
        _set_run_color(run, primary_hex)
        _add_horizontal_rule(p)
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(3)

    def _right_body(text: str, bold: bool = False, size: float = 9.5, color: str = "222222"):
        p = rc.add_paragraph()
        r = p.add_run(text)
        r.bold = bold
        r.font.size = Pt(size)
        _set_run_color(r, color)
        p.paragraph_format.space_after = Pt(1)

    def _right_bullet(text: str):
        p = rc.add_paragraph(style="List Bullet")
        p.add_run(text)
        p.runs[0].font.size = Pt(9.5)
        p.paragraph_format.space_after = Pt(1)

    if cv_data.get("summary"):
        _right_heading("Professional Summary")
        _right_body(cv_data["summary"])

    if cv_data.get("experience"):
        _right_heading("Professional Experience")
        for exp in cv_data["experience"]:
            p = rc.add_paragraph()
            r = p.add_run(exp.get("title", ""))
            r.bold = True
            r.font.size = Pt(10)
            _set_run_color(r, primary_hex)
            co = exp.get("company", "")
            if exp.get("location"):
                co += f"  —  {exp['location']}"
            if exp.get("start_date") or exp.get("end_date"):
                co += f"  |  {exp.get('start_date','')} – {exp.get('end_date','Present')}"
            _right_body(co, color="555555", size=9.0)
            for b in exp.get("bullets", []):
                _right_bullet(b)
            rc.add_paragraph().paragraph_format.space_after = Pt(2)

    if cv_data.get("education"):
        _right_heading("Education")
        for edu in cv_data["education"]:
            p = rc.add_paragraph()
            r = p.add_run(edu.get("degree", ""))
            r.bold = True
            r.font.size = Pt(10)
            _set_run_color(r, primary_hex)
            sub = edu.get("institution", "")
            if edu.get("year"):
                sub += f"  |  {edu['year']}"
            _right_body(sub, color="555555", size=9.0)

    if cv_data.get("certifications"):
        _right_heading("Certifications")
        for cert in cv_data["certifications"]:
            line = cert.get("name", "")
            if cert.get("issuer"):
                line += f"  —  {cert['issuer']}"
            if cert.get("date"):
                line += f"  ({cert['date']})"
            _right_bullet(line)

    if cv_data.get("training"):
        _right_heading("Professional Training")
        for item in cv_data["training"]:
            line = item.get("name", "")
            if item.get("organisation"):
                line += f"  —  {item['organisation']}"
            if item.get("date"):
                line += f"  ({item['date']})"
            _right_bullet(line)

    if cv_data.get("projects"):
        _right_heading("Projects")
        for proj in cv_data["projects"]:
            p = rc.add_paragraph()
            r = p.add_run(proj.get("name", ""))
            r.bold = True
            r.font.size = Pt(10)
            if proj.get("description"):
                _right_body(proj["description"])

    tmpl.apply_docx_styles(doc)
    doc.save(output_path)
    return output_path
