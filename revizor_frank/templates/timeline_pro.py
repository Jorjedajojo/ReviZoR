"""Timeline Pro template — vertical timeline layout, teal accents, modern sans-serif."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class TimelineProTemplate(BaseTemplate):
    name = "Timeline Pro"
    layout = "timeline"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#0d7a6e"),    # Deep teal
            secondary_color=colors.HexColor("#1a8f82"),
            accent_color=colors.HexColor("#14b8a6"),     # Bright teal
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#555555"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=26,
            section_heading_size=11,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="0d7a6e",
            docx_accent_hex="14b8a6",
        )
