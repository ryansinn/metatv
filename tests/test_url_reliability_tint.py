"""A source's URL rows are tinted by how well the address actually works.

Owner: "maybe to a very light tint of color coding based on the reliability".

Two things this must get right, and both are easy to get wrong:

* it must tint on the score the list is SORTED by. ``ordered_urls`` ranks on
  ``health_score`` (recency-weighted); ``reliability_score`` is a lifetime
  ratio. They disagree the moment a long-good host starts failing, and tinting
  on the wrong one puts a green row at the bottom of the list.
* an UNTESTED address must not read as good. ``reliability_score`` returns
  100.0 for one — "untested, assume good" — and ``health_score`` falls back to
  it, so tinting on the number alone paints an address nobody has ever reached
  in confident green.
"""

import pytest

from metatv.core.models import ConnectionAttempt, ProviderURL
from metatv.core.url_policy import get_url_ranking_policy
from metatv.gui.url_row_widget import URLRowWidget, reliability_tint_token


def _url(attempts: "list[bool]") -> ProviderURL:
    """A ProviderURL with *attempts* recorded oldest-first."""
    pu = ProviderURL(url="http://host")
    for ok in attempts:
        pu.add_attempt(ConnectionAttempt(success=ok))
        if ok:
            pu.success_count += 1
        else:
            pu.failure_count += 1
    return pu


# ── the honest cases ────────────────────────────────────────────────────────

def test_an_untested_url_is_not_tinted() -> None:
    """THE trap. reliability_score says 100.0 for an address nobody has tried.

    Tinting it green would assert something the app does not know, on the one
    screen where the user is deciding which addresses to keep.
    """
    assert reliability_tint_token(_url([])) is None


def test_a_consistently_working_url_reads_healthy() -> None:
    assert reliability_tint_token(_url([True] * 20)) == "OVERLAY_GREEN_15"


def test_a_consistently_failing_url_reads_failing() -> None:
    assert reliability_tint_token(_url([False] * 15)) == "OVERLAY_ERR_15"


def test_an_old_failure_fades_rather_than_branding_the_host() -> None:
    """The whole point of a recency-weighted score.

    One blip fifteen successes ago says nothing about the host now, and a
    permanent amber row would train the user to ignore the tint.
    """
    assert reliability_tint_token(_url([False] + [True] * 15)) == "OVERLAY_GREEN_15"


def test_a_fresh_failure_is_visible_immediately() -> None:
    """The mirror: a failure just now must show, even on a long-good host."""
    assert reliability_tint_token(_url([True] * 15 + [False])) != "OVERLAY_GREEN_15"


def test_a_recovering_host_is_not_still_branded_as_failing() -> None:
    """Six good runs after a bad patch is progress, and should look like it."""
    assert reliability_tint_token(_url([False] * 10 + [True] * 6)) == "OVERLAY_ORANGE_10"


# ── it must agree with the ordering the user sees ───────────────────────────

def test_the_tint_follows_health_not_the_lifetime_ratio() -> None:
    """A host with a great lifetime record that is failing RIGHT NOW.

    ``reliability_score`` is 90% here — healthy by any lifetime reading — while
    ``health_score`` has collapsed. ``ordered_urls`` sorts on the latter, so a
    tint driven by the former would paint the bottom-ranked row green.
    """
    pu = _url([True] * 18 + [False] * 2)

    assert pu.reliability_score >= 85, "fixture no longer has a good lifetime record"
    assert pu.health_score(get_url_ranking_policy().health_decay) < 0.9
    assert reliability_tint_token(pu) != "OVERLAY_GREEN_15", (
        "the tint is reading the lifetime ratio, which the list does not sort by"
    )


# ── it is reinforcement, never the only signal ──────────────────────────────

def test_the_row_still_states_the_number_in_text(qtbot) -> None:
    """CLAUDE.md: never encode state by colour alone.

    The tint is allowed precisely because the row already SAYS "87% reliability";
    if that text ever went away the tint would become the only signal.
    """
    row = URLRowWidget(_url([True] * 9 + [False]), 0, 1)
    qtbot.addWidget(row)
    assert "reliability" in row._stats_label.text()


def test_an_untested_row_says_so_in_text_and_has_no_tint(qtbot) -> None:
    row = URLRowWidget(_url([]), 0, 1)
    qtbot.addWidget(row)
    assert row._stats_label.text() == "Untested"
    assert not row.styleSheet(), "an untested row was tinted"


@pytest.mark.parametrize("attempts,expected_tinted", [
    ([], False),
    ([True] * 20, True),
    ([False] * 20, True),
])
def test_the_tint_is_actually_applied_to_the_widget(qtbot, attempts, expected_tinted) -> None:
    """Drives the real widget — a role nobody applies is not a feature."""
    row = URLRowWidget(_url(attempts), 0, 1)
    qtbot.addWidget(row)
    assert bool(row.styleSheet()) is expected_tinted


def test_every_tint_token_exists_in_the_theme() -> None:
    """Derived from what the helper can return, so a new band cannot ship
    pointing at a token that was never defined — in ANY palette."""
    from metatv.gui import theme

    roles = {
        reliability_tint_token(_url(a))
        for a in ([True] * 20, [True] * 15 + [False], [False] * 15)
    }
    assert None not in roles
    for role in roles:
        assert getattr(theme, role, None), f"{role} is not defined in theme"

    # And in every palette, not just the active one (CLAUDE.md: a new palette
    # key goes in all three).
    from metatv.gui import theme_palettes

    for palette_name in theme_palettes.PALETTES:
        values = theme_palettes.PALETTES[palette_name]
        for role in roles:
            assert role in values, f"{role} missing from the {palette_name} palette"
