"""Boxed template — bordered section boxes with colored heading tabs, navy & light grey."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class BoxedTemplate(BaseTemplate):
    name = "Boxed"
    layout = "boxed_sections"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1e3a5f"),    # Navy
            secondary_color=colors.HexColor("#2a4f7c"),
            accent_color=colors.HexColor("#3b7fc4"),     # Steel blue
            text_color=colors.HexColor("#111111"),
            muted_color=colors.HexColor("#555555"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=24,
            section_heading_size=10.5,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="1e3a5f",
            docx_accent_hex="3b7fc4",
        )
