"""Fresh start (Tools menu): wipe to a first launch, optionally keeping sources.

Drives the real core module on a tmp HOME (conftest isolates Path.home), and
the real restore path on a real database.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from metatv.core import app_paths, fresh_start
from metatv.core.database import ProviderDB


def _populate():
    db = app_paths.data_dir() / "metatv.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_text("db")
    (app_paths.data_dir() / "metatv.db-wal").write_text("wal")
    cfg = app_paths.config_dir()
    (cfg / "logs").mkdir(parents=True, exist_ok=True)
    (cfg / "config.yaml").write_text("theme: x")
    (cfg / "config.yaml.bak").write_text("theme: y")
    (cfg / "logs" / "metatv.log").write_text("log")
    (app_paths.image_cache_dir()).mkdir(parents=True, exist_ok=True)
    (app_paths.image_cache_dir() / "poster.jpg").write_text("img")
    return db


def test_a_fresh_start_deletes_the_library_settings_and_cache_but_not_logs():
    db = _populate()
    fresh_start.request(db, None)
    assert fresh_start.pending()

    assert fresh_start.perform() is None
    cfg = app_paths.config_dir()
    assert not db.exists() and not (app_paths.data_dir() / "metatv.db-wal").exists()
    assert not (cfg / "config.yaml").exists() and not (cfg / "config.yaml.bak").exists()
    assert not app_paths.cache_dir().exists()
    assert (cfg / "logs" / "metatv.log").exists(), "logs are kept"
    assert not fresh_start.pending()


def test_keeping_sources_hands_them_back_after_the_wipe():
    db = _populate()
    src = {"id": "p1", "name": "TREX", "url": "http://a", "urls": [{"url": "http://a"}]}
    fresh_start.request(db, [src])
    assert fresh_start.perform() == [src]
    assert not db.exists()


def test_a_cancelled_close_withdraws_the_request():
    db = _populate()
    fresh_start.request(db, None)
    fresh_start.cancel()
    assert fresh_start.perform() is None
    assert db.exists(), "nothing may be wiped once the request is withdrawn"


def test_restored_sources_are_added_through_the_normal_add_path(db):
    from metatv.gui.main_window import MainWindow

    host = SimpleNamespace(db=db, _on_provider_added=MagicMock())
    MainWindow.restore_sources(host, [
        {"id": "p1", "name": "TREX", "type": "xtream", "url": "http://a",
         "urls": [{"url": "http://a", "success_count": 9}, {"url": "http://b"}],
         "username": "u", "password": "p", "is_active": True, "epg_enabled": False},
    ])
    with db.session_scope(commit=False) as session:
        p = session.query(ProviderDB).filter_by(id="p1").one()
        assert p.name == "TREX" and p.username == "u"
        assert [u["url"] for u in p.urls] == ["http://a", "http://b"]
        assert all(u.get("success_count", 0) == 0 for u in p.urls), "stats start empty"
    host._on_provider_added.assert_called_once_with("p1", False)
    assert host._guided_to_first_source is True
