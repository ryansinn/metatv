"""The details title block's rows, measured (owner, 2026-10-19).

    SERIES · 2024                       [🦖 TREX Shared]
    Tires                               7.0 / 10 [TMDb]
    [Comedy] [Top Series]

Rendered geometry, not structure: the genre chips used to start ~10 px right
of every other row (Qt's default FlowLayout margins), the rating and the source
chip each took a row of their own, and the episode title had no line saying it
was an episode.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QPoint

from metatv.gui.details_title import _MetadataSection
from metatv.metadata_providers.base import MetadataResult


class _Ch:
    raw_data = None
    category = None
    is_favorite = False
    is_adult = False
    provider_id = "p1"
    id = "p1_1"
    name = "Tires"
    detected_title = "Tires"
    detected_year = "2024"
    detected_prefix = None
    detected_quality = None
    media_type = "series"


_PROVIDERS = {"p1": {"name": "TREX Shared", "icon": "", "enabled": True}}


def _x(widget, ancestor) -> int:
    return widget.mapTo(ancestor, QPoint(0, 0)).x()


def _y_mid(widget, ancestor) -> int:
    return widget.mapTo(ancestor, QPoint(0, widget.height() // 2)).y()


@pytest.fixture
def section(qapp, tmp_path, qtbot):
    from metatv.core.config import Config

    sec = _MetadataSection(Config(config_dir=tmp_path))
    qtbot.addWidget(sec)
    sec.resize(452, 300)
    sec.load_basic(_Ch(), _PROVIDERS)
    sec.load_metadata(MetadataResult(genres=["Comedy"], rating=7.0, tmdb_id="12345"))
    sec.show()
    qapp.processEvents()
    return sec


def _first_genre_chip(section):
    return section._genres_layout.itemAt(0).widget()


def test_genre_chips_start_at_the_same_edge_as_the_byline(section):
    chip = _first_genre_chip(section)
    assert _x(chip, section) == _x(section._byline_lbl, section), (
        "the genre chips are indented past the byline — the FlowLayout's "
        "default margins are back")


def test_the_rating_sits_at_the_right_of_the_title_line(section):
    title = section.title_label
    rating = section._rating_row_w
    assert abs(_y_mid(rating, section) - _y_mid(title, section)) <= 8, (
        "the rating is not on the title's line")
    right_gap = section.width() - (_x(rating, section) + rating.width())
    assert right_gap <= 4, f"the rating ends {right_gap}px short of the right edge"


def test_the_collection_chip_ends_the_genre_row(section):
    section.set_collection("Top Series")
    layout = section._genres_layout
    assert layout.itemAt(layout.count() - 1).widget() is section._collection_chip
    assert not section._collection_chip.isHidden()


def test_the_block_is_no_taller_than_it_needs(section):
    """The gap above "Available in": the block grew toward a size hint that
    assumed every chip on its own line."""
    assert section.sizeHint().height() == section.heightForWidth(section.width())


def test_the_source_chip_sits_at_the_right_of_the_byline(section):
    source = section._source_row_w
    assert not source.isHidden()
    assert abs(_y_mid(source, section) - _y_mid(section._byline_lbl, section)) <= 6, (
        "the source chip is not on the byline's row")
    assert section.width() - (_x(source, section) + source.width()) <= 4


# ── episode mode ────────────────────────────────────────────────────────────

def _episode(rating=7.4, air_date="2025-06-05", season=2, number=1):
    from metatv.core.repositories.dtos import EpisodeDTO

    return EpisodeDTO(
        id=str(uuid.uuid4()), episode_num=number, season_num=season,
        title="Bonus Money", series_name="Tires", stream_url="http://s/e",
        duration="22:00", is_watched=False, rating=rating, air_date=air_date,
    )


@pytest.fixture
def pane(qapp, qtbot):
    from PyQt6.QtWidgets import QApplication

    from metatv.core.config import Config
    from metatv.gui.details_pane import DetailsPaneWidget
    from tests.conftest import destroy_widget

    before = set(map(id, QApplication.topLevelWidgets()))
    cache = MagicMock()
    cache.get_image_sync.return_value = None
    p = DetailsPaneWidget(Config(), cache, db=None)
    qtbot.addWidget(p)
    p.resize(452, 900)
    yield p
    # The pane leaves parentless helpers behind (its _ActionBar — ledger F45 —
    # and rows its sections replace); free every top-level it created.
    destroy_widget(*[w for w in QApplication.topLevelWidgets()
                     if id(w) not in before and w is not p])


def _series():
    ch = MagicMock()
    ch.id, ch.name, ch.media_type = str(uuid.uuid4()), "Tires", "series"
    ch.detected_title, ch.detected_year = "Tires", "2024"
    ch.is_favorite = ch.is_adult = ch.watch_completed = False
    ch.detected_prefix = ch.detected_quality = ch.detected_region = None
    ch.raw_data = ch.provider_id = None
    return ch


def test_the_eyebrow_names_the_season_episode_and_total(pane, qapp):
    pane.show_channel(_series())
    pane.show_episode(_episode(), _series(), "Bonus Money", season_episode_count=12)
    assert pane._episode_eyebrow_lbl.text() == "SEASON 2 · EPISODE 1 OF 12"


def test_air_date_and_episode_rating_sit_at_the_right_of_their_rows(pane, qapp):
    series = _series()
    pane.show_channel(series)
    pane.show_episode(_episode(), series, "Bonus Money", season_episode_count=12)
    pane.show()
    qapp.processEvents()
    head = pane._episode_meta_row
    eyebrow, aired = pane._episode_eyebrow_lbl, pane._episode_air_date_lbl
    title, rating = pane._byline, pane._episode_rating_lbl

    assert abs(_y_mid(aired, head) - _y_mid(eyebrow, head)) <= 3
    assert head.width() - (_x(aired, head) + aired.width()) <= 2
    assert _y_mid(eyebrow, head) > _y_mid(title, head), "the season/episode line is not under the title"

    assert abs(_y_mid(rating, head) - _y_mid(title, head)) <= 8
    assert head.width() - (_x(rating, head) + rating.width()) <= 2
    assert "7.4 / 10" in rating.toolTip()   # stars in the row, the number on hover
