"""A compound prefix may carry its quality token in brackets (#281).

Owner: "IT-[4K] - Monty Python e il Sacro Graal (1975) … seems to be complete
with IT and 4K rather than those pruned to chips."

``_COMPOUND_PREFIX_RE`` accepted ``4K-DE``, ``DE-4K`` and ``DE 4K`` but not
``IT-[4K]``. A shape it does not match is not partially handled — it fails
entirely, so the whole prefix survived into ``detected_title`` and the row
rendered the raw provider string instead of a clean title with IT and 4K lifted
into chips. 101 rows in the owner's library.

The optional brackets sit OUTSIDE the capture group so the token stays ``"4K"``
rather than ``"[4K]"`` — callers normalise it and would otherwise get a value
that matches no quality vocabulary.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import parse_channel_name


class TestBracketedQuality:

    def test_the_owner_reported_name(self):
        parsed = parse_channel_name("IT-[4K] - Monty Python e il Sacro Graal (1975)")
        assert parsed.bare_name == "Monty Python e il Sacro Graal"
        assert parsed.quality[:1] == ["4K"]
        assert parsed.year == "1975"

    @pytest.mark.parametrize("name,title", [
        ("IT-[4K] - Alien vs. Predator", "Alien vs. Predator"),
        ("[4K]-IT - Bracketed First (1980)", "Bracketed First"),
        ("DE [UHD] - Ein Film (1999)", "Ein Film"),
    ])
    def test_bracketed_forms_parse(self, name, title):
        assert parse_channel_name(name).bare_name == title

    def test_the_quality_token_is_clean(self):
        """"4K", not "[4K]" — the brackets must not land inside the capture.

        A bracketed value would match no quality vocabulary downstream, so the
        chip and the filter group would both silently miss.
        """
        quality = parse_channel_name("IT-[4K] - Film (2001)").quality
        assert quality[:1] == ["4K"], f"got {quality!r}"


class TestUnbracketedFormsStillWork:
    """The shapes that already worked must not regress."""

    @pytest.mark.parametrize("name,title", [
        ("IT-4K - Some Film (2001)", "Some Film"),
        ("4K-DE - Ein Film (1999)", "Ein Film"),
        ("[US] 4K-DE - Movie (2010)", "Movie"),
        ("PL 4K - Film (2020)", "Film"),
    ])
    def test_existing_compound_shapes(self, name, title):
        assert parse_channel_name(name).bare_name == title


def test_a_bracket_that_is_not_a_quality_is_left_alone():
    """Only the known quality tokens are eligible.

    An arbitrary bracketed word must not be treated as a compound prefix and
    silently eaten out of the title.
    """
    parsed = parse_channel_name("IT-[SUB] - Real Title (2001)")
    assert "Real Title" in parsed.bare_name
