"""Creative (ATS-Safe) template — bold accent bar, indigo & coral, single-column."""

from reportlab.lib import colors
from reportlab.platypus import HRFlowable, Paragraph, Spacer

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class CreativeTemplate(BaseTemplate):
    name = "Creative (ATS-Safe)"
    layout = "split_header"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#3d348b"),    # Indigo
            secondary_color=colors.HexColor("#5c4db1"),
            accent_color=colors.HexColor("#e63946"),     # Coral red
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#6b7280"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=26,
            section_heading_size=10.5,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="3d348b",
            docx_accent_hex="e63946",
        )

    def _section_heading(self, title: str) -> list:
        """Override: thicker accent line above section heading."""
        return [
            HRFlowable(width="100%", thickness=2.5, color=self.style.accent_color,
                       spaceAfter=3, spaceBefore=self.style.section_space_before),
            Paragraph(title.upper(), self._heading_style()),
        ]
