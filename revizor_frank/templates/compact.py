"""Compact template — dense layout for experienced candidates with many roles."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class CompactTemplate(BaseTemplate):
    name = "Compact"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1f2d3d"),
            secondary_color=colors.HexColor("#2c3e50"),
            accent_color=colors.HexColor("#2980b9"),
            text_color=colors.HexColor("#1f2d3d"),
            muted_color=colors.HexColor("#7f8c8d"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=20,
            section_heading_size=9,
            body_size=8.5,
            small_size=7.5,
            docx_primary_hex="1f2d3d",
            docx_accent_hex="2980b9",
        )
