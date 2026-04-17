"""Modern Minimalist template — clean, white space, charcoal & teal accents."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class ModernTemplate(BaseTemplate):
    name = "Modern Minimalist"
    layout = "header_banner"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1c1c1e"),    # Charcoal
            secondary_color=colors.HexColor("#2c2c2e"),
            accent_color=colors.HexColor("#00897b"),     # Teal
            text_color=colors.HexColor("#1c1c1e"),
            muted_color=colors.HexColor("#6e6e73"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=26,
            section_heading_size=10,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="1c1c1e",
            docx_accent_hex="00897b",
        )
