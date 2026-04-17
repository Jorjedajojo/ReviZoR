"""Classic Professional template — traditional, conservative, navy & white."""

from reportlab.lib import colors

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class ClassicTemplate(BaseTemplate):
    name = "Classic Professional"
    layout = "single_column"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#002147"),    # Oxford Navy
            secondary_color=colors.HexColor("#1a3a5c"),
            accent_color=colors.HexColor("#8b0000"),     # Dark red rule lines
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#555555"),
            heading_font="Times-Bold",
            body_font="Times-Roman",
            name_size=24,
            section_heading_size=11,
            body_size=10,
            small_size=9,
            docx_primary_hex="002147",
            docx_accent_hex="8b0000",
        )
