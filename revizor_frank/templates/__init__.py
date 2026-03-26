"""Template registry for ReviZoR FranK."""

from revizor_frank.templates.classic    import ClassicTemplate
from revizor_frank.templates.modern     import ModernTemplate
from revizor_frank.templates.executive  import ExecutiveTemplate
from revizor_frank.templates.creative   import CreativeTemplate
from revizor_frank.templates.technical  import TechnicalTemplate
from revizor_frank.templates.academic   import AcademicTemplate
from revizor_frank.templates.healthcare import HealthcareTemplate
from revizor_frank.templates.graduate   import GraduateTemplate

REGISTRY: dict = {
    "classic":    ClassicTemplate,
    "modern":     ModernTemplate,
    "executive":  ExecutiveTemplate,
    "creative":   CreativeTemplate,
    "technical":  TechnicalTemplate,
    "academic":   AcademicTemplate,
    "healthcare": HealthcareTemplate,
    "graduate":   GraduateTemplate,
}


def get_template(name: str):
    cls = REGISTRY.get(name, ModernTemplate)
    return cls()
