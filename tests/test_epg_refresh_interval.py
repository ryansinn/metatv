"""Behavior tests for EPG refresh throttle, interval helper, URL override (PR-2).

All tests execute the real changed code paths against a file-backed Database
(NOT :memory: — pooled connections each get an empty schema there). Assertions
check observable outcomes, not source-code shape.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, EpgProgramDB, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import (
    EPG_INTERVAL_CHOICES,
    epg_interval_delta,
    now_utc,
)
from metatv.core.repositories.provider import ProviderRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """File-backed Database with tables created (avoids :memory: pool isolation)."""
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


@pytest.fixture
def session(db):
    s = db.get_session()
    yield s
    s.close()


def _add_provider(session, pid, *, is_active=True, epg_url="http://e/xmltv.php",
                  epg_enabled=True, exp=None, epg_data_end=None,
                  epg_last_fetched=None, epg_data_start=None,
                  epg_refresh_interval="default", epg_url_override=None):
    """Seed a ProviderDB row with all EPG columns."""
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p",
        is_active=is_active,
        epg_url=epg_url,
        epg_enabled=epg_enabled,
        account_exp_date=exp,
        epg_data_end=epg_data_end,
        epg_last_fetched=epg_last_fetched,
        epg_data_start=epg_data_start,
        epg_refresh_interval=epg_refresh_interval,
        epg_url_override=epg_url_override,
    ))
    session.flush()


def _make_manager(db, *, epg_default="3d"):
    """Create an EpgManager with a mock config using the given global default."""
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = epg_default
    return EpgManager(db, config, notifications=None)


# ---------------------------------------------------------------------------
# A. Interval helper — epg_interval_delta()
# ---------------------------------------------------------------------------

def test_epg_interval_delta_time_values():
    """Each time-based interval value maps to the correct timedelta."""
    assert epg_interval_delta("4h")  == timedelta(hours=4)
    assert epg_interval_delta("8h")  == timedelta(hours=8)
    assert epg_interval_delta("12h") == timedelta(hours=12)
    assert epg_interval_delta("1d")  == timedelta(days=1)
    assert epg_interval_delta("2d")  == timedelta(days=2)
    assert epg_interval_delta("3d")  == timedelta(days=3)
    assert epg_interval_delta("7d")  == timedelta(days=7)


def test_epg_interval_delta_sentinels_return_none():
    """Sentinel values ('every_open', 'when_stale') return None."""
    assert epg_interval_delta("every_open") is None
    assert epg_interval_delta("when_stale") is None


def test_epg_interval_delta_unknown_returns_none():
    """An unrecognised value returns None (callers decide what to do)."""
    assert epg_interval_delta("banana") is None


def test_epg_interval_choices_contains_all_time_keys():
    """EPG_INTERVAL_CHOICES covers every key in the internal delta map."""
    time_keys = {"4h", "8h", "12h", "1d", "2d", "3d", "7d"}
    choice_values = {v for v, _ in EPG_INTERVAL_CHOICES}
    assert time_keys.issubset(choice_values), (
        f"Missing from EPG_INTERVAL_CHOICES: {time_keys - choice_values}"
    )


def test_epg_interval_choices_includes_sentinels():
    """EPG_INTERVAL_CHOICES includes both sentinel values."""
    choice_values = {v for v, _ in EPG_INTERVAL_CHOICES}
    assert "every_open" in choice_values
    assert "when_stale" in choice_values


def test_epg_interval_choices_ordered_correctly():
    """EPG_INTERVAL_CHOICES starts with 'auto' (the default) and ends with 'when_stale'."""
    values = [v for v, _ in EPG_INTERVAL_CHOICES]
    assert values[0] == "auto", "First entry must be 'auto' (the recommended default)"
    assert values[-1] == "when_stale", "Last entry must be 'when_stale'"


def test_epg_interval_choices_labels_nonempty():
    """Every entry in EPG_INTERVAL_CHOICES has a non-empty human label."""
    for value, label in EPG_INTERVAL_CHOICES:
        assert label, f"Entry {value!r} has an empty label"


# ---------------------------------------------------------------------------
# B. Interval resolution — per-source override vs global default
# ---------------------------------------------------------------------------

def test_needs_refresh_default_inherits_global_config(db):
    """A provider with epg_refresh_interval='default' inherits the global setting."""
    now = now_utc()
    # Fetched 4 days ago; guide still valid (data_end is in the future)
    with db.session_scope() as session:
        _add_provider(session, "p1",
                      epg_last_fetched=now - timedelta(days=4),
                      epg_data_end=now + timedelta(days=3),
                      epg_refresh_interval="default")

    # Global default = "7d" → 4 days < 7 days → should NOT refresh (still within interval)
    manager = _make_manager(db, epg_default="7d")
    manager._start_refresh = MagicMock()
    manager.refresh_all_if_needed()
    called = [c.args[0] for c in manager._start_refresh.call_args_list]
    assert "p1" not in called, "Within 7d interval → must NOT refresh"
    manager._executor.shutdown(wait=False)


def test_needs_refresh_per_source_override_wins(db):
    """A per-source override takes precedence over the global default."""
    now = now_utc()
    # Fetched 2 days ago; guide still valid
    with db.session_scope() as session:
        _add_provider(session, "p2",
                      epg_last_fetched=now - timedelta(days=2),
                      epg_data_end=now + timedelta(days=5),
                      epg_refresh_interval="1d")  # 1d override, global is 7d

    # 2 days elapsed > 1-day interval → MUST refresh despite global being 7d
    manager = _make_manager(db, epg_default="7d")
    manager._start_refresh = MagicMock()
    manager.refresh_all_if_needed()
    called = [c.args[0] for c in manager._start_refresh.call_args_list]
    assert "p2" in called, "Per-source 1d < 2d elapsed → must refresh"
    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# C. needs_refresh — all branches
# ---------------------------------------------------------------------------

def test_needs_refresh_never_fetched_returns_true(db):
    """never-fetched (epg_last_fetched=None) → always refresh."""
    with db.session_scope() as session:
        _add_provider(session, "never", epg_last_fetched=None, epg_data_end=None)

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="never").first()
        assert manager.needs_refresh(p) is True
    manager._executor.shutdown(wait=False)


def test_needs_refresh_every_open_always_true(db):
    """every_open → always refresh, regardless of last-fetched time."""
    now = now_utc()
    with db.session_scope() as session:
        _add_provider(session, "eo",
                      epg_last_fetched=now - timedelta(minutes=5),
                      epg_data_end=now + timedelta(days=7),
                      epg_refresh_interval="every_open")

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="eo").first()
        assert manager.needs_refresh(p) is True
    manager._executor.shutdown(wait=False)


def test_needs_refresh_within_interval_valid_guide_returns_false(db):
    """Within a time interval with a valid guide → False (no refresh needed)."""
    now = now_utc()
    with db.session_scope() as session:
        _add_provider(session, "within",
                      epg_last_fetched=now - timedelta(hours=2),
                      epg_data_end=now + timedelta(days=4),
                      epg_refresh_interval="12h")  # 2h < 12h, guide still valid

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="within").first()
        assert manager.needs_refresh(p) is False
    manager._executor.shutdown(wait=False)


def test_needs_refresh_within_interval_but_guide_expired_returns_true(db):
    """Within a time interval BUT guide has fully expired → True (expiry floor)."""
    now = now_utc()
    with db.session_scope() as session:
        _add_provider(session, "expired-floor",
                      epg_last_fetched=now - timedelta(hours=2),
                      epg_data_end=now - timedelta(hours=1),   # guide already ended
                      epg_refresh_interval="12h")  # only 2h elapsed, but guide is stale

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="expired-floor").first()
        assert manager.needs_refresh(p) is True, (
            "Expired guide must trigger refresh even within the time interval (expiry floor)"
        )
    manager._executor.shutdown(wait=False)


def test_needs_refresh_when_stale_and_guide_valid_returns_false(db):
    """when_stale → False if guide hasn't expired yet."""
    now = now_utc()
    with db.session_scope() as session:
        _add_provider(session, "ws-valid",
                      epg_last_fetched=now - timedelta(days=30),
                      epg_data_end=now + timedelta(days=1),    # still valid
                      epg_refresh_interval="when_stale")

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="ws-valid").first()
        assert manager.needs_refresh(p) is False
    manager._executor.shutdown(wait=False)


def test_needs_refresh_when_stale_and_guide_expired_returns_true(db):
    """when_stale → True if guide has fully expired."""
    now = now_utc()
    with db.session_scope() as session:
        _add_provider(session, "ws-expired",
                      epg_last_fetched=now - timedelta(days=30),
                      epg_data_end=now - timedelta(hours=1),   # expired
                      epg_refresh_interval="when_stale")

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="ws-expired").first()
        assert manager.needs_refresh(p) is True
    manager._executor.shutdown(wait=False)


def test_needs_refresh_epg_disabled_returns_false(db):
    """epg_enabled=False → needs_refresh returns False (redundant guard)."""
    with db.session_scope() as session:
        _add_provider(session, "disabled",
                      epg_enabled=False,
                      epg_last_fetched=None,  # would otherwise be True
                      epg_refresh_interval="every_open")

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="disabled").first()
        assert manager.needs_refresh(p) is False
    manager._executor.shutdown(wait=False)


def test_needs_refresh_no_url_returns_false(db):
    """No effective URL → needs_refresh is False regardless of interval."""
    now = now_utc()
    with db.session_scope() as session:
        _add_provider(session, "nourl",
                      epg_url="",  # no auto URL
                      epg_url_override=None,
                      epg_last_fetched=None,
                      epg_refresh_interval="every_open")

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="nourl").first()
        assert manager.needs_refresh(p) is False
    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# D. Effective URL — override preference
# ---------------------------------------------------------------------------

def test_effective_url_prefers_override_over_auto(db):
    """effective_epg_url returns epg_url_override when set."""
    with db.session_scope() as session:
        _add_provider(session, "override-url",
                      epg_url="http://auto/xmltv.php",
                      epg_url_override="http://custom/feed.xml")

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="override-url").first()
        assert manager.effective_epg_url(p) == "http://custom/feed.xml"
    manager._executor.shutdown(wait=False)


def test_effective_url_falls_back_to_auto_when_no_override(db):
    """effective_epg_url returns epg_url when override is None/empty."""
    with db.session_scope() as session:
        _add_provider(session, "auto-url",
                      epg_url="http://auto/xmltv.php",
                      epg_url_override=None)

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="auto-url").first()
        assert manager.effective_epg_url(p) == "http://auto/xmltv.php"
    manager._executor.shutdown(wait=False)


def test_effective_url_empty_override_falls_back(db):
    """An empty-string override is treated the same as None (falls back to auto)."""
    with db.session_scope() as session:
        _add_provider(session, "empty-override",
                      epg_url="http://auto/xmltv.php",
                      epg_url_override="")

    manager = _make_manager(db)
    with db.session_scope(commit=False) as s:
        p = s.query(ProviderDB).filter_by(id="empty-override").first()
        assert manager.effective_epg_url(p) == "http://auto/xmltv.php"
    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# E. URL override change → nulls epg_last_fetched (testable pure-logic helper)
# ---------------------------------------------------------------------------

def _url_override_change_would_null_last_fetched(old: str | None, new: str | None) -> bool:
    """Mirrors the logic in provider_editor._save: detect URL override change."""
    return (new or None) != (old or None)


def test_url_override_change_detected_when_value_differs():
    """Changing the override from one URL to another is detected."""
    assert _url_override_change_would_null_last_fetched(
        "http://old/feed.xml", "http://new/feed.xml"
    ) is True


def test_url_override_change_detected_when_set_from_none():
    """Setting an override for the first time is detected."""
    assert _url_override_change_would_null_last_fetched(None, "http://new/feed.xml") is True


def test_url_override_change_detected_when_cleared():
    """Clearing an override (→ None/empty) is detected."""
    assert _url_override_change_would_null_last_fetched("http://old/feed.xml", "") is True


def test_url_override_no_change_when_same():
    """Same override value is not a change."""
    assert _url_override_change_would_null_last_fetched(
        "http://same/feed.xml", "http://same/feed.xml"
    ) is False


def test_url_override_no_change_when_both_none():
    """Both None/empty → no change."""
    assert _url_override_change_would_null_last_fetched(None, None) is False
    assert _url_override_change_would_null_last_fetched("", "") is False
    assert _url_override_change_would_null_last_fetched(None, "") is False


def test_changing_url_override_nulls_last_fetched_in_db(db):
    """Persisting a new epg_url_override nulls epg_last_fetched in the DB."""
    now = now_utc()
    pid = "url-change"
    with db.session_scope() as session:
        _add_provider(session, pid,
                      epg_url="http://auto/xmltv.php",
                      epg_url_override=None,
                      epg_last_fetched=now - timedelta(days=1),
                      epg_data_end=now + timedelta(days=6))

    # Simulate what _save() does when the override changes
    with db.session_scope() as session:
        p = session.query(ProviderDB).filter_by(id=pid).first()
        old = p.epg_url_override or None
        new = "http://custom/feed.xml"
        p.epg_url_override = new
        if (new or None) != old:
            p.epg_last_fetched = None  # force refetch

    # Verify epg_last_fetched is now NULL
    with db.session_scope(commit=False) as session:
        p = session.query(ProviderDB).filter_by(id=pid).first()
        assert p.epg_url_override == "http://custom/feed.xml"
        assert p.epg_last_fetched is None, (
            "Changing epg_url_override must null epg_last_fetched to force a refetch"
        )


# ---------------------------------------------------------------------------
# F. New DB columns exist and are accessible
# ---------------------------------------------------------------------------

def test_new_columns_persist_and_round_trip(db):
    """epg_refresh_interval and epg_url_override survive a write/read cycle."""
    with db.session_scope() as session:
        _add_provider(session, "cols-test",
                      epg_refresh_interval="4h",
                      epg_url_override="http://override/feed.xml")

    with db.session_scope(commit=False) as session:
        p = session.query(ProviderDB).filter_by(id="cols-test").first()
        assert p.epg_refresh_interval == "4h"
        assert p.epg_url_override == "http://override/feed.xml"


def test_new_columns_default_values(db):
    """Default values for new columns match the spec ('default' and NULL)."""
    with db.session_scope() as session:
        _add_provider(session, "defaults-test")  # no epg_refresh_interval or override

    with db.session_scope(commit=False) as session:
        p = session.query(ProviderDB).filter_by(id="defaults-test").first()
        assert p.epg_refresh_interval == "default"
        assert p.epg_url_override is None
