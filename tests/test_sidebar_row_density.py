"""Sidebar rows: compact by default, comfortable by choice, icons never words.

The owner, on the two-line row that shipped in #457:

    "I don't like the 2 line watch queue as designed. it could be a second
     option that could be set in settings -> interface. However, I do like the
     previous design with the colored chips and single line and years with an
     outline. it was much cleaner. and simplier and more entries were visible."

    "the whole point of the movie, series, live icons reduce the need for all
     this busy and repetitive text. So rather than using the words, use the
     icons."

Both halves are asserted here, because both were regressions a green suite
missed: the row shape is a preference with compact as the default, and the
media type is a GLYPH — a row that spells out "Series · " on every line is
repetition the icon column already handled, paid for in the width the title
needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.gui import theme as _theme
from metatv.gui.chip_row import (
    CHIP_LANG,
    CHIP_QUALITY,
    CHIP_YEAR,
    DENSITY_COMFORTABLE,
    DENSITY_COMPACT,
    build_chip_row,
    media_icon_role,
    row_meta_label,
    row_title_label,
)

_CHIPS = ((CHIP_QUALITY, "4K"), (CHIP_YEAR, "1985"), (CHIP_LANG, "EN"))


def _row(**over):
    base = dict(
        title="Rambo 2 First Blood Part II",
        icon_role="movie",
        chips=_CHIPS,
        meta="1985 · EN · 4K",
        density=DENSITY_COMPACT,
    )
    base.update(over)
    return build_chip_row(**base)


def _all_text(row) -> list[str]:
    return [
        w.text()
        for w in row.findChildren(QLabel) + row.findChildren(QPushButton)
        if w.text()
    ]


# ── The correction: a glyph, not a word ──────────────────────────────────────

@pytest.mark.parametrize("density", [DENSITY_COMPACT, DENSITY_COMFORTABLE])
@pytest.mark.parametrize("media_type", ["movie", "series", "live"])
def test_the_media_type_is_never_spelled_out(qtbot, density, media_type):
    """The words are the regression. "Movie · " on every row is what the icon
    column exists to prevent, and it costs the width the title needed."""
    row = _row(icon_role=media_icon_role(media_type), density=density)
    qtbot.addWidget(row)
    joined = " ".join(_all_text(row))
    for word in ("Movie", "Series", "Live"):
        assert word not in joined, (
            f"{density}/{media_type}: the row spells out {word!r} — "
            f"that is what the icon is for: {joined!r}"
        )


@pytest.mark.parametrize("media_type,expected", [
    ("movie", "movie"), ("series", "series"), ("live", "live"),
    ("unknown", ""), ("", ""), (None, ""),
])
def test_media_icon_role_maps_types_and_refuses_the_rest(media_type, expected):
    """An unknown type draws NO glyph — it loses its icon, never its row."""
    assert media_icon_role(media_type) == expected


def test_the_icon_actually_paints_a_glyph(qtbot):
    """A role that resolves to nothing would leave a silent blank column."""
    row = _row()
    qtbot.addWidget(row)
    pixmaps = [
        w.pixmap() for w in row.findChildren(QLabel)
        if w.pixmap() is not None and not w.pixmap().isNull()
    ]
    assert pixmaps, "no row icon was painted"
    assert pixmaps[0].width() > 4, "the icon resolved to an empty pixmap"


def test_a_row_with_no_icon_role_still_renders(qtbot):
    row = _row(icon_role="")
    qtbot.addWidget(row)
    assert row_title_label(row).text() == "Rambo 2 First Blood Part II"


# ── The two shapes ───────────────────────────────────────────────────────────

def test_compact_draws_chips_and_no_second_line(qtbot):
    row = _row(density=DENSITY_COMPACT)
    qtbot.addWidget(row)
    texts = _all_text(row)
    assert "4K" in texts and "1985" in texts and "EN" in texts, texts
    assert row_meta_label(row) is None, "compact grew a second line"


def test_comfortable_draws_a_second_line_and_no_chips(qtbot):
    row = _row(density=DENSITY_COMFORTABLE)
    qtbot.addWidget(row)
    assert row_meta_label(row) is not None
    assert row_meta_label(row).text() == "1985 · EN · 4K"
    assert not row.findChildren(QPushButton), "chips survived into comfortable"
    texts = _all_text(row)
    assert "1985" not in texts or texts.count("1985") == 0, (
        f"a year chip is drawn alongside the meta line that already says it: {texts}"
    )


def test_compact_fits_more_entries_in_the_same_space(qtbot):
    """"more entries were visible" — the owner's actual reason, measured as rows.

    Asserted as entries-per-allocation rather than a pixel ratio: the ratio is
    an assumption (my first version guessed 1.5x and was wrong — chips are
    taller than the title, so a compact row is ~27px, not the ~20px a bare one
    is), while "how many rows do I get" is the thing being chosen between.
    """
    ALLOCATION = 200  # a typical expanded section, per the V3 render's own figures
    compact = _row(density=DENSITY_COMPACT).sizeHint().height()
    comfy = _row(density=DENSITY_COMFORTABLE).sizeHint().height()

    compact_rows = ALLOCATION // compact
    comfy_rows = ALLOCATION // comfy
    assert compact_rows > comfy_rows, (
        f"compact fits {compact_rows} rows in {ALLOCATION}px and comfortable "
        f"fits {comfy_rows} — the preference buys nothing ({compact}px vs {comfy}px)"
    )
    assert compact_rows - comfy_rows >= 2, (
        f"compact buys only {compact_rows - comfy_rows} extra row in "
        f"{ALLOCATION}px — not enough to be worth a setting"
    )


def test_an_unknown_density_falls_back_to_compact(qtbot):
    """A bad stored value costs the preference, never the sidebar."""
    row = build_chip_row(title="X", chips=_CHIPS, meta="m", density="nonsense")
    qtbot.addWidget(row)
    assert row_meta_label(row) is None
    assert "4K" in _all_text(row)


def test_an_empty_chip_draws_nothing(qtbot):
    row = _row(chips=((CHIP_QUALITY, ""), (CHIP_YEAR, "1985"), (CHIP_LANG, "")))
    qtbot.addWidget(row)
    chips = [b.text() for b in row.findChildren(QPushButton)]
    assert chips == ["1985"], (
        f"a chip with no value still drew a box: {chips}"
    )


def test_every_chip_is_the_same_widget_kind(qtbot):
    """One box model, so one padding.

    They were QLabel (year, language) and QPushButton (quality) on IDENTICAL
    declared padding and still looked different: a QLabel's border wraps the
    font's whole line box, a button's hugs content + padding. Owner: "quality
    chips on the sidebar have the right padding" / "seems crazy to manage two
    different paddings this way."
    """
    row = _row()
    qtbot.addWidget(row)
    chips = sorted(b.text() for b in row.findChildren(QPushButton))
    assert chips == ["1985", "4K", "EN"], f"not every chip is a button: {chips}"
    heights = {b.sizeHint().height() for b in row.findChildren(QPushButton)}
    assert len(heights) == 1, f"chips disagree about their height: {heights}"


def test_the_chips_keep_their_distinct_styles(qtbot):
    """Year outlined, language filled — "years with an outline" was the ask."""
    row = _row()
    qtbot.addWidget(row)
    year = next(w for w in row.findChildren(QPushButton) if w.text() == "1985")
    lang = next(w for w in row.findChildren(QPushButton) if w.text() == "EN")
    assert year.styleSheet() == _theme.SIDEBAR_CHIP_YEAR
    assert lang.styleSheet() == _theme.SIDEBAR_CHIP_LANG
    assert year.styleSheet() != lang.styleSheet()
    assert "border" in _theme.SIDEBAR_CHIP_YEAR, "the year chip lost its outline"
    # Its own family, sized for a 20px row — not the channel list's.
    assert year.styleSheet() != _theme.YEAR_CHIP, (
        "the sidebar is borrowing the channel list's chip, which is 15px type "
        "against a 13px title and inflates the row it sits in"
    )


def test_the_tail_rides_the_right_edge_in_compact_only(qtbot):
    compact = _row(tail="2h", density=DENSITY_COMPACT)
    qtbot.addWidget(compact)
    assert "2h" in _all_text(compact)

    comfy = _row(tail="2h", density=DENSITY_COMFORTABLE)
    qtbot.addWidget(comfy)
    assert "2h" not in _all_text(comfy), (
        "the terse tail is compact's substitute for the meta line, not an addition to it"
    )


# ── The sections spend their chips on what tells THEIR rows apart ────────────

def test_history_spends_its_chips_on_the_episode_and_the_age(qtbot, tmp_path):
    """Q2 option A. A language chip would say the same thing on every row of a
    personal history; when you watched it is what separates them."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.core.repositories.dtos import HistoryDTO
    from metatv.gui.sidebar.history import HistorySection
    from tests.conftest import sidebar_config

    obj = HistorySection.__new__(HistorySection)
    obj.history_list = QListWidget()
    obj.config = sidebar_config()
    obj.set_empty = lambda *_: None
    now = datetime.now()
    obj._populate_rows([
        HistoryDTO(id="1", name="It's Always Sunny", media_type="series",
                   episode_code="S18E01", last_played=now - timedelta(hours=2),
                   detected_title="It's Always Sunny", detected_prefix="EN"),
    ])

    row = obj.history_list.itemWidget(obj.history_list.item(0))
    texts = _all_text(row)
    assert "S18E01" in texts, texts
    assert "2h" in texts, f"history dropped the age it is ordered by: {texts}"
    assert "EN" not in texts, f"history spent a chip on a constant: {texts}"


def test_queue_shows_quality_year_and_language(qtbot):
    from PyQt6.QtWidgets import QListWidget
    from metatv.core.repositories.queue import QueueEntry
    from metatv.gui.sidebar.queue import WatchQueueSection
    from tests.conftest import sidebar_config, wire_watch_queue_filter

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = sidebar_config()
    obj._has_unavailable = False
    wire_watch_queue_filter(obj)
    obj._add_entry_item(QueueEntry(
        queue_id=1, channel_id="c1", channel_name="Rambo 2", media_type="movie",
        last_played=None, channel=None, search_title="Rambo 2",
        detected_year="1985", detected_prefix="EN", detected_quality="4K",
    ))

    row = obj._list.itemWidget(obj._list.item(0))
    texts = _all_text(row)
    for want in ("4K", "1985", "EN"):
        assert want in texts, f"{want} missing from a queue row: {texts}"


def test_a_series_queue_row_leads_with_its_episode_not_its_year(qtbot):
    from PyQt6.QtWidgets import QListWidget
    from metatv.core.repositories.queue import QueueEntry
    from metatv.gui.sidebar.queue import WatchQueueSection
    from tests.conftest import sidebar_config, wire_watch_queue_filter

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = sidebar_config()
    obj._has_unavailable = False
    wire_watch_queue_filter(obj)
    obj._add_entry_item(QueueEntry(
        queue_id=1, channel_id="c1", channel_name="Silicon Valley",
        media_type="series", last_played=None, channel=None,
        search_title="Silicon Valley", detected_year="2014",
        season_num=5, episode_num=3,
    ))

    texts = _all_text(obj._list.itemWidget(obj._list.item(0)))
    assert "S05E03" in texts, texts
    assert "2014" not in texts, (
        f"the episode is what tells this row from its siblings, not the year: {texts}"
    )


# ── The preference ───────────────────────────────────────────────────────────

def test_sections_read_the_density_from_config(qapp, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.sidebar.base import CollapsibleSection

    config = Config(config_dir=tmp_path)
    section = CollapsibleSection("History", "H", config)
    assert section._row_density() == DENSITY_COMPACT, "compact is the default"

    config.sidebar_row_density = DENSITY_COMFORTABLE
    assert section._row_density() == DENSITY_COMFORTABLE, "read fresh, not cached"

    config.sidebar_row_density = "garbage"
    assert section._row_density() == DENSITY_COMPACT


def test_compact_is_the_shipped_default():
    from metatv.core.config import Config
    assert Config().sidebar_row_density == DENSITY_COMPACT


def test_the_setting_round_trips_through_the_dialog(qapp):
    from PyQt6.QtWidgets import QComboBox
    from types import SimpleNamespace
    from metatv.gui.settings_dialog import _load_sidebar_density, _save_sidebar_density
    from metatv.gui.settings_dialog_tabs import _SIDEBAR_DENSITY_CHOICES

    combo = QComboBox()
    for label, value in _SIDEBAR_DENSITY_CHOICES:
        combo.addItem(label, value)

    cfg = SimpleNamespace(sidebar_row_density=DENSITY_COMFORTABLE)
    _load_sidebar_density(combo, cfg)
    assert combo.currentData() == DENSITY_COMFORTABLE

    combo.setCurrentIndex(combo.findData(DENSITY_COMPACT))
    _save_sidebar_density(combo, cfg)
    assert cfg.sidebar_row_density == DENSITY_COMPACT

    # An unknown stored value selects compact rather than leaving index -1.
    _load_sidebar_density(combo, SimpleNamespace(sidebar_row_density="nonsense"))
    assert combo.currentData() == DENSITY_COMPACT


def test_changing_the_setting_rebuilds_every_section(qapp):
    """A repaint cannot do this: the densities are different widget trees and
    every row's sizeHint moves with them."""
    from unittest.mock import MagicMock
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.sidebar_sections = {
        "history": MagicMock(), "queue": MagicMock(), "favorites": MagicMock(),
    }
    MainWindow._apply_sidebar_row_density(host)
    for name, section in host.sidebar_sections.items():
        section.refresh.assert_called_once_with(), f"{name} was not rebuilt"


# ── The glyphs themselves ────────────────────────────────────────────────────

def test_movie_and_series_do_not_draw_the_same_shape(qapp):
    """They did. `movie-open-outline` and `television-classic` are both small
    boxes at 13px and were near indistinguishable in a list — you could only
    tell them apart if you already knew which was which.

    Compares the PAINTED pixels, not the role names: two different mdi keys
    that happen to rasterise alike would pass a name check and fail a reader.
    """
    from metatv.gui import icon_utils as _icon_utils
    from metatv.gui import icons as _icons
    from metatv.gui.chip_row import ICON_PX

    shapes = {}
    for role in ("movie", "series", "live"):
        pixmap = _icon_utils.vector_pixmap(
            _icons.vector_key(role), _theme.COLOR_TEXT, ICON_PX
        )
        assert pixmap is not None and not pixmap.isNull(), f"{role} resolved to nothing"
        img = pixmap.toImage()
        shapes[role] = tuple(
            img.pixelColor(x, y).alpha() > 40
            for y in range(img.height()) for x in range(img.width())
        )

    assert shapes["movie"] != shapes["series"], (
        "movie and series rasterise to the same shape — the icon tells you "
        "nothing the row does not already say"
    )
    assert shapes["live"] != shapes["series"]
    assert shapes["live"] != shapes["movie"]

    differing = sum(a != b for a, b in zip(shapes["movie"], shapes["series"]))
    assert differing >= 12, (
        f"movie and series differ in only {differing} of "
        f"{len(shapes['movie'])} pixels — too close to read apart at {ICON_PX}px"
    )


def test_play_next_uses_the_skip_glyph_not_fast_forward(qapp):
    """">>" is the FAST-FORWARD glyph: it means "speed up", not "skip ahead"."""
    from types import SimpleNamespace
    from metatv.gui.sidebar.history import HistorySection

    obj = HistorySection.__new__(HistorySection)
    obj.playNextClicked = SimpleNamespace(emit=lambda *_: None)
    btn = HistorySection._build_play_next_button(
        obj, SimpleNamespace(next_episode_code="S01E18", next_episode_id="e1")
    )

    assert btn.text() == "", f"the button still renders text: {btn.text()!r}"
    assert not btn.icon().isNull(), "no glyph on the play-next button"
    assert "S01E18" in btn.toolTip(), "the tooltip must name the episode it plays"

    # Painted, not merely assigned: an icon that resolves to nothing leaves a
    # blank button that still passes every check above.
    img = btn.grab().toImage()
    lit = sum(
        1 for y in range(img.height()) for x in range(img.width())
        if img.pixelColor(x, y).lightness() > 90
    )
    assert lit > 20, f"the play-next glyph drew {lit} lit pixels — it is blank"
