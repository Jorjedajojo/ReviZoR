"""Bold template — near-black with striking red accent."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class BoldTemplate(BaseTemplate):
    name = "Bold"
    layout = "header_banner"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#0d0d0d"),
            secondary_color=colors.HexColor("#1a1a1a"),
            accent_color=colors.HexColor("#e63946"),
            text_color=colors.HexColor("#0d0d0d"),
            muted_color=colors.HexColor("#666666"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=26,
            section_heading_size=11,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="0d0d0d",
            docx_accent_hex="e63946",
        )
