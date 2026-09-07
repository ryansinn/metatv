"""Unit tests for ``core/migration_gate.py``.

``is_running``/``_set_running`` are the read-only gate covered end-to-end by
``tests/test_background_refresh_mixin.py`` (the sidebar consumer) and
``tests/test_json_migration.py`` (the ``MigrationManager`` writer side).

This file covers ``wait_until_idle`` — the bounded polling wait pulled out of
``TmdbEnrichmentManager._defer_for_migration`` and
``MetadataEnrichmentQueue._defer_for_migration`` (R4, docs/REFACTOR_PLAN.md),
which were byte-for-byte identical except for their own poll/ceiling
constants and ``should_stop`` source. Behaviour for each caller is still
pinned in ``tests/test_tmdb_enrichment.py``
(``test_defer_for_migration_*``, patching ``migration_gate.time.sleep``); this
file tests the shared function directly, independent of any caller.
"""
from __future__ import annotations

from metatv.core import migration_gate


class _FakeMigrationManager:
    """Reports ``.is_running`` True for a fixed number of polls, then False."""

    def __init__(self, running_for_n_checks: int) -> None:
        self._remaining = running_for_n_checks
        self.checks = 0

    @property
    def is_running(self) -> bool:
        self.checks += 1
        if self._remaining > 0:
            self._remaining -= 1
            return True
        return False


def test_wait_until_idle_returns_false_with_no_migration_manager(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(migration_gate.time, "sleep", lambda s: sleeps.append(s))

    result = migration_gate.wait_until_idle(
        None, max_wait_s=10.0, poll_s=1.0, should_stop=lambda: False)

    assert result is False
    assert sleeps == []


def test_wait_until_idle_returns_false_when_already_idle(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(migration_gate.time, "sleep", lambda s: sleeps.append(s))
    fake_mm = _FakeMigrationManager(running_for_n_checks=0)

    result = migration_gate.wait_until_idle(
        fake_mm, max_wait_s=10.0, poll_s=1.0, should_stop=lambda: False)

    assert result is False
    assert sleeps == []


def test_wait_until_idle_polls_until_manager_goes_idle(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(migration_gate.time, "sleep", lambda s: sleeps.append(s))
    fake_mm = _FakeMigrationManager(running_for_n_checks=3)

    result = migration_gate.wait_until_idle(
        fake_mm, max_wait_s=10.0, poll_s=1.0, should_stop=lambda: False)

    assert result is True
    assert sleeps == [1.0, 1.0, 1.0]
    assert fake_mm.checks == 4, "one extra check that finally saw not-running"


def test_wait_until_idle_bounded_by_max_wait_s(monkeypatch):
    """A stuck/misreporting manager can't wedge the caller forever."""
    sleeps: list[float] = []
    monkeypatch.setattr(migration_gate.time, "sleep", lambda s: sleeps.append(s))

    class _AlwaysRunning:
        is_running = True

    result = migration_gate.wait_until_idle(
        _AlwaysRunning(), max_wait_s=3.0, poll_s=1.0, should_stop=lambda: False)

    assert result is True
    # 3.0s ceiling / 1.0s poll interval => bails after 3 sleeps.
    assert len(sleeps) == 3


def test_wait_until_idle_stops_immediately_when_should_stop_fires(monkeypatch):
    """``should_stop`` breaks the wait even while the manager reports running —
    a caller already tearing down must not ride out the whole wait."""
    sleeps: list[float] = []
    monkeypatch.setattr(migration_gate.time, "sleep", lambda s: sleeps.append(s))

    class _AlwaysRunning:
        is_running = True

    result = migration_gate.wait_until_idle(
        _AlwaysRunning(), max_wait_s=10.0, poll_s=1.0, should_stop=lambda: True)

    assert result is False
    assert sleeps == []
