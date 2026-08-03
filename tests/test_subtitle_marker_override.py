"""An "<CODE>-SUB" category marker means SUBTITLES, not spoken language (#282).

Owner: "|AR| The Lobster" under "|AR-SUB| AMAZON PRIME" was tagged
``language: Arabic``. The Lobster is an English-language film; owner confirmed
"AR is in English, the subtitles are in Arabic".

Two feeders describing the same code disagreed and the vaguer one won. The name
prefix ``|AR|`` is ambiguous — it can mean Arabic audio OR an Arabic-subtitled
listing. The category marker ``AR-SUB`` is explicit. So an English film sat
under Arabic in the language filter and fed recommendations as Arabic content.

The override is deliberately narrow: only the language matching the marker's own
code is remapped, and only when the category actually carries a SUB marker. A
bare ``|AR|`` still means Arabic audio — the marker is the only thing that
licenses reinterpreting it.
"""

from __future__ import annotations

import pytest

from metatv.core.config import Config
from metatv.core.migrations.tag_backfill import _subtitle_language_from_marker


@pytest.fixture(scope="module")
def config():
    return Config()


class TestOverrideApplies:

    def test_the_owner_reported_case(self, config):
        assert _subtitle_language_from_marker(
            "|AR-SUB| AMAZON PRIME", "AR", config
        ) == "Arabic"

    def test_other_languages_too(self, config):
        assert _subtitle_language_from_marker(
            "|FR-SUB| CINEMA", "FR", config
        ) == "French"


class TestOverrideDoesNotApply:
    """Each of these would silently mislabel real content if it did."""

    def test_a_bare_prefix_still_means_audio(self, config):
        """No SUB marker — "|AR| MOVIES" really is Arabic-language content."""
        assert _subtitle_language_from_marker("|AR| MOVIES", "AR", config) is None

    def test_a_marker_for_a_DIFFERENT_code_is_ignored(self, config):
        """A French listing with Arabic subtitles keeps French as its language.

        Only the code the marker names is reinterpreted; remapping every
        language on the row would erase a real one.
        """
        assert _subtitle_language_from_marker(
            "|AR-SUB| AMAZON PRIME", "FR", config
        ) is None

    def test_a_DUB_marker_is_not_a_subtitle_marker(self, config):
        """"-DUB" means the audio WAS replaced — that is a language claim."""
        assert _subtitle_language_from_marker(
            "|AR-DUB| MOVIES", "AR", config
        ) is None

    @pytest.mark.parametrize("category,prefix", [
        ("", "AR"),
        (None, "AR"),
        ("|AR-SUB| AMAZON PRIME", ""),
        ("|AR-SUB| AMAZON PRIME", None),
    ])
    def test_missing_inputs_are_safe(self, category, prefix, config):
        assert _subtitle_language_from_marker(category, prefix, config) is None


def test_the_remap_is_wired_into_tag_collection():
    """Structural: the helper is useless if _collect_tags doesn't consult it."""
    import inspect

    from metatv.core.migrations import tag_backfill

    src = inspect.getsource(tag_backfill._collect_tags)
    assert "_subtitle_language_from_marker" in src
    assert '"subtitle"' in src, (
        "the matching language must be re-filed under the subtitle facet, not "
        "merely dropped — the information is real, it was just mis-typed"
    )
