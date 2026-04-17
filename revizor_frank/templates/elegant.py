"""Elegant template — deep indigo with purple accent."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class ElegantTemplate(BaseTemplate):
    name = "Elegant"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#2c2c54"),
            secondary_color=colors.HexColor("#393966"),
            accent_color=colors.HexColor("#9b59b6"),
            text_color=colors.HexColor("#1a1a2e"),
            muted_color=colors.HexColor("#6c6c8a"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=24,
            section_heading_size=10,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="2c2c54",
            docx_accent_hex="9b59b6",
        )
