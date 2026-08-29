"""Background work never runs against a source whose content is hidden.

``get_hidden_provider_ids()`` — inactive ∪ expired ∪ orphaned — is the canonical
gate, and the display layer already routes through it: an expired source's
content is correctly absent from results, the lightbox and similar titles.

The FETCH paths did not. They gated on ``is_active``, which stays true for an
expired subscription until the user removes it. So the app hid a source's
content while continuing to ask it for more.

Measured the evening TREX expired at 16:00: three hours of continuous fetching
at 130% CPU, every EPG attempt cycling all twenty of its hosts for a 451 apiece,
with the app laggy throughout. Owner: "it's brutally slow", and separately
"shouldn't it not run functions on an expired source?"

Asking a source for content the app would refuse to display even if it arrived
is work that cannot pay off.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.series_monitor import SeriesMonitorManager


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'exp.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(session, pid, *, expired=False, active=True):
    session.add(ProviderDB(
        id=pid, name=f"P {pid}", type="xtream", url=f"http://{pid}",
        username="u", password="p", is_active=active,
        account_exp_date=datetime.now() + timedelta(days=-1 if expired else 30),
    ))


def _series(session, cid, pid, key="tmdb:1|series"):
    session.add(ChannelDB(id=cid, source_id=cid, provider_id=pid, name="S",
                          media_type="series", detected_title="S",
                          content_key=key))


def test_the_gate_reports_an_expired_source_as_hidden(db):
    """Precondition — the rest of the file depends on this being the gate."""
    with db.session_scope() as s:
        _provider(s, "live")
        _provider(s, "dead", expired=True)
    with db.session_scope(commit=False) as s:
        hidden = RepositoryFactory(s).providers.get_hidden_provider_ids()
    assert "dead" in hidden and "live" not in hidden


def test_an_expired_primary_is_not_polled(db):
    """The bug: the primary was added unconditionally, siblings were gated.

    Every monitored series whose own source expired kept costing a live fetch
    per pass — and each fetch cycles every host of a source that answers 451.
    """
    with db.session_scope() as s:
        _provider(s, "dead", expired=True)
        _series(s, "c1", "dead")
    mon = SeriesMonitorManager.__new__(SeriesMonitorManager)
    with db.session_scope(commit=False) as s:
        mirrors = mon._resolve_mirrors(s, "c1", "dead", "c1")
    assert mirrors == [], (
        f"an expired source is still going to be fetched: {mirrors}"
    )


def test_a_live_primary_is_still_polled(db):
    """Regression floor — the gate must not silence working sources."""
    with db.session_scope() as s:
        _provider(s, "live")
        _series(s, "c1", "live")
    mon = SeriesMonitorManager.__new__(SeriesMonitorManager)
    with db.session_scope(commit=False) as s:
        mirrors = mon._resolve_mirrors(s, "c1", "live", "c1")
    assert ("live", "c1") in mirrors


def test_a_live_mirror_survives_an_expired_primary(db):
    """Expiry removes one source, not the series.

    The user still monitors this title, and another source still carries it.
    """
    with db.session_scope() as s:
        _provider(s, "dead", expired=True)
        _provider(s, "live")
        _series(s, "c1", "dead")
        _series(s, "c2", "live")
    mon = SeriesMonitorManager.__new__(SeriesMonitorManager)
    with db.session_scope(commit=False) as s:
        mirrors = mon._resolve_mirrors(s, "c1", "dead", "c1")
    assert ("dead", "c1") not in mirrors, "the expired source is still polled"
    assert ("live", "c2") in mirrors, "the live mirror was dropped with it"


def test_a_switched_off_source_is_also_skipped(db):
    """The gate is one set; expiry is not a special case within it."""
    with db.session_scope() as s:
        _provider(s, "off", active=False)
        _series(s, "c1", "off")
    mon = SeriesMonitorManager.__new__(SeriesMonitorManager)
    with db.session_scope(commit=False) as s:
        assert mon._resolve_mirrors(s, "c1", "off", "c1") == []


def test_the_epg_refresh_scan_consults_the_same_gate():
    """Derived: the auto-refresh loop must not gate on is_active alone.

    is_active stays true for an expired subscription, which is exactly how the
    guide fetch kept cycling twenty dead hosts every pass.
    """
    import inspect

    from metatv.core import epg_manager

    src = inspect.getsource(epg_manager)
    block = src[src.index("providers = session.query(ProviderDB).filter_by(is_active=True).all()"):]
    block = block[:2000]
    assert "get_hidden_provider_ids" in src, (
        "epg_manager never consults the canonical hidden-provider gate"
    )
    assert "hidden" in block, (
        "the auto-refresh scan selects providers by is_active alone, so an "
        "expired source is still fetched every pass"
    )
