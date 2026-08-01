"""Watch Queue / Favorites / History sidebar rows render the shared chip row.

End-to-end on a real ``Database`` (tmp_path file, not ``:memory:``): a seeded channel
carries an honest audio-language (``detected_prefix="EN"``) AND a source region
(``detected_region="DE"``).  For each section we produce the real DTO from the real
DB, feed it to the section's main-thread ``_populate_rows`` slot, and assert the row
is a chip-row widget showing the language chip (EN), the year/quality chips, and the
clean title — and that the source region (DE) is NEVER rendered (the regression the
Recommended chip work fixed, now shared by every content list).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.gui import theme as _theme
from metatv.gui.chip_row import MiddleElideLabel


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _config():
    return SimpleNamespace(
        live_icon="L", movie_icon="M", series_icon="S", unknown_icon="?",
        filter_adult_mode="all",
    )


def _seed_db(path: Path):
    """A real DB with one favorited, recently-played movie whose honest language (EN)
    differs from its source region (DE)."""
    from metatv.core.database import Database, ChannelDB, ProviderDB

    db = Database(f"sqlite:///{path}")
    db.create_tables()
    with db.session_scope() as session:
        session.add(ProviderDB(id="p1", name="Alpha", type="xtream", url="http://e",
                               username="u", password="p", is_active=True))
        session.flush()
        session.add(ChannelDB(
            id="c1", source_id="s1", provider_id="p1",
            name="EN - Cowboy Bebop (1998)", media_type="movie",
            detected_title="Cowboy Bebop", detected_prefix="EN",
            detected_region="DE", detected_quality="4K", detected_year="1998",
            is_favorite=True, last_played=datetime.now(), play_count=1,
        ))
    return db


def _first_chip_row(list_widget):
    """First item that hosts a setItemWidget chip row (skips plain header items)."""
    for i in range(list_widget.count()):
        w = list_widget.itemWidget(list_widget.item(i))
        if w is not None:
            return w
    return None


def _texts(row):
    return [w.text() for w in row.findChildren(QLabel) + row.findChildren(QPushButton)]


def _assert_honest_chip_row(row):
    assert row is not None, "content row must be a chip-row widget (setItemWidget)"
    texts = _texts(row)
    # Clean title, rendered as the anti-clip MiddleElideLabel.
    title = row.findChild(MiddleElideLabel)
    assert title is not None and title.text() == "Cowboy Bebop", texts
    # Honest language chip (EN) — its own LANG_CHIP-styled QLabel.
    assert any(w.text() == "EN" and w.styleSheet() == _theme.LANG_CHIP
               for w in row.findChildren(QLabel)), texts
    # Year + quality chips render from the stored fields.
    assert any(w.text() == "1998" and w.styleSheet() == _theme.YEAR_CHIP
               for w in row.findChildren(QLabel)), texts
    assert any(b.text() == "4K" for b in row.findChildren(QPushButton)), texts
    # The source region must NEVER leak anywhere in the row.
    assert not any("DE" in t for t in texts), f"region DE leaked: {texts}"


def test_favorites_row_is_honest_chip_row(qapp, tmp_path):
    from PyQt6.QtWidgets import QListWidget
    from metatv.core.repositories import RepositoryFactory
    from metatv.gui.sidebar.favorites import FavoritesSection

    db = _seed_db(tmp_path / "fav.db")
    with db.session_scope(commit=False) as session:
        dtos = RepositoryFactory(session).channels.get_favorites_dto(hidden_provider_ids=set())
    assert dtos and dtos[0].detected_prefix == "EN", "DTO must carry the stored prefix"

    obj = FavoritesSection.__new__(FavoritesSection)
    obj.favorites_list = QListWidget()
    obj.config = _config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False
    obj._populate_rows(dtos)

    _assert_honest_chip_row(_first_chip_row(obj.favorites_list))
    db.close()


def test_queue_row_is_honest_chip_row(qapp, tmp_path):
    from PyQt6.QtWidgets import QListWidget
    from metatv.core.repositories import RepositoryFactory
    from metatv.gui.sidebar.queue import WatchQueueSection

    db = _seed_db(tmp_path / "queue.db")
    with db.session_scope() as session:
        RepositoryFactory(session).queue.add(
            "c1", channel_name="Cowboy Bebop", media_type="movie", source_id="s1")
    with db.session_scope(commit=False) as session:
        entries = RepositoryFactory(session).queue.get_all()
    assert entries and entries[0].detected_prefix == "EN", "entry must carry the stored prefix"

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False
    obj._populate_rows(entries)

    _assert_honest_chip_row(_first_chip_row(obj._list))
    db.close()


def test_history_row_is_honest_chip_row(qapp, tmp_path):
    from PyQt6.QtWidgets import QListWidget
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.dtos import build_history_dtos
    from metatv.gui.sidebar.history import HistorySection

    db = _seed_db(tmp_path / "hist.db")
    with db.session_scope(commit=False) as session:
        dtos = build_history_dtos(RepositoryFactory(session), limit=30)
    assert dtos and dtos[0].detected_prefix == "EN", "HistoryDTO must carry the stored prefix"
    assert dtos[0].detected_title == "Cowboy Bebop"

    obj = HistorySection.__new__(HistorySection)
    obj.history_list = QListWidget()
    obj.config = _config()
    obj.set_empty = lambda *_: None
    obj._populate_rows(dtos)

    _assert_honest_chip_row(_first_chip_row(obj.history_list))
    db.close()


def test_history_row_keeps_episode_code_in_title(qapp, tmp_path):
    """A series row appends its episode code to the (elidable) title, keeping it visible."""
    from PyQt6.QtWidgets import QListWidget
    from metatv.core.repositories.dtos import HistoryDTO
    from metatv.gui.sidebar.history import HistorySection

    obj = HistorySection.__new__(HistorySection)
    obj.history_list = QListWidget()
    obj.config = _config()
    obj.set_empty = lambda *_: None
    obj._populate_rows([
        HistoryDTO(id="s1", name="My Show", media_type="series", episode_code="S01E02",
                   detected_title="My Show", detected_prefix="EN"),
    ])

    row = _first_chip_row(obj.history_list)
    title = row.findChild(MiddleElideLabel)
    assert title.text() == "My Show → S01E02", "episode code kept as a visible title suffix"
