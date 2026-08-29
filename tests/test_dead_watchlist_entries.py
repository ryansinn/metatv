"""A pinned channel that can never fire must say so.

The owner had two channels pinned to Watch Alerts. Both were structurally
incapable of ever producing an alert:

* ``RO| KISS TV`` — its provider row no longer exists at all;
* ``US| AMC PLUS`` — on TREX, a source they had switched off.

Both rendered "No EPG data", which is also what a perfectly healthy channel
shows when the guide simply has not covered it yet. So the panel presented a
permanently-dead pin and a momentarily-quiet one identically, and the six
patterns alongside them were working fine — nothing suggested anything was
wrong.

The distinction is not cosmetic: one resolves itself when the guide refreshes
and the other never does.
"""

import pytest
from PyQt6.QtWidgets import QLabel

from metatv.gui.epg_channel_card import _STATE_MESSAGE, build_pinned_channel_card


class _View:
    """The handful of attributes the card reads."""

    class config:
        series_icon = "S"
        play_icon = "P"
        close_icon = "X"

    _channel_quality_map: dict = {}
    _channel_region_map: dict = {}
    _channel_audio_map: dict = {}
    _channel_prefix_map: dict = {}
    _channel_title_map: dict = {}
    _channel_year_map: dict = {}

    def _emit_channel_selected(self, *a): pass
    def _play_channel(self, *a): pass
    def _unwatch_channel(self, *a): pass
    def show_epg_channel_menu(self, *a): pass


def _status_label(card) -> QLabel:
    known = {msg for msg, _advice in _STATE_MESSAGE.values()}
    for lbl in card.findChildren(QLabel):
        if lbl.text().strip() in known:
            return lbl
    raise AssertionError(
        f"no status line on the card; labels were "
        f"{[l.text() for l in card.findChildren(QLabel)]}"
    )


# ── the reported defect ─────────────────────────────────────────────────────

@pytest.mark.parametrize("state", ["source_off", "gone"])
def test_a_dead_pin_does_not_read_as_merely_missing_guide_data(qtbot, state: str) -> None:
    """THE assertion. Pre-fix both of these said "No EPG data"."""
    card = build_pinned_channel_card(_View(), "c1", "Chan", None, state)
    qtbot.addWidget(card)

    text = _status_label(card).text()
    assert "No EPG data" not in text, (
        f"a permanently dead pin ({state}) is still described as missing guide data"
    )
    assert "cannot fire" in text or "no longer exists" in text, text


def test_a_healthy_channel_without_a_programme_is_unchanged(qtbot) -> None:
    """The transient case must NOT be escalated into a warning.

    Crying wolf here would be worse than the original bug: every channel the
    guide has not reached yet would look broken.
    """
    card = build_pinned_channel_card(_View(), "c1", "Chan", None, "ok")
    qtbot.addWidget(card)

    assert _status_label(card).text().strip() == "No EPG data"
    assert not _status_label(card).toolTip()


def test_an_unknown_state_falls_back_to_the_neutral_message(qtbot) -> None:
    """A future state must not render a blank line or crash the panel."""
    card = build_pinned_channel_card(_View(), "c1", "Chan", None, "something_new")
    qtbot.addWidget(card)
    assert _status_label(card).text().strip() == "No EPG data"


# ── it must not signal by colour alone ──────────────────────────────────────

def test_the_warning_is_in_the_words_not_only_the_colour(qtbot) -> None:
    """CLAUDE.md: never encode state by colour alone.

    The card does turn the line amber, but the sentence itself has to carry
    the meaning for anyone who cannot see that.
    """
    for state in ("source_off", "gone"):
        card = build_pinned_channel_card(_View(), "c1", "Chan", None, state)
        qtbot.addWidget(card)
        text = _status_label(card).text().lower()
        assert "source" in text, f"{state} does not name the cause in words: {text!r}"


def test_each_dead_state_offers_advice_that_fits_it(qtbot) -> None:
    """"Re-enable the source" is nonsense for a provider that is gone.

    The first draft used one tooltip for both, which told the owner to switch
    a deleted source back on.
    """
    off = build_pinned_channel_card(_View(), "c1", "Chan", None, "source_off")
    gone = build_pinned_channel_card(_View(), "c1", "Chan", None, "gone")
    qtbot.addWidget(off)
    qtbot.addWidget(gone)

    off_tip = _status_label(off).toolTip()
    gone_tip = _status_label(gone).toolTip()

    assert off_tip and gone_tip, "a dead pin must say what to do about it"
    assert off_tip != gone_tip, "the two dead states share advice that cannot fit both"
    assert "back on" in off_tip, off_tip
    assert "Nothing can restore" in gone_tip, gone_tip


# ── the state must be derived from the canonical gate ───────────────────────

def test_the_state_is_computed_from_get_hidden_provider_ids() -> None:
    """Never an ad-hoc "is it inactive" check.

    ``get_hidden_provider_ids()`` is inactive ∪ expired ∪ orphaned, and
    CLAUDE.md forbids rebuilding that set per call site — a hand-rolled
    ``is_active == False`` here would miss expired sources and the orphaned
    provider the owner actually had.
    """
    import inspect

    from metatv.gui import epg_watchlist_mixin

    src = inspect.getsource(epg_watchlist_mixin._EpgWatchlistMixin._fetch_watchlist)
    assert "channel_state" in src, "the fetch does not compute a per-channel state"
    assert "excluded_ch_provider_ids" in src, (
        "the state is not derived from the canonical hidden-provider set"
    )
    assert "is_active" not in src, (
        "an ad-hoc activity check would miss expired and orphaned providers"
    )
