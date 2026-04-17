"""Corporate template — header banner layout, deep blue, clean sans-serif."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class CorporateTemplate(BaseTemplate):
    name = "Corporate"
    layout = "header_banner"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#003366"),    # Deep corporate blue
            secondary_color=colors.HexColor("#004080"),
            accent_color=colors.HexColor("#0066cc"),     # Bright blue
            text_color=colors.HexColor("#111111"),
            muted_color=colors.HexColor("#555555"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=28,
            section_heading_size=11,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="003366",
            docx_accent_hex="0066cc",
        )
