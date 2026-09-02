"""Behavioral tests for the one-shot "try this URL first" boost.

The Source editor's URL list used to have up/down reorder arrows that were a
placebo: the saved order landed in ``priority``, the LAST tiebreak in
``Provider.ordered_urls()``'s sort key, so evidence (cooldown/health/latency)
always overrode a manual reorder. ``ProviderURL.try_first`` replaces the
arrows with a one-shot override that deliberately outranks even cooldown —
the user is saying "I know something the stats don't" — and clears itself the
moment the next attempt on that URL is recorded.

These tests exercise the real dataclasses/sort key (never mocked) and the
persistence round-trip against a real file-backed
:class:`~metatv.core.database.Database` (never ``:memory:``), per the
project's "prove behavior" testing rule.
"""

from __future__ import annotations

from datetime import datetime

from metatv.core.database import Database, ProviderDB
from metatv.core.models import ConnectionAttempt, Provider, ProviderURL
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import provider_url_to_raw
from metatv.core.url_cycle import UrlCycler
from metatv.core.url_policy import UrlRankingPolicy


def _provider(urls: list[ProviderURL], provider_id: str = "prov-1") -> Provider:
    """Build a minimal in-memory Provider carrying *urls* (mirrors test_url_ranking.py)."""
    return Provider(
        id=provider_id,
        name="Test Provider",
        type="xtream",
        url=urls[0].url if urls else "http://fallback.example",
        urls=urls,
        username="user",
        password="pass",
    )


# ---------------------------------------------------------------------------
# 1: try_first outranks even a recent in-cooldown failure, above a healthy,
#    measured, untouched URL — the whole point of the boost ("I know
#    something the stats don't").
# ---------------------------------------------------------------------------

def test_try_first_outranks_cooldown_and_health():
    policy = UrlRankingPolicy(health_decay=0.85, cooldown_minutes=10, recent_attempts_kept=20)

    # Armed, and its most recent attempt failed just now — inside the
    # cooldown window and dragging health down too.
    armed = ProviderURL(
        url="http://armed.example", priority=5, try_first=True,
        failure_count=1,
        recent_attempts=[ConnectionAttempt(timestamp=datetime.now(), success=False)],
    )
    # Healthy, measured, better priority, no cooldown — everything the OLD
    # ranker would put first.
    healthy = ProviderURL(
        url="http://healthy.example", priority=0,
        success_count=10,
        recent_attempts=[
            ConnectionAttempt(timestamp=datetime.now(), success=True, response_time_ms=50)
            for _ in range(10)
        ],
    )
    provider = _provider([armed, healthy])

    ordered = provider.ordered_urls(policy)

    assert ordered[0] == "http://armed.example", ordered


# ---------------------------------------------------------------------------
# 2: recording an outcome clears the one-shot flag — evidence resumes control.
# ---------------------------------------------------------------------------

def test_record_success_clears_try_first():
    pu = ProviderURL(url="http://host.example", try_first=True)
    cycler = UrlCycler(_provider([pu]), "test_op")

    cycler.record_success("http://host.example")

    assert pu.try_first is False


def test_record_failure_clears_try_first():
    pu = ProviderURL(url="http://host.example", try_first=True)
    cycler = UrlCycler(_provider([pu]), "test_op")

    cycler.record_failure("http://host.example", "connection refused")

    assert pu.try_first is False


# ---------------------------------------------------------------------------
# 3: to_model reads try_first from the raw JSON blob — True when present,
#    False (never a crash) when the key is missing (every pre-upgrade row).
# ---------------------------------------------------------------------------

def test_to_model_reads_try_first_true_and_defaults_missing_to_false(tmp_path):
    db_path = tmp_path / "try_first_default.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    try:
        with db.session_scope() as session:
            session.add(ProviderDB(
                id="prov-1", name="Test Provider", type="xtream",
                url="http://a.example",
                urls=[
                    {"url": "http://a.example", "priority": 0, "try_first": True},
                    {"url": "http://b.example", "priority": 1},  # no try_first key at all
                ],
                username="user", password="pass",
            ))

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            provider = repos.providers.to_model(repos.providers.get_by_id("prov-1"))

        a = next(u for u in provider.urls if u.url == "http://a.example")
        b = next(u for u in provider.urls if u.url == "http://b.example")
        assert a.try_first is True
        assert b.try_first is False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4: provider_url_to_raw -> to_model full round trip — regression test for
#    the editor Save bug this slice also fixes: the old hand-built save dict
#    wrote only url/priority/is_active/success_count/failure_count, silently
#    discarding recent_attempts/last_success/last_failure/last_error (and
#    would have discarded try_first too). This proves the replacement
#    survives an actual DB write + a FRESH read, not just live in memory.
# ---------------------------------------------------------------------------

def test_provider_url_to_raw_round_trips_through_a_real_db(tmp_path):
    ts_fail = datetime(2026, 1, 1, 8, 0, 0)
    ts_ok = datetime(2026, 1, 2, 9, 30, 0)
    pu = ProviderURL(
        url="http://host.example",
        priority=7,
        success_count=3,
        failure_count=2,
        last_success=ts_ok,
        last_failure=ts_fail,
        last_error="connection refused",
        try_first=True,
        recent_attempts=[
            ConnectionAttempt(
                timestamp=ts_fail, success=False, client_ip="1.2.3.4",
                error_message="timeout", response_time_ms=None,
            ),
            ConnectionAttempt(
                timestamp=ts_ok, success=True, client_ip="1.2.3.4",
                error_message=None, response_time_ms=250,
            ),
        ],
    )

    raw = provider_url_to_raw(pu, priority=3)

    db_path = tmp_path / "url_to_raw_roundtrip.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    try:
        with db.session_scope() as session:
            session.add(ProviderDB(
                id="prov-1", name="Test Provider", type="xtream",
                url="http://host.example", urls=[raw],
                username="user", password="pass",
            ))

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            reloaded = repos.providers.to_model(repos.providers.get_by_id("prov-1"))

        got = reloaded.urls[0]
        assert got.priority == 3  # the priority ARG passed to provider_url_to_raw, not pu.priority
        assert got.try_first is True
        assert got.success_count == 3
        assert got.failure_count == 2
        assert got.last_success == ts_ok
        assert got.last_failure == ts_fail
        assert got.last_error == "connection refused"

        assert len(got.recent_attempts) == 2
        a0, a1 = got.recent_attempts
        assert a0.timestamp == ts_fail
        assert a0.success is False
        assert a0.client_ip == "1.2.3.4"
        assert a0.error_message == "timeout"
        assert a1.timestamp == ts_ok
        assert a1.success is True
        assert a1.response_time_ms == 250
    finally:
        db.close()
