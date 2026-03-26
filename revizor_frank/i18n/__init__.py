"""i18n loader for ReviZoR FranK."""

from revizor_frank.config import DEFAULT_LANGUAGE


def get_strings(lang: str = DEFAULT_LANGUAGE) -> dict:
    if lang == "en":
        from revizor_frank.i18n.en import STRINGS
        return STRINGS
    # Fallback to English for unsupported languages
    from revizor_frank.i18n.en import STRINGS
    return STRINGS


# Module-level convenience accessor
STRINGS = get_strings()
