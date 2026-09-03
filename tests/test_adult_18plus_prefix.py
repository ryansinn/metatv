"""'18+' is an age-rating prefix, not a quality tier — the parser never learned it.

Owner report 2026-09-03: exactly 466 rows shaped ``18+ - Title (Year) …`` (e.g.
``18+ - Sex With The Stars (1981)``, category "RATED R"), every one with
``is_adult=0``, ``detected_restricted=0``, and an EMPTY ``detected_prefix`` — the
leading digit fell outside ``_SEPARATOR_RE``'s ``[A-Z]``-only grammar, so the
parser never even tried to classify it. It is the only age-style leading prefix
in the corpus (a scan for other NN+ leaders found none), so the fix is a single
literal: ``_DIGIT_QUALITY_PREFIX_RE`` admits "18+" alongside 4K/8K and step 7 of
``parse_channel_name`` routes it to ``region`` (never ``quality[]``);
``BASE_PREFIX_GROUPS["Adult"]`` gained the code so ``is_restricted()`` matches it
the same way it already matches PORNBOX/X/XXX/ADULT.
"""

from __future__ import annotations

from metatv.core.channel_name_utils import is_restricted, parse_channel_name
from metatv.core.config import BASE_PREFIX_GROUPS
from tests.conftest import make_channel


def test_18plus_prefix_is_parsed_and_title_is_clean():
    parsed = parse_channel_name("18+ - Sex With The Stars (1981)")
    assert parsed.region == "18+"
    assert parsed.bare_name == "Sex With The Stars"
    assert parsed.year == "1981"


def test_18plus_prefix_with_double_space_after_dash():
    """Some rows carry a double space after the dash — the owner's exact string."""
    parsed = parse_channel_name("18+ -  69 (2025) (TAGALOG ENG-SUB)")
    assert parsed.region == "18+"
    assert parsed.bare_name == "69"


def test_18plus_does_not_regress_4k_8k_digit_quality_prefixes():
    """The literal admission must not swallow the sibling digit-quality tokens."""
    four_k = parse_channel_name("4K - Some Movie")
    assert four_k.quality == ["4K"]
    assert four_k.region == ""
    eight_k = parse_channel_name("8K ★ Another Movie")
    assert eight_k.quality == ["8K"]
    assert eight_k.region == ""


def test_18plus_joins_the_adult_prefix_group():
    assert "18+" in BASE_PREFIX_GROUPS["Adult"]


def test_is_restricted_true_for_18plus_prefix_under_base_groups():
    """Mutation-check (2026-09-03): drop '18+' from ``BASE_PREFIX_GROUPS["Adult"]``
    and this assertion goes RED — confirmed by hand, then restored.
    """
    assert is_restricted("18+", "18+ - Sex With The Stars (1981)") is True


def test_18plus_ingests_to_detected_prefix_and_restricted(db_session, repo):
    """End-to-end through the real ingestion chokepoint, the owner's exact string."""
    ch = make_channel(
        db_session,
        "18+ -  69 (2025) (TAGALOG ENG-SUB)",
        category="RATED R",
    )
    db_session.commit()
    repo.update_detected_prefixes()
    db_session.refresh(ch)
    assert ch.detected_prefix == "18+"
    assert bool(ch.detected_restricted) is True
    assert ch.detected_title == "69"


def test_prefix_rescan_version_covers_the_18plus_fix():
    """The rescan bump is what reaches the 466 rows already ingested before the fix."""
    from metatv.core.migrations.prefix_rescan import CURRENT_PREFIX_SCAN_VERSION

    assert CURRENT_PREFIX_SCAN_VERSION >= 6
