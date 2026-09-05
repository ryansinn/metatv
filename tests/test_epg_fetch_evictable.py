"""EPG-2 + EPG-2b: playback can evict a guide fetch, keeping only fully-parsed rows.

EPG is enrolled in the ``ConnectionAccountant`` but could not previously abort
mid-download (20-30s routinely), so a play needing the one connection a source
allows had to wait or fail behind it. The fix: playback pre-empting a guide
fetch raises ``XmltvEvicted`` out of the in-flight parse, carrying only the
programmes whose element had already fully closed (the iterparse "end"-event
guarantee — never a half-read row). ``EpgManager._run_fetch`` then REPLACES
the stored guide only when the partial holds MORE programmes than what's
already stored; otherwise it leaves the existing guide untouched. Either way
``epg_last_fetched`` is never stamped, so ``needs_refresh()`` retries at the
next scheduler tick.

Reuses the ``_FakeResponse`` fixture from ``test_xmltv_parser_gzip`` and the
``_programmes`` helper + ``manager``-construction pattern from
``test_epg_shutdown_does_not_blame_hosts`` (grepped per CLAUDE.md: reuse
existing test fixtures over writing duplicates).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from loguru import logger as _loguru_logger

from metatv.core.connection_accountant import AcquireResult
from metatv.core.database import Database, EpgProgramDB, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc
from metatv.core.xmltv_parser import XmltvEvicted
from tests.test_epg_shutdown_does_not_blame_hosts import _programmes
from tests.test_xmltv_parser_gzip import _FakeResponse

_HOST = "http://host.example"

_XML_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
<channel id="ch1"><display-name>Channel One</display-name></channel>
<programme channel="ch1" start="20260101120000 +0000" stop="20260101130000 +0000"><title>Show 1</title></programme>
<programme channel="ch1" start="20260101130000 +0000" stop="20260101140000 +0000"><title>Show 2</title></programme>
<programme channel="ch1" start="20260101140000 +0000" stop="20260101150000 +0000"><title>Show 3</title></programme>
<programme channel="ch1" start="20260101150000 +0000" stop="20260101160000 +0000"><title>Show 4</title></programme>
<programme channel="ch1" start="20260101160000 +0000" stop="20260101170000 +0000"><title>Show 5</title></programme>
<programme channel="ch1" start="20260101170000 +0000" stop="20260101180000 +0000"><title>Show 6</title></programme>
</tv>
"""


@pytest.fixture()
def db(tmp_path):
    """File-backed, per the DB-session testing rule (never :memory:)."""
    database = Database(f"sqlite:///{tmp_path / 'epg.db'}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _config():
    from unittest.mock import MagicMock
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = "3d"
    # A real int: prune_expired() does max(_MIN_EPG_RETENTION_HOURS, this),
    # which TypeErrors against an auto-generated MagicMock attribute.
    config.epg_retention_hours = 24
    return config


def _seed_provider(db, provider_id="p1", epg_last_fetched=None) -> None:
    with db.session_scope() as session:
        session.add(ProviderDB(
            id=provider_id, name="Prov", type="xtream", url=_HOST,
            urls=[{"url": _HOST, "priority": 0}],
            username="u", password="pw", is_active=True, epg_enabled=True,
            epg_last_fetched=epg_last_fetched,
        ))


def _seed_stored_programmes(db, provider_id: str, n: int) -> None:
    with db.session_scope() as session:
        now = now_utc()
        for i in range(n):
            session.add(EpgProgramDB(
                provider_id=provider_id, channel_epg_id=f"old{i}", channel_name="",
                title=f"Old {i}", description="",
                start_time=now - timedelta(hours=1), stop_time=now + timedelta(hours=1),
            ))


class _FakeAccountant:
    """Captures registered preempt listeners; ``acquire``/``release`` are no-ops."""

    def __init__(self) -> None:
        self.preempt_listeners: list = []

    def add_preempt_listener(self, callback) -> None:
        self.preempt_listeners.append(callback)

    def acquire(self, provider_id, kind, holder_id, preempt_kinds=()):
        return AcquireResult(True, provider_id, 0, (holder_id,))

    def release(self, provider_id, holder_id) -> None:
        pass


# ---------------------------------------------------------------------------
# Parser: XmltvEvicted carries exactly what finished parsing before it
# ---------------------------------------------------------------------------

def test_parser_evicted_carries_exactly_what_was_fully_parsed(monkeypatch):
    import metatv.core.xmltv_parser as parser

    monkeypatch.setattr(parser, "_PROGRESS_INTERVAL", 2)
    monkeypatch.setattr(
        parser.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(_XML_BODY.encode("utf-8")),
    )

    calls: list[int] = []

    def on_progress(count: int) -> None:
        calls.append(count)
        if len(calls) == 2:
            raise XmltvEvicted()

    errors: list[str] = []
    sink_id = _loguru_logger.add(
        lambda msg: errors.append(msg.record["message"]), level="ERROR")
    try:
        with pytest.raises(XmltvEvicted) as exc_info:
            parser.parse_xmltv_url("http://example.com/xmltv.php", on_progress=on_progress)
    finally:
        _loguru_logger.remove(sink_id)

    evicted = exc_info.value
    assert len(evicted.programmes) == 4, (
        f"expected exactly the 4 programmes parsed before eviction, "
        f"got {len(evicted.programmes)}"
    )
    assert [p.title for p in evicted.programmes] == [f"Show {i}" for i in range(1, 5)], (
        "no half-read item should ever appear — only the fully-closed ones"
    )
    assert errors == [], f"an eviction must not be logged as a parse error: {errors}"


# ---------------------------------------------------------------------------
# Manager: the stored-count comparison (EPG-2b's replace-only-if-bigger rule)
# ---------------------------------------------------------------------------

def test_a_smaller_partial_leaves_the_larger_stored_guide_untouched(db, monkeypatch):
    """Existing guide LARGER than the partial: nothing changes."""
    _seed_provider(db)
    _seed_stored_programmes(db, "p1", 10)

    monkeypatch.setattr(
        "metatv.core.epg_fetch.parse_xmltv_url",
        lambda url, timeout=180, on_progress=None: (_ for _ in ()).throw(
            XmltvEvicted([], _programmes(3))),
    )

    manager = EpgManager(db, _config(), notifications=None)
    finished: list[tuple] = []
    manager.refresh_finished.connect(lambda *a: finished.append(a))
    done_messages: list[str] = []
    manager._progress_done.connect(lambda notif_id, msg: done_messages.append(msg))

    manager._fetch_worker("p1", "Prov", notif_id="n1")

    with db.session_scope(commit=False) as session:
        provider = session.query(ProviderDB).filter_by(id="p1").one()
        stored = session.query(EpgProgramDB).filter_by(provider_id="p1").count()
        assert stored == 10, "a smaller partial replaced the larger stored guide"
        assert provider.epg_last_fetched is None, (
            "a partial fetch must never stamp epg_last_fetched"
        )
    assert finished == [], "nothing changed, so refresh_finished must not fire"
    assert any("paused for playback" in m for m in done_messages), done_messages


def test_a_larger_partial_replaces_the_smaller_stored_guide(db, monkeypatch):
    """Existing guide SMALLER than the partial: the partial replaces it."""
    _seed_provider(db)
    _seed_stored_programmes(db, "p1", 2)

    monkeypatch.setattr(
        "metatv.core.epg_fetch.parse_xmltv_url",
        lambda url, timeout=180, on_progress=None: (_ for _ in ()).throw(
            XmltvEvicted([], _programmes(5))),
    )

    manager = EpgManager(db, _config(), notifications=None)
    finished: list[tuple] = []
    manager.refresh_finished.connect(lambda *a: finished.append(a))

    manager._fetch_worker("p1", "Prov", notif_id="n1")

    with db.session_scope(commit=False) as session:
        provider = session.query(ProviderDB).filter_by(id="p1").one()
        stored = session.query(EpgProgramDB).filter_by(provider_id="p1").count()
        assert stored == 5, "the larger partial did not replace the smaller stored guide"
        assert provider.epg_last_fetched is None, (
            "a partial fetch must never stamp epg_last_fetched, even when it wins"
        )
    assert finished == [("p1", 5)], f"refresh_finished should report the new count: {finished}"


# ---------------------------------------------------------------------------
# Eviction plumbing: an accountant preemption reaches the in-flight parse
# ---------------------------------------------------------------------------

def test_an_accountant_eviction_ends_the_fetch_partial_instead_of_raising_out(db, monkeypatch):
    """End to end: accountant.add_preempt_listener -> on_parse_progress -> partial."""
    _seed_provider(db)
    accountant = _FakeAccountant()
    manager = EpgManager(db, _config(), notifications=None, connection_accountant=accountant)
    assert accountant.preempt_listeners, "EpgManager must register with the accountant"

    reached_past_eviction = []

    def fake_parse(url, timeout=180, on_progress=None):
        # Simulate the accountant announcing the eviction mid-download, exactly
        # as it calls every registered listener for a real preemption.
        for cb in accountant.preempt_listeners:
            cb("p1", "epg_fetch:p1", "playback")
        on_progress(1)  # must raise XmltvEvicted — the eviction is now recorded
        reached_past_eviction.append(True)  # pragma: no cover — must not run
        return [], _programmes(1)

    monkeypatch.setattr("metatv.core.epg_fetch.parse_xmltv_url", fake_parse)

    done_messages: list[str] = []
    manager._progress_done.connect(lambda notif_id, msg: done_messages.append(msg))

    manager._fetch_worker("p1", "Prov", notif_id="n1")  # must not raise

    assert reached_past_eviction == [], "the parse continued after the eviction was recorded"
    assert any("paused for playback" in m for m in done_messages), done_messages
