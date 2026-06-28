"""Behavioral tests for details-pane polish fixes.

#98 — variant chip queue context-menu shows correct "Add/Remove from Queue" label
#101 — genre chips wrap via _FlowLayout rather than overflowing a single-line QLabel
e87956eb — comma-joined genre strings split into one chip each (no over-wide chip)
backlog — empty Overview / Cast & Crew sections hide themselves (no empty boxes)
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


# ── Fix #98: variant chip queue label ─────────────────────────────────────

def test_chip_status_suffix_includes_queue_icon_when_queued(qapp):
    """_chip_status_suffix must include the queue icon when v.in_queue is True."""
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    section = _VersionSection(_make_config())
    v = ChannelVersion(channel_id="c1", name="T", in_queue=True)
    suffix = section._chip_status_suffix(v)
    assert section.config.queue_icon in suffix


def test_chip_status_suffix_omits_queue_icon_when_not_queued(qapp):
    """_chip_status_suffix must NOT include the queue icon when v.in_queue is False."""
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    section = _VersionSection(_make_config())
    v = ChannelVersion(channel_id="c1", name="T", in_queue=False)
    suffix = section._chip_status_suffix(v)
    assert section.config.queue_icon not in suffix


def test_version_chip_menu_queue_action_label_and_optimistic_flip(qapp, monkeypatch):
    """Queue menu action text must match v.in_queue; choosing it flips in_queue optimistically.

    Strategy: subclass QMenu so that exec() returns whichever action the code added for
    the queue slot.  This exercises the real _show_version_chip_menu code path and
    verifies that:
      - the action text is 'Add to Queue' when in_queue=False (and flips to True)
      - the action text is 'Remove from Queue' when in_queue=True (and flips to False)
    """
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    # QMenu subclass that immediately "selects" the queue action
    class _FakeMenuPickQueue(QMenu):
        def exec(self, pos=None):  # type: ignore[override]
            for act in self.actions():
                if "Queue" in act.text():
                    return act
            return None

    monkeypatch.setattr("metatv.gui.details_versions.QMenu", _FakeMenuPickQueue)

    section = _VersionSection(_make_config())
    emitted: list[str] = []
    section.queue_toggled.connect(lambda cid: emitted.append(cid))

    # Case A: not yet queued — choosing the action should flip in_queue True
    v_off = ChannelVersion(channel_id="c1", name="T", in_queue=False)
    section._show_version_chip_menu(QPoint(0, 0), v_off)
    assert v_off.in_queue is True, (
        "After choosing the 'Add to Queue' action, v.in_queue must flip True"
    )
    assert "c1" in emitted, "queue_toggled must emit the channel_id"

    # Case B: already queued — choosing the action should flip in_queue False
    emitted.clear()
    v_on = ChannelVersion(channel_id="c2", name="T", in_queue=True)
    section._show_version_chip_menu(QPoint(0, 0), v_on)
    assert v_on.in_queue is False, (
        "After choosing the 'Remove from Queue' action, v.in_queue must flip False"
    )
    assert "c2" in emitted, "queue_toggled must emit the channel_id"


def test_version_chip_menu_updates_chip_text_on_queue_toggle(qapp, monkeypatch):
    """When a chip reference is passed to the menu, its text updates after queue toggle."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QMenu, QPushButton
    from metatv.gui.details_versions import ChannelVersion, _VersionSection

    class _FakeMenuPickQueue(QMenu):
        def exec(self, pos=None):  # type: ignore[override]
            for act in self.actions():
                if "Queue" in act.text():
                    return act
            return None

    monkeypatch.setattr("metatv.gui.details_versions.QMenu", _FakeMenuPickQueue)

    cfg = _make_config()
    section = _VersionSection(cfg)
    v = ChannelVersion(channel_id="c1", name="T", in_queue=False, detected_prefix="EN")
    chip = QPushButton("EN")   # dummy chip for text-update check

    section._show_version_chip_menu(QPoint(0, 0), v, chip)

    # After the flip, the chip text should include the queue icon
    assert cfg.queue_icon in chip.text(), (
        f"Chip text '{chip.text()}' should include queue_icon after optimistic flip"
    )


# ── Fix #101: genre chips wrap in flow layout ─────────────────────────────

def test_genre_load_populates_flow_container(qapp):
    """After load_metadata with genres, _genres_container holds one chip per genre."""
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_sections import _MetadataSection
    from metatv.gui.details_versions import _FlowLayout
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Action", "Drama", "Science Fiction"]))

    assert not section._genres_container.isHidden(), (
        "_genres_container should not be hidden after genres are loaded"
    )
    assert isinstance(section._genres_layout, _FlowLayout), (
        "Genre row must use _FlowLayout so chips can wrap at the panel width"
    )
    chip_texts = {c.text() for c in section._genres_container.findChildren(QPushButton)}
    assert chip_texts == {"Action", "Drama", "Science Fiction"}, (
        f"Expected one chip per genre; got {chip_texts}"
    )


def test_genre_chip_click_emits_genre_clicked(qapp):
    """Clicking a genre chip emits genre_clicked with the raw (unescaped) genre name."""
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Science Fiction", "Drama"]))

    emitted: list[str] = []
    section.genre_clicked.connect(lambda g: emitted.append(g))

    chips = section._genres_container.findChildren(QPushButton)
    sf_chip = next((c for c in chips if c.text() == "Science Fiction"), None)
    assert sf_chip is not None, "Should have a 'Science Fiction' chip button"
    sf_chip.click()

    assert emitted == ["Science Fiction"], (
        f"genre_clicked should emit the raw genre name; got {emitted}"
    )


def test_genre_chips_not_shown_for_live_channels(qapp):
    """Live channels (no metadata genres) must leave the genre area hidden."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    section.set_mode(is_live=True)

    assert section._genres_container.isHidden(), (
        "_genres_container should be hidden for live channels"
    )
    assert section._genres_loading_lbl.isHidden(), (
        "Loading label should be hidden for live channels"
    )


def test_genre_loading_label_shown_while_metadata_pending(qapp):
    """After load_basic for a non-live channel, loading label is shown, not the container."""
    from unittest.mock import MagicMock
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())

    # Minimal stub channel DTO
    ch = MagicMock()
    ch.name = "Test Movie (2023)"
    ch.media_type = "movie"
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = "Test Movie"
    ch.detected_year = "2023"
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0

    section.load_basic(ch)

    assert not section._genres_loading_lbl.isHidden(), (
        "Loading label should be shown while metadata is pending"
    )
    assert section._genres_container.isHidden(), (
        "Genre container should be hidden until load_metadata is called"
    )


def test_genre_clear_hides_container(qapp):
    """After clear(), the genre container and loading label are hidden."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Action"]))
    assert not section._genres_container.isHidden(), (
        "_genres_container should not be hidden after genres loaded"
    )
    section.clear()
    assert section._genres_container.isHidden(), (
        "_genres_container should be hidden after clear()"
    )
    assert section._genres_loading_lbl.isHidden(), (
        "Loading label should be hidden after clear()"
    )


# ── e87956eb: comma-joined genre strings split into separate wrapping chips ──

def test_comma_joined_genres_split_into_separate_chips(qapp):
    """A single comma-joined genre string becomes one chip per genre so they wrap.

    Providers (e.g. for "Cowboy Bebop") often deliver all genres as one
    comma-separated string in a single list element.  Previously only '/' was
    split, so this produced one over-wide chip; now both ',' and '/' split.
    """
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(
        genres=["Animation, Action, Adventure, Comedy, Drama, Science Fiction"]
    ))
    chip_texts = {c.text() for c in section._genres_container.findChildren(QPushButton)}
    assert chip_texts == {
        "Animation", "Action", "Adventure", "Comedy", "Drama", "Science Fiction"
    }, f"comma-joined genres must split into one chip each; got {chip_texts}"


def test_comma_joined_genres_do_not_force_wide_minimum(qapp):
    """The over-wide single chip is the bug e87956eb: after splitting, the flow
    layout's minimum width is just the widest single genre, never the whole joined
    string — so it can never push the details panel (min 300px) wider."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    joined = "Animation, Action, Adventure, Comedy, Drama, Science Fiction"

    # Sanity: the un-split joined string is genuinely wider than the panel.
    unsplit = _MetadataSection(_make_config())
    unsplit._populate_genre_chips([joined])
    unsplit_w = unsplit._genres_layout.minimumSize().width()
    assert unsplit_w > 300, (
        f"precondition: a single joined chip should be over-wide; got {unsplit_w}"
    )

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=[joined]))
    split_w = section._genres_layout.minimumSize().width()
    assert split_w < 200, (
        f"genre flow min width {split_w} too wide — chips not wrapping; "
        "a single joined chip forces the panel wider than its width"
    )


def test_ampersand_genre_not_split(qapp):
    """'Sci-Fi & Fantasy' / 'Action & Adventure' are single TMDB genres — '&'
    must never split them, only ',' and '/' do."""
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Sci-Fi & Fantasy, Action"]))
    chip_texts = {c.text() for c in section._genres_container.findChildren(QPushButton)}
    assert chip_texts == {"Sci-Fi & Fantasy", "Action"}, (
        f"'&' must not split a genre; got {chip_texts}"
    )


def test_duplicate_genres_deduped(qapp):
    """Merged multi-provider metadata can repeat a genre — render it once."""
    from PyQt6.QtWidgets import QPushButton
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Action, Drama", "drama / Action"]))
    chips = [c.text() for c in section._genres_container.findChildren(QPushButton)]
    assert sorted(chips) == ["Action", "Drama"], (
        f"duplicate genres (case-insensitive) must collapse to one chip; got {chips}"
    )


# ── backlog: empty Overview / Cast & Crew sections hide themselves ──────────
# The section sequence below (set_mode -> clear -> load) mirrors exactly what
# DetailsPaneWidget.show_channel() does per selection, so these execute the
# real reset path used when the reused pane switches between titles.

def test_overview_hidden_when_no_plot(qapp):
    """A non-live title with no overview text hides the whole Overview section."""
    from metatv.gui.details_sections import _PlotSection

    s = _PlotSection()
    s.set_mode(is_live=False)
    s.clear()
    s.load(None)
    assert s.isHidden(), "Overview section must be hidden when there is no plot text"


def test_overview_visible_when_plot_present(qapp):
    """A title with an overview shows the Overview section with its text."""
    from metatv.gui.details_sections import _PlotSection

    s = _PlotSection()
    s.set_mode(is_live=False)
    s.clear()
    s.load("A bounty hunter drifts through space.")
    assert not s.isHidden(), "Overview section must be visible when a plot is present"
    assert s.plot_label.text() == "A bounty hunter drifts through space."


def test_overview_visible_while_loading(qapp):
    """While metadata is still loading the Overview section stays visible."""
    from metatv.gui.details_sections import _PlotSection

    s = _PlotSection()
    s.set_mode(is_live=False)
    s.clear()
    s.show_loading("...")
    assert not s.isHidden(), "Overview must be visible while metadata is loading"


def test_overview_visibility_resets_across_reuse(qapp):
    """Reused pane: title WITH plot -> title WITHOUT plot hides -> back re-shows."""
    from metatv.gui.details_sections import _PlotSection

    s = _PlotSection()
    s.set_mode(is_live=False); s.clear(); s.load("Plot one.")
    assert not s.isHidden()
    s.set_mode(is_live=False); s.clear(); s.load(None)
    assert s.isHidden(), "must hide when reused for a plot-less title"
    s.set_mode(is_live=False); s.clear(); s.load("Plot three.")
    assert not s.isHidden(), "must re-show when reused for a title that has a plot"


def test_cast_hidden_when_no_cast_or_crew(qapp):
    """A title with neither cast nor director hides the whole Cast & Crew section."""
    from metatv.gui.details_sections import _CastSection

    s = _CastSection(_make_config())
    s.set_mode(is_live=False)
    s.clear()
    s.load(cast=[], director=None)
    assert s.isHidden(), "Cast & Crew must hide with no cast and no director"


def test_cast_visible_with_cast(qapp):
    """Any cast members make the Cast & Crew section visible."""
    from metatv.gui.details_sections import _CastSection

    s = _CastSection(_make_config())
    s.set_mode(is_live=False)
    s.clear()
    s.load(cast=[{"name": "Jane Doe"}], director=None)
    assert not s.isHidden(), "Cast & Crew must be visible when there is cast"


def test_cast_visible_with_director_only(qapp):
    """A director alone is enough to show the Cast & Crew section."""
    from metatv.gui.details_sections import _CastSection

    s = _CastSection(_make_config())
    s.set_mode(is_live=False)
    s.clear()
    s.load(cast=[], director="Shinichiro Watanabe")
    assert not s.isHidden(), "director alone is enough content to show the section"


def test_cast_visibility_resets_across_reuse(qapp):
    """Reused pane: title WITH people -> title WITHOUT -> hides -> back re-shows."""
    from metatv.gui.details_sections import _CastSection

    s = _CastSection(_make_config())
    s.set_mode(is_live=False); s.clear(); s.load(cast=[{"name": "A"}], director="D")
    assert not s.isHidden()
    s.set_mode(is_live=False); s.clear(); s.load(cast=[], director=None)
    assert s.isHidden(), "must hide when reused for a title with no cast/crew"
    s.set_mode(is_live=False); s.clear(); s.load(cast=[{"name": "B"}], director=None)
    assert not s.isHidden(), "must re-show when reused for a title with cast"
