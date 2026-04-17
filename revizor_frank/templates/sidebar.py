"""Sidebar template — deep navy with steel-blue accent."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class SidebarTemplate(BaseTemplate):
    name = "Sidebar"
    layout = "two_column_left_sidebar"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1a3a5c"),
            secondary_color=colors.HexColor("#243f63"),
            accent_color=colors.HexColor("#4a90d9"),
            text_color=colors.HexColor("#1a1a2e"),
            muted_color=colors.HexColor("#6c757d"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=24,
            section_heading_size=10,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="1a3a5c",
            docx_accent_hex="4a90d9",
        )
