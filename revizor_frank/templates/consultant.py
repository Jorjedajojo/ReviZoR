"""Consultant template — two-column left sidebar, navy & gold, serif headings."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class ConsultantTemplate(BaseTemplate):
    name = "Consultant"
    layout = "two_column_left_sidebar"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1a2744"),    # Deep navy
            secondary_color=colors.HexColor("#2c3e6b"),
            accent_color=colors.HexColor("#c9a84c"),     # Gold
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#555555"),
            heading_font="Times-Bold",
            body_font="Times-Roman",
            name_size=22,
            section_heading_size=11,
            body_size=10,
            small_size=9,
            docx_primary_hex="1a2744",
            docx_accent_hex="c9a84c",
        )
