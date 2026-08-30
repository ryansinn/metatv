"""The provider sent a trailer for 114,308 channels and nothing ever read it.

``metadata_from_raw`` looked at ``info.get('youtube_trailer')`` alone. That is
the NESTED spelling; Xtream VOD rows put it at the top level under ``trailer``,
and the two together are the difference between **46,148** rows resolving a
trailer and **114,308** — measured across the owner's whole library.

Even the 46,148 went nowhere: ``trailer_url`` was stored on ``MetadataDB`` and
rendered by **nothing**. The pane had no control for it at all.

Order in the action row was settled against the rendered mockup —
``Resume · Play · Trailer ▶ · Watch Later · 👍 🙅 👎`` — so the tests below pin
Trailer as the leftmost, fixed-width item on the secondary row, not merely as
"present somewhere".

No lightbox: QtWebEngine is not available in this app, so an embedded player was
never possible. Left-click plays through mpv (which resolves YouTube via
yt-dlp); right-click hands it to the browser, which is the recovery when mpv's
extractor is stale.
"""

import pytest

from metatv.metadata_providers.provider_metadata import metadata_from_raw
from metatv.metadata_providers.raw_parse import extract_trailer


# --------------------------------------------------------------------------
# Reading it out of the payload
# --------------------------------------------------------------------------

@pytest.mark.parametrize("info, expected", [
    # The shape the owner's providers actually send: a bare 11-char id at the
    # TOP level. 68,282 rows.
    ({"trailer": "AklEaZVdm3c"}, "https://www.youtube.com/watch?v=AklEaZVdm3c"),
    # The nested spelling, which was the ONLY one read.
    ({"youtube_trailer": "AklEaZVdm3c"},
     "https://www.youtube.com/watch?v=AklEaZVdm3c"),
    # A share link's tracking query, arriving without its host.
    ({"trailer": "qYU_1Q8uc4A?si=PCziQRV4T2sF6lYx"},
     "https://www.youtube.com/watch?v=qYU_1Q8uc4A"),
    # A relative watch path.
    ({"trailer": "watch?v=aYNwBsXWNVM"},
     "https://www.youtube.com/watch?v=aYNwBsXWNVM"),
    # Full URLs pass through untouched, whatever the host — the field means
    # "a trailer lives here", and dropping Dailymotion would lose a working link.
    ({"trailer": "https://youtu.be/c3dukvXxtsc"}, "https://youtu.be/c3dukvXxtsc"),
    ({"trailer": "https://dai.ly/x92o7oa"}, "https://dai.ly/x92o7oa"),
    # Nothing usable.
    ({}, None), ({"trailer": ""}, None), ({"trailer": "   "}, None),
    ({"trailer": "not-an-id"}, None), ({"trailer": 12345}, None),
    ({"trailer": None}, None),
])
def test_every_shape_resolves_to_a_playable_url(info, expected):
    assert extract_trailer(info) == expected


def test_the_nested_spelling_still_wins():
    """Precedence, so a provider sending both does not change behaviour."""
    assert extract_trailer({
        "youtube_trailer": "AklEaZVdm3c", "trailer": "ZZZZZZZZZZZ",
    }) == "https://www.youtube.com/watch?v=AklEaZVdm3c"


def test_the_top_level_key_reaches_the_ingestion_path():
    """The whole point: the key that carries 68,282 of them must land."""
    result = metadata_from_raw(
        {"name": "Some Film", "trailer": "AklEaZVdm3c"}, name="Some Film")
    assert result.trailer_url == "https://www.youtube.com/watch?v=AklEaZVdm3c"


def test_an_unrecognised_fragment_is_none_not_a_guess():
    """A URL built from junk would be a button that always fails."""
    assert metadata_from_raw(
        {"name": "X", "trailer": "n/a"}, name="X").trailer_url is None


# --------------------------------------------------------------------------
# The button
# --------------------------------------------------------------------------

def _bar(qapp):
    from metatv.core.config import Config
    from metatv.gui.details_actions import _ActionBar
    return _ActionBar(Config())


def test_the_button_is_hidden_until_there_is_a_trailer(qapp):
    """A dead button on 670,000 channels is worse than no button."""
    bar = _bar(qapp)
    assert bar.trailer_button.isHidden()
    bar.set_trailer(True)
    assert not bar.trailer_button.isHidden()
    bar.set_trailer(False)
    assert bar.trailer_button.isHidden()


def test_clear_forgets_the_previous_title(qapp):
    """Between channels the button must not survive into a title with none."""
    bar = _bar(qapp)
    bar.set_trailer(True)
    bar.clear()
    assert bar.trailer_button.isHidden()


def test_the_label_reads_trailer_with_a_play_glyph(qapp):
    """"Trailer ▶" — the noun, then the verb applied to it."""
    bar = _bar(qapp)
    assert bar.trailer_button.text().startswith("Trailer")
    assert "▶" in bar.trailer_button.text()
    assert bar.trailer_button.toolTip(), "every clickable control needs a tooltip"


def test_the_button_offers_a_pointing_cursor(qapp):
    from PyQt6.QtCore import Qt
    bar = _bar(qapp)
    assert bar.trailer_button.cursor().shape() == Qt.CursorShape.PointingHandCursor


def test_left_click_and_the_menu_emit_different_signals(qapp):
    """Two entries because they fail differently: mpv's extractor can go stale,
    the browser always works."""
    from PyQt6.QtWidgets import QMenu

    bar = _bar(qapp)
    seen = []
    bar.trailer_clicked.connect(lambda: seen.append("play"))
    bar.trailer_youtube_clicked.connect(lambda: seen.append("youtube"))

    bar.trailer_button.click()
    assert seen == ["play"]

    # Build the menu the way _show_trailer_menu does and fire both entries,
    # without exec()ing a modal that would block the test.
    menu = QMenu(bar.trailer_button)
    menu.addAction("Play trailer").triggered.connect(bar.trailer_clicked)
    menu.addAction("Play trailer on YouTube").triggered.connect(
        bar.trailer_youtube_clicked)
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Play trailer", "Play trailer on YouTube"]
    for action in menu.actions():
        action.trigger()
    assert seen == ["play", "play", "youtube"]


def test_the_menu_is_wired_to_a_custom_context_menu(qapp):
    """Right-click must reach _show_trailer_menu, not Qt's default (nothing)."""
    from PyQt6.QtCore import Qt

    bar = _bar(qapp)
    assert (bar.trailer_button.contextMenuPolicy()
            == Qt.ContextMenuPolicy.CustomContextMenu)


# --------------------------------------------------------------------------
# Rendered appearance — geometry, not membership
# --------------------------------------------------------------------------

def test_the_button_is_painted_leftmost_on_the_secondary_row(qapp):
    """Order is a claim about PIXELS, and membership tests pass for any order.

    Settled against the rendered mockup: Resume · Play · Trailer ▶ · Watch
    Later · 👍 🙅 👎. Asserted on laid-out geometry so a row that merely
    CONTAINS the button in the wrong place fails.
    """
    from unittest.mock import MagicMock

    from metatv.core.config import Config
    from metatv.gui.details_sections import _PosterSection
    from tests.conftest import wire_details_action_buttons

    cfg = Config()
    poster = _PosterSection(cfg, MagicMock())
    bar = _bar(qapp)
    wire_details_action_buttons(poster, bar)
    # VOD mode, or the judgment trio stays hidden at (0, 0) and every
    # comparison against it is meaningless — a geometry test that passes on
    # unlaid-out widgets is the fake-coverage case this file exists to avoid.
    bar.set_mode(is_live=False)
    bar.set_trailer(True)
    poster._secondary_action_row.resize(400, 40)
    poster._secondary_action_row.show()
    qapp.processEvents()

    for name, btn in (("trailer", bar.trailer_button), ("queue", bar.queue_button),
                      ("like", bar.like_button)):
        assert not btn.isHidden(), f"{name} must be visible for this to mean anything"

    trailer = bar.trailer_button.geometry()
    queue = bar.queue_button.geometry()
    like = bar.like_button.geometry()

    assert trailer.left() < queue.left(), (
        f"Trailer must be painted LEFT of Watch Later; "
        f"trailer.x={trailer.left()} queue.x={queue.left()}")
    assert queue.right() <= like.left(), (
        "Watch Later must end before the judgment cluster begins")
    assert trailer.width() > 0 and trailer.height() > 0, (
        "the button must occupy real space, not a zero rect")
    # Fixed width: it must not have absorbed the row's slack.
    assert trailer.width() < queue.width(), (
        f"Trailer is fixed-width and Watch Later takes the slack; "
        f"trailer={trailer.width()} queue={queue.width()}")


def test_the_row_does_not_grow_the_pane_minimum(qapp):
    """docs/DETAILS_PANE_DESIGN.md → "Width discipline".

    A QHBoxLayout's minimum is the SUM of its children's minimums, so a
    fixed-width button added to this row raises the floor for the whole pane —
    which is the recurring details-pane bug. 300px is the pane's minimum.
    """
    from unittest.mock import MagicMock

    from metatv.core.config import Config
    from metatv.gui.details_sections import _PosterSection
    from tests.conftest import wire_details_action_buttons

    poster = _PosterSection(Config(), MagicMock())
    bar = _bar(qapp)
    wire_details_action_buttons(poster, bar)
    bar.set_trailer(True)
    qapp.processEvents()

    floor = poster._secondary_action_row.minimumSizeHint().width()
    assert floor < 300, (
        f"the secondary row's minimum is {floor}px, at or over the pane's "
        "300px floor — every other section would clip off the right edge")


# --------------------------------------------------------------------------
# The stale-URL bug the reset exists for
# --------------------------------------------------------------------------

def _pane(qapp):
    from unittest.mock import MagicMock

    from metatv.core.config import Config
    from metatv.gui.details_pane import DetailsPaneWidget
    return DetailsPaneWidget(Config(), MagicMock(), db=None)


def _channel(name="A Film"):
    """A detached ChannelDB, not a hand-rolled stub.

    An ad-hoc object with the four attributes I happened to think of died on
    ``raw_data`` the first time the pane touched it, which is CLAUDE.md's
    skeleton-double trap. A real ORM instance answers None for every column it
    was not given, so a column added tomorrow is covered the day it is added.
    """
    from metatv.core.database import ChannelDB

    return ChannelDB(id="c1", source_id="1", provider_id="p", name=name,
                     media_type="movie", detected_title=name)


def test_a_channel_with_no_metadata_does_not_inherit_the_last_trailer(qapp):
    """The bug the per-channel reset exists for.

    ``_apply_metadata`` only runs when a channel HAS metadata. Without an
    unconditional reset in ``show_channel``, the pane keeps the previous
    title's URL and the Trailer button plays the wrong film — silently, and
    only for the channels that happen to have no metadata yet.
    """
    from metatv.metadata_providers.base import MetadataResult

    pane = _pane(qapp)
    pane.show_channel(_channel("With Trailer"), MetadataResult(
        title="With Trailer",
        trailer_url="https://www.youtube.com/watch?v=AklEaZVdm3c"))
    assert pane._trailer_url.endswith("AklEaZVdm3c")
    assert not pane._action_bar.trailer_button.isHidden()

    pane.show_channel(_channel("No Metadata"), None)
    assert pane._trailer_url == "", (
        "the pane kept the previous title's trailer — the button would play "
        "the wrong film")
    assert pane._action_bar.trailer_button.isHidden()


def test_a_title_whose_metadata_has_no_trailer_hides_the_button(qapp):
    """Metadata present, trailer absent — the other half of the same reset."""
    from metatv.metadata_providers.base import MetadataResult

    pane = _pane(qapp)
    pane.show_channel(_channel("With Trailer"), MetadataResult(
        title="With Trailer",
        trailer_url="https://www.youtube.com/watch?v=AklEaZVdm3c"))
    pane.show_channel(_channel("No Trailer"),
                      MetadataResult(title="No Trailer", trailer_url=None))
    assert pane._trailer_url == ""
    assert pane._action_bar.trailer_button.isHidden()


def test_the_pane_emits_the_url_and_a_titled_window_name(qapp):
    """The host needs both: the URL to play and something to title the window."""
    from metatv.metadata_providers.base import MetadataResult

    pane = _pane(qapp)
    seen = []
    pane.trailer_requested.connect(lambda u, t: seen.append(("play", u, t)))
    pane.trailer_youtube_requested.connect(lambda u: seen.append(("web", u)))

    pane.show_channel(_channel("Dune"), MetadataResult(
        title="Dune", trailer_url="https://www.youtube.com/watch?v=AklEaZVdm3c"))
    pane._action_bar.trailer_clicked.emit()
    pane._action_bar.trailer_youtube_clicked.emit()

    assert seen[0] == ("play", "https://www.youtube.com/watch?v=AklEaZVdm3c",
                       "Dune — Trailer")
    assert seen[1] == ("web", "https://www.youtube.com/watch?v=AklEaZVdm3c")


def test_no_signal_fires_when_there_is_no_trailer(qapp):
    """A stray click must not emit an empty URL for the host to try to play."""
    pane = _pane(qapp)
    seen = []
    pane.trailer_requested.connect(lambda u, t: seen.append(u))
    pane.trailer_youtube_requested.connect(lambda u: seen.append(u))
    pane.show_channel(_channel("No Metadata"), None)
    pane._action_bar.trailer_clicked.emit()
    pane._action_bar.trailer_youtube_clicked.emit()
    assert seen == []
