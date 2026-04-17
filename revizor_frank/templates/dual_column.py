"""Dual Column template — compact two-column balanced grid, charcoal & orange accents."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class DualColumnTemplate(BaseTemplate):
    name = "Dual Column"
    layout = "compact_two_column"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#2c2c2c"),    # Charcoal
            secondary_color=colors.HexColor("#3d3d3d"),
            accent_color=colors.HexColor("#ea580c"),     # Orange
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#666666"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=24,
            section_heading_size=10.5,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="2c2c2c",
            docx_accent_hex="ea580c",
        )
