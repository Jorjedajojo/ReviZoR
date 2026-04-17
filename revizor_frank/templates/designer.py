"""Designer template — split header with photo placeholder, charcoal & amber accent."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class DesignerTemplate(BaseTemplate):
    name = "Designer"
    layout = "split_header"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#2d2d2d"),    # Charcoal
            secondary_color=colors.HexColor("#3d3d3d"),
            accent_color=colors.HexColor("#f59e0b"),     # Amber
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#666666"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=26,
            section_heading_size=10.5,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="2d2d2d",
            docx_accent_hex="f59e0b",
        )
