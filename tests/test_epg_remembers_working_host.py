"""A 403 on one host must not become a permanently wrong guide URL.

The fetch already cycles: hosts are tried in reliability order and a failure
advances to the next. What did not survive the attempt was the ANSWER. With no
explicit host, ``build_epg_url`` took the first entry in ``urls`` — a position,
not a fact about which host serves EPG — so on a panel with twenty hosts where
only some answer ``xmltv.php``, the displayed URL and the one ``effective_epg_url``
gates on could keep naming a host that returns 403 while every real fetch
succeeded somewhere else. Owner's report: a 403 sitting beside a green
AUTODETECTED badge that never updated.

Only the HOST is remembered. Credentials are re-derived on every build, so this
cannot rot the way the cached ``epg_url`` column did — that one froze a previous
account's credentials for 11 days.
"""

from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.epg_manager import EpgManager
from tests.conftest import wire_epg_manager_skeleton

DEAD = "http://dead.example"
WORKS = "http://works.example"


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'epg.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(db, remembered=None, hosts=(DEAD, WORKS)) -> None:
    """Insert the provider row. Callers re-read it inside their own scope.

    Deliberately returns nothing: a ProviderDB handed out of a closed
    session_scope is detached, and its next attribute access raises
    DetachedInstanceError (CLAUDE.md — ORM objects must not outlive their
    session). The first version of this helper did exactly that.
    """
    urls = [{"url": h, "priority": i, "is_active": True}
            for i, h in enumerate(hosts)]
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="T", type="xtream", url=hosts[0],
                         username="u", password="pw", urls=urls,
                         epg_last_good_base_url=remembered))


def _built(db) -> str:
    with db.session_scope(commit=False) as s:
        return EpgManager.build_epg_url(s.query(ProviderDB).filter_by(id="p1").one())


def _effective(db) -> str:
    with db.session_scope(commit=False) as s:
        return EpgManager.effective_epg_url(
            s.query(ProviderDB).filter_by(id="p1").one())


def test_without_a_remembered_host_the_first_configured_one_is_used(db):
    _provider(db)
    assert _built(db).startswith(DEAD)


def test_a_remembered_host_wins_over_position(db):
    """The point of the fix: the URL shown is one known to serve a guide."""
    _provider(db, remembered=WORKS)
    url = _built(db)
    assert url.startswith(WORKS), f"still naming the positionally-first host: {url}"
    assert "username=u&password=pw" in url, "credentials must still be derived live"


def test_effective_url_follows_the_remembered_host(db):
    """effective_epg_url gates refreshes and feeds the UI — it must agree."""
    _provider(db, remembered=WORKS)
    assert _effective(db).startswith(WORKS)


def test_a_remembered_host_that_was_removed_is_ignored(db):
    """Deleting a host from the source must drop it, not strand the guide."""
    _provider(db, remembered="http://removed.example")
    assert _built(db).startswith(DEAD)


def test_an_override_still_wins(db):
    """An explicit user URL is an instruction; remembering must not override it."""
    _provider(db, remembered=WORKS)
    with db.session_scope() as s:
        s.query(ProviderDB).filter_by(id="p1").one().epg_url_override = "http://mine/x.xml"
    assert _effective(db) == "http://mine/x.xml"


def test_a_403_on_the_first_host_advances_and_is_remembered(db, monkeypatch):
    """End to end: the reported failure mode, from 403 to a corrected URL."""
    import metatv.core.epg_manager as mod

    _provider(db)
    tried: list[str] = []

    def fake_parse(url, timeout=180, on_progress=None):
        tried.append(url)
        if url.startswith(DEAD):
            raise HTTPError(url, 403, "Forbidden", {}, None)
        return (["ch"], ["prog"])

    monkeypatch.setattr(mod, "parse_xmltv_url", fake_parse)
    mgr = EpgManager.__new__(EpgManager)
    wire_epg_manager_skeleton(mgr, db)

    channels, programmes = mgr._resolve_and_fetch_guide(
        "p1", "T", on_parse_progress=lambda n: None)

    assert programmes == ["prog"], "the working host's guide was not returned"
    assert len(tried) == 2, f"it did not advance past the 403: tried {tried}"
    assert tried[0].startswith(DEAD) and tried[1].startswith(WORKS)

    with db.session_scope(commit=False) as s:
        row = s.query(ProviderDB).filter_by(id="p1").one()
        assert row.epg_last_good_base_url == WORKS, (
            "the working host was not remembered, so the next fetch and the UI "
            "would go back to naming the host that 403s"
        )
        assert EpgManager.build_epg_url(row).startswith(WORKS)
