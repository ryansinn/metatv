"""Drift-guard + behavioral tests for prefix-code interpretation alignment (#138).

A prefix code (``AR``, ``BS``, ``PA`` …) is interpreted by several independent,
hand-maintained tables:

- ``config.BASE_PREFIX_GROUPS``   — language filter groups (the language axis).
- ``config.BASE_REGIONAL_GROUPS`` — region filter groups (the region axis).
- ``channel_name_utils.CODE_FACETS``       — curated dual-facet classification.
- ``channel_name_utils.REGION_FULL_NAMES`` — the human display name for a code.

When these drift apart, the *same* code gets filtered one way and displayed
another.  The three confirmed regressions this suite locks down:

- ``AR`` = Arabic (90k+ channels, 100% Arabic), NOT Argentina (that is ``ARG``).
- ``BS`` = Serbian/Croatian (Bosnia, "Balkan Sky"), NOT English/Bahamas.
- ``PA`` = Panama (Spanish); Punjabi is a *separate* code ``PB``.

The two drift-guard tests below import the ACTUAL tables and assert cross-table
consistency.  They FAIL on the pre-#138 tables and PASS after the fix — that is
the single-source-of-truth guardrail against future re-drift.  The behavioral
tests exercise the live decomposer path with a real ``Config``.

Pure-function tests: no DB, no Qt.  The autouse ``_isolate_user_config`` fixture
(tests/conftest.py) keeps ``Config()`` writing to a throwaway tmp dir.
"""

import pytest

from metatv.core import config as cfg_module
from metatv.core.channel_name_utils import (
    CODE_FACETS,
    REGION_FULL_NAMES,
    normalize_region_code,
)
from metatv.core.config import Config
from metatv.core.tag_decomposer import decompose, decompose_name_parse


# --------------------------------------------------------------------------- #
#  Shared helpers                                                             #
# --------------------------------------------------------------------------- #

def _family(group_name: str) -> str:
    """Language *family* = the group name before its parenthesised locale.

    ``"Spanish (South America)"`` and ``"Spanish"`` share family ``"Spanish"``;
    ``"Arabic (Gulf)"`` → ``"Arabic"``.  Two DIFFERENT families claiming one code
    is a real conflict (that code is filtered under both languages at once).
    """
    return group_name.split(" (")[0].strip()


def _families_by_code() -> dict[str, set[str]]:
    """Map each code (upper) → the set of language FAMILIES that claim it."""
    out: dict[str, set[str]] = {}
    for group, codes in cfg_module.BASE_PREFIX_GROUPS.items():
        for code in codes:
            out.setdefault(code.upper(), set()).add(_family(group))
    return out


# Countries whose IPTV channel population is genuinely multilingual: a single
# code legitimately sits in two language families (e.g. BE = Dutch + French).
# These are the ONLY codes allowed to appear in 2+ conflicting families.
# (After the #138 fix, AR / BS / PA must NOT be here.)
_MULTILINGUAL_ALLOWLIST = frozenset(
    {"BE", "CA", "CH", "CM", "CMR", "CY", "MZ", "MOZ", "NG", "SN", "TZ", "TZA"}
)

# REGION_FULL_NAMES values that are a LANGUAGE name or a language-region
# aggregate rather than a sovereign COUNTRY.  A language-primary code (one whose
# CODE_FACETS entry is language-only) is allowed to display one of these — e.g.
# EN → "English", LAT → "Latin America".  It must NOT display a country name
# that implies a different language (that is the AR → "Argentina" bug).
_LANGUAGE_OR_AGGREGATE_DISPLAYS = frozenset(
    {
        "English", "Hindi", "Tamil", "Telugu", "Malayalam", "Kannada",
        "Bengali", "Marathi", "Gujarati", "Punjabi", "Odia", "Bhojpuri",
        "Farsi / Persian", "Kurdish",
        "Latin America", "Latin America (Spanish)", "Ex-Yugoslavia",
        "Scandinavian",
    }
)


# --------------------------------------------------------------------------- #
#  Drift-guard 1 — no code in two conflicting language families               #
# --------------------------------------------------------------------------- #

class TestNoConflictingLanguageFamilies:
    """Criterion 1: no code is claimed by 2+ conflicting language families."""

    def test_no_unexpected_conflicting_families(self):
        """Every code in 2+ language families must be an allowlisted multilingual country."""
        fam = _families_by_code()
        offenders = {
            code: sorted(families)
            for code, families in fam.items()
            if len(families) >= 2 and code not in _MULTILINGUAL_ALLOWLIST
        }
        assert offenders == {}, (
            "Codes claimed by conflicting language families (not in the "
            f"multilingual allowlist): {offenders}"
        )

    @pytest.mark.parametrize(
        "code, expected_family",
        [
            ("AR", "Arabic"),            # not Spanish
            ("BS", "Serbian/Croatian"),  # not English
            ("PA", "Spanish"),           # not Indian (Panama)
            ("PB", "Indian"),            # Punjabi
        ],
    )
    def test_reconciled_codes_single_family(self, code, expected_family):
        """AR/BS/PA/PB each resolve to exactly one (correct) language family."""
        fam = _families_by_code()
        assert fam.get(code) == {expected_family}, (
            f"{code} expected single family {{{expected_family!r}}}, got {fam.get(code)}"
        )


# --------------------------------------------------------------------------- #
#  Drift-guard 2 — display name must not contradict language classification    #
# --------------------------------------------------------------------------- #

class TestDisplayLanguageAlignment:
    """Criterion 2: a country/region display must not contradict the language.

    The ``AR → "Argentina"`` bug: ``AR`` classifies as the Arabic *language* yet
    was displayed as the *country* Argentina (which speaks Spanish).  Reuses the
    reference audit's Divergence-1 logic over the live tables.
    """

    def test_language_primary_codes_have_no_conflicting_country_display(self):
        """No language-only CODE_FACETS code may display a foreign-country name."""
        offenders = []
        for code, facets in CODE_FACETS.items():
            types = {t for t, _v, _c in facets}
            if "language" not in types or "region" in types:
                continue  # not a language-primary code
            display = REGION_FULL_NAMES.get(code)
            if display and display not in _LANGUAGE_OR_AGGREGATE_DISPLAYS:
                offenders.append((code, display, sorted(types)))
        assert offenders == [], (
            "Language-primary codes displaying a conflicting country/region name "
            f"(the AR→Argentina class): {offenders}"
        )

    def test_ar_not_displayed_as_argentina(self):
        """AR must not resolve to a display name at all (Argentina = ARG)."""
        assert "AR" not in REGION_FULL_NAMES
        assert REGION_FULL_NAMES.get("AR", "") != "Argentina"

    def test_arg_still_argentina(self):
        """ARG (the real Argentine country code) still displays 'Argentina'."""
        assert REGION_FULL_NAMES.get("ARG") == "Argentina"

    def test_pa_display_and_language_agree(self):
        """PA displays 'Panama' and classifies Spanish — consistent, not a conflict."""
        assert REGION_FULL_NAMES.get("PA") == "Panama"
        fam = _families_by_code()
        assert fam.get("PA") == {"Spanish"}

    def test_pb_display_and_language_agree(self):
        """PB displays 'Punjabi' and classifies Indian — consistent."""
        assert REGION_FULL_NAMES.get("PB") == "Punjabi"
        fam = _families_by_code()
        assert fam.get("PB") == {"Indian"}


# --------------------------------------------------------------------------- #
#  Behavioral — the live decomposer path (real Config)                        #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def cfg():
    """A default Config() with the shipped base groups (tmp-isolated home)."""
    return Config()


class TestGroupMembership:
    """AR / BS memberships in the shipped BASE_PREFIX_GROUPS."""

    def test_ar_in_arabic_not_spanish(self):
        assert "AR" in cfg_module.BASE_PREFIX_GROUPS["Arabic"]
        assert "AR" not in cfg_module.BASE_PREFIX_GROUPS["Spanish"]
        assert "AR" not in cfg_module.BASE_PREFIX_GROUPS["Spanish (South America)"]

    def test_ar_not_in_south_or_latin_america_region_groups(self):
        assert "AR" not in cfg_module.BASE_REGIONAL_GROUPS["South America"]
        assert "AR" not in cfg_module.BASE_REGIONAL_GROUPS["Latin America"]

    def test_arg_still_in_argentine_region_groups(self):
        assert "ARG" in cfg_module.BASE_REGIONAL_GROUPS["South America"]
        assert "ARG" in cfg_module.BASE_REGIONAL_GROUPS["Latin America"]

    def test_bs_in_serbian_croatian_not_english(self):
        assert "BS" in cfg_module.BASE_PREFIX_GROUPS["Serbian/Croatian"]
        assert "BS" not in cfg_module.BASE_PREFIX_GROUPS["English"]

    def test_pa_still_spanish_pb_indian(self):
        assert "PA" in cfg_module.BASE_PREFIX_GROUPS["Spanish"]
        assert "PA" not in cfg_module.BASE_PREFIX_GROUPS["Indian"]
        assert "PB" in cfg_module.BASE_PREFIX_GROUPS["Indian"]


class TestPunjabiAlias:
    """The PUNJABI full-name alias must resolve to PB, never PA (Panama)."""

    def test_punjabi_normalizes_to_pb(self):
        assert normalize_region_code("PUNJABI") == "PB"

    def test_punjabi_not_pa(self):
        assert normalize_region_code("PUNJABI") != "PA"


class TestDecomposerClassification:
    """End-to-end tag classification through the live decomposer."""

    def test_ar_language_arabic_not_region_argentina(self, cfg):
        tags = decompose("provider_category", "AR", config=cfg)
        assert ("language", "Arabic") in [(t, v) for t, v, _ in tags]
        assert not any(v == "Argentina" for _t, v, _ in tags), tags

    def test_arg_language_spanish_region_argentina(self, cfg):
        tags = [(t, v) for t, v, _ in decompose("provider_category", "ARG", config=cfg)]
        assert ("language", "Spanish") in tags
        assert ("region", "ARG") in tags

    def test_bs_language_serbian_croatian(self, cfg):
        tags = [(t, v) for t, v, _ in decompose("provider_category", "BS", config=cfg)]
        assert ("language", "Serbian/Croatian") in tags

    def test_pa_panama_classifies_spanish(self, cfg):
        """A PA (Panama) channel classifies Spanish/Panama — NOT Indian."""
        tags = [(t, v) for t, v, _ in decompose("provider_category", "PA", config=cfg)]
        assert ("language", "Spanish") in tags
        assert ("region", "PA") in tags
        assert ("language", "Indian") not in tags

    def test_pb_classifies_indian_punjabi(self, cfg):
        tags = [(t, v) for t, v, _ in decompose("provider_category", "PB", config=cfg)]
        assert ("language", "Indian") in tags
        assert ("region", "PB") in tags

    def test_punjabi_prefix_classifies_indian_via_pb(self, cfg):
        """A PUNJABI| channel classifies Indian and its region resolves to PB."""
        tags = [(t, v) for t, v, _ in decompose("provider_category", "PUNJABI", config=cfg)]
        assert ("language", "Indian") in tags
        assert ("region", "PB") in tags

    def test_punjabi_detected_prefix_pb_classifies_indian(self, cfg):
        """After ingestion stores detected_prefix='PB', name-parse yields Indian."""
        tags = [
            (t, v)
            for t, v, _ in decompose_name_parse(
                detected_prefix="PB",
                detected_quality=None,
                detected_region=None,
                detected_year=None,
                config=cfg,
            )
        ]
        assert ("language", "Indian") in tags
        assert ("region", "PB") in tags
