"""Background stream/metadata work must stop when the window closes (#crash).

Reproduced from a real user log: the owner started an episode, the preflight
began working through 19 alternate hosts, and they quit the app 21 seconds
in. ``closeEvent`` saved config, cleaned up mpv, closed the database, and
destroyed ``MainWindow`` — but the failover loop in
``validate_and_failover_stream_url`` (``main_window_streaming.py``) kept
making network calls for 78 more seconds against a database that no longer
existed, then fired its ``future.add_done_callback`` and crashed with
``RuntimeError: wrapped C/C++ object of type MainWindow has been deleted``
when ``_on_preflight_done`` (``main_window_series.py``) tried to
``self._episode_failed.emit(...)`` into a destroyed window.

The fix: ``MainWindow.__init__`` sets a plain ``self._shutting_down = False``
attribute (first statement); ``closeEvent`` flips it to ``True`` as the very
FIRST statement, before any teardown (geometry save, layout persist, or the
``_cleanables`` loop that closes the database) runs. Reading a plain Python
attribute off a PyQt wrapper is always safe — even after the underlying C++
object is gone — so this has no sip/TOCTOU window; only calling INTO the C++
side (``emit``, any widget method) raises. Background code polls the flag and
abandons work instead of emitting into a dying window or querying a closed
DB:

  * ``validate_and_failover_stream_url`` (main_window_streaming.py) checks it
    at the top of every ``for alt_base in candidate_bases:`` iteration.
  * ``_on_preflight_done`` (main_window_series.py) checks it as the first
    statement, before ``future.result()`` is even unpacked.
  * ``on_metadata_loaded`` (main_window_metadata.py) checks it as the first
    statement, same reasoning.

All DB tests use file-backed SQLite (tmp_path), per CLAUDE.md rule — never
``:memory:``, and the isolated-user-config fixture (autouse, conftest.py)
keeps this away from any real ``~/.config/metatv``.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from metatv.core.models import ProviderURL


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    return d


def _insert_episode(session, episode_id: str, provider_id: str, stream_url: str,
                     title: str = "Test Episode"):
    from metatv.core.database import EpisodeDB
    ep = EpisodeDB(
        id=episode_id,
        season_id=str(uuid.uuid4()),
        series_id=str(uuid.uuid4()),
        provider_id=provider_id,
        episode_id=episode_id,
        episode_num=1,
        season_num=1,
        title=title,
        stream_url=stream_url,
    )
    session.add(ep)
    session.flush()
    return ep


def _read_stream_url(db, episode_id: str) -> str:
    """Re-read an episode's stored stream_url from a FRESH session."""
    from metatv.core.database import EpisodeDB
    with db.session_scope(commit=False) as session:
        row = session.get(EpisodeDB, episode_id)
        return row.stream_url


def _session_scope_yielding(session):
    """Return a session_scope contextmanager double that yields *session*."""
    @contextmanager
    def _scope(**_kwargs):
        yield session
    return _scope


class _ImmediateFuture:
    """A future-like object that is already done: .result()/.add_done_callback()
    both work synchronously, so tests don't need a real background thread."""

    def __init__(self):
        self._result = None
        self._exc = None

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._result

    def add_done_callback(self, cb):
        cb(self)


class _ImmediateExecutor:
    """A fake ThreadPoolExecutor whose submit() runs the callable immediately
    on the calling thread and returns an already-done future."""

    def submit(self, fn, *args, **kwargs):
        fut = _ImmediateFuture()
        try:
            fut._result = fn(*args, **kwargs)
        except Exception as e:  # pragma: no cover - defensive, mirrors real executor
            fut._exc = e
        return fut


# ===========================================================================
# 1. Failover aborts on shutdown — zero alternate-URL attempts.
#    Paired with the not-shutting-down case: proves the guard is
#    load-bearing, not just a coincidental early return.
# ===========================================================================

def _make_failover_scenario(shutting_down: bool, validate_fn):
    """Build a _StreamingMixin host + patched provider plumbing for a
    validate_and_failover_stream_url() call with 5 alternate candidates.

    Returns (obj, primary_url, alt_bases, alt_entries).
    """
    from metatv.gui.main_window_streaming import _StreamingMixin

    obj = _StreamingMixin.__new__(_StreamingMixin)
    obj._shutting_down = shutting_down
    obj.db = MagicMock()

    primary = "http://primary.example.com/live/u/p/1234.ts"
    alt_bases = [f"http://alt{i}.example.com" for i in range(1, 6)]
    alt_entries = [ProviderURL(url=b) for b in alt_bases]

    provider_db = MagicMock()
    provider_db.name = "TestProvider"
    provider_model = MagicMock()
    provider_model.ordered_urls.return_value = alt_bases
    provider_model.urls = alt_entries

    repos = MagicMock()
    repos.providers.get_by_id.return_value = provider_db
    repos.providers.to_model.return_value = provider_model

    session = MagicMock()
    obj.db.session_scope = _session_scope_yielding(session)
    obj.validate_stream_url = validate_fn

    return obj, repos, primary, alt_bases, alt_entries


def test_failover_aborts_immediately_when_shutting_down():
    """_shutting_down=True: the loop bails on the FIRST iteration — zero
    alternate-URL validations are attempted, and the result is ("", None)."""
    calls: list[str] = []

    def _validate(url):
        calls.append(url)
        return (False, None)  # primary always fails, no text error

    obj, repos, primary, alt_bases, alt_entries = _make_failover_scenario(
        shutting_down=True, validate_fn=_validate
    )

    with patch("metatv.gui.main_window_streaming.RepositoryFactory", return_value=repos):
        result = obj.validate_and_failover_stream_url(primary, "prov-1")

    assert result == ("", None)
    assert calls == [primary], (
        f"expected only the primary attempt, zero alternates tried; got {calls}"
    )


def test_failover_attempts_alternates_when_not_shutting_down():
    """Same setup, _shutting_down=False — the loop DOES try alternates.

    This is the load-bearing half of the pair: it proves
    validate_and_failover_stream_url isn't simply broken (which would also
    return ("", None) with zero calls) — the True case above is specifically
    the shutdown guard firing, not the function's normal behaviour.
    """
    calls: list[str] = []

    def _validate(url):
        calls.append(url)
        return (False, None)  # everything fails — exhausts the whole list

    obj, repos, primary, alt_bases, alt_entries = _make_failover_scenario(
        shutting_down=False, validate_fn=_validate
    )

    with patch("metatv.gui.main_window_streaming.RepositoryFactory", return_value=repos), \
         patch("metatv.gui.main_window_streaming.persist_url_stats"):
        result = obj.validate_and_failover_stream_url(primary, "prov-1")

    assert result == ("", None)
    assert len(calls) == 6, (
        f"expected 6 attempts (primary + 5 alternates), got {len(calls)}: {calls}"
    )


# ===========================================================================
# 2 & 3. Failover stops mid-loop when shutdown happens WHILE it's running
#    (the actual reported behaviour — preflight was already in progress when
#    the user quit) — and the attempts that DID complete are still recorded.
# ===========================================================================

def _run_mid_loop_shutdown_scenario():
    """Flip _shutting_down to True from inside the fake validate_stream_url
    after the 2nd alternate attempt completes, simulating closeEvent running
    on the main thread while the loop is mid-flight. Returns
    (result, calls, alt_entries, persist_mock, total_candidates).
    """
    calls: list[str] = []

    def _validate(url):
        calls.append(url)
        if len(calls) == 3:  # primary (1) + 2 alternates (2, 3) attempted so far
            # Simulate the window closing right as this attempt finishes.
            obj["host"]._shutting_down = True
        return (False, None)

    obj = {}
    host, repos, primary, alt_bases, alt_entries = _make_failover_scenario(
        shutting_down=False, validate_fn=_validate
    )
    obj["host"] = host

    with patch("metatv.gui.main_window_streaming.RepositoryFactory", return_value=repos), \
         patch("metatv.gui.main_window_streaming.persist_url_stats") as persist:
        result = host.validate_and_failover_stream_url(primary, "prov-1")

    return result, calls, alt_entries, persist, len(alt_bases)


def test_failover_stops_mid_loop_when_shutdown_flips_during_a_call():
    """The loop stops early (2-3 total attempts), not the full candidate list."""
    result, calls, alt_entries, persist, total_candidates = _run_mid_loop_shutdown_scenario()

    assert result == ("", None)
    alt_attempts = len(calls) - 1  # subtract the primary attempt
    assert 2 <= alt_attempts <= 3, (
        f"expected the loop to stop early (2-3 alternate attempts), "
        f"got {alt_attempts}: {calls}"
    )
    assert alt_attempts < total_candidates, (
        "loop must not have exhausted the full 5-candidate list"
    )


def test_failover_records_completed_attempts_before_aborting():
    """Attempts that DID run are still recorded — the abort doesn't silently
    discard reliability data (cycling without recording is a bug that has
    already shipped once, per CLAUDE.md).

    The expected attempt count is a FIXED constant (2 — the scenario flips
    _shutting_down right after the 2nd alternate completes), not derived from
    ``len(calls)``: deriving it from the observed calls would make this
    assertion vacuously true even with the loop guard removed (all 5
    candidates attempted, all 5 "attempted" entries correctly recorded, zero
    "unattempted" entries to check) — exactly the false-pass this test exists
    to rule out.
    """
    EXPECTED_ALT_ATTEMPTS = 2
    result, calls, alt_entries, persist, total_candidates = _run_mid_loop_shutdown_scenario()
    alt_attempts = len(calls) - 1

    assert alt_attempts == EXPECTED_ALT_ATTEMPTS, (
        f"scenario expects exactly {EXPECTED_ALT_ATTEMPTS} alternate attempts "
        f"before the abort fires, got {alt_attempts}: {calls}"
    )

    attempted = alt_entries[:EXPECTED_ALT_ATTEMPTS]
    unattempted = alt_entries[EXPECTED_ALT_ATTEMPTS:]
    for entry in attempted:
        assert entry.failure_count == 1, f"{entry.url} attempt was not recorded"
    for entry in unattempted:
        assert entry.failure_count == 0, (
            f"{entry.url} should never have been tried — recording ran past the abort point"
        )

    assert persist.call_count == EXPECTED_ALT_ATTEMPTS, (
        f"persist_url_stats should be flushed after each completed attempt "
        f"(reliability data must survive the abort); "
        f"got {persist.call_count} calls, expected {EXPECTED_ALT_ATTEMPTS}"
    )


# ===========================================================================
# 4. _on_preflight_done discards after shutdown.
# ===========================================================================

def _make_series_host(shutting_down: bool, db):
    from metatv.gui.main_window_series import _SeriesMixin
    obj = _SeriesMixin.__new__(_SeriesMixin)
    obj._shutting_down = shutting_down
    obj.db = db
    obj.executor = _ImmediateExecutor()
    obj.player_manager = MagicMock()
    obj.player_manager.is_available.return_value = True
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-123"
    obj.status_bar = MagicMock()
    obj._episode_ready = MagicMock()
    obj._episode_failed = MagicMock()
    return obj


def test_on_preflight_done_discards_after_shutdown(tmp_path):
    """_shutting_down=True: neither signal fires, and the DB write-back that
    a successful failover would otherwise trigger never happens — proving the
    guard bails before future.result() is even unpacked."""
    db = _make_db(tmp_path)
    episode_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    original_url = "http://deadhost.example/ep.mp4"
    alt_url = "http://goodhost.example/ep.mp4"

    with db.session_scope() as session:
        _insert_episode(session, episode_id, provider_id, original_url)

    host = _make_series_host(shutting_down=True, db=db)
    host.validate_and_failover_stream_url = MagicMock(return_value=(alt_url, None))

    host.launch_player_for_episode(
        original_url, "Test Episode", provider_id=provider_id, episode_id=episode_id,
    )

    host._episode_ready.emit.assert_not_called()
    host._episode_failed.emit.assert_not_called()
    assert _read_stream_url(db, episode_id) == original_url, (
        "the DB write-back must not have run — the episode row is untouched"
    )


def test_on_preflight_done_delivers_when_not_shutting_down(tmp_path):
    """Same setup, _shutting_down=False — the result IS delivered."""
    db = _make_db(tmp_path)
    episode_id = str(uuid.uuid4())
    provider_id = str(uuid.uuid4())
    original_url = "http://deadhost.example/ep.mp4"
    alt_url = "http://goodhost.example/ep.mp4"

    with db.session_scope() as session:
        _insert_episode(session, episode_id, provider_id, original_url)

    host = _make_series_host(shutting_down=False, db=db)
    host.validate_and_failover_stream_url = MagicMock(return_value=(alt_url, None))

    host.launch_player_for_episode(
        original_url, "Test Episode", provider_id=provider_id, episode_id=episode_id,
    )

    host._episode_ready.emit.assert_called_once()
    host._episode_failed.emit.assert_not_called()
    assert _read_stream_url(db, episode_id) == alt_url, (
        "the DB write-back must have run — the episode row picked up the new host"
    )


# ===========================================================================
# 5. on_metadata_loaded discards after shutdown.
# ===========================================================================

class _FakeChannel:
    def __init__(self, id: str, provider_id: str, name: str, media_type: str = "movie"):
        self.id = id
        self.provider_id = provider_id
        self.name = name
        self.media_type = media_type


class _ImmediateQueryResultSignal:
    """Synchronous stand-in for the pyqtSignal(_QueryResult) that _run_query
    emits to. _ImmediateExecutor already runs the worker on the calling
    thread, so dispatching straight to _on_query_result on emit keeps the
    whole _run_query round trip (UI-11's provider-url lookup) synchronous —
    matching what these tests need: everything settled before the call
    returns, no Qt event loop involved."""

    def __init__(self, host):
        self._host = host

    def emit(self, value):
        self._host._on_query_result(value)


def _make_metadata_host(shutting_down: bool, db, metadata_result):
    from metatv.gui.main_window_async import _AsyncMixin
    from metatv.gui.main_window_metadata import _MetadataMixin
    obj = _MetadataMixin.__new__(_MetadataMixin)
    obj._shutting_down = shutting_down
    obj.db = db
    obj.config = MagicMock(metadata_auto_fetch=True)
    obj.details_pane = MagicMock()
    obj.executor = _ImmediateExecutor()
    obj.metadata_loaded = MagicMock()
    # UI-11: update_details_pane_for_channel now routes the provider-url
    # lookup through the _run_query seam — wire it the same way
    # test_details_pane_debounce.py does.
    obj._details_urls_token = [0]
    obj._query_result = _ImmediateQueryResultSignal(obj)
    obj._run_query = _AsyncMixin._run_query.__get__(obj)
    obj._on_query_result = _AsyncMixin._on_query_result.__get__(obj)

    async def _get_metadata(_channel_id):
        return metadata_result

    obj.metadata_manager = MagicMock()
    obj.metadata_manager.get_metadata = _get_metadata
    return obj


def test_on_metadata_loaded_discards_after_shutdown(tmp_path):
    """_shutting_down=True: metadata_loaded never fires, even though the
    background fetch itself completed successfully."""
    db = _make_db(tmp_path)
    channel = _FakeChannel(id="ch1", provider_id="prov1", name="Test Movie")
    metadata = MagicMock(plot="A plot", cast=[], poster_url=None)

    host = _make_metadata_host(shutting_down=True, db=db, metadata_result=metadata)

    host.update_details_pane_for_channel(channel)

    host.metadata_loaded.emit.assert_not_called()


def test_on_metadata_loaded_delivers_when_not_shutting_down(tmp_path):
    """Same setup, _shutting_down=False — metadata_loaded DOES fire."""
    db = _make_db(tmp_path)
    channel = _FakeChannel(id="ch1", provider_id="prov1", name="Test Movie")
    metadata = MagicMock(plot="A plot", cast=[], poster_url=None)

    host = _make_metadata_host(shutting_down=False, db=db, metadata_result=metadata)

    host.update_details_pane_for_channel(channel)

    host.metadata_loaded.emit.assert_called_once_with(channel, metadata)


# ===========================================================================
# 6. Ordering: closeEvent sets _shutting_down BEFORE the _cleanables loop
#    runs — the property that keeps in-flight work from touching a closed
#    database. Invisible to every other test.
# ===========================================================================

def _build_close_event_window():
    """A minimal MainWindow skeleton wired the same way as
    tests/test_close_event_cleanup.py's _build_mock_window(), so closeEvent
    can run for real without a live QApplication or full __init__."""
    from metatv.gui import main_window as mw_module

    with patch.object(mw_module.MainWindow, "__init__", lambda self: None):
        win = mw_module.MainWindow.__new__(mw_module.MainWindow)

    win.player_manager = MagicMock()
    win.stream_retry_manager = MagicMock()
    win.db = MagicMock()
    win.epg_manager = MagicMock()
    win.image_cache = MagicMock()
    win.executor = MagicMock()
    win.config = MagicMock()
    # REC-3's quit guard counts non-terminal recordings before any teardown.
    win.recording_manager = MagicMock()
    win.recording_manager.progress.return_value = []

    for name in ("discover_view", "preferences_view", "epg_view", "recipe_view"):
        view = MagicMock()
        view.isVisible.return_value = False
        setattr(win, name, view)

    win.save_splitter_sizes = MagicMock()
    win.save_sidebar_section_sizes = MagicMock()
    win._save_filter_panel_width = MagicMock()
    win.saveGeometry = MagicMock(return_value=b"geometry")
    win._layout_save_debounce = MagicMock()

    return win


def test_closeevent_sets_shutting_down_before_cleanables_run():
    """A fake cleanable records self._shutting_down when it's invoked — it
    must already be True, proving the flag is set before teardown (including
    the db.close() this same loop performs) rather than after."""
    win = _build_close_event_window()

    observed = {}

    def _probe():
        observed["shutting_down"] = win._shutting_down

    win._cleanables = [("probe", _probe)]

    event = MagicMock()
    win.closeEvent(event)

    assert observed.get("shutting_down") is True, (
        "closeEvent must set _shutting_down before running _cleanables"
    )
