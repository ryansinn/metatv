"""Behavioral tests for lazy, viewport-only channel-list poster thumbnails
(wave6/list-posters).

Covers:
1. ``ChannelListDTO.poster_url`` reaches the DTO via ``ChannelRepository.get_all()``'s
   outerjoin against ``MetadataDB`` (the SAME join PR #382 added for ``plot``) —
   a real ``Database`` on ``tmp_path`` (not ``:memory:``), one channel with a
   poster + one without, and proof the number of metadata-referencing SQL
   statements does NOT scale with the number of channel rows (no N+1).
2. ``ChannelRowDelegate`` paints the muted placeholder tile (never a blank gap
   or a crash) when ``ImageCache.get_image_sync`` misses — whether because the
   channel has no poster URL at all, or because the URL isn't cached yet.
3. ``ChannelThumbnailHydrator.request_range`` only ever calls
   ``ImageCache.get_image_async`` for rows INSIDE the given range — offscreen
   rows are never requested.
4. A stub ``ImageCache.image_loaded`` firing triggers ``ChannelListModel.dataChanged``
   for exactly the row that requested that URL (via ``row_for_channel_id``).
5. With hydration disabled, ``request_range`` queues nothing even after the
   debounced hydrate pass runs; with the delegate's thumbnails flag off,
   ``sizeHint`` never reserves the thumbnail's height.
6. Compact density never reserves a thumbnail rect, regardless of the
   thumbnails setting.

Every test executes the changed path and asserts an outcome that would break
if the lazy-hydration logic regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QObject, QRect, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QStyleOptionViewItem

from metatv.core.config import Config
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_delegate import (
    _THUMB_H,
    DENSITY_COMFY,
    DENSITY_COMPACT,
    ChannelRowDelegate,
)
from metatv.gui.channel_list_model import POSTER_URL_ROLE, ChannelListModel
from metatv.gui.channel_list_thumbnails import ChannelThumbnailHydrator


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _StubImageCache(QObject):
    """Offline stand-in for ``ImageCache``: no disk, no network, no thread pool.

    Mirrors the real class's public surface exactly (the two signals plus
    ``get_image_sync``/``get_image_async``) so the delegate and the hydrator
    can use it unmodified.
    """

    image_loaded = pyqtSignal(str, QPixmap)
    image_failed = pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.sync_hits: dict[str, QPixmap] = {}
        self.async_requests: list[str] = []

    def get_image_sync(self, url: str):
        return self.sync_hits.get(url)

    def get_image_async(self, url: str, provider_urls=None) -> None:
        self.async_requests.append(url)


def _make_dto(**overrides) -> ChannelListDTO:
    base = dict(
        id=str(uuid.uuid4()),
        name="Channel",
        media_type="movie",
        provider_id="prov1",
        is_favorite=False,
        category="Action",
        quality=None,
        detected_prefix=None,
        detected_region="US",
        detected_quality="HD",
        detected_year="2021",
        detected_title="A Great Movie",
        poster_url="",
    )
    base.update(overrides)
    return ChannelListDTO(**base)


def _flat_model(dtos) -> ChannelListModel:
    model = ChannelListModel()
    model.set_channels(
        dtos,
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        favorite_icon="★",
        unfavorite_icon="☆",
        get_media_type_icon=lambda mt: {"movie": "🎬", "series": "📺", "live": "📡"}.get(mt, "?"),
    )
    return model


def _option(width: int = 320, height: int = 0) -> QStyleOptionViewItem:
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, width, height)
    return opt


# ---------------------------------------------------------------------------
# 1. poster_url reaches the DTO via the outerjoin — no N+1
# ---------------------------------------------------------------------------

def test_poster_url_reaches_dto_via_join_without_scaling_query_count(tmp_path):
    """``ChannelRepository.get_all()`` outerjoins ``MetadataDB`` for poster_url
    in the SAME paginated query used for the Comfy+ plot line — never a
    per-row lookup.

    A channel WITH a metadata row carrying a poster gets that URL; a channel
    WITHOUT one gets "". The number of SQL statements referencing the
    metadata table must stay the SAME (one join query) whether the corpus has
    2 rows or 27 — NOT grow with row count, which is exactly the N+1 this
    outerjoin exists to avoid.
    """
    from sqlalchemy import event

    from metatv.core.database import ChannelDB, Database, MetadataDB
    from metatv.core.repositories.channel import ChannelRepository

    db = Database(f"sqlite:///{tmp_path / 'thumbnails_join.db'}")
    db.create_tables()
    try:
        with db.session_scope() as session:
            session.add(MetadataDB(
                id="meta1", title="Movie One",
                poster_url="https://img.example/poster1.jpg",
            ))
            session.add(ChannelDB(
                id="c1", source_id="s1", provider_id="prov1", name="Chan1",
                media_type="movie", metadata_id="meta1",
            ))
            session.add(ChannelDB(
                id="c2", source_id="s2", provider_id="prov1", name="Chan2",
                media_type="movie", metadata_id=None,
            ))

        engine = db.engine
        counter = {"n": 0}

        def _count(conn, cursor, statement, *a):
            if "metadata" in statement.lower():
                counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _count)
        try:
            with db.session_scope() as session:
                repo = ChannelRepository(session)
                rows = repo.get_all(limit=100)
                dtos_by_id = {r.id: ChannelListDTO.from_orm(r) for r in rows}
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        small_query_count = counter["n"]
        assert dtos_by_id["c1"].poster_url == "https://img.example/poster1.jpg"
        assert dtos_by_id["c2"].poster_url == ""  # no metadata row → empty string

        with db.session_scope() as session:
            for i in range(25):
                session.add(ChannelDB(
                    id=f"bulk{i}", source_id=f"bsrc{i}", provider_id="prov1",
                    name=f"Bulk Channel {i:02d}", media_type="movie",
                ))

        counter["n"] = 0
        event.listen(engine, "before_cursor_execute", _count)
        try:
            with db.session_scope() as session:
                repo = ChannelRepository(session)
                repo.get_all(limit=100)
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        assert counter["n"] == small_query_count == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. Placeholder paints on a cache miss (no URL, and an uncached URL)
# ---------------------------------------------------------------------------

def test_placeholder_paints_when_channel_has_no_poster_url(qapp):
    model = _flat_model([_make_dto(poster_url="")])
    index = model.index(0)
    stub = _StubImageCache()
    delegate = ChannelRowDelegate(image_cache=stub)

    with patch.object(ChannelRowDelegate, "_paint_thumbnail_placeholder") as mock_ph:
        delegate._paint_thumbnail(MagicMock(), QRect(0, 0, 32, 48), index)

    mock_ph.assert_called_once()
    assert stub.async_requests == []  # paint() never downloads


def test_placeholder_paints_when_url_present_but_not_yet_cached(qapp):
    url = "https://img.example/not-cached.jpg"
    model = _flat_model([_make_dto(poster_url=url)])
    index = model.index(0)
    stub = _StubImageCache()  # sync_hits empty → get_image_sync(url) misses
    delegate = ChannelRowDelegate(image_cache=stub)

    with patch.object(ChannelRowDelegate, "_paint_thumbnail_placeholder") as mock_ph:
        delegate._paint_thumbnail(MagicMock(), QRect(0, 0, 32, 48), index)

    mock_ph.assert_called_once()


def test_real_pixmap_painted_when_cache_hits(qapp):
    url = "https://img.example/cached.jpg"
    model = _flat_model([_make_dto(poster_url=url)])
    index = model.index(0)
    stub = _StubImageCache()
    stub.sync_hits[url] = QPixmap(10, 10)
    delegate = ChannelRowDelegate(image_cache=stub)

    with patch.object(ChannelRowDelegate, "_paint_thumbnail_placeholder") as mock_ph:
        delegate._paint_thumbnail(MagicMock(), QRect(0, 0, 32, 48), index)

    mock_ph.assert_not_called()  # real pixmap was available — no placeholder


# ---------------------------------------------------------------------------
# 3. Viewport-only hydration: only rows in the requested range are fetched
# ---------------------------------------------------------------------------

def test_only_rows_in_requested_range_trigger_async_fetch(qapp):
    dtos = [
        _make_dto(id=f"c{i}", poster_url=f"https://img.example/{i}.jpg")
        for i in range(5)
    ]
    model = _flat_model(dtos)
    stub = _StubImageCache()
    hydrator = ChannelThumbnailHydrator(model, stub)
    hydrator.set_enabled(True)

    hydrator.request_range(1, 2)
    hydrator._hydrate_pending_range()  # bypass the debounce timer — deterministic

    assert stub.async_requests == [
        "https://img.example/1.jpg", "https://img.example/2.jpg",
    ]
    # Offscreen rows (0, 3, 4) must never be requested.
    for offscreen in (0, 3, 4):
        assert f"https://img.example/{offscreen}.jpg" not in stub.async_requests


def test_already_cached_rows_in_range_are_not_re_requested(qapp):
    url = "https://img.example/cached.jpg"
    model = _flat_model([_make_dto(id="c0", poster_url=url)])
    stub = _StubImageCache()
    stub.sync_hits[url] = QPixmap(4, 4)
    hydrator = ChannelThumbnailHydrator(model, stub)
    hydrator.set_enabled(True)

    hydrator.request_range(0, 0)
    hydrator._hydrate_pending_range()

    assert stub.async_requests == []  # already on disk — delegate paints it directly


# ---------------------------------------------------------------------------
# 4. image_loaded triggers dataChanged for the requesting row(s) only
# ---------------------------------------------------------------------------

def test_image_loaded_emits_datachanged_for_the_right_row(qapp):
    dtos = [
        _make_dto(id="c0", poster_url="https://img.example/0.jpg"),
        _make_dto(id="c1", poster_url="https://img.example/1.jpg"),
        _make_dto(id="c2", poster_url="https://img.example/2.jpg"),
    ]
    model = _flat_model(dtos)
    stub = _StubImageCache()
    hydrator = ChannelThumbnailHydrator(model, stub)
    hydrator.set_enabled(True)
    hydrator.request_range(0, 2)
    hydrator._hydrate_pending_range()

    seen: list[tuple[int, int, list]] = []
    model.dataChanged.connect(lambda tl, br, roles: seen.append((tl.row(), br.row(), list(roles))))

    stub.image_loaded.emit("https://img.example/1.jpg", QPixmap(4, 4))

    assert len(seen) == 1
    top_row, bottom_row, roles = seen[0]
    assert top_row == bottom_row == 1  # row for channel "c1" only
    assert POSTER_URL_ROLE in roles


def test_image_failed_clears_pending_without_datachanged(qapp):
    url = "https://img.example/broken.jpg"
    model = _flat_model([_make_dto(id="c0", poster_url=url)])
    stub = _StubImageCache()
    hydrator = ChannelThumbnailHydrator(model, stub)
    hydrator.set_enabled(True)
    hydrator.request_range(0, 0)
    hydrator._hydrate_pending_range()

    seen = []
    model.dataChanged.connect(lambda *a: seen.append(a))
    stub.image_failed.emit(url, "404")

    assert seen == []  # no repaint needed — placeholder already renders
    assert hydrator._pending == {}  # entry cleared, not leaked


# ---------------------------------------------------------------------------
# 5. Setting off: no requests queued; sizeHint reserves no thumbnail height
# ---------------------------------------------------------------------------

def test_disabled_hydrator_requests_nothing(qapp):
    dtos = [_make_dto(id="c0", poster_url="https://img.example/0.jpg")]
    model = _flat_model(dtos)
    stub = _StubImageCache()
    hydrator = ChannelThumbnailHydrator(model, stub)
    hydrator.set_enabled(False)

    hydrator.request_range(0, 0)
    hydrator._hydrate_pending_range()

    assert stub.async_requests == []


def test_sizehint_reserves_no_thumbnail_height_when_disabled(qapp):
    model = _flat_model([_make_dto(poster_url="https://img.example/x.jpg")])
    index = model.index(0)
    delegate = ChannelRowDelegate()
    delegate.set_density(DENSITY_COMFY)
    opt = _option()

    delegate.set_thumbnails_enabled(False)
    height_off = delegate.sizeHint(opt, index).height()

    delegate.set_thumbnails_enabled(True)
    height_on = delegate.sizeHint(opt, index).height()

    # ON reserves at least the fixed artwork height; OFF never does.
    # The PROPERTY, not the arithmetic: the row's padding formula is the
    # layout module's business and has changed once already, but "a row with
    # artwork is tall enough to show it, and one without is not" is what this
    # test is named for and is what must never drift.
    assert height_on >= _THUMB_H, (
        f"artwork enabled but the row is {height_on}px — too short for a "
        f"{_THUMB_H}px poster, which would be cropped"
    )
    assert height_off < _THUMB_H, (
        f"artwork disabled but the row still reserves {height_off}px"
    )
    assert height_on > height_off


# ---------------------------------------------------------------------------
# 6. Compact density never reserves a thumbnail
# ---------------------------------------------------------------------------

def test_compact_density_never_reserves_thumbnail(qapp):
    model = _flat_model([_make_dto(poster_url="https://img.example/x.jpg")])
    index = model.index(0)
    delegate = ChannelRowDelegate()
    delegate.set_density(DENSITY_COMPACT)
    opt = _option()

    delegate.set_thumbnails_enabled(False)
    height_off = delegate.sizeHint(opt, index).height()
    delegate.set_thumbnails_enabled(True)
    height_on = delegate.sizeHint(opt, index).height()

    assert height_off == height_on  # thumbnails setting has zero effect
    assert delegate._shows_thumbnail("channel", index) is False


def test_comfy_density_reserves_thumbnail_when_enabled(qapp):
    """Sanity converse of the compact test — comfy DOES gate on the flag."""
    model = _flat_model([_make_dto(poster_url="https://img.example/x.jpg")])
    index = model.index(0)
    delegate = ChannelRowDelegate()
    delegate.set_density(DENSITY_COMFY)

    delegate.set_thumbnails_enabled(False)
    assert delegate._shows_thumbnail("channel", index) is False
    delegate.set_thumbnails_enabled(True)
    assert delegate._shows_thumbnail("channel", index) is True


# ---------------------------------------------------------------------------
# Config field sanity
# ---------------------------------------------------------------------------

def test_config_channel_list_thumbnails_defaults_true():
    assert Config().channel_list_thumbnails is True
