"""Direct tests for the shared migration-task base classes (R2, docs/REFACTOR_PLAN.md).

``VersionGatedTask`` (``core/migrations/base.py``) and ``DetectedFieldsReparseTask``
(``core/migrations/detected_fields_reparse.py``) replace what used to be a
byte-identical ``__init__``/``needs_run``/``on_completed``/``run`` in each of
``category_marker_backfill.py``, ``collection_token_cleanup_backfill.py``,
``detected_genre_backfill.py``, ``detected_title_reparse.py`` and
``restricted_backfill.py``. Per-task behaviour (real DB, real
``update_detected_prefixes`` rewrite) is already covered where each task
lives (``tests/test_category_marker_row_layout.py``,
``tests/test_detected_genre_backfill.py``, etc., all still green against the
shared base). This file covers the SHARED classes themselves:

1. ``VersionGatedTask`` in isolation (no channels/DB involved at all) — the
   generic version-gate contract.
2. ``DetectedFieldsReparseTask.run()`` really calls
   ``update_detected_prefixes`` exactly once.
3. The deliberate no-coalescing decision: two sibling ``DetectedFieldsReparseTask``
   subclasses, each pending, each run independently — two full passes, not one
   shared pass (docs/REFACTOR_PLAN.md R2 explains why coalescing was rejected).
"""
from __future__ import annotations

import pytest

from metatv.core.migrations.base import MigrationTask, VersionGatedTask
from metatv.core.migrations.detected_fields_reparse import DetectedFieldsReparseTask


# ---------------------------------------------------------------------------
# 1. VersionGatedTask — generic, no channels/DB involved
# ---------------------------------------------------------------------------

class _FakeTask(VersionGatedTask):
    id = "fake_task"
    label = "A fake version-gated task"
    VERSION_FIELD = "fake_task_version"
    CURRENT_VERSION = 5

    def run(self, progress_cb, is_cancelled, config=None) -> None:
        progress_cb(1, 1)


class _Cfg:
    """Bare stand-in for Config — just attribute storage + a save() spy."""

    def __init__(self):
        self.save_calls = 0

    def save(self):
        self.save_calls += 1


def test_version_gated_task_satisfies_the_migration_task_protocol():
    task = _FakeTask(db=None)
    assert isinstance(task, MigrationTask)


def test_needs_run_true_when_config_field_missing_or_behind():
    task = _FakeTask(db=None)
    cfg = _Cfg()
    assert task.needs_run(cfg) is True  # no fake_task_version attr at all
    cfg.fake_task_version = 4
    assert task.needs_run(cfg) is True  # behind CURRENT_VERSION


def test_needs_run_false_once_at_or_past_current_version():
    task = _FakeTask(db=None)
    cfg = _Cfg()
    cfg.fake_task_version = 5
    assert task.needs_run(cfg) is False


def test_on_completed_bumps_the_field_and_saves():
    task = _FakeTask(db=None)
    cfg = _Cfg()
    task.on_completed(cfg)
    assert cfg.fake_task_version == 5
    assert cfg.save_calls == 1


def test_new_without_init_still_works_needs_run_and_on_completed():
    """A test double built with ``Cls.__new__(Cls)`` (skipping ``__init__``,
    as tests/test_dedup_mojibake_and_singleton_enrich.py does for
    DetectedTitleReparseTask) must not touch ``self._db`` — both methods only
    read/write class attributes."""
    task = _FakeTask.__new__(_FakeTask)
    cfg = _Cfg()
    assert task.needs_run(cfg) is True
    task.on_completed(cfg)
    assert task.needs_run(cfg) is False


def test_init_stores_db_verbatim():
    sentinel = object()
    task = _FakeTask(sentinel)
    assert task._db is sentinel


# ---------------------------------------------------------------------------
# 2 + 3. DetectedFieldsReparseTask.run() and the no-coalescing decision
# ---------------------------------------------------------------------------

class _StubReparseTaskA(DetectedFieldsReparseTask):
    id = "stub_reparse_a"
    label = "Stub reparse A"
    VERSION_FIELD = "stub_reparse_a_version"
    CURRENT_VERSION = 1


class _StubReparseTaskB(DetectedFieldsReparseTask):
    id = "stub_reparse_b"
    label = "Stub reparse B"
    VERSION_FIELD = "stub_reparse_b_version"
    CURRENT_VERSION = 1


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'migration_base.db'}")
    db.create_tables()
    yield db
    db.close()


def test_run_calls_update_detected_prefixes_once(file_db, monkeypatch):
    from metatv.core.repositories import channel as channel_mod

    calls = []
    real = channel_mod.ChannelRepository.update_detected_prefixes

    def _counted(self, *args, **kwargs):
        calls.append((args, kwargs))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(channel_mod.ChannelRepository, "update_detected_prefixes", _counted)

    task = _StubReparseTaskA(file_db)
    task.run(progress_cb=lambda *a: None, is_cancelled=lambda: False)

    assert len(calls) == 1
    assert calls[0][1].get("provider_id") is None


def test_two_pending_sibling_tasks_each_run_their_own_full_pass(file_db, monkeypatch):
    """Deliberate no-coalescing: docs/REFACTOR_PLAN.md R2 rejected collapsing
    several pending DetectedFieldsReparseTask subclasses into one shared
    update_detected_prefixes() pass. Pin that as tested behaviour, not just a
    docstring claim — two sibling tasks running means two full passes."""
    from metatv.core.repositories import channel as channel_mod

    calls = []
    real = channel_mod.ChannelRepository.update_detected_prefixes

    def _counted(self, *args, **kwargs):
        calls.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(channel_mod.ChannelRepository, "update_detected_prefixes", _counted)

    task_a = _StubReparseTaskA(file_db)
    task_b = _StubReparseTaskB(file_db)
    task_a.run(progress_cb=lambda *a: None, is_cancelled=lambda: False)
    task_b.run(progress_cb=lambda *a: None, is_cancelled=lambda: False)

    assert len(calls) == 2, "each sibling task must still run its own full pass"


def test_run_propagates_exceptions_without_swallowing(file_db, monkeypatch):
    """#364: a crashed run() must propagate so the caller (MigrationManager)
    skips on_completed and the version stays unbumped."""
    from metatv.core.repositories import channel as channel_mod

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(channel_mod.ChannelRepository, "update_detected_prefixes", _boom)

    task = _StubReparseTaskA(file_db)
    with pytest.raises(RuntimeError):
        task.run(progress_cb=lambda *a: None, is_cancelled=lambda: False)
