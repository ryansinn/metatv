"""Behavioral tests for the Downloaded channel-list scope (DL-5).

Downloaded joins All/Hidden as a third mutually-exclusive scope tab. It is a
record/engaged view (DR-0007), same family as History/Favorites/Queue: it
lists channels with at least one COMPLETED download regardless of the
source's active state or Global Exclusions — a file already saved to disk is
the definition of engaged content and stays playable even when its source is
disabled.

Repository-level tests (1-3) drive a real file-backed ``Database`` on
``tmp_path`` (never ``:memory:``, per CLAUDE.md) so the ``downloaded_only``
predicate and its exemptions run against real SQL. Tests 4-5 drive the
``_NavMixin``/``_ChannelListMixin`` seams the way ``test_remember_search.py``
and ``test_load_channels_keep_rows.py`` already do.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, DownloadDB, ProviderDB
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures — file-backed DB (CLAUDE.md: never :memory:)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'downloaded_scope.db'}")
    database.create_tables()
    yield database
    database.close()


def _seed(db: Database, tmp_path: Path) -> Path:
    """3 channels: one completed download (on an INACTIVE provider, with a
    title a Global Exclusion keyword would hide), one running download, one
    with none at all.

    The completed download's ``dest_path`` points at a REAL file under
    ``tmp_path`` — DL-2: the scope is truth-checked against the disk, so a
    ``dest_path`` that does not exist must not count, and these tests would
    fail against the pre-DL-2 predicate if it were still a bare path string.
    Returns that file's path so callers can delete it mid-test.
    """
    completed_file = tmp_path / "forbidden-movie.mkv"
    completed_file.write_bytes(b"fake movie bytes")
    with db.session_scope() as session:
        session.add_all([
            ProviderDB(id="active-src", name="Active", type="xtream",
                       url="http://e.com", is_active=True),
            ProviderDB(id="inactive-src", name="Inactive", type="xtream",
                       url="http://e.com", is_active=False),
        ])
        session.add(ChannelDB(
            id="ch-completed", name="Forbidden Movie", provider_id="inactive-src",
            media_type="movie", source_id="src-completed",
        ))
        session.add(ChannelDB(
            id="ch-running", name="Running Movie", provider_id="active-src",
            media_type="movie", source_id="src-running",
        ))
        session.add(ChannelDB(
            id="ch-none", name="Untouched Movie", provider_id="active-src",
            media_type="movie", source_id="src-none",
        ))
        session.add(DownloadDB(
            id=str(uuid.uuid4()), channel_id="ch-completed", provider_id="inactive-src",
            channel_name="Forbidden Movie", source_url="http://x/1.mkv",
            dest_path=str(completed_file), state="completed",
        ))
        session.add(DownloadDB(
            id=str(uuid.uuid4()), channel_id="ch-running", provider_id="active-src",
            channel_name="Running Movie", source_url="http://x/2.mkv",
            dest_path=str(tmp_path / "running-movie.mkv"), state="running",
        ))
    return completed_file


# ---------------------------------------------------------------------------
# 1-3: the repository predicate + its record-view exemptions
# ---------------------------------------------------------------------------

def test_downloaded_scope_lists_only_completed(db, tmp_path):
    """downloaded_only=True returns exactly the completed-download channel."""
    _seed(db, tmp_path)
    with db.session_scope() as session:
        channels = RepositoryFactory(session).channels.get_all(downloaded_only=True)
        ids = {c.id for c in channels}
    assert ids == {"ch-completed"}, "running != downloaded; must not appear"


def test_downloaded_scope_ignores_source_scoping(db, tmp_path):
    """Its provider is inactive — the channel still appears (record-view exemption).

    Passes the inactive provider as excluded_provider_ids on purpose, mirroring
    what a caller (mistakenly) forwarding active-source scoping would do — the
    engine must ignore it for downloaded_only regardless of caller input.
    """
    _seed(db, tmp_path)
    with db.session_scope() as session:
        channels = RepositoryFactory(session).channels.get_all(
            downloaded_only=True, excluded_provider_ids=["inactive-src"],
        )
        ids = {c.id for c in channels}
    assert "ch-completed" in ids


def test_downloaded_scope_ignores_global_exclusions(db, tmp_path):
    """A Global Exclusion keyword matching its title still doesn't hide it."""
    _seed(db, tmp_path)
    with db.session_scope() as session:
        channels = RepositoryFactory(session).channels.get_all(
            downloaded_only=True, excluded_keywords=["forbidden"],
        )
        ids = {c.id for c in channels}
    assert "ch-completed" in ids


# ---------------------------------------------------------------------------
# DL-2: truth, not a stored boolean — a file deleted outside the app drops
# out of the scope on the next refresh.
# ---------------------------------------------------------------------------

def test_downloaded_scope_drops_a_completed_row_whose_file_is_gone(db, tmp_path):
    """The whole point of DL-2. ``state == "completed"`` is not enough."""
    completed_file = _seed(db, tmp_path)
    with db.session_scope() as session:
        before = {c.id for c in RepositoryFactory(session)
                  .channels.get_all(downloaded_only=True)}
    assert before == {"ch-completed"}

    completed_file.unlink()  # deleted outside the app

    with db.session_scope() as session:
        after = {c.id for c in RepositoryFactory(session)
                 .channels.get_all(downloaded_only=True)}
    assert after == set(), "the badge/scope must clear once the file is gone"


def test_downloaded_scope_predicate_verifies_the_filesystem_not_the_state_column(db, tmp_path):
    """Direct unit test of ``channel_downloads.predicate`` against a fake
    completed row whose ``dest_path`` was never written — proves the check
    is a real ``Path.is_file()``, not ``state == "completed"``."""
    from metatv.core.database import DownloadDB
    from metatv.core.repositories import channel_downloads

    with db.session_scope() as session:
        session.add(ChannelDB(
            id="ch-phantom", name="Phantom", provider_id="p",
            media_type="movie", source_id="src-phantom",
        ))
        session.add(DownloadDB(
            id=str(uuid.uuid4()), channel_id="ch-phantom", provider_id="p",
            channel_name="Phantom", source_url="http://x/3.mkv",
            dest_path=str(tmp_path / "never-written.mkv"), state="completed",
        ))
    with db.session_scope(commit=False) as session:
        matches = (session.query(ChannelDB)
                   .filter(channel_downloads.predicate(session)).all())
    assert matches == []


# ---------------------------------------------------------------------------
# 4: the three scope buttons are mutually exclusive, and the load carries
#    downloaded_only=True
# ---------------------------------------------------------------------------

def _make_scope_host():
    """A MainWindow built without __init__, wired like test_load_channels_keep_rows.py."""
    from metatv.gui import main_window as mw_module
    from metatv.gui.channel_list_model import ChannelListModel
    from tests.conftest import wire_channel_banner_widgets

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.channel_model = ChannelListModel()
    wire_channel_banner_widgets(win)
    win._bypass_global_exclusions = False
    win.all_channels = []
    win.stats_label = MagicMock()
    win.status_bar = MagicMock()
    win.config = MagicMock()
    win.config.global_filter_paused = True
    win.config.remember_search = True
    # Non-empty so `current_filter_state or (... hasattr(self, 'filter_panel') ...)`
    # short-circuits — hasattr on a __new__'d QObject raises RuntimeError, not
    # AttributeError (CLAUDE.md: bare-host trap).
    win.current_filter_state = {"_language_prefixes": [], "_region_prefixes": [],
                                "_platform_prefixes": [], "_quality_prefixes": []}
    win.search_input = MagicMock()
    win.search_input.text.return_value = ""
    win._search_debounce = MagicMock()
    win._bypass_tier1_filters = False
    win._details_genre_filter = None
    win._details_person_filter = None
    win._details_tag_filter = None
    win._details_category_filter = None
    win._details_id_filter = None
    win._id_filter_show_all = False
    win._search_page_size = 1000
    win._hidden_mode = False
    win._list_scope = "all"
    win._load_channels_token = [0]
    win._run_query = MagicMock()
    win._tab_all_btn = MagicMock()
    win._tab_hidden_btn = MagicMock()
    win._tab_downloaded_btn = MagicMock()
    win._hidden_banner = MagicMock()
    win.view_mode = "list"
    win.selected_provider_id = None
    win._register_cleanable = MagicMock()
    return win


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_scope_buttons_are_mutually_exclusive(qapp, monkeypatch):
    """Checking Downloaded unchecks All/Hidden; the load carries downloaded_only=True."""
    import metatv.gui.main_window_channels as mw_channels_module

    host = _make_scope_host()
    host.db = MagicMock()
    host.db.get_session.return_value = MagicMock()

    class _FakeRepos:
        def __init__(self, _session):
            self.providers = MagicMock()
            self.providers.get_all.return_value = []

    monkeypatch.setattr(mw_channels_module, "RepositoryFactory", _FakeRepos)

    captured = {}

    def _spy_query_channels(repos, params):
        captured["params"] = params
        return [], params

    monkeypatch.setattr(
        mw_channels_module._ChannelListMixin, "_query_channels", staticmethod(_spy_query_channels)
    )

    host._set_list_scope("downloaded")

    host._tab_downloaded_btn.setChecked.assert_called_with(True)
    host._tab_all_btn.setChecked.assert_called_with(False)
    host._tab_hidden_btn.setChecked.assert_called_with(False)
    assert host._list_scope == "downloaded"

    # Inspect the params the load was re-triggered with, at the _run_query seam.
    assert host._run_query.called
    query_fn = host._run_query.call_args[0][0]
    query_fn(MagicMock())  # invokes _spy_query_channels(repos, params)
    assert captured["params"]["downloaded_only"] is True


# ---------------------------------------------------------------------------
# 5: scope persists across save/restore
# ---------------------------------------------------------------------------

def test_scope_persists_and_restores():
    from metatv.gui import deferred_config_save as defer
    from metatv.gui.main_window_channels import _ChannelListMixin

    config = MagicMock()
    config.remember_search = True
    search_input = MagicMock()
    search_input.text.return_value = ""
    save_host = SimpleNamespace(
        config=config, search_input=search_input, selected_provider_id=None,
        _list_scope="downloaded", _hidden_mode=False,
        _details_genre_filter=None, _details_person_filter=None,
        _register_cleanable=MagicMock(),
    )
    _ChannelListMixin._save_search_state(save_host)
    assert defer.flush(save_host) is True

    saved_state = config.last_search_state
    assert saved_state["list_scope"] == "downloaded"
    assert saved_state["hidden_mode"] is False

    restore_config = MagicMock()
    restore_config.remember_search = True
    restore_config.last_search_state = saved_state
    load_channels = MagicMock()
    restore_host = SimpleNamespace(
        config=restore_config, search_input=MagicMock(),
        selected_provider_id=None, _hidden_mode=False,
        _details_genre_filter=None, _details_person_filter=None,
        _tab_all_btn=MagicMock(), _tab_hidden_btn=MagicMock(),
        _tab_downloaded_btn=MagicMock(),
        load_channels=load_channels,
    )
    restore_host.search_input.text.return_value = ""

    result = _ChannelListMixin.restore_search_state(restore_host)

    assert result is True
    assert restore_host._list_scope == "downloaded"
    assert restore_host._hidden_mode is False
    restore_host._tab_downloaded_btn.setChecked.assert_called_with(True)
    restore_host._tab_all_btn.setChecked.assert_called_with(False)
    restore_host._tab_hidden_btn.setChecked.assert_called_with(False)
    load_channels.assert_called_once()
