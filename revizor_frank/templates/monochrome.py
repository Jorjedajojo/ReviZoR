"""Monochrome template — pure black & white, minimal centered, serif throughout."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class MonochromeTemplate(BaseTemplate):
    name = "Monochrome"
    layout = "minimal_centered"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#000000"),
            secondary_color=colors.HexColor("#111111"),
            accent_color=colors.HexColor("#333333"),
            text_color=colors.HexColor("#000000"),
            muted_color=colors.HexColor("#555555"),
            heading_font="Times-Bold",
            body_font="Times-Roman",
            name_size=26,
            section_heading_size=11,
            body_size=10,
            small_size=9,
            docx_primary_hex="000000",
            docx_accent_hex="333333",
        )
