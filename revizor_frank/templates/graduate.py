"""Graduate / Entry-Level template — fresh, friendly, sky blue & light grey."""

from reportlab.lib import colors
from reportlab.platypus import KeepTogether, Paragraph, Spacer

from revizor_frank.templates.base_template import BaseTemplate, TemplateStyle


class GraduateTemplate(BaseTemplate):
    name = "Graduate / Entry-Level"

    def __init__(self):
        super().__init__()
        self.style = TemplateStyle(
            primary_color=colors.HexColor("#1565c0"),    # Sky blue
            secondary_color=colors.HexColor("#1976d2"),
            accent_color=colors.HexColor("#42a5f5"),     # Light blue
            text_color=colors.HexColor("#1a1a1a"),
            muted_color=colors.HexColor("#607d8b"),
            heading_font="Helvetica-Bold",
            body_font="Helvetica",
            name_size=24,
            section_heading_size=10.5,
            body_size=9.5,
            small_size=8.5,
            docx_primary_hex="1565c0",
            docx_accent_hex="42a5f5",
        )

    def render_pdf_story(self, cv: dict) -> list:
        """Override: puts Education and Projects near the top for entry-level candidates."""
        story = []
        ns = self._name_style()
        cs = self._contact_style()
        bs = self._body_style()
        bolds = self._bold_style()
        muted = self._muted_style()
        bullets = self._bullet_style()

        # Header
        story.append(Paragraph(cv.get("name", ""), ns))
        contact = self._contact_line(cv)
        if contact:
            story.append(Paragraph(contact, cs))
        story.append(Spacer(1, 8))

        # Summary
        if cv.get("summary"):
            story.extend(self._section_heading("Objective / Summary"))
            story.append(Paragraph(cv["summary"], bs))

        # Education (high priority for graduates)
        if cv.get("education"):
            story.extend(self._section_heading("Education"))
            for edu in cv["education"]:
                block = [Paragraph(f"<b>{edu.get('degree', '')}</b>", bolds)]
                sub = edu.get("institution", "")
                if edu.get("year"):
                    sub += f"  |  {edu['year']}"
                block.append(Paragraph(sub, muted))
                if edu.get("honors"):
                    block.append(Paragraph(edu["honors"], muted))
                if edu.get("gpa"):
                    block.append(Paragraph(edu["gpa"], muted))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        # Projects (high priority for graduates)
        if cv.get("projects"):
            story.extend(self._section_heading("Projects"))
            for proj in cv["projects"]:
                block = [Paragraph(f"<b>{proj.get('name', '')}</b>", bolds)]
                if proj.get("description"):
                    block.append(Paragraph(proj["description"], bs))
                if proj.get("technologies"):
                    block.append(Paragraph(
                        f"<i>Technologies:</i> {', '.join(proj['technologies'])}", muted
                    ))
                block.append(Spacer(1, 3))
                story.append(KeepTogether(block))

        # Experience
        if cv.get("experience"):
            story.extend(self._section_heading("Experience"))
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
            story.extend(self._section_heading("Skills"))
            for cat in cv["skills"]["categories"]:
                items = ", ".join(cat.get("items", []))
                if items:
                    story.append(Paragraph(f"<b>{cat['name']}:</b>  {items}", bs))

        # Certifications
        if cv.get("certifications"):
            story.extend(self._section_heading("Certifications"))
            for cert in cv["certifications"]:
                line = cert.get("name", "")
                if cert.get("issuer"):
                    line += f"  —  {cert['issuer']}"
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
