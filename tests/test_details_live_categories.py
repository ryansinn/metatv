"""Behavioral tests for two details-pane bugs.

Bug #3 — genres_label stuck on "Loading categories…" for LIVE channels:
    load_basic() must hide genres_label for live channels (metadata never arrives)
    and show the loading text only for VOD/series channels.

Bug #4 — version chips include channels from disabled/expired providers:
    _bg_fetch_versions() must exclude channels whose provider_id is in
    get_hidden_provider_ids(), so disabled/expired-source variants never
    appear as chips in the details pane.

All DB tests use file-backed SQLite (NOT :memory: — pooled connections each
get an empty schema there).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Shared Qt fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Process-wide QApplication for headless Qt widget tests."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Shared DB helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_tables()
    return db


def _add_provider(session, pid, *, is_active=True, exp=None):
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active,
        account_exp_date=exp,
    ))
    session.flush()


def _add_channel(session, cid, name, provider_id, media_type="live", **kwargs):
    from metatv.core.database import ChannelDB
    session.add(ChannelDB(
        id=cid, source_id=cid, provider_id=provider_id,
        name=name, media_type=media_type, **kwargs,
    ))
    session.flush()


# ---------------------------------------------------------------------------
# Bug #3 — genres_label visibility in load_basic
# ---------------------------------------------------------------------------

class TestLoadBasicGenresLabelVisibility:
    """load_basic hides genres_label for live; shows loading text for VOD/series."""

    def _make_config(self):
        """Minimal config stub for _MetadataSection."""
        return SimpleNamespace(
            category_name_overrides={},
            preferred_version_prefixes=[],
            rating_star_icon="★",
            # _TechnicalSection / _CastSection use these for toggle buttons:
            collapse_icon="▼",
            expand_icon="▶",
        )

    def _make_meta_section(self, qapp):
        """Construct a real _MetadataSection (QWidget requires Qt event loop)."""
        from metatv.gui.details_sections import _MetadataSection
        return _MetadataSection(self._make_config())

    def _fake_channel(self, media_type: str, name: str = "Test Channel") -> SimpleNamespace:
        return SimpleNamespace(
            name=name,
            media_type=media_type,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            is_adult=False,
            raw_data=None,
            provider_id="p1",
            id=str(uuid.uuid4()),
        )

    def test_live_channel_genres_label_hidden(self, qapp):
        """load_basic with a LIVE channel must hide genres_label, not show loading text."""
        obj = self._make_meta_section(qapp)
        channel = self._fake_channel("live", "EN | BEIN Sports 1")

        obj.load_basic(channel)

        # isHidden() reflects explicit hide() / show() state regardless of whether
        # the parent widget has been shown (unlike isVisible() which checks the tree).
        assert obj.genres_label.isHidden(), (
            "genres_label must be hidden for live channels — "
            "metadata never arrives so 'Loading categories...' would be permanent"
        )

    def test_live_channel_genres_label_not_showing_loading_text(self, qapp):
        """genres_label text must NOT be the loading sentinel for live channels."""
        from metatv.gui import icons as _icons
        obj = self._make_meta_section(qapp)
        channel = self._fake_channel("live")

        obj.load_basic(channel)

        loading_sentinel = f"{_icons.loading_icon} Loading categories..."
        assert obj.genres_label.text() != loading_sentinel, (
            "genres_label must not contain the 'Loading categories...' text "
            "for live channels — that text never gets replaced and would show forever"
        )

    def test_movie_channel_genres_label_shows_loading(self, qapp):
        """load_basic with a MOVIE channel must show genres_label with loading text."""
        from metatv.gui import icons as _icons
        obj = self._make_meta_section(qapp)
        channel = self._fake_channel("movie", "The Matrix (1999)")

        obj.load_basic(channel)

        # isHidden() reflects explicit hide()/show() calls on the child widget.
        assert not obj.genres_label.isHidden(), (
            "genres_label must NOT be hidden for movie channels — "
            "load_metadata() will replace it with real genres"
        )
        assert obj.genres_label.text() == f"{_icons.loading_icon} Loading categories...", (
            "genres_label must show loading text for movie channels "
            "while metadata is fetched"
        )

    def test_series_channel_genres_label_shows_loading(self, qapp):
        """load_basic with a SERIES channel must show genres_label with loading text."""
        from metatv.gui import icons as _icons
        obj = self._make_meta_section(qapp)
        channel = self._fake_channel("series", "Breaking Bad (2008)")

        obj.load_basic(channel)

        assert not obj.genres_label.isHidden(), (
            "genres_label must NOT be hidden for series channels"
        )
        assert obj.genres_label.text() == f"{_icons.loading_icon} Loading categories..."


# ---------------------------------------------------------------------------
# Bug #4 — version chips exclude hidden-provider channels
# ---------------------------------------------------------------------------

class TestVersionChipsProviderScoping:
    """_bg_fetch_versions must exclude variants from disabled/expired providers."""

    def _fake_config(self):
        return SimpleNamespace(
            global_filter_paused=False,
            global_filter_excluded_categories=[],
            global_filter_excluded_prefixes=[],
            preferred_version_prefixes=[],
            preferred_version_provider_ids=[],
            preferred_version_quality=None,
        )

    def _make_mixin(self, db):
        """Construct a _MetadataMixin via __new__ with minimal state."""
        from metatv.gui.main_window_metadata import _MetadataMixin

        emitted: list[tuple] = []

        class FakeSignal:
            def emit(self, channel_id, versions):
                emitted.append((channel_id, versions))

        obj = _MetadataMixin.__new__(_MetadataMixin)
        obj.db = db
        obj.config = self._fake_config()
        obj._versions_loaded = FakeSignal()
        obj._emitted = emitted
        return obj

    def test_disabled_provider_variant_excluded_from_live_versions(self, tmp_path):
        """A LIVE variant on a disabled provider appears as is_inactive=True in emitted versions.

        Source-picker chips show ALL variants (including inactive) so the user can
        opt into an inactive source explicitly (mirror-not-cage).  Inactive variants
        are marked is_inactive=True and rendered dimmed with a 'Reactivate & play'
        affordance rather than hidden entirely.
        """
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "active-p", is_active=True)
            _add_provider(session, "disabled-p", is_active=False)
            # Current channel on active provider
            _add_channel(session, "ch-main", "EN | BEIN Sports 1",
                         "active-p", media_type="live", detected_prefix="EN")
            # Same-normalized name on disabled provider
            _add_channel(session, "ch-dead", "EN | BEIN Sports 1",
                         "disabled-p", media_type="live", detected_prefix="EN")
            # Another variant on active provider (different prefix)
            _add_channel(session, "ch-alt", "AR | BEIN Sports 1",
                         "active-p", media_type="live", detected_prefix="AR")

        import concurrent.futures
        obj = self._make_mixin(db)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(obj._bg_fetch_versions, "ch-main")
            future.result(timeout=10)

        assert obj._emitted, "No versions signal was emitted"
        _, versions = obj._emitted[0]
        version_map = {v.channel_id: v for v in versions}

        # Inactive-source variant IS included but flagged is_inactive=True
        assert "ch-dead" in version_map, (
            "Inactive-source variant must be included in version chips (dimmed, with reactivate affordance)"
        )
        assert version_map["ch-dead"].is_inactive is True, (
            "Variant on a disabled provider must be marked is_inactive=True"
        )
        # Active-source variant is not marked inactive
        assert "ch-alt" in version_map, (
            "Variant on an active provider must still appear as a version chip"
        )
        assert version_map["ch-alt"].is_inactive is False, (
            "Active-source variant must have is_inactive=False"
        )
        db.close()

    def test_disabled_provider_variant_excluded_from_vod_versions(self, tmp_path):
        """A VOD variant on a disabled provider appears as is_inactive=True in emitted versions.

        Source-picker chips show ALL variants (including inactive) so the user can
        opt into an inactive source explicitly (mirror-not-cage).  Inactive variants
        are marked is_inactive=True and rendered dimmed with a 'Reactivate & play'
        affordance rather than hidden entirely.
        """
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "ok-p",  is_active=True)
            _add_provider(session, "off-p", is_active=False)
            # VOD current channel on active provider
            _add_channel(session, "vod-main", "EN The Matrix (1999)",
                         "ok-p", media_type="movie", detected_prefix="EN")
            # Same-normalized name on disabled provider
            _add_channel(session, "vod-dead", "EN The Matrix (1999)",
                         "off-p", media_type="movie", detected_prefix="EN")
            # Another variant (4K) on active provider
            _add_channel(session, "vod-4k", "4K The Matrix (1999)",
                         "ok-p", media_type="movie", detected_prefix="4K")

        import concurrent.futures
        obj = self._make_mixin(db)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(obj._bg_fetch_versions, "vod-main")
            future.result(timeout=10)

        assert obj._emitted, "No versions signal was emitted"
        _, versions = obj._emitted[0]
        version_map = {v.channel_id: v for v in versions}

        # Inactive-source variant IS included but flagged is_inactive=True
        assert "vod-dead" in version_map, (
            "Inactive-source variant must be included in version chips (dimmed, with reactivate affordance)"
        )
        assert version_map["vod-dead"].is_inactive is True, (
            "VOD variant on a disabled provider must be marked is_inactive=True"
        )
        # Active-source variant is still shown normally
        assert "vod-4k" in version_map, (
            "VOD variant on an active provider must still appear as a version chip"
        )
        assert version_map["vod-4k"].is_inactive is False, (
            "Active-source variant must have is_inactive=False"
        )
        db.close()

    def test_active_only_providers_all_variants_appear(self, tmp_path):
        """When all providers are active, all normalized variants are included."""
        db = _make_db(tmp_path)

        with db.session_scope() as session:
            _add_provider(session, "p1", is_active=True)
            _add_provider(session, "p2", is_active=True)
            _add_channel(session, "live-main", "EN | BEIN Sports 1",
                         "p1", media_type="live", detected_prefix="EN")
            _add_channel(session, "live-alt",  "EN | BEIN Sports 1",
                         "p2", media_type="live", detected_prefix="EN")

        import concurrent.futures
        obj = self._make_mixin(db)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(obj._bg_fetch_versions, "live-main")
            future.result(timeout=10)

        assert obj._emitted, "No versions signal was emitted"
        _, versions = obj._emitted[0]
        version_ids = {v.channel_id for v in versions}

        assert "live-alt" in version_ids, (
            "With all providers active, cross-provider variants must appear"
        )
        db.close()
