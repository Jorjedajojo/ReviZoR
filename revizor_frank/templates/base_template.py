"""Base template class — defines the interface all templates must implement.

Each template provides:
- Visual style constants (colors, fonts, sizes)
- A render_pdf() method that returns a ReportLab Story (list of Flowables)
- A render_docx() method that styles a python-docx Document in-place

All templates use single-column layout for maximum ATS compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Spacer,
    KeepTogether,
)
from reportlab.platypus import SimpleDocTemplate


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
    """Abstract base — subclasses must set `style` and may override render methods."""

    name: str = "Base"
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
        if cv.get("phone"):
            parts.append(cv["phone"])
        if cv.get("location"):
            parts.append(cv["location"])
        if cv.get("linkedin"):
            parts.append(cv["linkedin"])
        if cv.get("website"):
            parts.append(cv["website"])
        return "  |  ".join(parts)

    # ── Main render method (shared logic, subclasses can override) ────────────

    def render_pdf_story(self, cv: dict) -> list:
        """Return a list of ReportLab Flowables for the full CV."""
        story = []
        hs = self._heading_style()
        ns = self._name_style()
        cs = self._contact_style()
        bs = self._body_style()
        bolds = self._bold_style()
        muted = self._muted_style()
        bullets = self._bullet_style()

        # ── Header ────────────────────────────────────────────────────────────
        story.append(Paragraph(cv.get("name", ""), ns))
        contact_line = self._contact_line(cv)
        if contact_line:
            story.append(Paragraph(contact_line, cs))
        story.append(Spacer(1, 8))

        # ── Summary ───────────────────────────────────────────────────────────
        if cv.get("summary"):
            story.extend(self._section_heading("Professional Summary"))
            story.append(Paragraph(cv["summary"], bs))

        # ── Experience ────────────────────────────────────────────────────────
        if cv.get("experience"):
            story.extend(self._section_heading("Professional Experience"))
            for exp in cv["experience"]:
                title_line = exp.get("title", "")
                company_line = exp.get("company", "")
                if exp.get("location"):
                    company_line += f"  —  {exp['location']}"
                date_line = ""
                if exp.get("start_date") or exp.get("end_date"):
                    date_line = f"{exp.get('start_date', '')} – {exp.get('end_date', 'Present')}"

                block = [
                    Paragraph(f"<b>{title_line}</b>", bolds),
                    Paragraph(
                        f"{company_line}&nbsp;&nbsp;&nbsp;<font color='#{self.style.docx_accent_hex}'>{date_line}</font>",
                        muted,
                    ),
                ]
                for b in exp.get("bullets", []):
                    block.append(Paragraph(f"• {b}", bullets))
                block.append(Spacer(1, 4))
                story.append(KeepTogether(block))

        # ── Education ─────────────────────────────────────────────────────────
        if cv.get("education"):
            story.extend(self._section_heading("Education"))
            for edu in cv["education"]:
                degree = edu.get("degree", "")
                institution = edu.get("institution", "")
                year = edu.get("year", "")
                honors = edu.get("honors", "")
                gpa = edu.get("gpa", "")
                block = [Paragraph(f"<b>{degree}</b>", bolds)]
                sub = institution
                if year:
                    sub += f"  |  {year}"
                block.append(Paragraph(sub, muted))
                if honors:
                    block.append(Paragraph(honors, muted))
                if gpa:
                    block.append(Paragraph(gpa, muted))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        # ── Skills ────────────────────────────────────────────────────────────
        if cv.get("skills", {}).get("categories"):
            story.extend(self._section_heading("Skills"))
            for cat in cv["skills"]["categories"]:
                items = ", ".join(cat.get("items", []))
                if items:
                    story.append(Paragraph(
                        f"<b>{cat['name']}:</b>  {items}", bs
                    ))

        # ── Certifications ────────────────────────────────────────────────────
        if cv.get("certifications"):
            story.extend(self._section_heading("Certifications"))
            for cert in cv["certifications"]:
                line = cert.get("name", "")
                if cert.get("issuer"):
                    line += f"  —  {cert['issuer']}"
                if cert.get("date"):
                    line += f"  ({cert['date']})"
                story.append(Paragraph(f"• {line}", bullets))

        # ── Projects ─────────────────────────────────────────────────────────
        if cv.get("projects"):
            story.extend(self._section_heading("Projects"))
            for proj in cv["projects"]:
                block = [Paragraph(f"<b>{proj.get('name', '')}</b>", bolds)]
                if proj.get("description"):
                    block.append(Paragraph(proj["description"], bs))
                if proj.get("technologies"):
                    block.append(Paragraph(
                        f"<i>Technologies:</i> {', '.join(proj['technologies'])}", muted
                    ))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        # ── Languages ─────────────────────────────────────────────────────────
        if cv.get("languages"):
            story.extend(self._section_heading("Languages"))
            story.append(Paragraph(", ".join(cv["languages"]), bs))

        return story

    def build_pdf(self, cv: dict, output_path: str) -> str:
        """Build a PDF file at output_path and return the path."""
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=1.8 * cm,
            leftMargin=1.8 * cm,
            topMargin=1.8 * cm,
            bottomMargin=1.8 * cm,
        )
        story = self.render_pdf_story(cv)
        doc.build(story)
        return output_path

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
