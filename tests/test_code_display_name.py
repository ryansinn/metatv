"""A code's human-readable display name resolves via one shared resolver:
region name for a place, language name for a language code (AR → Arabic, NOT the
region "Argentina"), else "" so callers fall back to the raw code. Guards the
details-pane chip fix (#139) that pairs with the AR=Arabic alignment (#138)."""

from metatv.gui.details_versions import resolve_category_name


def test_language_code_resolves_to_language_name():
    # AR is a LANGUAGE code (Arabic) — must not be "" (bare code) or "Argentina".
    assert resolve_category_name("AR") == "Arabic"
    assert resolve_category_name("PB") == "Punjabi"


def test_region_code_still_resolves_to_place():
    assert resolve_category_name("US") == "United States"
    assert resolve_category_name("FR") == "France"
    # Argentina is ARG (not AR) and stays correct.
    assert resolve_category_name("ARG") == "Argentina"


def test_unknown_code_returns_empty_for_raw_fallback():
    assert resolve_category_name("ZZZ") == ""


def test_chip_renders_name_and_code():
    # The details title chip shows "{name} ({code})" so a language never displays as
    # a bare, ambiguous code.
    for code, expected in [("AR", "Arabic (AR)"), ("US", "United States (US)")]:
        name = resolve_category_name(code)
        assert (f"{name} ({code})" if name else code) == expected
    # Unresolved code falls back to the raw code alone.
    assert (resolve_category_name("ZZZ") or "ZZZ") == "ZZZ"
