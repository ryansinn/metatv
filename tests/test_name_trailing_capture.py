"""``parse_channel_name`` surfaces the trailing credits it strips (#26, part 1).

Owner: "EN - Adaptation. 4K (2002) NICOLAS CAGE … it prunes the actor's name but
then does not add it to cast/crew."

Step 1b of the parser already IDENTIFIED that span as provider-appended extra
credits — it has guards distinguishing "HARVEY KEITEL, TARANTINO" from a real
subtitle like "FBI (2024) Reboot" — and then discarded it. The information was
not merely unused: it was never surfaced to any caller, so nothing downstream
could have used it even if it wanted to.

``ParsedChannel.trailing`` now carries it. The parser's job is to refuse to throw
it away; deciding what it MEANS is the caller's.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import parse_channel_name


class TestTrailingIsCaptured:

    @pytest.mark.parametrize("name,expected", [
        ("EN - Adaptation. 4K (2002) NICOLAS CAGE", "NICOLAS CAGE"),
        ("EN - Forrest Gump (1994) TOM HANKS", "TOM HANKS"),
        ("Title 4K (1996) HARVEY KEITEL, TARANTINO", "HARVEY KEITEL, TARANTINO"),
    ])
    def test_provider_appended_credits_survive(self, name, expected):
        assert parse_channel_name(name).trailing == expected

    def test_the_title_is_still_clean(self):
        """Capturing must not change what gets stored as the title."""
        parsed = parse_channel_name("EN - Adaptation. 4K (2002) NICOLAS CAGE")
        assert parsed.bare_name == "Adaptation."
        assert parsed.year == "2002"
        assert parsed.quality[:1] == ["4K"]


class TestNoFalsePositives:
    """The guards that made step 1b safe must keep holding."""

    def test_a_real_subtitle_is_not_credits(self):
        """Mixed-case trailing text is part of the title, not metadata junk."""
        parsed = parse_channel_name("FBI (2024) Reboot")
        assert parsed.trailing == ""
        assert "Reboot" in parsed.bare_name

    @pytest.mark.parametrize("name", [
        "Hanna (2019) (US)",            # a parenthetical qualifier
        "Title (2022) (ENG DUB)",       # an audio qualifier
    ])
    def test_qualifiers_are_not_credits(self, name):
        assert parse_channel_name(name).trailing == ""

    def test_a_plain_title_has_no_trailing(self):
        assert parse_channel_name("EN - Ballerina 4K (2025)").trailing == ""

    def test_no_year_means_no_capture(self):
        """The span is only identifiable RELATIVE to a year — without one there
        is nothing to distinguish credits from the title itself."""
        assert parse_channel_name("Adaptation. NICOLAS CAGE").trailing == ""
