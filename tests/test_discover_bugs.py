"""Behavioral tests for the Discover-view bug fixes (A, D2, D1, F).

Bug A  — get_all_genres/get_all_decades no longer materialise full ORM objects;
         streaming scalar-select preserves exact output.
Bug D2 — get_all_genres filters "null"/"undefined" sentinel genre tokens.
Bug D1 — set_cards() resizes the inner widget so cards render at full width.
Bug F  — _ContentCard emits doubleClicked; a wired _Shelf forwards it to play.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def seeded_db(tmp_path):
    """File-backed DB seeded with enough rows to test enumeration functions."""
    from metatv.core.database import Database, ChannelDB, ProviderDB

    db = Database(f"sqlite:///{tmp_path / 'bug_test.db'}")
    db.create_tables()

    session = db.get_session()
    try:
        session.add(ProviderDB(
            id="p1", name="Test Provider", type="xtream",
            url="http://test.example.com", is_active=True,
        ))

        # 12 Action movies from 2000 (decade 2000)
        for i in range(12):
            session.add(ChannelDB(
                id=str(uuid.uuid4()),
                source_id=f"action_{i}",
                provider_id="p1",
                name=f"Action Movie {i} (2000)",
                media_type="movie",
                raw_data={"genre": "Action", "rating": "8.0",
                          "stream_icon": "", "releaseDate": "2000-01-01"},
            ))

        # 12 Drama series from 1990 (decade 1990)
        for i in range(12):
            session.add(ChannelDB(
                id=str(uuid.uuid4()),
                source_id=f"drama_{i}",
                provider_id="p1",
                name=f"Drama Series {i} (1990)",
                media_type="series",
                raw_data={"genre": "Drama", "rating": "7.5",
                          "stream_icon": "", "releaseDate": "1990-06-01"},
            ))

        # Channels with bogus "null" and empty genre (Bug D2)
        session.add(ChannelDB(
            id=str(uuid.uuid4()),
            source_id="null_genre_1",
            provider_id="p1",
            name="Null Genre Movie",
            media_type="movie",
            raw_data={"genre": "null", "rating": "6.0",
                      "stream_icon": "", "releaseDate": "2005-01-01"},
        ))
        session.add(ChannelDB(
            id=str(uuid.uuid4()),
            source_id="undef_genre",
            provider_id="p1",
            name="Undefined Genre Movie",
            media_type="movie",
            raw_data={"genre": "undefined", "rating": "6.0",
                      "stream_icon": "", "releaseDate": "2005-01-01"},
        ))

        session.commit()
    finally:
        session.close()

    yield db
    db.close()


# ---------------------------------------------------------------------------
# Bug A — get_all_genres streaming scalar-select preserves output
# ---------------------------------------------------------------------------

class TestGetAllGenresScalar:

    def test_returns_correct_genres(self, seeded_db):
        """get_all_genres returns Action and Drama (each ≥ min_count=10).

        Pure "Action" stays "Action" — it is NOT folded into the "Action &
        Adventure" compound (de-pollution: pures and compounds are distinct).
        """
        from metatv.core.discovery_engine import get_all_genres
        session = seeded_db.get_session()
        try:
            genres = get_all_genres(session, min_count=10)
        finally:
            session.close()

        assert "Action" in genres
        assert "Drama" in genres

    def test_min_count_threshold(self, seeded_db):
        """Genres below min_count are excluded; Action+Drama both exceed it."""
        from metatv.core.discovery_engine import get_all_genres
        session = seeded_db.get_session()
        try:
            genres_high = get_all_genres(session, min_count=100)
            genres_low  = get_all_genres(session, min_count=1)
        finally:
            session.close()

        assert genres_high == [], "no genre reaches count=100"
        assert "Action" in genres_low
        assert "Drama" in genres_low


# ---------------------------------------------------------------------------
# Bug D2 — "null"/"undefined" sentinel tokens are excluded
# ---------------------------------------------------------------------------

class TestGetAllGenresExcludesSentinels:

    def test_null_genre_excluded(self, seeded_db):
        """get_all_genres must not return the literal string 'null'."""
        from metatv.core.discovery_engine import get_all_genres
        session = seeded_db.get_session()
        try:
            # Use min_count=1 so even single-channel genres would show up.
            genres = get_all_genres(session, min_count=1)
        finally:
            session.close()

        assert "null" not in genres, "'null' is a sentinel value and must be excluded"
        assert "NULL" not in genres
        # Case-insensitive — any capitalisation is wrong.
        assert not any(g.lower() == "null" for g in genres)

    def test_undefined_genre_excluded(self, seeded_db):
        """get_all_genres must not return the literal string 'undefined'."""
        from metatv.core.discovery_engine import get_all_genres
        session = seeded_db.get_session()
        try:
            genres = get_all_genres(session, min_count=1)
        finally:
            session.close()

        assert not any(g.lower() == "undefined" for g in genres)


# ---------------------------------------------------------------------------
# Bug A — get_all_decades streaming scalar-select preserves output
# ---------------------------------------------------------------------------

class TestGetAllDecadesScalar:

    def test_returns_correct_decades(self, seeded_db):
        """get_all_decades returns 2000 and 1990 (each ≥ 5 entries)."""
        from metatv.core.discovery_engine import get_all_decades
        session = seeded_db.get_session()
        try:
            decades = get_all_decades(session)
        finally:
            session.close()

        assert 2000 in decades, "decade 2000 must appear (12 Action movies)"
        assert 1990 in decades, "decade 1990 must appear (12 Drama series)"

    def test_sorted_descending(self, seeded_db):
        """Decades are returned newest-first."""
        from metatv.core.discovery_engine import get_all_decades
        session = seeded_db.get_session()
        try:
            decades = get_all_decades(session)
        finally:
            session.close()

        assert decades == sorted(decades, reverse=True), "decades must be descending"


# ---------------------------------------------------------------------------
# Bug D1 — set_cards() resizes inner widget so cards render at full width
# ---------------------------------------------------------------------------

class TestSetCardsResizesInnerWidget:

    def test_card_width_after_set_cards(self, qapp):
        """Cards added via set_cards() must be full _CARD_W wide, not squashed."""
        from metatv.core.config import Config
        from metatv.core.discovery_engine import ContentCard
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import _CARD_W

        cfg = Config()
        image_cache = MagicMock()
        image_cache.get_image_async = MagicMock()

        # Build a header-only shelf (no cards at construction time).
        shelf = _Shelf("Test Genre", "genre:Test", [], image_cache, cfg,
                       collapsed=False)

        assert shelf._cards_widgets == []
        # Inner widget starts essentially empty — sizeHint width should be tiny.
        initial_hint_w = shelf._inner_widget.sizeHint().width()

        cards = [
            ContentCard(
                channel_id=f"ch-{i}",
                title=f"Movie {i}",
                media_type="movie",
                thumbnail_url=None,
                rating=7.5,
                year=2020,
                genre="Test",
            )
            for i in range(3)
        ]

        shelf.set_cards(cards, image_cache=image_cache, config=cfg)
        qapp.processEvents()

        assert len(shelf._cards_widgets) == 3

        # After set_cards the inner widget must be wide enough for 3 cards.
        # Each card is _CARD_W (120) px; with spacing the hint must exceed that.
        hint_w = shelf._inner_widget.sizeHint().width()
        assert hint_w >= _CARD_W, (
            f"inner widget hint ({hint_w}px) must be ≥ _CARD_W ({_CARD_W}px) "
            f"after set_cards — was {initial_hint_w}px before"
        )

        # Each individual card widget must be exactly _CARD_W wide.
        for w in shelf._cards_widgets:
            assert w.width() == _CARD_W, (
                f"card widget width is {w.width()}, expected {_CARD_W}"
            )

    def test_inner_widget_grows_with_cards(self, qapp):
        """Inner widget hint grows proportionally when more cards are added."""
        from metatv.core.config import Config
        from metatv.core.discovery_engine import ContentCard
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        image_cache = MagicMock()

        def _card(i):
            return ContentCard(
                channel_id=f"cg-{i}", title=f"Movie {i}",
                media_type="movie", thumbnail_url=None,
                rating=7.0, year=2000, genre="G",
            )

        shelf_3 = _Shelf("G3", "genre:G3", [], image_cache, cfg, collapsed=False)
        shelf_3.set_cards([_card(i) for i in range(3)], image_cache=image_cache, config=cfg)

        shelf_6 = _Shelf("G6", "genre:G6", [], image_cache, cfg, collapsed=False)
        shelf_6.set_cards([_card(i) for i in range(6)], image_cache=image_cache, config=cfg)

        hint_3 = shelf_3._inner_widget.sizeHint().width()
        hint_6 = shelf_6._inner_widget.sizeHint().width()

        assert hint_6 > hint_3, (
            f"6-card shelf ({hint_6}px) must be wider than 3-card shelf ({hint_3}px)"
        )


# ---------------------------------------------------------------------------
# Bug F — _ContentCard emits doubleClicked; wired _Shelf forwards to play
# ---------------------------------------------------------------------------

class TestDoubleClickEmitsBehavior:

    def test_content_card_emits_double_clicked(self, qapp):
        """_ContentCard.mouseDoubleClickEvent emits doubleClicked(channel_id)."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF
        from metatv.core.config import Config
        from metatv.core.discovery_engine import ContentCard
        from metatv.gui.discover_card import _ContentCard

        cfg = Config()
        image_cache = MagicMock()
        card_data = ContentCard(
            channel_id="ch-dbl-1",
            title="Double Click Me",
            media_type="movie",
            thumbnail_url=None,
            rating=8.0,
            year=2022,
            genre="Action",
        )

        widget = _ContentCard(card_data, image_cache, cfg)

        emitted: list[str] = []
        widget.doubleClicked.connect(emitted.append)

        # Synthesise a double-click event (left button).
        evt = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.mouseDoubleClickEvent(evt)

        assert emitted == ["ch-dbl-1"], (
            f"doubleClicked must emit channel_id 'ch-dbl-1', got {emitted!r}"
        )

    def test_wired_shelf_forwards_double_click_to_play_slot(self, qapp):
        """A wired _Shelf routes card doubleClicked through to the play slot."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF
        from metatv.core.config import Config
        from metatv.core.discovery_engine import ContentCard
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        image_cache = MagicMock()

        card_data = ContentCard(
            channel_id="ch-play-1",
            title="Play This",
            media_type="movie",
            thumbnail_url=None,
            rating=7.0,
            year=2021,
            genre="Drama",
        )

        # Eager shelf (card at construction time).
        shelf = _Shelf("Drama", "genre:Drama", [card_data], image_cache, cfg,
                       collapsed=False)

        played: list[str] = []
        selected: list[str] = []
        shelf.wire(selected.append, played.append, lambda *_: None, lambda *_: None)

        # Trigger a double-click on the first card widget.
        card_w = shelf._cards_widgets[0]
        evt = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        card_w.mouseDoubleClickEvent(evt)

        assert played == ["ch-play-1"], (
            f"play slot must be called with channel_id, got {played!r}"
        )

    def test_lazy_expanded_card_double_click_wired(self, qapp):
        """Cards added via set_cards() get doubleClicked wired to the play slot."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QPointF
        from metatv.core.config import Config
        from metatv.core.discovery_engine import ContentCard
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        image_cache = MagicMock()

        # Header-only shelf (no cards at construction time).
        shelf = _Shelf("Lazy", "genre:Lazy", [], image_cache, cfg, collapsed=True)

        played: list[str] = []
        shelf.wire(lambda _: None, played.append, lambda *_: None, lambda *_: None)

        card_data = ContentCard(
            channel_id="ch-lazy-1",
            title="Lazy Movie",
            media_type="movie",
            thumbnail_url=None,
            rating=8.5,
            year=2023,
            genre="Lazy",
        )

        # Simulate the lazy-expand fill path.
        shelf.set_cards([card_data], image_cache=image_cache, config=cfg)

        card_w = shelf._cards_widgets[0]
        evt = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        card_w.mouseDoubleClickEvent(evt)

        assert played == ["ch-lazy-1"], (
            f"lazy-expanded card must route double-click to play slot, got {played!r}"
        )

