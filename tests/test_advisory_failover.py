"""An HTTP 403 from one host must not abort the whole failover sweep (owner log,
2026-08-16): 19 alternate hosts configured, one tried, one 403, gave up in 3
seconds. ``validate_and_failover_stream_url`` (main_window_streaming.py) ended
every failed attempt with a bare ``if alt_err: return "", alt_err`` — but
``_is_advisory_error`` already classifies 401/403/511 as HOST-level (auth/
gating), not content-level, and was only ever consulted when building the
failure TOAST, never at the decision point in the loop itself.

Three defects, three groups of tests below:

  1. The failover loop now continues past an advisory error (on the primary
     OR an alternate) and only stops for a genuine content-level text error.
     Cases 1-5, 8.
  2. The primary URL's own attempt was never recorded through UrlCycler, so a
     permanently-dead primary host kept health=1.00 forever. Cases 6-7.
  3. The episode failure path never got the advisory "Play Anyway" handling
     the channel path already has, and unconditionally fed
     stream_retry_manager.add_failure even for advisory errors. Cases 9-11.

All DB tests use file-backed SQLite (tmp_path), per CLAUDE.md rule — never
``:memory:``. Expected counts/URLs are hard-coded from each scenario's own
design, never derived from an observed run (a prior slice on this code had
exactly that false-pass: an attempt count computed from ``len(calls)``
silently adapted when the guard it was meant to test was removed).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from metatv.core.url_cycle import UrlCycler


# ---------------------------------------------------------------------------
# Helpers — mirror tests/test_url_latency_recording.py's DB/mixin scaffolding.
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    return d


def _insert_provider(session, provider_id: str, name: str, url: str, urls=None):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id,
        name=name,
        type="xtream",
        url=url,
        urls=urls or [],
        is_active=True,
    )
    session.add(p)
    session.flush()
    return p


def _make_mixin(db):
    """A bare ``_StreamingMixin`` instance wired with a real Database."""
    from tests.conftest import wire_shutdown_flag
    from metatv.gui.main_window_streaming import _StreamingMixin
    obj = wire_shutdown_flag(_StreamingMixin.__new__(_StreamingMixin))
    obj.loading_channels = set()
    obj.db = db
    obj.executor = MagicMock()
    obj.player_manager = MagicMock()
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-123"
    obj.status_bar = MagicMock()
    obj._stream_ready = MagicMock()
    return obj


def _reload_url(db, provider_id: str, base_url: str):
    """Re-read a provider's alternate-URL stats from a FRESH session."""
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope(commit=False) as session:
        provider_model = RepositoryFactory(session).providers.to_model(
            RepositoryFactory(session).providers.get_by_id(provider_id)
        )
    return next(u for u in provider_model.urls if u.url.rstrip('/') == base_url.rstrip('/'))


# ---------------------------------------------------------------------------
# Group 1: the sweep continues past advisory errors, stops only on content.
# ---------------------------------------------------------------------------

def test_advisory_error_on_alternate_does_not_stop_sweep(tmp_path):
    """Case 1 — the owner's exact bug. alt1 403s, alt2 succeeds: alt2 must be
    tried and its URL returned, not abandoned after alt1."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://primary.example:8080"
    alt1_base = "http://alt1.example:9001"
    alt2_base = "http://alt2.example:9002"
    path_and_query = "/live/u/p/1001.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProv1", primary_base,
            urls=[
                {"url": alt1_base, "priority": 0, "is_active": True},
                {"url": alt2_base, "priority": 1, "is_active": True},
            ],
        )

    obj = _make_mixin(db)
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, None),         # primary fails, no text error
        (False, "HTTP 403"),   # alt1: advisory — must NOT stop the sweep
        (True, None),          # alt2: succeeds
    ]) as mock_validate:
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert mock_validate.call_count == 3
    assert final_url == alt2_base + path_and_query
    assert err is None


def test_genuine_text_error_on_alternate_stops_sweep(tmp_path):
    """Case 2 — alt1 returns a genuine content-level text error: alt2 must
    NEVER be attempted."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://primary.example:8080"
    alt1_base = "http://alt1.example:9001"
    alt2_base = "http://alt2.example:9002"
    path_and_query = "/live/u/p/1002.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProv2", primary_base,
            urls=[
                {"url": alt1_base, "priority": 0, "is_active": True},
                {"url": alt2_base, "priority": 1, "is_active": True},
            ],
        )

    obj = _make_mixin(db)
    # Only 2 entries: if the code incorrectly proceeds to alt2, the mock runs
    # out and raises StopIteration rather than silently passing.
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, None),                                  # primary fails
        (False, "This channel is not available"),       # alt1: content-level
    ]) as mock_validate:
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert mock_validate.call_count == 2
    assert final_url == ""
    assert err == "This channel is not available"


def test_all_alternates_advisory_fail_returns_advisory_error(tmp_path):
    """Case 3 — every alternate advisory-fails: the LAST advisory error is
    returned (not None), so the failure toast can still offer Play Anyway."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://primary.example:8080"
    alt1_base = "http://alt1.example:9001"
    alt2_base = "http://alt2.example:9002"
    stream_url = primary_base + "/live/u/p/1003.ts"

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProv3", primary_base,
            urls=[
                {"url": alt1_base, "priority": 0, "is_active": True},
                {"url": alt2_base, "priority": 1, "is_active": True},
            ],
        )

    obj = _make_mixin(db)
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, None),          # primary fails
        (False, "HTTP 403"),    # alt1: advisory
        (False, "HTTP 403"),    # alt2: advisory too (same code — deterministic)
    ]) as mock_validate:
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert mock_validate.call_count == 3
    assert final_url == ""
    assert err == "HTTP 403"


def test_advisory_error_on_primary_still_runs_failover(tmp_path):
    """Case 4 — pre-fix, an advisory primary error returned immediately.
    Post-fix, the alternate must still be attempted."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://primary.example:8080"
    alt_base = "http://alt.example:9001"
    path_and_query = "/live/u/p/1004.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProv4", primary_base,
            urls=[{"url": alt_base, "priority": 0, "is_active": True}],
        )

    obj = _make_mixin(db)
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, "HTTP 403"),   # primary: advisory
        (True, None),          # alt: succeeds
    ]) as mock_validate:
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert mock_validate.call_count == 2
    assert final_url == alt_base + path_and_query
    assert err is None


def test_genuine_text_error_on_primary_skips_failover(tmp_path):
    """Case 5 — a genuine content-level primary error stops immediately;
    zero alternates attempted."""
    obj = _make_mixin(db=MagicMock())  # self.db must never be touched here
    primary_base = "http://primary.example:8080"
    stream_url = primary_base + "/live/u/p/1005.ts"

    # Single entry: any second call raises StopIteration, proving no alternate
    # was attempted (rather than a call-count assertion alone).
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, "This channel is not available"),
    ]) as mock_validate:
        final_url, err = obj.validate_and_failover_stream_url(stream_url, "prov-x")

    assert mock_validate.call_count == 1
    assert final_url == ""
    assert err == "This channel is not available"


def test_unknown_original_base_does_not_raise(tmp_path):
    """Case 8 — the primary's base URL has no matching ProviderURL row (only
    the alternate does). record_failure's no-match branch must be a safe
    no-op — the sweep still runs and succeeds."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://deadhost.example:8080"
    alt_base = "http://goodhost.example:9090"
    path_and_query = "/live/u/p/1008.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        # primary_base is NOT in this urls list — only alt_base is tracked.
        _insert_provider(
            session, provider_id, "TestProv8", primary_base,
            urls=[{"url": alt_base, "priority": 0, "is_active": True}],
        )

    obj = _make_mixin(db)
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, None),   # primary fails — no ProviderURL row matches it
        (True, None),    # alt succeeds
    ]):
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert final_url == alt_base + path_and_query
    assert err is None


# ---------------------------------------------------------------------------
# Group 2: the primary attempt is recorded through UrlCycler.
# ---------------------------------------------------------------------------

def test_primary_failure_is_recorded_before_candidates(tmp_path):
    """Case 6 — record_failure(primary_base, ...) is called, with a non-None
    response_time_ms, and it happens BEFORE candidates() is called."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://primary.example:8080"
    alt_base = "http://alt.example:9001"
    path_and_query = "/live/u/p/1006.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        # primary_base is ALSO tracked as its own ProviderURL row here, so its
        # record_failure call actually mutates real, re-readable stats.
        _insert_provider(
            session, provider_id, "TestProv6", primary_base,
            urls=[
                {"url": primary_base, "priority": 0, "is_active": True},
                {"url": alt_base, "priority": 1, "is_active": True},
            ],
        )

    obj = _make_mixin(db)

    order: list[str] = []
    orig_record_failure = UrlCycler.record_failure
    orig_candidates = UrlCycler.candidates

    def _spy_record_failure(self, *a, **kw):
        order.append("record_failure")
        return orig_record_failure(self, *a, **kw)

    def _spy_candidates(self, *a, **kw):
        order.append("candidates")
        return orig_candidates(self, *a, **kw)

    with patch.object(UrlCycler, "record_failure", _spy_record_failure), \
         patch.object(UrlCycler, "candidates", _spy_candidates), \
         patch.object(obj, "validate_stream_url", side_effect=[
             (False, None),   # primary fails
             (True, None),    # alt succeeds
         ]):
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert final_url == alt_base + path_and_query
    # The primary's own record_failure call is the very first thing recorded
    # — strictly before the first candidates() call.
    assert order == ["record_failure", "candidates"]

    primary_pu = _reload_url(db, provider_id, primary_base)
    assert primary_pu.failure_count == 1
    assert len(primary_pu.recent_attempts) == 1
    attempt = primary_pu.recent_attempts[0]
    assert attempt.success is False
    assert attempt.response_time_ms is not None
    assert isinstance(attempt.response_time_ms, int)


def test_primary_text_error_not_recorded_against_host(tmp_path):
    """Case 7 — a genuine content-level primary error must NOT damage host
    health: UrlCycler.record_failure is never called for it."""
    obj = _make_mixin(db=MagicMock())
    primary_base = "http://primary.example:8080"
    stream_url = primary_base + "/live/u/p/1007.ts"

    with patch.object(UrlCycler, "record_failure") as mock_record_failure, \
         patch.object(obj, "validate_stream_url", return_value=(False, "This channel is not available")):
        final_url, err = obj.validate_and_failover_stream_url(stream_url, "prov-x")

    mock_record_failure.assert_not_called()
    assert final_url == ""
    assert err == "This channel is not available"


# ---------------------------------------------------------------------------
# Group 4 (URL-1): a single-address provider's inconclusive probe lets mpv
# decide rather than damaging that address's ranking stats — there is
# nothing to fail over TO, so the probe's verdict on a timeout/advisory error
# is worthless. See the "no alternate" early-return in
# validate_and_failover_stream_url (main_window_streaming.py).
# ---------------------------------------------------------------------------

def test_single_url_timeout_lets_mpv_decide(tmp_path):
    """A single-URL provider times out on its only address: record_failure
    must NOT be called (nothing to compare it against), and the original URL
    is handed back unchanged so the caller launches mpv directly."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://onlyhost.example:8080"
    stream_url = primary_base + "/live/u/p/2001.ts"

    with db.session_scope() as session:
        _insert_provider(session, provider_id, "TestProvSingle", primary_base)

    obj = _make_mixin(db)
    with patch.object(UrlCycler, "record_failure") as mock_record_failure, \
         patch.object(obj, "validate_stream_url",
                       return_value=(False, None)) as mock_validate:
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert mock_validate.call_count == 1
    assert final_url == stream_url
    mock_record_failure.assert_not_called()


def test_single_url_text_error_still_fails(tmp_path):
    """A genuine content-level text error on a single-URL provider keeps the
    existing failure behavior — content-level, so the toast is right and mpv
    is never handed a URL the server explicitly refused."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://onlyhost2.example:8080"
    stream_url = primary_base + "/live/u/p/2002.ts"

    with db.session_scope() as session:
        _insert_provider(session, provider_id, "TestProvSingle2", primary_base)

    obj = _make_mixin(db)
    with patch.object(UrlCycler, "record_failure") as mock_record_failure, \
         patch.object(obj, "validate_stream_url",
                       return_value=(False, "This channel is not available")):
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert final_url == ""
    assert err == "This channel is not available"
    mock_record_failure.assert_not_called()


def test_multi_url_timeout_still_records_and_cycles(tmp_path):
    """A multi-URL provider keeps the FULL existing behavior: a timeout on
    the primary is still recorded through UrlCycler, and the sweep still
    tries the alternate — pinned so the single-URL shortcut above never
    silently widens to cover a provider that actually has somewhere to fail
    over TO."""
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://primary.example:8080"
    alt_base = "http://alt.example:9001"
    path_and_query = "/live/u/p/2003.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProvMulti", primary_base,
            urls=[{"url": alt_base, "priority": 0, "is_active": True}],
        )

    obj = _make_mixin(db)
    with patch.object(UrlCycler, "record_failure") as mock_record_failure, \
         patch.object(obj, "validate_stream_url", side_effect=[
             (False, None),   # primary: timeout
             (True, None),    # alt: succeeds
         ]) as mock_validate:
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert mock_validate.call_count == 2
    assert final_url == alt_base + path_and_query
    assert err is None
    mock_record_failure.assert_called_once()
    assert mock_record_failure.call_args[0][0] == primary_base


# ---------------------------------------------------------------------------
# Group 3: episode path gets the same advisory handling as the channel path.
# ---------------------------------------------------------------------------

def _make_episode_host():
    """A skeleton composing ``_SeriesMixin`` + ``_StreamingMixin`` — real
    multiple inheritance (mirrors ``MainWindow``'s own composition), so
    ``self._is_advisory_error`` resolves for real via ``_StreamingMixin``,
    exactly as it does on the real MainWindow.
    """
    from tests.conftest import wire_shutdown_flag
    from metatv.gui.main_window_series import _SeriesMixin
    from metatv.gui.main_window_streaming import _StreamingMixin

    class _EpisodeHost(_SeriesMixin, _StreamingMixin):
        pass

    obj = wire_shutdown_flag(_EpisodeHost.__new__(_EpisodeHost))
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "fail-notif-1"
    obj.status_bar = MagicMock()
    obj.stream_retry_manager = MagicMock()
    obj._do_launch_episode = MagicMock()
    return obj


def _shown_action_labels(obj) -> list[str]:
    kwargs = obj.notification_manager.show.call_args.kwargs
    return [label for (label, _fn) in kwargs["actions"]]


def test_episode_advisory_offers_play_anyway_and_records_failure():
    """Case 9 — advisory episode error (HTTP 403): Play Anyway is offered
    FIRST, and the failure still reaches the retry ledger.

    Recording advisory codes is deliberate, not an oversight: the channel path
    removed exactly this gate in #227 because streams that return 511 forever
    never graduated to "dead" while advisory errors were skipped, so the ledger
    never learned about the streams it exists to surface.
    """
    obj = _make_episode_host()

    obj._on_episode_stream_unavailable(
        "notif-1", "Ep Title", "HTTP 403", "http://host/ep.mp4",
        queue_episodes=None, provider_id="prov-1", start_seconds=42,
    )

    labels = _shown_action_labels(obj)
    assert labels[0] == "Play Anyway"   # first, not merely present
    obj.stream_retry_manager.add_failure.assert_called_once_with(
        "http://host/ep.mp4", "Ep Title", "http://host/ep.mp4", "HTTP 403",
    )


def test_episode_non_advisory_also_offers_play_anyway_and_records_failure():
    """Case 10 — a genuine content-level error behaves IDENTICALLY.

    This is the regression guard for re-gating the escape hatch. Play Anyway is
    an override of the pre-flight check, not a reward for a particular status
    code: mpv routinely plays what ``requests`` rejected, so withholding the
    override on a content-level guess is precisely the failure the owner hit —
    an episode that would not play and no way to insist.
    """
    obj = _make_episode_host()

    obj._on_episode_stream_unavailable(
        "notif-1", "Ep Title", "This channel is not available",
        "http://host/ep.mp4", queue_episodes=None, provider_id="prov-1",
        start_seconds=0,
    )

    labels = _shown_action_labels(obj)
    assert labels[0] == "Play Anyway"
    assert "Copy Error" in labels
    obj.stream_retry_manager.add_failure.assert_called_once_with(
        "http://host/ep.mp4", "Ep Title", "http://host/ep.mp4",
        "This channel is not available",
    )


def test_episode_play_anyway_threads_full_payload():
    """Case 11 — invoking the Play Anyway action calls _do_launch_episode
    with exactly the notif_id/stream_url/title/queue_episodes/provider_id/
    start_seconds carried through the widened _episode_failed signal."""
    obj = _make_episode_host()
    queue = [SimpleNamespace(stream_url="http://host/ep2.mp4", title="Ep 2")]

    obj._on_episode_stream_unavailable(
        "notif-1", "Ep Title", "HTTP 401", "http://host/ep.mp4",
        queue_episodes=queue, provider_id="prov-7", start_seconds=99,
    )

    kwargs = obj.notification_manager.show.call_args.kwargs
    play_anyway_fn = next(fn for (label, fn) in kwargs["actions"] if label == "Play Anyway")
    play_anyway_fn()

    obj._do_launch_episode.assert_called_once_with(
        "notif-1", "http://host/ep.mp4", "Ep Title", queue, "prov-7", 99,
    )
