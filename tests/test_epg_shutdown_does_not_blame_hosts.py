"""Closing the app during an EPG fetch must not mark the hosts unreliable.

Reported from a live run (2026-08-22)::

    ERROR   xmltv_parser:parse_xmltv_url:119 - XMLTV fetch/parse error:
            wrapped C/C++ object of type EpgManager has been deleted
    WARNING epg_manager:_resolve_and_fetch_guide:604 - EPG fetch failed for
            TREX Shared @ http://vpn.gamesupside-t-rex.top: wrapped C/C++ object

``shutdown()`` tears the executor down with ``wait=False``, so an in-flight
parse keeps running after Qt has deleted the EpgManager's C++ side. The parse
progress callback then emits on a dead QObject and raises ``RuntimeError``.

The log lines are the harmless part. The damage is where that exception landed:
the per-host handler in ``_resolve_and_fetch_guide`` treats ANY exception as
"this host failed", so it called ``record_failure`` and persisted it — then
moved to the next host, which aborted identically. One app close permanently
marked EVERY host of the provider unreliable, corrupting the ranking data that
decides which host gets tried first.

These assert the PERSISTED counters, not that a mock went uncalled: the
poisoned ranking is what the user actually suffers, and it lives in the DB.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc
from metatv.core.xmltv_parser import XmltvAborted, XmltvProgramme

_HOSTS = ["http://host-a.example", "http://host-b.example",
          "http://host-c.example"]


@pytest.fixture
def db(tmp_path):
    """File-backed, per the DB-session testing rule (never :memory:)."""
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_tables()
    yield database
    database.engine.dispose()


@pytest.fixture
def manager(db):
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = "3d"
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="trex", name="TREX Shared", type="xtream", url=_HOSTS[0],
            urls=[{"url": h, "priority": i} for i, h in enumerate(_HOSTS)],
            username="u", password="p", is_active=True, epg_enabled=True,
        ))
    return EpgManager(db, config, notifications=None)


def _failure_counts(db) -> dict[str, int]:
    with db.session_scope(commit=False) as session:
        provider = session.query(ProviderDB).filter_by(id="trex").first()
        return {
            entry["url"]: int(entry.get("failure_count") or 0)
            for entry in (provider.urls or [])
        }


def _programmes(n=2):
    now = now_utc()
    return [
        XmltvProgramme(channel_id=f"c{i}", title=f"Show {i}", description="",
                       start_time=now - timedelta(hours=1),
                       stop_time=now + timedelta(hours=1))
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# The reported bug
# ---------------------------------------------------------------------------

def test_a_teardown_abort_blames_no_host(manager, db, monkeypatch):
    """The whole point: nothing is recorded against any host."""
    attempted: list[str] = []

    def _aborting_parse(url, timeout=180, on_progress=None):
        attempted.append(url)
        raise XmltvAborted("EPG manager is shutting down")

    monkeypatch.setattr("metatv.core.epg_manager.parse_xmltv_url",
                        _aborting_parse)

    with pytest.raises(XmltvAborted):
        manager._resolve_and_fetch_guide("trex", "TREX Shared", lambda n: None)

    assert _failure_counts(db) == dict.fromkeys(_HOSTS, 0), (
        "a shutdown was recorded as host unreliability"
    )
    assert len(attempted) == 1, (
        f"the abort should stop the cycle immediately, but {len(attempted)} "
        "hosts were tried — a single app close would blame all of them"
    )


def test_the_real_runtime_error_is_what_triggers_it(manager, db, monkeypatch):
    """Drive the ACTUAL failure mode, not a hand-thrown XmltvAborted.

    The production path is: progress callback emits on a deleted QObject ->
    PyQt raises RuntimeError -> that must become an abort. A test that only
    ever raises XmltvAborted itself would pass even if the translation from
    RuntimeError were missing entirely, which is the half that broke.
    """
    def _parse_calling_progress(url, timeout=180, on_progress=None):
        if on_progress:
            on_progress(10_000)          # the tick that used to explode
        return [], _programmes()

    monkeypatch.setattr("metatv.core.epg_manager.parse_xmltv_url",
                        _parse_calling_progress)

    # Exactly what PyQt does once the C++ side is gone, quoted from the
    # traceback the owner reported. The whole signal is shadowed rather than
    # its .emit patched, because a bound signal's emit is read-only.
    #
    # Deleting the manager for real (PyQt6.sip.delete) was tried and rejected:
    # it segfaults the interpreter, because the object still owns connected
    # signals and QTimers. A test that takes the whole suite down with SIGSEGV
    # is worse than no test, and the reported traceback is already first-hand
    # evidence that this is the error PyQt raises.
    class _DeadSignal:
        def emit(self, *args, **kwargs):
            raise RuntimeError(
                "wrapped C/C++ object of type EpgManager has been deleted")

    monkeypatch.setattr(manager, "_progress_update", _DeadSignal())

    manager._fetch_worker("trex", "TREX Shared", notif_id="n1")

    assert _failure_counts(db) == dict.fromkeys(_HOSTS, 0), (
        "the reported RuntimeError still lands in the host-failure recorder"
    )


def test_the_shutdown_flag_stops_a_fetch_that_has_not_crashed_yet(
        manager, db, monkeypatch):
    """After shutdown() the next progress tick abandons the fetch.

    Cheaper and more deterministic than waiting to crash on a deleted object:
    the flag is a plain Python attribute precisely so it stays readable once
    Qt has torn the wrapper down.
    """
    def _parse_calling_progress(url, timeout=180, on_progress=None):
        if on_progress:
            on_progress(10_000)
        return [], _programmes()

    monkeypatch.setattr("metatv.core.epg_manager.parse_xmltv_url",
                        _parse_calling_progress)
    manager.shutdown()
    assert manager._shutting_down is True

    manager._fetch_worker("trex", "TREX Shared", notif_id="n1")
    assert _failure_counts(db) == dict.fromkeys(_HOSTS, 0)


def test_the_worker_stays_quiet_on_abort(manager, monkeypatch):
    """No error signal and no toast — both touch objects being destroyed."""
    monkeypatch.setattr(
        "metatv.core.epg_manager.parse_xmltv_url",
        lambda url, timeout=180, on_progress=None: (_ for _ in ()).throw(
            XmltvAborted("gone")))

    errors: list[tuple] = []
    manager.refresh_error.connect(lambda *a: errors.append(a))
    shown: list[tuple] = []
    monkeypatch.setattr(manager, "_show_notification",
                        lambda *a, **k: shown.append((a, k)))

    manager._fetch_worker("trex", "TREX Shared", notif_id="n1")

    assert errors == [], "an abort raised a user-facing EPG error"
    assert shown == [], "an abort raised a user-facing notification"
    assert "trex" not in manager._active_refreshes, "the refresh was not released"


# ---------------------------------------------------------------------------
# ...without breaking the behaviour that must survive
# ---------------------------------------------------------------------------

def test_a_genuine_host_failure_is_still_recorded(manager, db, monkeypatch):
    """The guard must not swallow real failures — that would be a worse bug.

    A dead first host still gets a failure recorded, and the cycle still moves
    on and succeeds on the next one.
    """
    def _first_host_dies(url, timeout=180, on_progress=None):
        if _HOSTS[0] in url:
            raise OSError("connection refused")
        return [], _programmes()

    monkeypatch.setattr("metatv.core.epg_manager.parse_xmltv_url",
                        _first_host_dies)

    fetch = manager._resolve_and_fetch_guide(
        "trex", "TREX Shared", lambda n: None)
    channels, programmes = fetch.channels, fetch.programmes

    assert len(programmes) == 2, "the cycle did not fall through to a live host"
    counts = _failure_counts(db)
    assert counts[_HOSTS[0]] == 1, (
        f"a genuinely dead host was not recorded: {counts}"
    )
    assert counts[_HOSTS[1]] == 0, "a working host was blamed"


def test_an_abort_is_not_logged_as_a_parse_error(monkeypatch, caplog):
    """parse_xmltv_url must let the abort through without the error log.

    The reported "XMLTV fetch/parse error" line came from the parser's catch-all
    dressing a teardown up as a fetch problem.
    """
    import metatv.core.xmltv_parser as parser

    def _boom(*args, **kwargs):
        raise XmltvAborted("shutting down")

    monkeypatch.setattr(parser.urllib.request, "urlopen", _boom)

    with caplog.at_level("ERROR"):
        with pytest.raises(XmltvAborted):
            parser.parse_xmltv_url("http://host-a.example/xmltv.php")

    assert "XMLTV fetch/parse error" not in caplog.text, (
        "a teardown is still logged as a fetch/parse error"
    )

