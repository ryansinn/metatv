"""Watch Queue / Favorites / History sidebar rows render the shared chip row.

End-to-end on a real ``Database`` (tmp_path file, not ``:memory:``): a seeded channel
carries an honest audio-language (``detected_prefix="EN"``) AND a source region
(``detected_region="DE"``).  For each section we produce the real DTO from the real
DB, feed it to the section's main-thread ``_populate_rows`` slot, and assert the row
is a shared sidebar row showing the clean title over a meta line carrying the honest
language (EN), the year and the quality — and that the source region (DE) is NEVER
rendered (the regression the Recommended chip work fixed, now shared by every content
list).

V3 moved those facts from chips into the meta line; the thing being guarded here is
unchanged, so these tests were retargeted rather than retired. "Never render the
region" is the whole point and it outlives any particular row shape.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from PyQt6.QtWidgets import QLabel, QPushButton

from metatv.gui.chip_row import row_meta_label, row_title_label


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


def _meta_parts(row):
    meta = row_meta_label(row)
    assert meta is not None, f"no meta line on the row: {_texts(row)}"
    return [p.strip() for p in meta.text().split("·")]


def _assert_clean_title_and_no_region(row):
    """What every section owes, whatever its meta line says.

    The region check is the one that matters: ``detected_region`` ("DE") is the
    SOURCE's country, not the content's language, and rendering it told the user
    a German-dubbed film was on offer when it was not.
    """
    assert row is not None, "content row must be a shared row widget (setItemWidget)"
    texts = _texts(row)
    title = row_title_label(row)
    assert title is not None and title.text() == "Cowboy Bebop", texts
    assert not any("DE" in t for t in texts), f"region DE leaked: {texts}"


def _assert_honest_chip_row(row):
    """Favorites / Queue: the meta line carries type, year, honest language, quality."""
    _assert_clean_title_and_no_region(row)
    parts = _meta_parts(row)
    assert "EN" in parts, f"honest language missing: {parts}"
    assert "1998" in parts, f"year missing: {parts}"
    assert "4K" in parts, f"quality missing: {parts}"


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
    # _populate_rows now takes (channel_dtos, episode_dtos) — Wave 2 Slice 2B.
    obj._populate_rows((dtos, []))

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

    from tests.conftest import wire_watch_queue_filter

    obj = WatchQueueSection.__new__(WatchQueueSection)
    obj._list = QListWidget()
    obj.config = _config()
    obj.set_empty = lambda *_: None
    obj._has_unavailable = False
    wire_watch_queue_filter(obj)
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

    # History's meta line is deliberately NOT the other sections': it reads
    # "1998 · just now" — the identifying fact and then WHEN, because History is
    # a list ordered by exactly that. Language and quality are not what tells one
    # history entry from another.
    row = _first_chip_row(obj.history_list)
    _assert_clean_title_and_no_region(row)
    parts = _meta_parts(row)
    assert parts[0] == "1998", f"the year should lead the line: {parts}"
    assert len(parts) == 2 and parts[1], f"a time should close the line: {parts}"
    db.close()


def test_history_row_puts_the_episode_code_on_the_meta_line(qapp, tmp_path):
    """A series row carries its episode code on the second line, always fully visible.

    It used to be appended to the title as "My Show → S01E02" so middle-elision
    would preserve it. That worked, and it spent title width to do it; on its own
    line the code never competes with the name it belongs to.
    """
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
    assert row_title_label(row).text() == "My Show", "the title is just the title now"
    assert row_meta_label(row).text().startswith("S01E02"), (
        "the episode code leads the meta line — it is what tells this row from its "
        f"siblings: {row_meta_label(row).text()!r}"
    )
