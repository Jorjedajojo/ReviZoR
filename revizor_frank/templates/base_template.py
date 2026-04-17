"""Base template class — defines the interface all templates must implement.

Each template provides:
- Visual style constants (colors, fonts, sizes)
- A render_pdf() method that returns a ReportLab Story (list of Flowables)
- A render_docx() method that styles a python-docx Document in-place

All templates use single-column layout for maximum ATS compatibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Spacer,
    KeepTogether,
    Table,
    TableStyle,
)
from reportlab.platypus import SimpleDocTemplate

# ── Arabic text support ───────────────────────────────────────────────────────

_ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
_arabic_font_name: str = ""   # cached font name; empty = not yet checked


def _has_arabic(text: str) -> bool:
    return bool(_ARABIC_CHAR_RE.search(text))


def _reshape_arabic(text: str) -> str:
    """Reshape and apply BiDi algorithm to Arabic text for correct PDF rendering."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


def _get_arabic_font() -> str:
    """Find and register a system font with Arabic support. Returns font name or ''."""
    global _arabic_font_name
    if _arabic_font_name:
        return _arabic_font_name

    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = [
        ("FreeSans",       "/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
        ("DejaVuSans",     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("NotoSans",       "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        ("LiberationSans", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ("Arial",          "C:/Windows/Fonts/arial.ttf"),
    ]
    for fname, fpath in candidates:
        if os.path.exists(fpath):
            try:
                pdfmetrics.registerFont(TTFont(fname, fpath))
                _arabic_font_name = fname
                return fname
            except Exception:
                continue
    _arabic_font_name = "Helvetica"  # fallback — Arabic glyphs won't show perfectly
    return _arabic_font_name


# ── Page geometry (A4 with 1.8 cm margins) ────────────────────────────────────
_USABLE_W: float = (21.0 - 2 * 1.8) * cm   # ≈ 493 pts


@dataclass
class TemplateStyle:
    # Colors (R, G, B) as reportlab Color objects
    primary_color: Any = colors.HexColor("#1a1a2e")
    secondary_color: Any = colors.HexColor("#16213e")
    accent_color: Any = colors.HexColor("#0f3460")
    text_color: Any = colors.HexColor("#222222")
    muted_color: Any = colors.HexColor("#666666")
    bg_color: Any = colors.white

    # Fonts (ReportLab built-ins for max compatibility)
    heading_font: str = "Helvetica-Bold"
    body_font: str = "Helvetica"
    mono_font: str = "Courier"

    # Sizes
    name_size: float = 22
    section_heading_size: float = 11
    body_size: float = 9.5
    small_size: float = 8.5

    # Spacing
    section_space_before: float = 0.25 * 28.35  # ~0.25cm in points
    bullet_indent: float = 0.35 * 28.35

    # DOCX theme colors (hex without #)
    docx_primary_hex: str = "1a1a2e"
    docx_accent_hex: str = "0f3460"


class BaseTemplate:
    """Abstract base — subclasses must set `style` and may override render methods.

    layout: str — one of:
        "single_column"            default, single-column ATS-safe
        "header_banner"            full-width colored header block, single-column body
        "two_column_left_sidebar"  narrow dark sidebar on left, main content on right
        "two_column_right_sidebar" mirror of above
        "split_header"             photo-placeholder left, name/title/contact right, single body
        "timeline"                 vertical date-line for experience entries
        "boxed_sections"           each section in a bordered box with colored heading tab
        "minimal_centered"         centered header, no dividers, lots of whitespace
        "compact_two_column"       equal two-column body; summary/header full-width
    """

    name: str = "Base"
    layout: str = "single_column"
    style: TemplateStyle = field(default_factory=TemplateStyle)

    def __init__(self):
        self.style = TemplateStyle()
        self._base_styles = getSampleStyleSheet()

    # ── ReportLab style helpers ───────────────────────────────────────────────

    def _ps(self, **kwargs) -> ParagraphStyle:
        """Create a ParagraphStyle with defaults from this template."""
        defaults = {
            "fontName": self.style.body_font,
            "fontSize": self.style.body_size,
            "textColor": self.style.text_color,
            "leading": self.style.body_size * 1.35,
            "spaceAfter": 2,
        }
        defaults.update(kwargs)
        return ParagraphStyle("custom", **defaults)

    def _heading_style(self) -> ParagraphStyle:
        return self._ps(
            fontName=self.style.heading_font,
            fontSize=self.style.section_heading_size,
            textColor=self.style.primary_color,
            spaceBefore=self.style.section_space_before,
            spaceAfter=4,
            leading=self.style.section_heading_size * 1.2,
        )

    def _name_style(self) -> ParagraphStyle:
        return self._ps(
            fontName=self.style.heading_font,
            fontSize=self.style.name_size,
            textColor=self.style.primary_color,
            spaceAfter=4,
            leading=self.style.name_size * 1.1,
        )

    def _contact_style(self) -> ParagraphStyle:
        return self._ps(
            fontName=self.style.body_font,
            fontSize=self.style.small_size,
            textColor=self.style.muted_color,
            spaceAfter=2,
        )

    def _body_style(self) -> ParagraphStyle:
        return self._ps()

    def _bold_style(self) -> ParagraphStyle:
        return self._ps(fontName=self.style.heading_font)

    def _muted_style(self) -> ParagraphStyle:
        return self._ps(textColor=self.style.muted_color, fontSize=self.style.small_size)

    def _bullet_style(self) -> ParagraphStyle:
        return self._ps(
            leftIndent=self.style.bullet_indent,
            firstLineIndent=-self.style.bullet_indent,
            spaceAfter=1,
        )

    # ── Section divider ───────────────────────────────────────────────────────

    def _divider(self) -> HRFlowable:
        return HRFlowable(
            width="100%",
            thickness=0.75,
            color=self.style.accent_color,
            spaceAfter=4,
            spaceBefore=2,
        )

    # ── Common section builders ───────────────────────────────────────────────

    def _section_heading(self, title: str) -> list:
        return [
            Paragraph(title.upper(), self._heading_style()),
            self._divider(),
        ]

    def _contact_line(self, cv: dict) -> str:
        parts = []
        if cv.get("email"):
            parts.append(cv["email"])
        # phones: prefer list; fall back to splitting the joined string
        phones = cv.get("phones") or (
            [p.strip() for p in cv["phone"].split("|") if p.strip()]
            if cv.get("phone") else []
        )
        if phones:
            parts.append(" | ".join(phones))
        if cv.get("location"):
            parts.append(cv["location"])
        if cv.get("linkedin"):
            parts.append("LinkedIn")
        if cv.get("website"):
            parts.append(cv["website"])
        return "  |  ".join(parts)

    def _safe_para(self, text: str, style: ParagraphStyle) -> Paragraph:
        """Return a Paragraph with Arabic reshaping + RTL alignment if needed."""
        if not text:
            return Paragraph("", style)
        if _has_arabic(text):
            shaped = _reshape_arabic(text)
            ar_font = _get_arabic_font()
            ar_style = ParagraphStyle(
                "ar_safe",
                parent=style,
                fontName=ar_font,
                alignment=TA_RIGHT,
            )
            return Paragraph(shaped, ar_style)
        return Paragraph(text, style)

    # ── Content builder helpers ───────────────────────────────────────────────

    def _build_header_section(self, cv: dict) -> list:
        """Standard name / title / contact / dob header flowables."""
        ns = self._name_style()
        ts = self._ps(
            fontSize=self.style.body_size + 1,
            textColor=self.style.secondary_color,
            leading=14, fontName=self.style.heading_font,
        )
        cs = self._contact_style()
        items: list = [self._safe_para(cv.get("name", ""), ns)]
        if cv.get("title"):
            items.append(self._safe_para(cv["title"], ts))
        cl = self._contact_line(cv)
        if cl:
            items.append(Paragraph(cl, cs))
        if cv.get("dob"):
            items.append(Paragraph(f"Date of Birth: {cv['dob']}", cs))
        items.append(Spacer(1, 8))
        return items

    def _build_body_sections(self, cv: dict, skip: frozenset = frozenset()) -> list:
        """All CV sections below the header. skip = set of section keys to omit."""
        story: list = []
        bs = self._body_style()
        bolds = self._bold_style()
        muted = self._muted_style()
        bullets = self._bullet_style()

        if "summary" not in skip and cv.get("summary"):
            story.extend(self._section_heading("Professional Summary"))
            story.append(self._safe_para(cv["summary"], bs))

        if "skills" not in skip and cv.get("skills", {}).get("categories"):
            story.extend(self._section_heading("Core & Technical Competencies"))
            for cat in cv["skills"]["categories"]:
                items = cat.get("items", [])
                if items:
                    story.append(Paragraph(
                        f"<b>{cat.get('name', 'Skills')}:</b>  {', '.join(items)}", bs))

        if "experience" not in skip and cv.get("experience"):
            story.extend(self._section_heading("Professional Experience"))
            for exp in cv["experience"]:
                co = exp.get("company", "")
                if exp.get("location"):
                    co += f"  —  {exp['location']}"
                dr = ""
                if exp.get("start_date") or exp.get("end_date"):
                    dr = f"{exp.get('start_date', '')} – {exp.get('end_date', 'Present')}"
                block = [
                    Paragraph(f"<b>{exp.get('title', '')}</b>", bolds),
                    Paragraph(
                        f"{co}&nbsp;&nbsp;&nbsp;<font color='#{self.style.docx_accent_hex}'>{dr}</font>",
                        muted),
                ]
                for b in exp.get("bullets", []):
                    block.append(Paragraph(f"• {b}", bullets))
                block.append(Spacer(1, 4))
                story.append(KeepTogether(block))

        if "education" not in skip and cv.get("education"):
            story.extend(self._section_heading("Education"))
            for edu in cv["education"]:
                block = [Paragraph(f"<b>{edu.get('degree', '')}</b>", bolds)]
                sub = edu.get("institution", "")
                if edu.get("year"):
                    sub += f"  |  {edu['year']}"
                block.append(Paragraph(sub, muted))
                if edu.get("honors"):
                    block.append(Paragraph(edu["honors"], muted))
                if edu.get("gpa"):
                    block.append(Paragraph(edu["gpa"], muted))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        if "certifications" not in skip and cv.get("certifications"):
            story.extend(self._section_heading("Certifications"))
            for cert in cv["certifications"]:
                line = cert.get("name", "")
                if cert.get("issuer"):
                    line += f"  —  {cert['issuer']}"
                if cert.get("date"):
                    line += f"  ({cert['date']})"
                story.append(Paragraph(f"• {line}", bullets))

        if "training" not in skip and cv.get("training"):
            story.extend(self._section_heading("Professional Training"))
            for item in cv["training"]:
                line = item.get("name", "")
                if item.get("organisation"):
                    line += f"  —  {item['organisation']}"
                if item.get("date"):
                    line += f"  ({item['date']})"
                story.append(Paragraph(f"• {line}", bullets))
                if item.get("description"):
                    story.append(Paragraph(item["description"], muted))

        if "projects" not in skip and cv.get("projects"):
            story.extend(self._section_heading("Projects"))
            for proj in cv["projects"]:
                block = [Paragraph(f"<b>{proj.get('name', '')}</b>", bolds)]
                if proj.get("description"):
                    block.append(Paragraph(proj["description"], bs))
                if proj.get("technologies"):
                    block.append(Paragraph(
                        f"<i>Technologies:</i> {', '.join(proj['technologies'])}", muted))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        if "languages" not in skip and cv.get("languages"):
            story.extend(self._section_heading("Languages"))
            story.append(Paragraph(", ".join(cv["languages"]), bs))

        return story

    # ── Layout-agnostic story (used for single_column and as fallback) ────────

    def render_pdf_story(self, cv: dict) -> list:
        """Single-column layout: header + all body sections."""
        return self._build_header_section(cv) + self._build_body_sections(cv)

    # ── Layout-specific PDF builders ──────────────────────────────────────────

    def _build_pdf_single_column(self, cv: dict, output_path: str) -> str:
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            rightMargin=1.8 * cm, leftMargin=1.8 * cm,
            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        )
        doc.build(self.render_pdf_story(cv))
        return output_path

    def _build_pdf_header_banner(self, cv: dict, output_path: str) -> str:
        """Full-width colored banner for name/title/contact, single-column body."""
        ws = lambda sz, bold=False: self._ps(
            fontName=self.style.heading_font if bold else self.style.body_font,
            fontSize=sz, textColor=colors.white,
            leading=sz * 1.25, spaceAfter=2,
        )
        banner: list = [self._safe_para(cv.get("name", ""), ws(self.style.name_size, True))]
        if cv.get("title"):
            banner.append(self._safe_para(cv["title"], ws(11)))
        cl = self._contact_line(cv)
        if cl:
            banner.append(Paragraph(cl, ws(8.5)))
        if cv.get("dob"):
            banner.append(Paragraph(f"DOB: {cv['dob']}", ws(8.5)))

        t = Table([[banner]], colWidths=[_USABLE_W])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), self.style.primary_color),
            ("TOPPADDING",    (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            rightMargin=1.8 * cm, leftMargin=1.8 * cm,
            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        )
        doc.build([t, Spacer(1, 10)] + self._build_body_sections(cv))
        return output_path

    def _build_pdf_two_column_left_sidebar(self, cv: dict, output_path: str) -> str:
        """Dark left sidebar using BaseDocTemplate Frames (avoids Table height-overflow bugs)."""
        from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, FrameBreak
        from reportlab.lib.pagesizes import A4 as _A4

        _W, _H = _A4
        m = 1.8 * cm
        lw = _USABLE_W * 0.33
        rw = _USABLE_W - lw
        uh = _H - 2 * m
        _primary = self.style.primary_color

        def _draw_bg(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(_primary)
            canvas.rect(m, m, lw, uh, fill=1, stroke=0)
            canvas.restoreState()

        lf = Frame(m, m, lw, uh,
                   leftPadding=10, rightPadding=8, topPadding=12, bottomPadding=12, id="left")
        rf = Frame(m + lw, m, rw, uh,
                   leftPadding=14, rightPadding=0, topPadding=6, bottomPadding=6, id="right")

        doc_obj = BaseDocTemplate(
            output_path, pagesize=_A4,
            leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=m,
        )
        doc_obj.addPageTemplates([PageTemplate(id="TwoCol", frames=[lf, rf], onPage=_draw_bg)])

        sw = lambda sz, c=colors.white, bold=False: self._ps(
            fontName=self.style.heading_font if bold else self.style.body_font,
            fontSize=sz, textColor=c, leading=sz * 1.35, spaceAfter=2,
        )
        sn = sw(min(self.style.name_size * 0.72, 16), bold=True)
        st = sw(9, c=colors.HexColor("#dddddd"))
        sh = sw(8.5, bold=True)
        sb = sw(8, c=colors.HexColor("#dddddd"))
        sc = sw(7.5, c=colors.HexColor("#cccccc"))

        left: list = [self._safe_para(cv.get("name", ""), sn)]
        if cv.get("title"):
            left.append(self._safe_para(cv["title"], st))
        left.append(Spacer(1, 10))

        def _sec(title: str, items: list) -> None:
            left.append(Paragraph(title.upper(), sh))
            left.append(Spacer(1, 3))
            left.extend(items)
            left.append(Spacer(1, 8))

        phones = cv.get("phones") or (
            [p.strip() for p in cv.get("phone", "").split("|") if p.strip()])
        ct = [Paragraph(p, sc) for p in phones]
        for fld in ("email", "location", "linkedin", "website"):
            if cv.get(fld):
                ct.append(Paragraph(str(cv[fld]), sc))
        if cv.get("dob"):
            ct.append(Paragraph(f"DOB: {cv['dob']}", sc))
        if ct:
            _sec("Contact", ct)
        if cv.get("skills", {}).get("categories"):
            for cat in cv["skills"]["categories"]:
                its = cat.get("items", [])
                if its:
                    _sec(cat.get("name", "Skills"), [Paragraph(f"• {i}", sb) for i in its])
        if cv.get("languages"):
            _sec("Languages", [Paragraph(f"• {l}", sb) for l in cv["languages"]])

        right: list = self._build_body_sections(cv, skip=frozenset({"skills", "languages"}))
        doc_obj.build(left + [FrameBreak()] + right)
        return output_path

    def _build_pdf_two_column_right_sidebar(self, cv: dict, output_path: str) -> str:
        """Main content on left, dark sidebar on right — mirror of left_sidebar."""
        from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, FrameBreak
        from reportlab.lib.pagesizes import A4 as _A4

        _W, _H = _A4
        m = 1.8 * cm
        rw = _USABLE_W * 0.33
        lw = _USABLE_W - rw
        uh = _H - 2 * m
        _primary = self.style.primary_color

        def _draw_bg(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(_primary)
            canvas.rect(m + lw, m, rw, uh, fill=1, stroke=0)
            canvas.restoreState()

        lf = Frame(m, m, lw, uh,
                   leftPadding=0, rightPadding=14, topPadding=6, bottomPadding=6, id="left")
        rf = Frame(m + lw, m, rw, uh,
                   leftPadding=10, rightPadding=8, topPadding=12, bottomPadding=12, id="right")

        doc_obj = BaseDocTemplate(
            output_path, pagesize=_A4,
            leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=m,
        )
        doc_obj.addPageTemplates([PageTemplate(id="TwoCol", frames=[lf, rf], onPage=_draw_bg)])

        sw = lambda sz, c=colors.white, bold=False: self._ps(
            fontName=self.style.heading_font if bold else self.style.body_font,
            fontSize=sz, textColor=c, leading=sz * 1.35, spaceAfter=2,
        )
        sn = sw(min(self.style.name_size * 0.72, 16), bold=True)
        st = sw(9, c=colors.HexColor("#dddddd"))
        sh = sw(8.5, bold=True)
        sb = sw(8, c=colors.HexColor("#dddddd"))
        sc = sw(7.5, c=colors.HexColor("#cccccc"))

        sidebar: list = [self._safe_para(cv.get("name", ""), sn)]
        if cv.get("title"):
            sidebar.append(self._safe_para(cv["title"], st))
        sidebar.append(Spacer(1, 10))

        def _sec(title: str, items: list) -> None:
            sidebar.append(Paragraph(title.upper(), sh))
            sidebar.append(Spacer(1, 3))
            sidebar.extend(items)
            sidebar.append(Spacer(1, 8))

        phones = cv.get("phones") or (
            [p.strip() for p in cv.get("phone", "").split("|") if p.strip()])
        ct = [Paragraph(p, sc) for p in phones]
        for fld in ("email", "location", "linkedin", "website"):
            if cv.get(fld):
                ct.append(Paragraph(str(cv[fld]), sc))
        if cv.get("dob"):
            ct.append(Paragraph(f"DOB: {cv['dob']}", sc))
        if ct:
            _sec("Contact", ct)
        if cv.get("skills", {}).get("categories"):
            for cat in cv["skills"]["categories"]:
                its = cat.get("items", [])
                if its:
                    _sec(cat.get("name", "Skills"), [Paragraph(f"• {i}", sb) for i in its])
        if cv.get("languages"):
            _sec("Languages", [Paragraph(f"• {l}", sb) for l in cv["languages"]])

        main: list = self._build_body_sections(cv, skip=frozenset({"skills", "languages"}))
        doc_obj.build(main + [FrameBreak()] + sidebar)
        return output_path

    def _build_pdf_split_header(self, cv: dict, output_path: str) -> str:
        """Left photo placeholder | right name/contact, single-column body below."""
        photo_w = _USABLE_W * 0.28
        info_w  = _USABLE_W - photo_w

        photo_items: list = [
            Spacer(1, 18),
            Paragraph("[ Photo ]", self._ps(
                fontSize=10, textColor=colors.white,
                fontName=self.style.heading_font, leading=13,
            )),
            Spacer(1, 2),
            Paragraph("Placeholder", self._ps(fontSize=7.5, textColor=colors.HexColor("#cccccc"))),
        ]
        info_items: list = [self._safe_para(cv.get("name", ""), self._name_style())]
        ts = self._ps(
            fontSize=self.style.body_size + 1, textColor=self.style.secondary_color,
            fontName=self.style.heading_font, leading=14,
        )
        if cv.get("title"):
            info_items.append(self._safe_para(cv["title"], ts))
        cl = self._contact_line(cv)
        if cl:
            info_items.append(Paragraph(cl, self._contact_style()))
        if cv.get("dob"):
            info_items.append(Paragraph(f"DOB: {cv['dob']}", self._contact_style()))

        t = Table([[photo_items, info_items]], colWidths=[photo_w, info_w])
        t.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND",    (0, 0), (0, -1),  colors.HexColor("#888888")),
            ("TOPPADDING",    (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING",   (0, 0), (0, -1),  10),
            ("RIGHTPADDING",  (0, 0), (0, -1),  8),
            ("LEFTPADDING",   (1, 0), (1, -1),  14),
            ("RIGHTPADDING",  (1, 0), (1, -1),  0),
            ("ALIGN",         (0, 0), (0, -1),  "CENTER"),
        ]))
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            rightMargin=1.8 * cm, leftMargin=1.8 * cm,
            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        )
        doc.build([t, Spacer(1, 12)] + self._build_body_sections(cv))
        return output_path

    def _build_pdf_timeline(self, cv: dict, output_path: str) -> str:
        """Vertical date-line with entries on the right for experience and education."""
        story: list = self._build_header_section(cv)
        bs     = self._body_style()
        bolds  = self._bold_style()
        muted  = self._muted_style()
        bullets = self._bullet_style()
        date_col_w    = 68
        content_col_w = _USABLE_W - date_col_w
        date_s = self._ps(
            fontSize=8, textColor=self.style.primary_color,
            fontName=self.style.heading_font, leading=10, spaceAfter=0,
        )

        if cv.get("summary"):
            story.extend(self._section_heading("Professional Summary"))
            story.append(self._safe_para(cv["summary"], bs))

        if cv.get("skills", {}).get("categories"):
            story.extend(self._section_heading("Core & Technical Competencies"))
            for cat in cv["skills"]["categories"]:
                its = cat.get("items", [])
                if its:
                    story.append(Paragraph(
                        f"<b>{cat.get('name','Skills')}:</b>  {', '.join(its)}", bs))

        if cv.get("experience"):
            story.extend(self._section_heading("Professional Experience"))
            for exp in cv["experience"]:
                dr = "\n–\n".join(filter(None, [
                    exp.get("start_date", ""), exp.get("end_date", "Present"),
                ]))
                co = exp.get("company", "")
                if exp.get("location"):
                    co += f"  —  {exp['location']}"
                right_block: list = [
                    Paragraph(f"<b>{exp.get('title', '')}</b>", bolds),
                    Paragraph(co, muted),
                ]
                for b in exp.get("bullets", []):
                    right_block.append(Paragraph(f"• {b}", bullets))
                right_block.append(Spacer(1, 6))
                row = Table(
                    [[Paragraph(dr, date_s), right_block]],
                    colWidths=[date_col_w, content_col_w],
                )
                row.setStyle(TableStyle([
                    ("VALIGN",     (0, 0), (-1, -1), "TOP"),
                    ("RIGHTPADDING", (0, 0), (0, -1),  8),
                    ("LEFTPADDING",  (0, 0), (0, -1),  0),
                    ("LEFTPADDING",  (1, 0), (1, -1),  10),
                    ("LINEBEFORE",   (1, 0), (1, -1),  1.5, self.style.accent_color),
                ]))
                story.append(row)

        if cv.get("education"):
            story.extend(self._section_heading("Education"))
            for edu in cv["education"]:
                right_block = [
                    Paragraph(f"<b>{edu.get('degree','')}</b>", bolds),
                    Paragraph(edu.get("institution", ""), muted),
                ]
                if edu.get("honors"):
                    right_block.append(Paragraph(edu["honors"], muted))
                right_block.append(Spacer(1, 4))
                row = Table(
                    [[Paragraph(edu.get("year", ""), date_s), right_block]],
                    colWidths=[date_col_w, content_col_w],
                )
                row.setStyle(TableStyle([
                    ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                    ("RIGHTPADDING", (0, 0), (0, -1),  8),
                    ("LEFTPADDING",  (0, 0), (0, -1),  0),
                    ("LEFTPADDING",  (1, 0), (1, -1),  10),
                    ("LINEBEFORE",   (1, 0), (1, -1),  1.5, self.style.accent_color),
                ]))
                story.append(row)

        story.extend(self._build_body_sections(
            cv, skip=frozenset({"summary", "skills", "experience", "education"})))
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            rightMargin=1.8 * cm, leftMargin=1.8 * cm,
            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        )
        doc.build(story)
        return output_path

    def _build_pdf_boxed_sections(self, cv: dict, output_path: str) -> str:
        """Each section in a bordered box with a colored heading tab."""
        story: list = self._build_header_section(cv)
        story.append(Spacer(1, 4))

        box_bg = colors.HexColor("#f0f4f8")
        bs     = self._body_style()
        bolds  = self._bold_style()
        muted  = self._muted_style()
        bullets = self._bullet_style()

        def _boxed(title: str, items: list) -> None:
            if not items:
                return
            head_s = self._ps(
                fontName=self.style.heading_font,
                fontSize=self.style.section_heading_size,
                textColor=colors.white,
                leading=self.style.section_heading_size * 1.2,
                spaceAfter=0,
            )
            inner = Table(
                [[Paragraph(title.upper(), head_s)], [items]],
                colWidths=[_USABLE_W - 4],
            )
            inner.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  self.style.primary_color),
                ("TOPPADDING",    (0, 0), (-1, 0),  6),
                ("BOTTOMPADDING", (0, 0), (-1, 0),  6),
                ("LEFTPADDING",   (0, 0), (-1, 0),  8),
                ("RIGHTPADDING",  (0, 0), (-1, 0),  8),
                ("BACKGROUND",    (0, 1), (-1, -1), box_bg),
                ("TOPPADDING",    (0, 1), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
                ("LEFTPADDING",   (0, 1), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 1), (-1, -1), 8),
                ("BOX",           (0, 0), (-1, -1), 0.75, self.style.primary_color),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(inner)
            story.append(Spacer(1, 8))

        if cv.get("summary"):
            _boxed("Professional Summary", [self._safe_para(cv["summary"], bs)])

        if cv.get("skills", {}).get("categories"):
            skill_items: list = []
            for cat in cv["skills"]["categories"]:
                its = cat.get("items", [])
                if its:
                    skill_items.append(Paragraph(
                        f"<b>{cat.get('name','Skills')}:</b>  {', '.join(its)}", bs))
            _boxed("Core & Technical Competencies", skill_items)

        if cv.get("experience"):
            exp_items: list = []
            for exp in cv["experience"]:
                co = exp.get("company", "")
                if exp.get("location"):
                    co += f"  —  {exp['location']}"
                dr = ""
                if exp.get("start_date") or exp.get("end_date"):
                    dr = f"{exp.get('start_date','')} – {exp.get('end_date','Present')}"
                exp_items.append(Paragraph(f"<b>{exp.get('title','')}</b>", bolds))
                exp_items.append(Paragraph(
                    f"{co}&nbsp;&nbsp;&nbsp;<font color='#{self.style.docx_accent_hex}'>{dr}</font>",
                    muted))
                for b in exp.get("bullets", []):
                    exp_items.append(Paragraph(f"• {b}", bullets))
                exp_items.append(Spacer(1, 4))
            _boxed("Professional Experience", exp_items)

        if cv.get("education"):
            edu_items: list = []
            for edu in cv["education"]:
                edu_items.append(Paragraph(f"<b>{edu.get('degree','')}</b>", bolds))
                sub = edu.get("institution", "")
                if edu.get("year"):
                    sub += f"  |  {edu['year']}"
                edu_items.append(Paragraph(sub, muted))
                if edu.get("honors"):
                    edu_items.append(Paragraph(edu["honors"], muted))
                edu_items.append(Spacer(1, 3))
            _boxed("Education", edu_items)

        if cv.get("certifications"):
            cert_items: list = []
            for cert in cv["certifications"]:
                line = cert.get("name", "")
                if cert.get("issuer"):
                    line += f"  —  {cert['issuer']}"
                if cert.get("date"):
                    line += f"  ({cert['date']})"
                cert_items.append(Paragraph(f"• {line}", bullets))
            _boxed("Certifications", cert_items)

        if cv.get("training"):
            tr_items: list = []
            for item in cv["training"]:
                line = item.get("name", "")
                if item.get("organisation"):
                    line += f"  —  {item['organisation']}"
                if item.get("date"):
                    line += f"  ({item['date']})"
                tr_items.append(Paragraph(f"• {line}", bullets))
            _boxed("Professional Training", tr_items)

        if cv.get("projects"):
            proj_items: list = []
            for proj in cv["projects"]:
                proj_items.append(Paragraph(f"<b>{proj.get('name','')}</b>", bolds))
                if proj.get("description"):
                    proj_items.append(Paragraph(proj["description"], bs))
                proj_items.append(Spacer(1, 3))
            _boxed("Projects", proj_items)

        if cv.get("languages"):
            _boxed("Languages", [Paragraph(", ".join(cv["languages"]), bs)])

        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            rightMargin=1.8 * cm, leftMargin=1.8 * cm,
            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        )
        doc.build(story)
        return output_path

    def _build_pdf_minimal_centered(self, cv: dict, output_path: str) -> str:
        """Centered header, no section dividers — whitespace only."""
        ctr = lambda sz, **kw: self._ps(
            fontSize=sz, alignment=TA_CENTER, **kw)
        story: list = []
        story.append(self._safe_para(cv.get("name", ""), ctr(
            self.style.name_size,
            fontName=self.style.heading_font,
            textColor=self.style.primary_color,
            leading=self.style.name_size * 1.1, spaceAfter=4,
        )))
        if cv.get("title"):
            story.append(self._safe_para(cv["title"], ctr(
                self.style.body_size + 1,
                fontName=self.style.body_font,
                textColor=self.style.secondary_color, leading=14, spaceAfter=3,
            )))
        cl = self._contact_line(cv)
        if cl:
            story.append(Paragraph(cl, ctr(
                self.style.small_size,
                fontName=self.style.body_font,
                textColor=self.style.muted_color, spaceAfter=2,
            )))
        if cv.get("dob"):
            story.append(Paragraph(f"DOB: {cv['dob']}", ctr(
                self.style.small_size, fontName=self.style.body_font,
                textColor=self.style.muted_color, spaceAfter=2,
            )))
        story.append(Spacer(1, 14))

        heading_s = self._ps(
            fontName=self.style.heading_font,
            fontSize=self.style.section_heading_size,
            textColor=self.style.primary_color,
            spaceBefore=10, spaceAfter=6,
            leading=self.style.section_heading_size * 1.2,
        )
        bs     = self._body_style()
        bolds  = self._bold_style()
        muted  = self._muted_style()
        bullets = self._bullet_style()

        def _sec(title: str) -> None:
            story.append(Paragraph(title.upper(), heading_s))

        if cv.get("summary"):
            _sec("Professional Summary")
            story.append(self._safe_para(cv["summary"], bs))

        if cv.get("skills", {}).get("categories"):
            _sec("Core & Technical Competencies")
            for cat in cv["skills"]["categories"]:
                its = cat.get("items", [])
                if its:
                    story.append(Paragraph(
                        f"<b>{cat.get('name','Skills')}:</b>  {', '.join(its)}", bs))

        if cv.get("experience"):
            _sec("Professional Experience")
            for exp in cv["experience"]:
                co = exp.get("company", "")
                if exp.get("location"):
                    co += f"  —  {exp['location']}"
                dr = ""
                if exp.get("start_date") or exp.get("end_date"):
                    dr = f"{exp.get('start_date','')} – {exp.get('end_date','Present')}"
                block = [
                    Paragraph(f"<b>{exp.get('title','')}</b>", bolds),
                    Paragraph(
                        f"{co}&nbsp;&nbsp;&nbsp;<font color='#{self.style.docx_accent_hex}'>{dr}</font>",
                        muted),
                ]
                for b in exp.get("bullets", []):
                    block.append(Paragraph(f"• {b}", bullets))
                block.append(Spacer(1, 4))
                story.append(KeepTogether(block))

        if cv.get("education"):
            _sec("Education")
            for edu in cv["education"]:
                block = [Paragraph(f"<b>{edu.get('degree','')}</b>", bolds)]
                sub = edu.get("institution", "")
                if edu.get("year"):
                    sub += f"  |  {edu['year']}"
                block.append(Paragraph(sub, muted))
                if edu.get("honors"):
                    block.append(Paragraph(edu["honors"], muted))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        if cv.get("certifications"):
            _sec("Certifications")
            for cert in cv["certifications"]:
                line = cert.get("name", "")
                if cert.get("issuer"):
                    line += f"  —  {cert['issuer']}"
                if cert.get("date"):
                    line += f"  ({cert['date']})"
                story.append(Paragraph(f"• {line}", bullets))

        if cv.get("training"):
            _sec("Professional Training")
            for item in cv["training"]:
                line = item.get("name", "")
                if item.get("organisation"):
                    line += f"  —  {item['organisation']}"
                if item.get("date"):
                    line += f"  ({item['date']})"
                story.append(Paragraph(f"• {line}", bullets))

        if cv.get("languages"):
            _sec("Languages")
            story.append(Paragraph(", ".join(cv["languages"]), bs))

        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            rightMargin=1.8 * cm, leftMargin=1.8 * cm,
            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        )
        doc.build(story)
        return output_path

    def _build_pdf_compact_two_column(self, cv: dict, output_path: str) -> str:
        """Full-width header + summary, then equal two-column body via BaseDocTemplate Frames."""
        from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, FrameBreak
        from reportlab.lib.pagesizes import A4 as _A4

        _W, _H = _A4
        m = 1.8 * cm
        col_w = (_USABLE_W - 4) / 2
        uh = _H - 2 * m
        _accent = colors.HexColor("#dddddd")

        def _draw_divider(canvas, doc):
            canvas.saveState()
            canvas.setStrokeColor(_accent)
            canvas.setLineWidth(0.5)
            canvas.line(m + col_w + 2, m, m + col_w + 2, _H - m)
            canvas.restoreState()

        lf = Frame(m, m, col_w, uh,
                   leftPadding=0, rightPadding=6, topPadding=6, bottomPadding=6, id="left")
        rf = Frame(m + col_w + 4, m, col_w, uh,
                   leftPadding=6, rightPadding=0, topPadding=6, bottomPadding=6, id="right")

        doc_obj = BaseDocTemplate(
            output_path, pagesize=_A4,
            leftMargin=m, rightMargin=m, topMargin=m, bottomMargin=m,
        )
        doc_obj.addPageTemplates([PageTemplate(id="TwoCol", frames=[lf, rf], onPage=_draw_divider)])

        left_items = (self._build_header_section(cv)
                      + self._build_body_sections(
                          cv, skip=frozenset({"education", "skills", "languages",
                                              "training", "certifications"})))
        right_items = self._build_body_sections(
            cv, skip=frozenset({"summary", "experience", "projects"}))

        doc_obj.build(left_items + [FrameBreak()] + (right_items or [Spacer(1, 1)]))
        return output_path

    # ── Main PDF entry point ──────────────────────────────────────────────────

    def build_pdf(self, cv: dict, output_path: str) -> str:
        """Dispatch to the layout-specific renderer based on self.layout."""
        _dispatch = {
            "single_column":            self._build_pdf_single_column,
            "header_banner":            self._build_pdf_header_banner,
            "two_column_left_sidebar":  self._build_pdf_two_column_left_sidebar,
            "two_column_right_sidebar": self._build_pdf_two_column_right_sidebar,
            "split_header":             self._build_pdf_split_header,
            "timeline":                 self._build_pdf_timeline,
            "boxed_sections":           self._build_pdf_boxed_sections,
            "minimal_centered":         self._build_pdf_minimal_centered,
            "compact_two_column":       self._build_pdf_compact_two_column,
        }
        return _dispatch.get(self.layout, self._build_pdf_single_column)(cv, output_path)

    # ── DOCX styling (applied to a Document object) ───────────────────────────

    def apply_docx_styles(self, doc) -> None:
        """Apply template-specific styles to a python-docx Document.
        Subclasses can override for additional customization.
        Called by the DOCX exporter after building the document structure.
        """
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        primary = tuple(int(self.style.docx_primary_hex[i:i+2], 16) for i in (0, 2, 4))

        for para in doc.paragraphs:
            for run in para.runs:
                if run.bold and para.style.name.startswith("Heading"):
                    run.font.color.rgb = RGBColor(*primary)
