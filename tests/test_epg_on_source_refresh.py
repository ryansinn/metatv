"""EPG-on-source-refresh: a source refresh also pulls current EPG.

A *refresh* of an existing source previously did only a DB-only EPG relink — it
never re-fetched the guide, so the user had to separately hit "Refresh EPG" on the
EPG screen. ``_maybe_refresh_provider_epg`` closes that gap, while skipping sources
whose EPG is disabled or that have no usable EPG URL.

Driven via ``__new__`` (the real MainWindow init needs Qt + the world; the gating
helper needs only ``db`` / ``epg_manager`` / ``_on_provider_epg_refresh``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.gui.main_window_providers import _ProviderMixin


@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'epg.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_provider(db, *, epg_enabled: bool) -> str:
    from metatv.core.database import ProviderDB
    s = db.get_session()
    try:
        s.add(ProviderDB(id="p1", name="P", type="xtream",
                         url="http://x.example.com", is_active=True,
                         epg_enabled=epg_enabled))
        s.commit()
    finally:
        s.close()
    return "p1"


def _host(db, *, epg_url: str) -> _ProviderMixin:
    host = _ProviderMixin.__new__(_ProviderMixin)
    host.db = db
    host.epg_manager = MagicMock()
    host.epg_manager.effective_epg_url.return_value = epg_url
    host._on_provider_epg_refresh = MagicMock()
    return host


def test_enabled_with_url_triggers_epg(db):
    """epg_enabled + a usable URL → the canonical EPG refresh runs."""
    pid = _seed_provider(db, epg_enabled=True)
    host = _host(db, epg_url="http://x.example.com/epg.xml")
    host._maybe_refresh_provider_epg(pid)
    host._on_provider_epg_refresh.assert_called_once_with(pid)


def test_disabled_skips_epg(db):
    """A source with EPG turned off must NOT trigger an EPG fetch."""
    pid = _seed_provider(db, epg_enabled=False)
    host = _host(db, epg_url="http://x.example.com/epg.xml")
    host._maybe_refresh_provider_epg(pid)
    host._on_provider_epg_refresh.assert_not_called()


def test_no_url_skips_epg(db):
    """epg_enabled but no resolvable EPG URL → nothing to fetch, skip."""
    pid = _seed_provider(db, epg_enabled=True)
    host = _host(db, epg_url="")
    host._maybe_refresh_provider_epg(pid)
    host._on_provider_epg_refresh.assert_not_called()


def test_missing_provider_is_safe(db):
    """An unknown provider id must not crash and must not trigger a fetch."""
    host = _host(db, epg_url="http://x.example.com/epg.xml")
    host._maybe_refresh_provider_epg("nonexistent")
    host._on_provider_epg_refresh.assert_not_called()
