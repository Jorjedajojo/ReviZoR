"""PDF exporter — uses ReportLab + the selected template."""

from __future__ import annotations

from pathlib import Path


def export_pdf(cv_data: dict, template_name: str, output_path: str,
               template_color: str = "") -> str:
    """Render cv_data as a PDF using the given template. Returns output_path."""
    from revizor_frank.templates import get_template
    template = get_template(template_name, primary_color=template_color)
    template.build_pdf(cv_data, output_path)
    return output_path
