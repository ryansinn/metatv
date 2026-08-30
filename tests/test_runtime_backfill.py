"""``MetadataDB.runtime`` was NULL on every row, and the data was right there.

Providers send the runtime in their own catalogue payload. Movies carry
``info.duration``; **series carry ``episode_run_time`` as a bare minutes string
at the TOP level, with no ``info`` sub-dict at all** — and that third shape is
the one the owner's three providers actually use. ``metadata_from_raw`` read
only ``info.get('duration')``, so on the owner's library:

    metadata rows with a runtime ......  0 of 652,216
    series whose payload carries one .. 48,322 of 127,552   (37.9%)
    series sending the string "0" ..... 79,230

The zero-senders are the reason ``_parse_runtime`` maps ``"0"`` to ``None``:
``"0"`` is a truthy string, so the existing ``if not duration_value`` guard
could not catch it, and a stored 0 renders as a real "0 min" — worse than
showing nothing.

Fixing ingestion alone would only reach content the owner happens to re-refresh
(cached metadata is not re-derived on read), hence ``RuntimeBackfillTask``.

The tests below execute the real resolver and the real migration against a real
file-backed database, and each was confirmed to FAIL against the pre-fix code:
reverting ``runtime_from_raw`` to ``_parse_runtime(info.get('duration'))``
reddens the series cases; dropping the ``or None`` guards reddens the zero
cases; and replacing keyset paging with OFFSET reddens ``test_pages_past_the_``
``rows_it_writes`` (see its docstring — that one is a bug this file caught).
"""

import pytest
from sqlalchemy import text

from metatv.core.database import ChannelDB, Database, MetadataDB
from metatv.core.migrations.runtime_backfill import (
    CURRENT_VERSION, RuntimeBackfillTask,
)
from metatv.metadata_providers.provider_metadata import (
    metadata_from_raw, runtime_from_raw,
)


# --------------------------------------------------------------------------
# The resolver — one definition of "where the runtime lives"
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    # The shape the owner's providers actually send: top-level, no info dict.
    ({"episode_run_time": "45"}, 45),
    ({"episode_run_time": "22"}, 22),
    ('{"episode_run_time": "50"}', 50),          # stored as a JSON string
    # A nested series shape, and the movie shape.
    ({"info": {"episode_run_time": "30"}}, 30),
    ({"info": {"duration": "120 min"}}, 120),
    ({"info": {"duration": 95}}, 95),
    # info present but empty/unusable -> still find the top-level key.
    ({"info": {}, "episode_run_time": "30"}, 30),
    ({"info": {"duration": None}, "episode_run_time": "24"}, 24),
    ({"info": "junk", "episode_run_time": "60"}, 60),
    # Zero is "unknown", never a runtime.
    ({"episode_run_time": "0"}, None),
    ({"episode_run_time": 0}, None),
    ({"info": {"duration": "0"}}, None),
    ({"info": {"duration": "00:00:00"}}, None),
    # Nothing parseable.
    (None, None), ("", None), ("not json", None), ([], None), ({}, None),
    ({"episode_run_time": "unknown"}, None),
])
def test_resolver_reads_every_shape(raw, expected):
    assert runtime_from_raw(raw) == expected


def test_zero_is_none_not_zero():
    """The distinction the whole guard exists for.

    ``None`` means "no runtime known" and renders nothing; ``0`` is a real
    value and renders "0 min". ``assert not runtime`` would pass on both, so
    assert the identity.
    """
    assert runtime_from_raw({"episode_run_time": "0"}) is None
    assert runtime_from_raw({"info": {"duration": 0}}) is None


def test_ingestion_path_reaches_the_field():
    """The fix has to land in ``metadata_from_raw``, not just in the helper."""
    result = metadata_from_raw(
        {"name": "Some Series", "episode_run_time": "45"}, name="Some Series")
    assert result.runtime == 45


def test_ingestion_still_prefers_the_movie_shape():
    """``info.duration`` wins where both exist — movies keep their own value."""
    result = metadata_from_raw(
        {"info": {"duration": "118 min"}, "episode_run_time": "45"},
        name="A Film")
    assert result.runtime == 118


# --------------------------------------------------------------------------
# The migration
# --------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """A real file-backed database — the migration pages over a real join."""
    database = Database(f"sqlite:///{tmp_path / 'runtime.db'}")
    database.create_tables()
    return database


class _Cfg:
    """Config double: only the version field and save() are touched."""

    def __init__(self):
        self.runtime_backfill_version = 0
        self.saved = 0

    def save(self):
        self.saved += 1


def _seed(db, payloads, *, runtime=None):
    """Create one channel + one metadata row per payload, sharing no rows."""
    with db.session_scope() as s:
        for i, raw in enumerate(payloads):
            s.add(MetadataDB(id=f"m{i:05d}", title=f"T{i}", runtime=runtime))
            s.add(ChannelDB(id=f"c{i:05d}", name=f"T{i}", provider_id="p", source_id=f"s{i}",
                            metadata_id=f"m{i:05d}", raw_data=raw))


def _runtimes(db):
    with db.session_scope() as s:
        return {r[0]: r[1] for r in
                s.execute(text("SELECT id, runtime FROM metadata")).all()}


def _run(db, cfg=None, is_cancelled=lambda: False):
    task = RuntimeBackfillTask(db)
    calls = []
    task.run(lambda done, total: calls.append((done, total)), is_cancelled)
    if cfg is not None:
        task.on_completed(cfg)
    return calls


def test_backfill_writes_the_runtimes_the_payloads_imply(db):
    _seed(db, [
        {"episode_run_time": "45"},      # m00000
        {"episode_run_time": "0"},       # m00001 — unknown, stays NULL
        {"info": {"duration": "120 min"}},  # m00002
        {"name": "no runtime here"},     # m00003 — stays NULL
    ])
    _run(db)
    assert _runtimes(db) == {
        "m00000": 45, "m00001": None, "m00002": 120, "m00003": None,
    }


def test_backfill_never_stores_a_literal_zero(db):
    """A stored 0 renders "0 min". 79,230 of the owner's series send "0"."""
    _seed(db, [{"episode_run_time": "0"}] * 5)
    _run(db)
    assert set(_runtimes(db).values()) == {None}


def test_backfill_leaves_an_existing_runtime_alone(db):
    """Enrichment may have supplied a better value; the filter is IS NULL."""
    _seed(db, [{"episode_run_time": "45"}], runtime=99)
    _run(db)
    assert _runtimes(db)["m00000"] == 99


def test_pages_past_the_rows_it_writes(db):
    """Every candidate row is examined exactly once, across many batches.

    This is the case that caught a real bug in the first draft. The query
    filters on ``runtime IS NULL`` and the loop's own writes remove rows from
    that set, so paging with OFFSET steps past exactly as many rows as the
    previous batch wrote — with a 2000-row batch and this mix, roughly half of
    the library would silently never be examined. Keyset paging on the last
    channel id is immune to the set shrinking underneath it.

    The seed alternates writable and unwritable payloads so a skip is
    guaranteed to lose real work, and it is deliberately larger than one batch.
    """
    import metatv.core.migrations.runtime_backfill as mod
    monkey_batch, mod._BATCH = mod._BATCH, 10
    try:
        payloads = [{"episode_run_time": "45"} if i % 2 == 0
                    else {"episode_run_time": "0"} for i in range(100)]
        _seed(db, payloads)
        _run(db)
    finally:
        mod._BATCH = monkey_batch

    got = _runtimes(db)
    assert sum(1 for v in got.values() if v == 45) == 50, (
        "rows were skipped: the pager advanced past rows it had written")
    assert sum(1 for v in got.values() if v is None) == 50


def test_second_run_is_a_no_op(db):
    """Idempotent: nothing left to write, and nothing rewritten."""
    _seed(db, [{"episode_run_time": "45"}, {"episode_run_time": "0"}])
    _run(db)
    before = _runtimes(db)
    _run(db)
    assert _runtimes(db) == before


def test_cancel_stops_and_keeps_committed_work(db):
    """A cancel returns early; batches already committed stay written."""
    import metatv.core.migrations.runtime_backfill as mod
    monkey_batch, mod._BATCH = mod._BATCH, 10
    try:
        _seed(db, [{"episode_run_time": "45"}] * 100)
        seen = {"n": 0}

        def cancel_after_two():
            seen["n"] += 1
            return seen["n"] > 3

        _run(db, is_cancelled=cancel_after_two)
    finally:
        mod._BATCH = monkey_batch

    written = sum(1 for v in _runtimes(db).values() if v == 45)
    assert 0 < written < 100, f"expected a partial write, got {written}"


def test_version_gate(db):
    """``needs_run`` is the only thing that keeps this off every launch."""
    task = RuntimeBackfillTask(db)
    cfg = _Cfg()
    assert task.needs_run(cfg) is True
    task.on_completed(cfg)
    assert cfg.runtime_backfill_version == CURRENT_VERSION
    assert cfg.saved == 1
    assert task.needs_run(cfg) is False


def test_version_gate_survives_a_config_without_the_field(db):
    """An older config on disk has no such attribute — it must still run."""
    class _Old:
        pass
    assert RuntimeBackfillTask(db).needs_run(_Old()) is True


def test_config_declares_the_version_field():
    """The gate reads it off Config; a missing field would run every launch.

    Asserted through ``model_fields``, not ``hasattr``: Config is a pydantic v2
    BaseModel, which moves declared fields off the class, so ``hasattr`` is
    False for every field and would pass this test for a name that does not
    exist at all.
    """
    from metatv.core.config import Config
    assert "runtime_backfill_version" in Config.model_fields
    assert Config().runtime_backfill_version == 0


def test_registered_with_the_migration_manager():
    """Registration is the whole delivery — an unregistered task never runs."""
    from pathlib import Path
    import metatv.gui.main_window as mw
    source = Path(mw.__file__).read_text()
    assert "RuntimeBackfillTask" in source
    assert "self.migration_manager.register(RuntimeBackfillTask(self.db))" in source
