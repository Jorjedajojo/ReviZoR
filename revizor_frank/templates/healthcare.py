"""Healthcare template — clean, clinical, teal & white, trust-first design."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class HealthcareTemplate(BaseTemplate):
    name = "Healthcare"
    layout = "two_column_left_sidebar"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#005f73"),    # Clinical teal
            secondary_color=colors.HexColor("#0a9396"),
            accent_color=colors.HexColor("#94d2bd"),     # Soft seafoam
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#5c7a7a"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=22,
            section_heading_size=10.5,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="005f73",
            docx_accent_hex="94d2bd",
        )
