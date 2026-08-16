"""Behavior tests: the EPG URL must be DERIVED from live credentials, never cached,
and the guide fetch must cycle hosts via the one canonical UrlCycler chokepoint.

Root cause pinned here (owner's live database, 2026-08): a re-subscription on the
same provider row (new username/password, same account) left ``epg_url`` holding
the PREVIOUS account's credentials forever, because ``_ensure_epg_url`` was
write-once — it only ever populated the column when empty, never refreshed it.
The guide died silently for 11 days behind a green "AUTODETECTED" badge.

Fix: ``EpgManager.effective_epg_url()`` derives from ``epg_url_override`` (wins
if set) or live ``username``/``password``/``urls`` — never the stored ``epg_url``
column, which stays in place only as migration debt. The guide fetch itself now
cycles the provider's ranked hosts via ``UrlCycler`` (never a bare loop), recording
success/failure (no latency — mirrors the ``fetch_channels`` exclusion) after every
attempt, and treats only a connection error / HTTP error / unparseable payload /
zero-programme payload as a reason to advance — an already-expired-but-parseable
guide is accepted as-is (re-downloading identical stale content from every other
host would be a serious harm, not a fix).

All tests execute the real changed code paths against a file-backed Database
(NOT :memory:) and fake the HTTP layer by monkeypatching
``metatv.core.epg_manager.parse_xmltv_url`` — no real network calls.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, EpgProgramDB, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc
from metatv.core.repositories.provider import parse_provider_urls
from metatv.core.xmltv_parser import XmltvProgramme


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """File-backed Database with tables created (avoids :memory: pool isolation)."""
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _make_manager(db, *, epg_default="3d"):
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = epg_default
    return EpgManager(db, config, notifications=None)


def _add_cycling_provider(session, pid, *, hosts, username="u", password="p",
                          override=None):
    """A provider with one or more ranked hosts (``urls`` JSON), for exercising
    the UrlCycler-driven fetch path in ``_fetch_worker``."""
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url=hosts[0],
        urls=[{"url": h, "priority": i} for i, h in enumerate(hosts)],
        username=username, password=password, is_active=True,
        epg_enabled=True, epg_url_override=override,
    ))
    session.flush()


def _fake_programmes(n=1, *, start_offset_hours=-1, stop_offset_hours=1):
    now = now_utc()
    return [
        XmltvProgramme(
            channel_id=f"c{i}", title=f"Show {i}", description="",
            start_time=now + timedelta(hours=start_offset_hours),
            stop_time=now + timedelta(hours=stop_offset_hours),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1-4: effective_epg_url — derivation, not caching
# ---------------------------------------------------------------------------

def test_owner_bug_new_credentials_used_old_credentials_absent(db):
    """The exact production bug: epg_url holds the OLD account's credentials
    while username/password hold the NEW ones (post re-subscription, same
    provider row). effective_epg_url must build from the CURRENT credentials
    and must not contain the old ones anywhere in the result."""
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="owner-bug", name="owner-bug", type="xtream",
            url="http://vpn.vpntxvpn.ru",
            urls=[{"url": "http://vpn.vpntxvpn.ru", "priority": 0}],
            username="c2f40295e9", password="aadcf4fe0c",   # CURRENT account
            is_active=True,
            epg_url=(
                "http://vpn.vpntxvpn.ru/xmltv.php"
                "?username=ef1b3dcac4&password=a248a0cb8f"  # STALE, OLD account
            ),
        ))

    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="owner-bug").first()
        url = EpgManager.effective_epg_url(p)

    assert "c2f40295e9" in url, "must build from the CURRENT username"
    assert "aadcf4fe0c" in url, "must build from the CURRENT password"
    assert "ef1b3dcac4" not in url, "must NOT contain the OLD username"
    assert "a248a0cb8f" not in url, "must NOT contain the OLD password"


def test_credential_change_picked_up_with_no_invalidation_step(db):
    """Changing username/password on the row is reflected on the very next
    effective_epg_url call — nothing needs to be nulled/reset first."""
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="cred-change", name="cred-change", type="xtream",
            url="http://host.example",
            urls=[{"url": "http://host.example", "priority": 0}],
            username="olduser", password="oldpass", is_active=True,
        ))

    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="cred-change").first()
        before = EpgManager.effective_epg_url(p)
    assert "olduser" in before and "oldpass" in before

    # Simulate a re-subscription: change credentials, touch NOTHING else.
    with db.session_scope() as session:
        p = session.query(ProviderDB).filter_by(id="cred-change").first()
        p.username = "newuser"
        p.password = "newpass"

    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="cred-change").first()
        after = EpgManager.effective_epg_url(p)

    assert "newuser" in after and "newpass" in after
    assert "olduser" not in after and "oldpass" not in after


def test_override_always_wins_verbatim_even_as_credentials_change(db):
    """A user-supplied override takes precedence over derivation, unconditionally,
    and stays fixed even when the credentials underneath it change."""
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="override-wins", name="override-wins", type="xtream",
            url="http://host.example",
            urls=[{"url": "http://host.example", "priority": 0}],
            username="u1", password="p1", is_active=True,
            epg_url_override="http://custom.example/my-guide.xml",
        ))

    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="override-wins").first()
        assert EpgManager.effective_epg_url(p) == "http://custom.example/my-guide.xml"

    with db.session_scope() as session:
        p = session.query(ProviderDB).filter_by(id="override-wins").first()
        p.username = "u2"
        p.password = "p2"

    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="override-wins").first()
        assert EpgManager.effective_epg_url(p) == "http://custom.example/my-guide.xml", (
            "the override must not move when credentials change underneath it"
        )


def test_blank_whitespace_override_falls_through_to_derivation(db):
    """A whitespace-only override is treated the same as no override at all —
    NOT as a static URL to fetch verbatim."""
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="blank-override", name="blank-override", type="xtream",
            url="http://host.example",
            urls=[{"url": "http://host.example", "priority": 0}],
            username="u", password="p", is_active=True,
            epg_url_override="   ",
        ))

    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="blank-override").first()
        assert EpgManager.effective_epg_url(p) == (
            "http://host.example/xmltv.php?username=u&password=p"
        )


# ---------------------------------------------------------------------------
# 5-9: the fetch itself cycles hosts via UrlCycler
# ---------------------------------------------------------------------------

def test_cycling_first_working_host_wins(db, monkeypatch):
    """Host 1 fails outright (connection error), host 2 returns a valid guide:
    the guide from host 2 is stored, host 2's URL was actually fetched, and
    the outcome of BOTH attempts is recorded."""
    import metatv.core.epg_manager as epgmod

    with db.session_scope() as session:
        _add_cycling_provider(
            session, "cyc-first-wins",
            hosts=["http://host1.example", "http://host2.example"],
        )

    calls: list[str] = []
    good_progs = _fake_programmes(2)

    def fake_parse(url, timeout=180, on_progress=None):
        calls.append(url)
        if "host1.example" in url:
            raise ConnectionError("host1 refused connection")
        if "host2.example" in url:
            return ([], good_progs)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(epgmod, "parse_xmltv_url", fake_parse)

    manager = _make_manager(db)
    manager._fetch_worker("cyc-first-wins", "Cyc First Wins", None)

    with db.session_scope(commit=False) as session:
        count = session.query(EpgProgramDB).filter_by(provider_id="cyc-first-wins").count()
        prov = session.query(ProviderDB).filter_by(id="cyc-first-wins").first()
        by_url = {e["url"]: e for e in parse_provider_urls(prov.urls)}

    assert count == 2, "the working host's guide must be stored"
    assert any("host2.example" in u for u in calls), "host 2 must actually have been fetched"
    assert by_url["http://host1.example"]["failure_count"] == 1, "host 1 must be recorded as a failure"
    assert by_url["http://host2.example"]["success_count"] == 1, "host 2 must be recorded as a success"
    manager._executor.shutdown(wait=False)


def test_cycling_zero_programme_payload_advances(db, monkeypatch):
    """A host that parses cleanly but returns ZERO programmes must be treated
    as a failure and the cycle must advance to the next host."""
    import metatv.core.epg_manager as epgmod

    with db.session_scope() as session:
        _add_cycling_provider(
            session, "cyc-empty",
            hosts=["http://host1.example", "http://host2.example"],
        )

    good_progs = _fake_programmes(3)

    def fake_parse(url, timeout=180, on_progress=None):
        if "host1.example" in url:
            return ([], [])  # parses fine, but an EMPTY guide
        if "host2.example" in url:
            return ([], good_progs)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(epgmod, "parse_xmltv_url", fake_parse)

    manager = _make_manager(db)
    manager._fetch_worker("cyc-empty", "Cyc Empty", None)

    with db.session_scope(commit=False) as session:
        count = session.query(EpgProgramDB).filter_by(provider_id="cyc-empty").count()
        prov = session.query(ProviderDB).filter_by(id="cyc-empty").first()
        by_url = {e["url"]: e for e in parse_provider_urls(prov.urls)}

    assert count == 3, "host 2's non-empty guide must be stored"
    assert by_url["http://host1.example"]["failure_count"] == 1, (
        "a zero-programme payload must be recorded as a failure"
    )
    assert by_url["http://host2.example"]["success_count"] == 1
    manager._executor.shutdown(wait=False)


def test_cycling_expired_guide_does_not_advance(db, monkeypatch):
    """A guide that parses with real programmes — even ones that are already
    fully expired (date range entirely in the past) — is NOT a failure and
    must NOT advance to the next host. Every host on a panel serves the same
    guide; re-downloading an identical stale payload from every other host
    (hundreds of thousands of programmes) would be a harm, not a fix. Exactly
    ONE host must be attempted."""
    import metatv.core.epg_manager as epgmod

    with db.session_scope() as session:
        _add_cycling_provider(
            session, "cyc-expired",
            hosts=["http://host1.example", "http://host2.example"],
        )

    now = now_utc()
    expired_progs = [
        XmltvProgramme(
            channel_id="c1", title="Old Show", description="",
            start_time=now - timedelta(days=10),
            stop_time=now - timedelta(days=10) + timedelta(hours=1),
        ),
    ]
    calls: list[str] = []

    def fake_parse(url, timeout=180, on_progress=None):
        calls.append(url)
        if "host2.example" in url:
            raise AssertionError(
                "must NOT advance to host 2 for an expired-but-parseable guide"
            )
        return ([], expired_progs)

    monkeypatch.setattr(epgmod, "parse_xmltv_url", fake_parse)

    manager = _make_manager(db)
    manager._fetch_worker("cyc-expired", "Cyc Expired", None)

    with db.session_scope(commit=False) as session:
        count = session.query(EpgProgramDB).filter_by(provider_id="cyc-expired").count()

    assert count == 1, "the (expired) guide must still be stored, not discarded"
    assert len(calls) == 1, "exactly one host must have been attempted"
    assert "host1.example" in calls[0]
    manager._executor.shutdown(wait=False)


def test_override_never_cycles_one_attempt_even_on_failure(db, monkeypatch):
    """A user override is fetched exactly once — even when it fails — never
    falling back to the provider's other configured hosts."""
    import metatv.core.epg_manager as epgmod

    with db.session_scope() as session:
        _add_cycling_provider(
            session, "cyc-override-fail",
            hosts=["http://host1.example", "http://host2.example"],
            override="http://custom.example/guide.xml",
        )

    calls: list[str] = []

    def fake_parse(url, timeout=180, on_progress=None):
        calls.append(url)
        raise ConnectionError("custom host is down")

    monkeypatch.setattr(epgmod, "parse_xmltv_url", fake_parse)

    manager = _make_manager(db)
    manager._fetch_worker("cyc-override-fail", "Cyc Override Fail", None)

    assert calls == ["http://custom.example/guide.xml"], (
        "override must be tried exactly once, verbatim, with no cycling"
    )

    with db.session_scope(commit=False) as session:
        count = session.query(EpgProgramDB).filter_by(provider_id="cyc-override-fail").count()
        prov = session.query(ProviderDB).filter_by(id="cyc-override-fail").first()
        by_url = {e["url"]: e for e in parse_provider_urls(prov.urls)}

    assert count == 0, "a failed override attempt must not store anything"
    # An override skips UrlCycler entirely — neither configured host's stats moved
    # (no "failure_count" key at all, since persist_url_stats() was never called).
    assert by_url["http://host1.example"].get("failure_count", 0) == 0
    assert by_url["http://host2.example"].get("failure_count", 0) == 0
    manager._executor.shutdown(wait=False)


def test_no_latency_recorded_for_epg_attempts(db, monkeypatch):
    """EPG cycling attempts (success AND failure) must record no response-time —
    mirrors the fetch_channels exclusion: a full XMLTV download is a bulk
    transfer, not a comparably-sized request, so mixing it into
    median_latency_ms() would make the median meaningless."""
    import metatv.core.epg_manager as epgmod

    with db.session_scope() as session:
        _add_cycling_provider(
            session, "cyc-no-latency",
            hosts=["http://host1.example", "http://host2.example"],
        )

    good_progs = _fake_programmes(1)

    def fake_parse(url, timeout=180, on_progress=None):
        if "host1.example" in url:
            raise ConnectionError("down")
        return ([], good_progs)

    monkeypatch.setattr(epgmod, "parse_xmltv_url", fake_parse)

    manager = _make_manager(db)
    manager._fetch_worker("cyc-no-latency", "Cyc No Latency", None)

    with db.session_scope(commit=False) as session:
        prov = session.query(ProviderDB).filter_by(id="cyc-no-latency").first()
        by_url = {e["url"]: e for e in parse_provider_urls(prov.urls)}

    for host in ("http://host1.example", "http://host2.example"):
        attempts = by_url[host].get("recent_attempts") or []
        assert attempts, f"{host} must have a recorded attempt"
        assert attempts[-1]["response_time_ms"] is None, (
            f"{host}: EPG cycling attempts must not record latency"
        )
    manager._executor.shutdown(wait=False)
