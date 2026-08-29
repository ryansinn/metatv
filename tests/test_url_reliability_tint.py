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


# ── the tint must agree with the number printed beside it ──────────────────

def _url_counts(ok: int, bad: int) -> ProviderURL:
    pu = ProviderURL(url="http://host")
    pu.success_count, pu.failure_count = ok, bad
    return pu


def test_a_good_address_and_a_dead_one_do_not_look_the_same() -> None:
    """THE bug, from the owner's screenshot.

    Six addresses on a disabled source: every one had failed recently, so
    ``health_score`` was 0.00 across the board while the printed figures ranged
    0% to 86% — and an 86% row was tinted exactly like a 0% row. Owner: "86%
    and 68% should not have the same as 0% and 1%".
    """
    good = reliability_tint_token(_url_counts(6714, 1108))   # 86%
    dead = reliability_tint_token(_url_counts(1, 1115))      # 0%
    assert good != dead, "an 86% address is tinted the same as a 0% one"


@pytest.mark.parametrize("ok,bad,expected", [
    (6714, 1108, "OVERLAY_GREEN_15"),    # 86%
    (2355, 1117, "OVERLAY_ORANGE_10"),   # 68%
    (7,    1112, "OVERLAY_ERR_15"),      # 1%
    (1,    1115, "OVERLAY_ERR_15"),      # 0%
])
def test_the_tint_follows_the_printed_percentage(ok, bad, expected) -> None:
    """The exact rows from the owner's screenshot."""
    assert reliability_tint_token(_url_counts(ok, bad)) == expected


def test_an_untested_url_is_not_tinted() -> None:
    """``reliability_score`` says 100.0 for an address nobody has tried.

    Tinting it green would assert something the app does not know, on the one
    screen where the user is deciding which addresses to keep.
    """
    assert reliability_tint_token(_url_counts(0, 0)) is None


def test_the_tint_reads_the_same_number_the_row_prints(qtbot) -> None:
    """The invariant the first version broke.

    A colour that disagrees with the figure next to it is worse than no colour
    at all — the screen contradicts itself and neither reading can be trusted.
    """
    pu = _url_counts(6714, 1108)
    row = URLRowWidget(pu, 0, 1)
    qtbot.addWidget(row)

    printed = row._stats_label.text()
    assert "86% reliability" in printed, printed
    assert reliability_tint_token(pu) == "OVERLAY_GREEN_15", (
        f"the row prints {printed!r} and the tint disagrees"
    )


# ── the tint belongs on the fields, not the whole row ───────────────────────

def test_only_the_url_and_stats_are_tinted(qtbot) -> None:
    """Owner: "both lines don't need to be tinted either. just the url and #".

    Tinting the row washed colour behind the reorder arrows, the #N badge and
    the remove button — controls whose look has nothing to do with how well the
    address works.
    """
    row = URLRowWidget(_url_counts(1, 1115), 0, 1)
    qtbot.addWidget(row)

    assert not row.styleSheet(), "the whole row is still tinted"
    assert row._info_widget.styleSheet(), "the url/stats block carries no tint"


def test_an_untested_row_tints_nothing_at_all(qtbot) -> None:
    row = URLRowWidget(_url_counts(0, 0), 0, 1)
    qtbot.addWidget(row)
    assert not row.styleSheet()
    assert not row._info_widget.styleSheet()
    assert row._stats_label.text() == "Untested"


def test_every_tint_token_exists_in_every_palette() -> None:
    """A band cannot ship pointing at a token some palette lacks."""
    from metatv.gui import theme, theme_palettes

    tokens = {
        reliability_tint_token(_url_counts(*c))
        for c in ((10, 0), (7, 3), (0, 10))
    }
    assert None not in tokens
    for token in tokens:
        assert getattr(theme, token, None), f"{token} missing from theme"
        for name, values in theme_palettes.PALETTES.items():
            assert token in values, f"{token} missing from the {name} palette"
