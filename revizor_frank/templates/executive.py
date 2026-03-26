"""Executive template — bold, authoritative, deep slate & gold."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class ExecutiveTemplate(BaseTemplate):
    name = "Executive"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1b2631"),    # Deep slate
            secondary_color=colors.HexColor("#2e4057"),
            accent_color=colors.HexColor("#c9a84c"),     # Gold
            text_color=colors.HexColor("#1b2631"),
            muted_color=colors.HexColor("#5d6d7e"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=28,
            section_heading_size=11,
            body_size=10,
            small_size=9,
            docx_primary_hex="1b2631",
            docx_accent_hex="c9a84c",
        )
