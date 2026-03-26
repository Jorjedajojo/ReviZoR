"""PNG exporter — renders the first page of the PDF as a high-res PNG."""

from __future__ import annotations

import os
import tempfile


def export_png(cv_data: dict, template_name: str, output_path: str, dpi: int = 200) -> str:
    """Render the first page of the CV PDF as a PNG. Returns output_path."""
    from revizor_frank.exporters.pdf_exporter import export_pdf

    # Build intermediate PDF in a temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_pdf = tmp.name

    try:
        export_pdf(cv_data, template_name, tmp_pdf)

        import fitz  # PyMuPDF
        doc = fitz.open(tmp_pdf)
        page = doc[0]
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        pix.save(output_path)
        doc.close()
    finally:
        os.unlink(tmp_pdf)

    return output_path
