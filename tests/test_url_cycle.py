"""Behavioral tests for the URL-cycling chokepoint (core/url_cycle.py).

Seven+ code paths across the app cycle through a provider's alternate URLs
looking for a working host; most of them never fed outcomes back to the
ranker (#302). :class:`~metatv.core.url_cycle.UrlCycler` is now the single
place that records "what happened on this attempt" onto the in-memory
:class:`~metatv.core.models.Provider`, and
:func:`~metatv.core.repositories.provider.persist_url_stats` is the single
place that makes it durable. These tests exercise the real mutation path
against real dataclasses (never mocked) and the persistence round-trip
against a real file-backed :class:`~metatv.core.database.Database` — a
count-only assertion would pass on exactly the bug this slice fixes
(``fetch_channels`` used to bump ``success_count``/``failure_count`` and
nothing else).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.models import Provider, ProviderURL
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import persist_url_stats
from metatv.core.url_cycle import UrlCycler


def _provider(urls: list[ProviderURL], provider_id: str = "prov-1") -> Provider:
    """Build a minimal in-memory Provider carrying *urls*."""
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
# 1-2: record_success / record_failure mutate ALL the fields they claim to
# ---------------------------------------------------------------------------

def test_record_success_bumps_count_sets_timestamp_clears_error():
    """A count-only assertion here is exactly the bug #302 fixes — the old
    inline ``fetch_channels`` write-back bumped ``success_count`` and nothing
    else, so ``last_success``/``last_error`` never moved."""
    pu = ProviderURL(url="http://host.example", last_error="stale failure")
    provider = _provider([pu])
    cycler = UrlCycler(provider, "test_op")

    before = datetime.now()
    cycler.record_success("http://host.example")

    assert pu.success_count == 1
    assert pu.last_success is not None
    assert pu.last_success >= before
    assert pu.last_error is None
    assert cycler.dirty is True


def test_record_failure_bumps_count_sets_timestamp_stores_message():
    pu = ProviderURL(url="http://host.example")
    provider = _provider([pu])
    cycler = UrlCycler(provider, "test_op")

    before = datetime.now()
    cycler.record_failure("http://host.example", "connection refused")

    assert pu.failure_count == 1
    assert pu.last_failure is not None
    assert pu.last_failure >= before
    assert pu.last_error == "connection refused"
    assert cycler.dirty is True


# ---------------------------------------------------------------------------
# 3: trailing-slash-insensitive matching
# ---------------------------------------------------------------------------

def test_trailing_slash_mismatch_still_matches():
    """A stored URL with a trailing slash must still match a candidate
    without one — mirrors ``ordered_urls()``'s own ``rstrip('/')`` normalization."""
    pu = ProviderURL(url="http://host.example/")
    provider = _provider([pu])
    cycler = UrlCycler(provider, "test_op")

    cycler.record_success("http://host.example")

    assert pu.success_count == 1
    assert pu.last_success is not None


# ---------------------------------------------------------------------------
# 4: unknown base URL never raises
# ---------------------------------------------------------------------------

def test_unknown_base_url_is_a_noop_and_never_raises():
    """An untracked base URL (e.g. the legacy ``provider.url`` fallback, which
    has no ``ProviderURL`` row) must be silently ignored, not raise."""
    pu = ProviderURL(url="http://known.example")
    provider = _provider([pu])
    cycler = UrlCycler(provider, "test_op")

    cycler.record_success("http://totally-unknown.example")
    cycler.record_failure("http://also-unknown.example", "boom")

    assert pu.success_count == 0
    assert pu.failure_count == 0
    assert cycler.dirty is False


# ---------------------------------------------------------------------------
# 5: the demotion property, end to end — the user-visible point of the slice
# ---------------------------------------------------------------------------

def test_recording_failures_changes_ordered_urls_ranking():
    """Recording via UrlCycler must actually move the needle on ordered_urls().

    ``Provider.ordered_urls()`` (core/models.py) is a 3-tier ranker: tier 0 =
    has at least one recorded success (ranked by ratio), tier 1 = untested,
    tier 2 = only failures. Under that algorithm a URL that has EVER recorded
    a success can never be demoted below an untested URL no matter how many
    failures follow — tier 0 always sorts before tier 1, regardless of ratio.
    So the real, achievable demotion case (and the one #302's bug actually
    produces) is: a URL currently ranked FIRST purely because it's
    untested-but-higher-priority accumulates only failures and drops from
    tier 1 to tier 2, while a second URL left untested (tier 1) overtakes it.

    Before this slice, nothing ever recorded those failures (five of the
    seven cycling call sites recorded no outcome at all), so a chronically
    failing host stayed pinned in the untested tier — and ahead of healthier
    alternatives — forever. This test proves recording via UrlCycler is what
    breaks that: the order actually changes, not just the counters.
    """
    url_a = ProviderURL(url="http://flaky.example", priority=0)  # wins the untested tiebreak on priority
    url_b = ProviderURL(url="http://untouched.example", priority=1)
    provider = _provider([url_a, url_b])

    # Before recording: both untested (tier 1) — A wins on priority.
    assert provider.ordered_urls()[0].rstrip('/') == "http://flaky.example"

    cycler = UrlCycler(provider, "test_op")
    for _ in range(5):
        cycler.record_failure("http://flaky.example", "connection refused")

    # After recording: A has only failures (tier 2), B is still untested
    # (tier 1) — B now ranks first. The ORDER changed, not just the counts.
    ordered = provider.ordered_urls()
    assert ordered[0].rstrip('/') == "http://untouched.example"
    assert ordered.index("http://untouched.example") < ordered.index("http://flaky.example")
    assert url_a.failure_count == 5


# ---------------------------------------------------------------------------
# 6: persist_url_stats round-trips through a REAL file-backed Database
# ---------------------------------------------------------------------------

def test_persist_url_stats_round_trips_counts_and_timestamps(tmp_path):
    """Counts AND all three timestamp/error fields must survive a real
    commit + a fresh read (not just live on in the in-memory object) —
    DB-session work uses a real file, never ``:memory:``."""
    db_path = tmp_path / "url_cycle_test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    try:
        with db.session_scope() as session:
            session.add(ProviderDB(
                id="prov-1",
                name="Test Provider",
                type="xtream",
                url="http://primary.example",
                urls=[
                    {"url": "http://primary.example", "priority": 0},
                    {"url": "http://backup.example", "priority": 1},
                ],
                username="user",
                password="pass",
            ))

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            provider = repos.providers.to_model(repos.providers.get_by_id("prov-1"))

        cycler = UrlCycler(provider, "test_op")
        cycler.record_success("http://primary.example")
        cycler.record_failure("http://backup.example", "timeout")

        persist_url_stats(db, provider)

        # Re-read from a FRESH session/model to prove it actually persisted,
        # not just that the in-memory object still holds the values.
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            reloaded = repos.providers.to_model(repos.providers.get_by_id("prov-1"))

        primary = next(u for u in reloaded.urls if u.url == "http://primary.example")
        backup = next(u for u in reloaded.urls if u.url == "http://backup.example")

        assert primary.success_count == 1
        assert primary.last_success is not None
        assert primary.last_error is None

        assert backup.failure_count == 1
        assert backup.last_failure is not None
        assert backup.last_error == "timeout"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 7: drift guard — ordered_urls() must never be called outside the chokepoint
# ---------------------------------------------------------------------------
#
# #302 built UrlCycler as the one place that reads a provider's reliability
# order AND records what happened. Nothing stops a LATER PR from hand-rolling
# `provider.ordered_urls()` again in some new call site that reads the order
# but has no disciplined way to feed outcomes back — exactly how the original
# seven-call-site drift happened. This test closes that hole: any future
# direct call anywhere under metatv/ outside the chokepoint fails the suite.

_REPO_ROOT = Path(__file__).resolve().parents[1]
_METATV_ROOT = _REPO_ROOT / "metatv"
_ALLOWED_REL = {"metatv/core/url_cycle.py", "metatv/core/models.py"}
_CALL_RE = re.compile(r"\.ordered_urls\(")


def test_ordered_urls_call_sites_confined_to_chokepoint() -> None:
    """``Provider.ordered_urls()`` must be called only from
    ``core/url_cycle.py`` (the ``UrlCycler`` chokepoint) or ``core/models.py``
    (its own definition). If this test fires: replace the direct call with
    ``UrlCycler(provider, operation).candidates()``.
    """
    violations: list[tuple[str, int, str]] = []
    for path in _METATV_ROOT.rglob("*.py"):
        rel = str(path.relative_to(_REPO_ROOT))
        if rel in _ALLOWED_REL:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, start=1):
            if _CALL_RE.search(line):
                violations.append((rel, lineno, line.strip()))

    if not violations:
        return

    report = "\n".join(
        f"  {rel}:{lineno}  →  {snippet}" for rel, lineno, snippet in violations
    )
    pytest.fail(
        f"Found {len(violations)} direct ordered_urls() call site(s) outside "
        "core/url_cycle.py. Route through UrlCycler(provider, operation)"
        f".candidates() instead:\n{report}"
    )
