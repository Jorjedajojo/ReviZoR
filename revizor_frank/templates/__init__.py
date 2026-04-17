"""Template registry for ReviZoR FranK."""

from revizor_frank.templates.classic    import ClassicTemplate
from revizor_frank.templates.modern     import ModernTemplate
from revizor_frank.templates.executive  import ExecutiveTemplate
from revizor_frank.templates.creative   import CreativeTemplate
from revizor_frank.templates.technical  import TechnicalTemplate
from revizor_frank.templates.academic   import AcademicTemplate
from revizor_frank.templates.healthcare import HealthcareTemplate
from revizor_frank.templates.graduate   import GraduateTemplate
from revizor_frank.templates.minimal    import MinimalTemplate
from revizor_frank.templates.bold       import BoldTemplate
from revizor_frank.templates.sidebar    import SidebarTemplate
from revizor_frank.templates.compact    import CompactTemplate
from revizor_frank.templates.elegant    import ElegantTemplate

REGISTRY: dict = {
    "classic":    ClassicTemplate,
    "modern":     ModernTemplate,
    "executive":  ExecutiveTemplate,
    "creative":   CreativeTemplate,
    "technical":  TechnicalTemplate,
    "academic":   AcademicTemplate,
    "healthcare": HealthcareTemplate,
    "graduate":   GraduateTemplate,
    "minimal":    MinimalTemplate,
    "bold":       BoldTemplate,
    "sidebar":    SidebarTemplate,
    "compact":    CompactTemplate,
    "elegant":    ElegantTemplate,
}


def get_template(name: str, primary_color: str = ""):
    """Instantiate a template by name, optionally overriding the primary colour.

    primary_color: hex string with or without leading '#', e.g. '#1a3a5c' or '1a3a5c'.
    """
    cls = REGISTRY.get(name, ModernTemplate)
    tmpl = cls()
    if primary_color:
        from reportlab.lib.colors import HexColor
        hex_clean = primary_color.lstrip("#")
        if len(hex_clean) == 6:
            tmpl.style.primary_color = HexColor(f"#{hex_clean}")
            tmpl.style.accent_color = HexColor(f"#{hex_clean}")
            tmpl.style.docx_primary_hex = hex_clean
            tmpl.style.docx_accent_hex = hex_clean
    return tmpl
