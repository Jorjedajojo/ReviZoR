"""Academic template — formal, comprehensive, serif, burgundy & cream."""

from reportlab.lib import colors
from reportlab.platypus import HRFlowable, Paragraph, Spacer

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class AcademicTemplate(BaseTemplate):
    name = "Academic"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#6b0f1a"),    # Burgundy
            secondary_color=colors.HexColor("#8b1a28"),
            accent_color=colors.HexColor("#6b0f1a"),
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#5a5a5a"),
            heading_font="Times-Bold",
            body_font="Times-Roman",
            name_size=22,
            section_heading_size=12,
            body_size=10,
            small_size=9,
            docx_primary_hex="6b0f1a",
            docx_accent_hex="6b0f1a",
        )

    def render_pdf_story(self, cv: dict) -> list:
        """Override: Academic CVs put Education before Experience and add Publications/Awards."""
        story = []
        ns = self._name_style()
        cs = self._contact_style()
        bs = self._body_style()
        bolds = self._bold_style()
        muted = self._muted_style()
        bullets = self._bullet_style()

        from reportlab.platypus import KeepTogether

        # Header
        story.append(Paragraph(cv.get("name", ""), ns))
        contact = self._contact_line(cv)
        if contact:
            story.append(Paragraph(contact, cs))
        story.append(Spacer(1, 8))

        # Education first for academic CVs
        if cv.get("education"):
            story.extend(self._section_heading("Education"))
            for edu in cv["education"]:
                block = [Paragraph(f"<b>{edu.get('degree', '')}</b>", bolds)]
                sub = edu.get("institution", "")
                if edu.get("year"):
                    sub += f",  {edu['year']}"
                block.append(Paragraph(sub, muted))
                if edu.get("honors"):
                    block.append(Paragraph(edu["honors"], muted))
                if edu.get("gpa"):
                    block.append(Paragraph(edu["gpa"], muted))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        # Summary / Research Statement
        if cv.get("summary"):
            story.extend(self._section_heading("Research Statement"))
            story.append(Paragraph(cv["summary"], bs))

        # Experience / Academic Positions
        if cv.get("experience"):
            story.extend(self._section_heading("Academic & Professional Positions"))
            for exp in cv["experience"]:
                date_line = f"{exp.get('start_date', '')} – {exp.get('end_date', 'Present')}"
                block = [
                    Paragraph(f"<b>{exp.get('title', '')}</b>", bolds),
                    Paragraph(f"{exp.get('company', '')}  |  {date_line}", muted),
                ]
                for b in exp.get("bullets", []):
                    block.append(Paragraph(f"• {b}", bullets))
                block.append(Spacer(1, 4))
                story.append(KeepTogether(block))

        # Skills
        if cv.get("skills", {}).get("categories"):
            story.extend(self._section_heading("Research Areas & Skills"))
            for cat in cv["skills"]["categories"]:
                items = ", ".join(cat.get("items", []))
                if items:
                    story.append(Paragraph(f"<b>{cat['name']}:</b>  {items}", bs))

        # Certifications
        if cv.get("certifications"):
            story.extend(self._section_heading("Certifications & Awards"))
            for cert in cv["certifications"]:
                line = cert.get("name", "")
                if cert.get("issuer"):
                    line += f"  —  {cert['issuer']}"
                if cert.get("date"):
                    line += f"  ({cert['date']})"
                story.append(Paragraph(f"• {line}", bullets))

        # Training
        if cv.get("training"):
            story.extend(self._section_heading("Professional Training"))
            for item in cv["training"]:
                line = item.get("name", "")
                if item.get("organisation"):
                    line += f"  —  {item['organisation']}"
                if item.get("date"):
                    line += f"  ({item['date']})"
                story.append(Paragraph(f"• {line}", bullets))
                if item.get("description"):
                    story.append(Paragraph(item["description"], muted))

        # Languages
        if cv.get("languages"):
            story.extend(self._section_heading("Languages"))
            story.append(Paragraph(", ".join(cv["languages"]), bs))

        return story
