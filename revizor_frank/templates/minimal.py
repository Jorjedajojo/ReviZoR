"""Minimal template — clean, near-black, no decorative colour."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class MinimalTemplate(BaseTemplate):
    name = "Minimal"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#111111"),
            secondary_color=colors.HexColor("#333333"),
            accent_color=colors.HexColor("#111111"),
            text_color=colors.HexColor("#111111"),
            muted_color=colors.HexColor("#777777"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=22,
            section_heading_size=10,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="111111",
            docx_accent_hex="111111",
        )
