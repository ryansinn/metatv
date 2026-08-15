"""Behavioral tests for recency-aware URL ranking (Provider.ordered_urls()).

Host ranking used to be a lifetime success/failure ratio with no notion of
latency or recency (models.py's old ``ordered_urls()``): a host that answers
in 10-12 seconds every single time counted exactly the same as one that
answers in 200ms (both just "success"), and a host with 1,000 lifetime
successes needed on the order of 1,000 consecutive failures before it would
ever fall below a healthier peer — it effectively never demoted in practice.
These tests exercise the rewritten ranker (``(cooldown_tier, -health,
median_latency_ms, priority)``) against real dataclasses, and the persistence
round-trip against a real file-backed :class:`~metatv.core.database.Database`
(never ``:memory:``), per the project's "prove behavior" testing rule.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from metatv.core.config import Config
from metatv.core.database import Database, ProviderDB
from metatv.core.models import ConnectionAttempt, Provider, ProviderURL
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import persist_url_stats


def _provider(urls: list[ProviderURL], provider_id: str = "prov-1") -> Provider:
    """Build a minimal in-memory Provider carrying *urls* (mirrors test_url_cycle.py)."""
    return Provider(
        id=provider_id,
        name="Test Provider",
        type="xtream",
        url=urls[0].url if urls else "http://fallback.example",
        urls=urls,
        username="user",
        password="pass",
    )


def _attempts(n: int, success: bool, response_time_ms: int | None = None,
              minutes_ago: float = 0.0) -> list[ConnectionAttempt]:
    """Build *n* identical ConnectionAttempts, oldest-first (append order)."""
    ts = datetime.now() - timedelta(minutes=minutes_ago)
    return [
        ConnectionAttempt(timestamp=ts, success=success, response_time_ms=response_time_ms)
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# 1: the owner's actual bug — latency must break a tie between two 100%
#    successful hosts. Under the OLD ranker (lifetime success ratio only,
#    no latency term) this was IMPOSSIBLE to express: both hosts are simply
#    "100% successful" and the tie is broken by ``priority``/insertion order,
#    never by which one is actually fast.
# ---------------------------------------------------------------------------

def test_fast_host_ranks_above_slow_host_with_equal_success():
    slow = ProviderURL(
        url="http://slow.example", priority=0,
        success_count=5, failure_count=0,
        recent_attempts=_attempts(5, success=True, response_time_ms=11000),
    )
    fast = ProviderURL(
        url="http://fast.example", priority=1,  # worse priority — latency must still win
        success_count=5, failure_count=0,
        recent_attempts=_attempts(5, success=True, response_time_ms=200),
    )
    provider = _provider([slow, fast])

    ordered = provider.ordered_urls()

    assert ordered[0].rstrip('/') == "http://fast.example"
    assert ordered.index("http://fast.example") < ordered.index("http://slow.example")


# ---------------------------------------------------------------------------
# 2: fast demotion — 1000 lifetime successes cannot save a host that just
#    started failing. Under the OLD lifetime ratio this needed ~1000
#    consecutive failures; here 5 recent failures are enough.
# ---------------------------------------------------------------------------

def test_five_recent_failures_demote_a_1000_success_host_below_a_healthy_peer():
    chronically_good = ProviderURL(
        url="http://was-great.example", priority=0,
        success_count=1000, failure_count=0,
        # Failures pushed far enough into the past that cooldown doesn't
        # also demote this URL — isolates the assertion to the health axis.
        recent_attempts=_attempts(5, success=False, minutes_ago=60),
    )
    healthy_peer = ProviderURL(
        url="http://healthy.example", priority=0,
        success_count=10, failure_count=0,
        recent_attempts=_attempts(3, success=True, response_time_ms=100),
    )
    provider = _provider([chronically_good, healthy_peer])

    # Old lifetime-ratio ranker: chronically_good is 1000/1000 = 100%,
    # healthy_peer is 10/10 = 100% too — a coin flip on priority, and
    # certainly never demoted by 5 failures against 1000 successes.
    ordered = provider.ordered_urls()

    assert ordered[0].rstrip('/') == "http://healthy.example"
    assert ordered.index("http://healthy.example") < ordered.index("http://was-great.example")

    good_health = chronically_good.health_score(Config().url_health_decay)
    peer_health = healthy_peer.health_score(Config().url_health_decay)
    assert good_health < peer_health


# ---------------------------------------------------------------------------
# 3: cooldown — recency of the failure (not just its existence) decides
#    whether a URL is demoted. Same attempt history, only the newest
#    attempt's timestamp differs; assert BOTH directions.
# ---------------------------------------------------------------------------

def test_cooldown_demotes_only_when_the_failure_is_recent():
    def _flaky(minutes_ago: float) -> ProviderURL:
        # 4 old successes + 1 failure as the NEWEST attempt (index -1).
        attempts = _attempts(4, success=True, response_time_ms=50, minutes_ago=999)
        attempts.append(ConnectionAttempt(
            timestamp=datetime.now() - timedelta(minutes=minutes_ago), success=False,
        ))
        return ProviderURL(url="http://flaky.example", priority=0, recent_attempts=attempts)

    # No recent_attempts at all -> legacy fallback health (0.5), and — with
    # no attempt history to judge recency from — this peer can never be put
    # in cooldown itself. Its health (0.5) is deliberately lower than the
    # flaky host's recent-attempts health (~0.73 with 4/5 recent successes),
    # so cooldown_tier — not health — is what must decide the order below.
    peer = ProviderURL(url="http://peer.example", priority=0,
                        success_count=1, failure_count=1)

    # Direction A: failure 1 minute ago -> within the default 10-minute
    # cooldown -> flaky host demoted below the peer despite its better health.
    recent_failure = _provider([_flaky(minutes_ago=1), peer], provider_id="p-recent")
    ordered_recent = recent_failure.ordered_urls()
    assert ordered_recent[0].rstrip('/') == "http://peer.example"
    assert ordered_recent.index("http://peer.example") < ordered_recent.index("http://flaky.example")

    # Direction B: same host, failure 60 minutes ago -> outside the 10-minute
    # cooldown -> ranks on health instead, and wins (0.73 > 0.5).
    old_failure = _provider([_flaky(minutes_ago=60), peer], provider_id="p-old")
    ordered_old = old_failure.ordered_urls()
    assert ordered_old[0].rstrip('/') == "http://flaky.example"
    assert ordered_old.index("http://flaky.example") < ordered_old.index("http://peer.example")


# ---------------------------------------------------------------------------
# 4: cooldown only demotes, it never removes — a total outage must still
#    return every URL so there's something left to try.
# ---------------------------------------------------------------------------

def test_cooldown_never_empties_the_list():
    urls = [
        ProviderURL(
            url=f"http://host{i}.example", priority=i,
            recent_attempts=[ConnectionAttempt(
                timestamp=datetime.now() - timedelta(minutes=1), success=False,
                error_message="connection refused",
            )],
        )
        for i in range(3)
    ]
    provider = _provider(urls)
    # Every URL is in cooldown; provider.url mirrors urls[0] so it can't add
    # a phantom 4th entry.
    ordered = provider.ordered_urls()

    assert len(ordered) == 3
    assert {u.rstrip('/') for u in ordered} == {u.url for u in urls}


# ---------------------------------------------------------------------------
# 5: legacy fallback — the upgrade-safety test. Every existing user's
#    ProviderURL rows have counts but an empty recent_attempts (persisted
#    before this slice existed); they must rank by their lifetime ratio, NOT
#    reset to "untested" (1.0).
# ---------------------------------------------------------------------------

def test_legacy_counts_with_no_recent_attempts_use_lifetime_ratio_not_untested():
    pu = ProviderURL(url="http://legacy.example", success_count=3, failure_count=1)

    assert pu.recent_attempts == []
    health = pu.health_score(Config().url_health_decay)

    assert health == 0.75  # 3 / (3 + 1) — the pre-existing lifetime ratio
    assert health != 1.0   # must NOT be treated as untested


# ---------------------------------------------------------------------------
# 6: untested (no counts, no attempts) stays optimistic (1.0) and therefore
#    still gets tried early, ahead of a proven-bad host.
# ---------------------------------------------------------------------------

def test_untested_url_is_optimistic_and_tried_before_a_proven_bad_host():
    untested = ProviderURL(url="http://never-tried.example", priority=5)

    assert untested.health_score(Config().url_health_decay) == 1.0
    assert untested.median_latency_ms() == 0

    proven_bad = ProviderURL(
        url="http://proven-bad.example", priority=0,  # better priority, still loses
        recent_attempts=_attempts(5, success=False, minutes_ago=60),
    )
    provider = _provider([untested, proven_bad])

    ordered = provider.ordered_urls()
    assert ordered[0].rstrip('/') == "http://never-tried.example"


# ---------------------------------------------------------------------------
# 7: persist_url_stats() / to_model() round-trip recent_attempts through a
#    REAL file-backed Database, capped at config.url_recent_attempts_kept,
#    keeping the NEWEST entries.
# ---------------------------------------------------------------------------

def test_persist_and_reload_caps_recent_attempts_to_newest_n(tmp_path):
    db_path = tmp_path / "url_ranking_test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    try:
        with db.session_scope() as session:
            session.add(ProviderDB(
                id="prov-1", name="Test Provider", type="xtream",
                url="http://primary.example",
                urls=[{"url": "http://primary.example", "priority": 0}],
                username="user", password="pass",
            ))

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            provider = repos.providers.to_model(repos.providers.get_by_id("prov-1"))

        pu = provider.urls[0]
        # Append 5 attempts, oldest to newest, with distinguishable latencies.
        for rt in (100, 200, 300, 400, 500):
            pu.add_attempt(ConnectionAttempt(success=True, response_time_ms=rt))

        persist_url_stats(db, provider, config=Config(url_recent_attempts_kept=3))

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            reloaded = repos.providers.to_model(repos.providers.get_by_id("prov-1"))

        reloaded_pu = reloaded.urls[0]
        assert len(reloaded_pu.recent_attempts) == 3
        # Newest 3 kept, in original (oldest-of-the-kept-first) order.
        assert [a.response_time_ms for a in reloaded_pu.recent_attempts] == [300, 400, 500]
        assert all(isinstance(a.timestamp, datetime) for a in reloaded_pu.recent_attempts)
        assert all(a.success for a in reloaded_pu.recent_attempts)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 8: EWMA weighting — newest outcome dominates. Same total successes/
#    failures, different order, must produce a different health score.
# ---------------------------------------------------------------------------

def test_ewma_weighting_makes_newest_outcome_dominate():
    decay = Config().url_health_decay

    # Oldest -> newest: two failures, then three successes (recovering host).
    recovering = ProviderURL(url="http://recovering.example")
    recovering.recent_attempts = (
        _attempts(2, success=False) + _attempts(3, success=True, response_time_ms=100)
    )

    # Oldest -> newest: three successes, then two failures (degrading host).
    degrading = ProviderURL(url="http://degrading.example")
    degrading.recent_attempts = (
        _attempts(3, success=True, response_time_ms=100) + _attempts(2, success=False)
    )

    health_recovering = recovering.health_score(decay)
    health_degrading = degrading.health_score(decay)

    # Same 3 successes / 2 failures either way — only the order differs.
    assert health_recovering != health_degrading
    assert health_recovering > health_degrading
