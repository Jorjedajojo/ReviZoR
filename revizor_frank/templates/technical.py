"""Technical / Engineering template — monospace accents, dark green, structured."""

from reportlab.lib import colors
from reportlab.platypus import HRFlowable, Paragraph

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class TechnicalTemplate(BaseTemplate):
    name = "Technical / Engineering"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1e3a2f"),    # Forest green
            secondary_color=colors.HexColor("#2d5a40"),
            accent_color=colors.HexColor("#00b894"),     # Mint green
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#546e7a"),
            heading_font="Courier-Bold",
            body_font="Helvetica",
            mono_font="Courier",
            name_size=22,
            section_heading_size=10.5,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="1e3a2f",
            docx_accent_hex="00b894",
        )

    def _section_heading(self, title: str) -> list:
        """Override: prefix heading with > marker for tech feel."""
        styled_title = f"&gt; {title.upper()}"
        return [
            Paragraph(styled_title, self._heading_style()),
            HRFlowable(width="100%", thickness=0.5,
                       color=self.style.accent_color, spaceAfter=4, spaceBefore=2),
        ]
