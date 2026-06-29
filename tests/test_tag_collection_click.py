"""Behavioral tests for clickable Tags / Collections in the details pane.

Covers the three layers the feature touches:

1. ``_TagsSection`` chips are interactive — LEFT-click emits
   ``tag_filter_clicked(facet_type, value)`` and RIGHT-click emits
   ``tag_discover_clicked(facet_type, value)`` for the chip's exact facet/value.

2. The strict SQL context filter actually narrows the corpus —
   ``ChannelRepository.get_all(context_tag_filter=(type, value))`` returns ONLY
   channels carrying that exact tag (no hierarchy rollup), and
   ``context_category_filter`` returns the curated provider category set.

3. A COLLECTION chip resolves to the curated category membership, NOT the lossy
   'collection' residual: the control-layer handler
   (``_NavMixin._on_tag_filter_requested``) resolves the current channel's stored
   ``category`` and filters on it, and the residual value is demonstrably
   ambiguous (two different curated categories share one residual).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.database import Database, ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import ChannelTagDTO
from metatv.gui import icons as _icons


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Process-wide QApplication for headless Qt widget tests."""
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


def _make_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'tagclick.db'}")
    db.create_tables()
    return db


def _add_channel(session, *, name: str, category: str = "") -> str:
    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id="src1",
        provider_id="prov1",
        name=name,
        category=category,
        media_type="movie",
    ))
    session.flush()
    return cid


def _fake_config():
    return SimpleNamespace(
        collapse_icon=_icons.collapse_icon,
        expand_icon=_icons.expand_icon,
        details_pane_collapsed_sections=[],
    )


def _collect_chips(section) -> list:
    """Walk the section's content tree and return every chip QPushButton."""
    from PyQt6.QtWidgets import QPushButton

    result = []
    layout = section._content.layout()
    if layout is None:
        return result
    for i in range(layout.count()):
        w = layout.itemAt(i).widget() if layout.itemAt(i) else None
        if w is None or w.layout() is None:
            continue
        row = w.layout()
        for j in range(row.count()):
            sub = row.itemAt(j)
            if sub and isinstance(sub.widget(), QPushButton):
                result.append(sub.widget())
    return result


# ---------------------------------------------------------------------------
# 1. _TagsSection interactivity
# ---------------------------------------------------------------------------

class TestTagsSectionInteractivity:
    """Tag chips emit filter (left) / discover (right) with the exact facet."""

    def _section(self):
        from metatv.gui.details_sections import _TagsSection
        return _TagsSection(_fake_config())

    def test_left_click_emits_tag_filter_clicked(self, qapp):
        sec = self._section()
        captured: list[tuple[str, str]] = []
        sec.tag_filter_clicked.connect(lambda ft, v: captured.append((ft, v)))

        sec.load([ChannelTagDTO("genre", "Drama", True, 0.9, ("provider_category",))])
        chips = _collect_chips(sec)
        assert len(chips) == 1
        chips[0].click()  # left-click

        assert captured == [("genre", "Drama")], (
            "Left-click must emit tag_filter_clicked with the exact (facet, value)"
        )

    def test_right_click_emits_tag_discover_clicked(self, qapp):
        from PyQt6.QtCore import QPoint

        sec = self._section()
        captured: list[tuple[str, str]] = []
        sec.tag_discover_clicked.connect(lambda ft, v: captured.append((ft, v)))

        sec.load([ChannelTagDTO("language", "French", False, 0.4, ("name_parse",))])
        chips = _collect_chips(sec)
        assert len(chips) == 1
        # Right-click → custom context menu request signal.
        chips[0].customContextMenuRequested.emit(QPoint(1, 1))

        assert captured == [("language", "French")], (
            "Right-click must emit tag_discover_clicked with the exact (facet, value)"
        )

    def test_collection_chip_emits_collection_facet(self, qapp):
        sec = self._section()
        captured: list[tuple[str, str]] = []
        sec.tag_filter_clicked.connect(lambda ft, v: captured.append((ft, v)))

        sec.load([ChannelTagDTO("collection", "Wow Action", True, 0.9, ("header",))])
        chips = _collect_chips(sec)
        chips[0].click()

        assert captured == [("collection", "Wow Action")]

    def test_chip_has_pointing_hand_cursor(self, qapp):
        from PyQt6.QtCore import Qt

        sec = self._section()
        sec.load([ChannelTagDTO("genre", "Drama", True, 0.9, ("provider_category",))])
        chip = _collect_chips(sec)[0]
        assert chip.cursor().shape() == Qt.CursorShape.PointingHandCursor

    def test_chip_tooltip_mentions_actions(self, qapp):
        sec = self._section()
        sec.load([ChannelTagDTO("genre", "Drama", True, 0.9, ("provider_category",))])
        tip = _collect_chips(sec)[0].toolTip()
        assert "Click" in tip and "Right-click" in tip


# ---------------------------------------------------------------------------
# 2. Strict SQL context filter (exact tag + curated category)
# ---------------------------------------------------------------------------

class TestContextFilterSQL:
    """get_all(context_tag_filter=...) / context_category_filter=... are strict."""

    def test_exact_tag_filter_returns_only_matching(self, tmp_path):
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            drama = _add_channel(session, name="Drama Movie")
            comedy = _add_channel(session, name="Comedy Movie")
            repos.tags.set_content_tags(drama, [("genre", "Drama", "provider_category")])
            repos.tags.set_content_tags(comedy, [("genre", "Comedy", "provider_category")])

            rows = repos.channels.get_all(context_tag_filter=("genre", "Drama"))
            ids = {r.id for r in rows}

        assert drama in ids, "channel with the exact tag must be returned"
        assert comedy not in ids, "channel with a different tag value must be excluded"

    def test_exact_tag_filter_no_hierarchy_rollup(self, tmp_path):
        """Exact match only — a near value (different string) does not pass."""
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            ch = _add_channel(session, name="Sci-Fi Movie")
            repos.tags.set_content_tags(ch, [("genre", "Science Fiction", "genre")])

            rows = repos.channels.get_all(context_tag_filter=("genre", "Sci-Fi"))

        assert rows == [], "no fuzzy/hierarchy match — only the exact stored value passes"

    def test_category_filter_returns_curated_set(self, tmp_path):
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            a = _add_channel(session, name="Action One", category="Action HD")
            b = _add_channel(session, name="Action Two", category="Action HD")
            c = _add_channel(session, name="Kids One", category="Kids")

            rows = repos.channels.get_all(context_category_filter="Action HD")
            ids = {r.id for r in rows}

        assert ids == {a, b}, "category filter returns exactly the curated category set"
        assert c not in ids


# ---------------------------------------------------------------------------
# 3. Collection click resolves to the curated category, NOT the residual
# ---------------------------------------------------------------------------

class TestCollectionResolution:
    """A collection chip groups on ChannelDB.category, not the lossy residual."""

    def test_residual_is_ambiguous_but_category_is_not(self, tmp_path):
        """Two channels share one 'collection' residual but DIFFERENT categories.

        Filtering on the residual collapses both curated sets together (lossy);
        filtering on category returns only the one curated set — which is why the
        collection click must resolve to category, not the residual.
        """
        db = _make_db(tmp_path)
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            a = _add_channel(session, name="Action One", category="Action HD")
            b = _add_channel(session, name="Kids One", category="Kids HD")
            # Same lossy residual on two DIFFERENT curated categories.
            repos.tags.set_content_tags(a, [("collection", "Wow", "header")])
            repos.tags.set_content_tags(b, [("collection", "Wow", "header")])

            by_residual = {
                r.id for r in repos.channels.get_all(context_tag_filter=("collection", "Wow"))
            }
            by_category = {
                r.id for r in repos.channels.get_all(context_category_filter="Action HD")
            }

        assert by_residual == {a, b}, "residual is lossy — collapses distinct curated sets"
        assert by_category == {a}, "category is the precise curated grouping"

    def test_handler_resolves_collection_to_channel_category(self, tmp_path):
        """_on_tag_filter_requested('collection', …) filters on the channel's category."""
        from metatv.gui.main_window_nav import _NavMixin

        db = _make_db(tmp_path)
        with db.session_scope() as session:
            cid = _add_channel(session, name="Action One", category="Action HD")

        host = self._fake_host(db, current_channel_id=cid)
        host._on_tag_filter_requested("collection", "Wow Action Residual")

        assert host._details_category_filter == "Action HD", (
            "collection click must resolve to the channel's curated category"
        )
        assert host._details_tag_filter is None, "collection routes to category, not the tag path"
        assert host._context_filter_label.text == "Collection: Action HD"
        assert host._load_called, "load_channels must be triggered to apply the filter"

    def test_handler_routes_non_collection_to_exact_tag(self, tmp_path):
        from metatv.gui.main_window_nav import _NavMixin

        db = _make_db(tmp_path)
        with db.session_scope() as session:
            cid = _add_channel(session, name="Drama Movie", category="Drama HD")

        host = self._fake_host(db, current_channel_id=cid)
        host._on_tag_filter_requested("genre", "Drama")

        assert host._details_tag_filter == ("genre", "Drama")
        assert host._details_category_filter is None
        assert host._context_filter_label.text == "Genre: Drama"

    def test_resolve_returns_none_without_current_channel(self, tmp_path):
        db = _make_db(tmp_path)
        host = self._fake_host(db, current_channel_id=None)
        assert host._resolve_current_channel_category() is None

    # -- fake control-layer host ------------------------------------------- #

    @staticmethod
    def _fake_host(db, *, current_channel_id):
        from metatv.gui.main_window_nav import _NavMixin

        host = SimpleNamespace()
        host.db = db
        host.details_pane = SimpleNamespace(
            current_channel=(
                SimpleNamespace(id=current_channel_id)
                if current_channel_id else None
            )
        )
        host._details_genre_filter = None
        host._details_person_filter = None
        host._details_tag_filter = None
        host._details_category_filter = None
        host._context_filter_label = SimpleNamespace(text="", setText=lambda t: setattr(host._context_filter_label, "text", t))
        host._context_filter_chip = SimpleNamespace(show=lambda: None, hide=lambda: None)
        host._save_search_state = lambda: None
        host.switch_to_list_view = lambda: None
        host._load_called = []
        host.load_channels = lambda: host._load_called.append(True)
        # Bind the real mixin methods under test.
        for name in (
            "_reset_context_filters",
            "_resolve_current_channel_category",
            "_on_tag_filter_requested",
        ):
            setattr(host, name, getattr(_NavMixin, name).__get__(host))
        return host
