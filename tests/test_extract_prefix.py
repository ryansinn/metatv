"""Unit tests for extract_prefix() and categorize_prefix() in filter_utils.

These are pure-function tests — no DB, no Qt.  They guard the ETL layer that
populates detected_prefix at ingestion time.  A regression here corrupts the
entire filter system because bad prefix data is stored and never re-parsed.
"""

import pytest
from metatv.core.filter_utils import extract_prefix, categorize_prefix


# ── extract_prefix ─────────────────────────────────────────────────────────────

class TestExtractPrefix:

    def test_dash_separator(self):
        assert extract_prefix("EN - BBC News") == "EN"

    def test_star_separator(self):
        assert extract_prefix("AF ★ Wede - Doc") == "AF"

    def test_pipe_separator(self):
        assert extract_prefix("AFR| RTN TELE SAHEL") == "AFR"

    def test_bracket_format(self):
        assert extract_prefix("[SE] Star Trek") == "SE"

    def test_colon_separator(self):
        assert extract_prefix("UK: Channel Name") == "UK"

    def test_streaming_brand_with_plus(self):
        assert extract_prefix("D+ - Movie Name") == "D+"

    def test_platform_prefix_nf(self):
        assert extract_prefix("NF - Squid Game") == "NF"

    def test_platform_prefix_ear(self):
        assert extract_prefix("EAR - Dan Da Dan") == "EAR"

    def test_no_prefix_lowercase_in_candidate(self):
        # "Breaking Bad" has lowercase — not a valid prefix
        assert extract_prefix("Breaking Bad - S01") is None

    def test_no_prefix_plain_title(self):
        assert extract_prefix("Just A Title") is None

    def test_empty_string(self):
        assert extract_prefix("") is None

    def test_none_equivalent_empty(self):
        # Should not raise
        assert extract_prefix("") is None

    def test_star_without_spaces(self):
        assert extract_prefix("FR★TF1") == "FR"

    def test_pipe_with_space(self):
        assert extract_prefix("DE | Das Erste") == "DE"

    def test_quality_as_prefix_4k(self):
        # Quality tokens are valid uppercase — extract_prefix returns them;
        # the ETL layer later moves them to detected_quality if they're quality tokens
        assert extract_prefix("4K - Movie Title") == "4K"

    def test_multichar_prefix(self):
        assert extract_prefix("NGA - Nigeria Channel") == "NGA"

    def test_prefix_with_slash(self):
        # Slash is allowed in the regex
        assert extract_prefix("N/A - Test") == "N/A"

    def test_longer_separator_wins(self):
        # " ★ " (with spaces) should win over bare "★" — test separator priority
        result = extract_prefix("AF ★ Wede ★ Doc")
        assert result == "AF"

    def test_custom_separators(self):
        # "::" IS found within "EN :: BBC News"; "EN " strips to "EN" → valid
        assert extract_prefix("EN :: BBC News", separators=["::"]) == "EN"
        # No separator match at all → None
        assert extract_prefix("EN - BBC News", separators=["::"]) is None


# ── categorize_prefix ──────────────────────────────────────────────────────────

LANG_GROUPS = {
    "English": ["EN", "ENG"],
    "French":  ["FR"],
    "German":  ["DE"],
}
QUAL_GROUPS = {
    "HD":       ["HD", "FHD"],
    "4K / UHD": ["4K", "UHD"],
    "SD":       ["SD"],
}
PLAT_GROUPS = {
    "EAR":     ["EAR"],
    "Netflix": ["NF", "NETFLIX"],
}


class TestCategorizePrefix:

    def test_language_match(self):
        result = categorize_prefix("EN", LANG_GROUPS, QUAL_GROUPS, PLAT_GROUPS)
        assert result["language"] == "English"
        assert result["quality"] == ""
        assert result["platform"] == ""

    def test_platform_match(self):
        result = categorize_prefix("EAR", LANG_GROUPS, QUAL_GROUPS, PLAT_GROUPS)
        assert result["platform"] == "EAR"
        assert result["language"] == ""

    def test_quality_match(self):
        result = categorize_prefix("HD", LANG_GROUPS, QUAL_GROUPS, PLAT_GROUPS)
        assert result["quality"] == "HD"
        assert result["language"] == ""

    def test_unmapped_prefix(self):
        result = categorize_prefix("GO", LANG_GROUPS, QUAL_GROUPS, PLAT_GROUPS)
        assert result == {"language": "", "quality": "", "platform": ""}

    def test_case_insensitive_match(self):
        result = categorize_prefix("en", LANG_GROUPS, QUAL_GROUPS, PLAT_GROUPS)
        assert result["language"] == "English"

    def test_alias_in_group(self):
        # NETFLIX is an alias for Netflix group
        result = categorize_prefix("NETFLIX", LANG_GROUPS, QUAL_GROUPS, PLAT_GROUPS)
        assert result["platform"] == "Netflix"

    def test_4k_quality(self):
        result = categorize_prefix("4K", LANG_GROUPS, QUAL_GROUPS, PLAT_GROUPS)
        assert result["quality"] == "4K / UHD"
