"""Behavior tests: Sources status strip + Sources manager view (Wave 6).

Sources left the sidebar ``CollapsibleSection`` stack for an always-visible
status strip (compact "N active / M expiring" summary above Settings) plus a
full-window Sources manager view (provider list + embedded configuration).
See ``metatv/gui/sidebar/sources_strip.py`` and
``metatv/gui/sources_manager_view.py``.

These execute the real widget/view/config code — a real file-backed
``Database`` on ``tmp_path`` (never ``:memory:``), real Qt widgets under the
offscreen platform — never source-string shape checks.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.repositories import RepositoryFactory


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'sources_strip_manager.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(
    session, pid: str, *, name: str | None = None, is_active: bool = True,
    exp_days: float | None = None, created_days_ago: float | None = None,
) -> str:
    """Seed a ProviderDB row. exp_days/created_days_ago are relative to now."""
    exp = datetime.now() + timedelta(days=exp_days) if exp_days is not None else None
    created = (
        datetime.now() - timedelta(days=created_days_ago)
        if created_days_ago is not None else None
    )
    session.add(ProviderDB(
        id=pid, name=name or f"Provider {pid}", type="xtream",
        url="http://example.com", username="u", password="p",
        is_active=is_active, account_exp_date=exp, account_created_at=created,
    ))
    session.flush()
    return pid


# ---------------------------------------------------------------------------
# 1. summarize_providers — pure classification logic behind the strip text
# ---------------------------------------------------------------------------

class TestSummarizeProviders:
    def test_active_and_expiring_split(self, db):
        from metatv.gui.sidebar.sources_strip import summarize_providers

        with db.session_scope() as session:
            _provider(session, "healthy", is_active=True, exp_days=120, created_days_ago=30)
            _provider(session, "soon", is_active=True, exp_days=1, created_days_ago=30)
            _provider(session, "off", is_active=False)  # no exp date, disabled — neither bucket

        with db.session_scope(commit=False) as session:
            providers = RepositoryFactory(session).providers.get_all()
            active, expiring = summarize_providers(providers, datetime.now())

        assert active == 1
        assert expiring == 1


# ---------------------------------------------------------------------------
# 2. SourcesStatusStrip — renders the summary, Refresh All, click-to-open
# ---------------------------------------------------------------------------

class TestSourcesStatusStrip:
    def test_strip_shows_active_and_expiring_summary(self, qapp, db):
        from metatv.gui.sidebar.sources_strip import SourcesStatusStrip

        with db.session_scope() as session:
            _provider(session, "healthy", is_active=True, exp_days=120, created_days_ago=30)
            _provider(session, "soon", is_active=True, exp_days=1, created_days_ago=30)

        strip = SourcesStatusStrip(SimpleNamespace(), db)

        text = strip._summary_lbl.text()
        assert "1 active" in text
        assert "1 expiring" in text

    def test_refresh_all_button_emits_refresh_all_clicked(self, qapp, db):
        from metatv.gui.sidebar.sources_strip import SourcesStatusStrip

        strip = SourcesStatusStrip(SimpleNamespace(), db)
        received = []
        strip.refreshAllClicked.connect(lambda: received.append(True))

        strip._refresh_btn.click()

        assert received == [True]

    def test_set_busy_disables_refresh_button(self, qapp, db):
        from metatv.gui.sidebar.sources_strip import SourcesStatusStrip

        strip = SourcesStatusStrip(SimpleNamespace(), db)
        assert strip._refresh_btn.isEnabled()

        strip.set_busy(True)
        assert not strip._refresh_btn.isEnabled()

        strip.set_busy(False)
        assert strip._refresh_btn.isEnabled()

    def test_click_on_strip_emits_clicked_signal(self, qapp, db):
        """A press anywhere on the strip (not the Refresh button) opens the manager —
        this is what MainWindow.create_sidebar wires to switch_to_sources_manager."""
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        from metatv.gui.sidebar.sources_strip import SourcesStatusStrip

        strip = SourcesStatusStrip(SimpleNamespace(), db)
        received = []
        strip.clicked.connect(lambda: received.append(True))

        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(4, 4),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        strip.mousePressEvent(event)

        assert received == [True]


# ---------------------------------------------------------------------------
# 3. MainWindow.switch_to_sources_manager — the strip's `clicked` target
# ---------------------------------------------------------------------------

class TestSwitchToSourcesManager:
    def test_switch_shows_manager_and_activates_it(self):
        """Real ``_NavMixin`` instance (same idiom as
        test_series_drill_overlay_hide.py) so ``self._hide_all_content_views()``
        binds via normal method resolution — proves the seam the strip's
        `clicked` signal is wired to in MainWindow.create_sidebar."""
        from metatv.gui.main_window_nav import _NavMixin

        manager = MagicMock()
        host = _NavMixin.__new__(_NavMixin)
        host.epg_view = MagicMock()
        host.discover_view = MagicMock()
        host.preferences_view = MagicMock()
        host.channels_list = MagicMock()
        host.series_tree = MagicMock()
        host.provider_editor = MagicMock()
        host.search_controls = MagicMock()
        host._hidden_banner = MagicMock()
        host.back_button = MagicMock()
        host.breadcrumb_label = MagicMock()
        host.stats_label = MagicMock()
        host.sources_manager_view = manager
        host._deactivate_view_chips = MagicMock()

        host.switch_to_sources_manager()

        assert host.view_mode == "sources_manager"
        # _hide_all_content_views() blanks it first (setVisible(False), and — since
        # the mock reads as "visible" by default — on_deactivate()); the switch then
        # shows it. The LAST setVisible call is what the user actually sees.
        manager.setVisible.assert_called_with(True)
        manager.on_activate.assert_called_once()


# ---------------------------------------------------------------------------
# 4. SourcesManagerView — lists every provider, shows the selected one's config
# ---------------------------------------------------------------------------

class TestSourcesManagerView:
    def test_lists_every_provider_and_auto_selects_one(self, qapp, db):
        from metatv.gui.provider_editor import ProviderEditorView
        from metatv.gui.sources_manager_view import SourcesManagerView

        with db.session_scope() as session:
            _provider(session, "p1", name="Provider One")
            _provider(session, "p2", name="Provider Two")

        editor = ProviderEditorView(db)
        view = SourcesManagerView(SimpleNamespace(), db, editor)
        view.on_activate()

        assert len(view._item_widgets) == 2
        assert view.sources_tree.topLevelItemCount() == 2
        assert view._selected_id in ("p1", "p2")
        # The embedded (real) editor actually loaded the selected provider.
        assert editor._provider_id == view._selected_id

    def test_select_provider_switches_the_embedded_editor(self, qapp, db):
        from metatv.gui.provider_editor import ProviderEditorView
        from metatv.gui.sources_manager_view import SourcesManagerView

        with db.session_scope() as session:
            _provider(session, "p1", name="Provider One")
            _provider(session, "p2", name="Provider Two")

        editor = ProviderEditorView(db)
        view = SourcesManagerView(SimpleNamespace(), db, editor)
        view.on_activate()

        view.select_provider("p2")

        assert view._selected_id == "p2"
        assert editor._provider_id == "p2"
        # isVisibleTo (not isVisible) — the view is never top-level .show()'n in
        # this test, so isVisible() would read False regardless of the explicit
        # setVisible(True) call; isVisibleTo checks visibility relative to `view`.
        assert editor.isVisibleTo(view)


# ---------------------------------------------------------------------------
# 5. Config migration — "sources" dropped from stored sidebar lists
# ---------------------------------------------------------------------------

class TestSourcesSidebarRetirementMigration:
    def test_inject_new_sections_strips_sources(self):
        from metatv.core.config import Config

        cfg = Config()
        cfg.sidebar_sections = [
            "alerts", "recommended", "queue", "favorites", "history", "sources",
        ]
        cfg.sidebar_visible_sections = [
            "alerts", "recommended", "queue", "favorites", "history", "sources",
        ]

        cfg._inject_new_sections()

        assert "sources" not in cfg.sidebar_sections
        assert "sources" not in cfg.sidebar_visible_sections
        # Unrelated ids are preserved.
        assert "alerts" in cfg.sidebar_sections
        assert "history" in cfg.sidebar_sections

    def test_fresh_config_never_had_sources(self):
        """A brand-new config's defaults don't include "sources" at all."""
        from metatv.core.config import Config

        cfg = Config()

        assert "sources" not in cfg.sidebar_sections
        assert "sources" not in cfg.sidebar_visible_sections


# ---------------------------------------------------------------------------
# 6. _sources_status_target — the chokepoint account-info-updated (and every
#    other busy/refresh call site) resolves through.
# ---------------------------------------------------------------------------

class TestSourcesStatusTarget:
    def test_prefers_manager_view_when_present(self):
        from metatv.gui.main_window import MainWindow

        manager = MagicMock()
        me = SimpleNamespace(
            sources_manager_view=manager, sidebar_sections={"sources": MagicMock()}
        )

        assert MainWindow._sources_status_target(me) is manager

    def test_falls_back_to_legacy_sidebar_sections(self):
        """Back-compat: test doubles that still stub the retired sidebar
        section (many existing tests) keep working unchanged."""
        from metatv.gui.main_window import MainWindow

        legacy = MagicMock()
        me = SimpleNamespace(sidebar_sections={"sources": legacy})

        assert MainWindow._sources_status_target(me) is legacy

    def test_returns_none_when_neither_present(self):
        from metatv.gui.main_window import MainWindow

        me = SimpleNamespace(sidebar_sections={})

        assert MainWindow._sources_status_target(me) is None


# ---------------------------------------------------------------------------
# 7. Account-info-updated poll still reaches the strip (+ the manager)
# ---------------------------------------------------------------------------

class TestAccountInfoUpdatedReachesStrip:
    def test_account_info_updated_refreshes_manager_and_strip(self):
        """A real MainWindow.__new__ host (not SimpleNamespace) — the handler
        calls self._sources_status_target(), a bound METHOD lookup, which needs
        a genuine instance of the class (same idiom as test_provider_view_refresh's
        _bare_window())."""
        from metatv.gui.main_window import MainWindow

        manager = MagicMock()
        strip = MagicMock()
        me = MainWindow.__new__(MainWindow)
        me.sources_manager_view = manager
        me.sources_strip = strip

        MainWindow._on_account_info_updated(me, "p1")

        manager.refresh.assert_called_once()
        strip.refresh.assert_called_once()

    def test_account_info_updated_is_safe_with_neither_built_yet(self):
        """Must not crash if called before setup_ui() has constructed either."""
        from metatv.gui.main_window import MainWindow

        me = MainWindow.__new__(MainWindow)
        me.sidebar_sections = {}

        MainWindow._on_account_info_updated(me, "p1")  # must not raise
