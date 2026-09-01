"""The user's selections and watermarks move to the database — CFG-5.

Measured on the owner's config: 1,849 of 2,252 lines are user state, not
settings, and every one of the 130 ``config.save()`` sites rewrote all of it
because you cannot write one key to a photograph.

What is asserted here is the part that could lose data:

* a key is only taken out of ``config.yaml`` after it has been written, read
  back and compared — never on a promise;
* ``None`` and ``[]`` survive the round trip as different values, because the
  filter sentinels mean "never configured" and "explicitly nothing" and the
  config carries a schema migration whose whole job is telling them apart;
* with no database bound, every field still goes to YAML — the fallback is the
  old behaviour, unchanged, not a degraded mode;
* a save writes only the keys that CHANGED, or the store reinstates in SQLite
  exactly the rewrite-everything cost it was built to remove.

Real ``Database`` on a real file throughout (CLAUDE.md forbids ``:memory:`` for
session work), and every test drives ``Config.save()`` rather than calling the
store directly, because the seam under test is the one the app uses.
"""

from __future__ import annotations

from contextlib import contextmanager

import yaml
import pytest

from metatv.core import profile_store
from metatv.core.config import Config, _profile_field_names
from metatv.core.database import Database, ProfileDB


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'profile.db'}")
    database.create_tables()
    return database


@pytest.fixture
def config(tmp_path):
    cfg = Config(config_dir=tmp_path / "cfg", data_dir=tmp_path / "data",
                 cache_dir=tmp_path / "cache")
    cfg.save()
    return cfg


def _yaml_keys(cfg) -> set:
    return set(yaml.safe_load((cfg.config_dir / "config.yaml").read_text()) or {})


@contextmanager
def _captured_logs(level: str = "ERROR"):
    """Collect loguru messages emitted inside the block.

    pytest's ``caplog`` cannot see these: loguru does not route through stdlib
    ``logging``, so a caplog assertion here is vacuously true and passes against
    a version that logs nothing at all. A temporary sink is what the rest of
    this suite uses (see ``test_series_monitor``).
    """
    from loguru import logger

    records: list[str] = []
    sink = logger.add(lambda m: records.append(str(m)), level=level)
    try:
        yield records
    finally:
        logger.remove(sink)


def _rows(db) -> dict:
    with db.session_scope(commit=False) as session:
        return {r.key: r.value for r in session.query(ProfileDB).all()}


# ── the field set is derived, not listed ────────────────────────────────────

def test_the_profile_is_derived_from_the_field_declarations():
    """A list of names in this module would go stale; the marker cannot."""
    names = _profile_field_names(Config)

    assert len(names) >= 30, "the PROFILE marker stopped matching — the sweep is empty"
    assert "filter_known_genres" in names, "the largest single key, 669 lines"
    assert "monitored_series" in names
    assert "global_filter_excluded_categories" in names
    # The other side of the line: these are settings, and settings stay in YAML.
    assert "theme_name" not in names
    assert "database_url" not in names
    assert not any(n.startswith("qa_") for n in names), \
        "QA state has its own sidecar; a field must not claim both"


# ── unbound: nothing changes ────────────────────────────────────────────────

def test_with_no_database_every_field_still_goes_to_yaml(config):
    """The fallback is the previous behaviour, still there and still complete."""
    config.filter_known_genres = ["Action", "Drama"]
    config.monitored_series = [{"series_channel_id": "s1"}]
    config.save()

    keys = _yaml_keys(config)
    assert "filter_known_genres" in keys
    assert "monitored_series" in keys
    assert profile_store.owned_keys() == frozenset()

    reloaded = yaml.safe_load((config.config_dir / "config.yaml").read_text())
    assert reloaded["filter_known_genres"] == ["Action", "Drama"]


# ── attach migrates, verifies, and only then prunes ─────────────────────────

def test_attach_migrates_yaml_values_into_the_database(config, db):
    config.filter_known_genres = ["Action", "Drama"]
    config.global_filter_excluded_categories = ["XXX"]
    config.save()
    assert "filter_known_genres" in _yaml_keys(config)

    owned = config.attach_profile_store(db)

    assert "filter_known_genres" in owned
    assert _rows(db)["filter_known_genres"] == ["Action", "Drama"]
    assert _rows(db)["global_filter_excluded_categories"] == ["XXX"]
    # In memory the value is untouched — the 46 call sites do not move.
    assert config.filter_known_genres == ["Action", "Drama"]


def test_the_yaml_loses_the_profile_only_after_a_save(config, db):
    """Attach proves ownership; the next save is what actually prunes the file."""
    config.filter_known_genres = ["Action"]
    config.save()
    config.attach_profile_store(db)

    assert "filter_known_genres" in _yaml_keys(config), \
        "attach must not rewrite the file by itself"

    config.theme_name = "daylight"
    config.save()

    keys = _yaml_keys(config)
    assert "filter_known_genres" not in keys
    assert "monitored_series" not in keys
    assert "theme_name" in keys, "settings stay — only the profile leaves"


def test_a_key_that_fails_read_back_stays_in_the_yaml(config, db, monkeypatch):
    """The prune is irreversible with one .bak behind it, so it is not assumed.

    A value that will not survive the round trip must keep its YAML home, and it
    must not take the other thirty-three keys with it.
    """
    config.filter_known_genres = ["Action"]
    config.monitored_series = [{"series_channel_id": "s1"}]
    config.save()

    # A write that reports success and silently does not land — the realistic
    # failure, and the one a read-back is the only defence against.
    real_write = profile_store._write_now

    def _dropping_write(values):
        real_write({k: v for k, v in values.items() if k != "filter_known_genres"})

    monkeypatch.setattr(profile_store, "_write_now", _dropping_write)
    owned = config.attach_profile_store(db)

    assert "filter_known_genres" not in owned, "a mismatched read-back is refused"
    assert "monitored_series" in owned, "one bad key must not block the rest"

    monkeypatch.undo()
    config.theme_name = "daylight"
    config.save()

    keys = _yaml_keys(config)
    assert "filter_known_genres" in keys, "the refused key keeps its YAML home"
    assert "monitored_series" not in keys


def test_a_stored_value_wins_over_the_yaml_on_the_next_launch(config, db):
    """The store is authoritative once it owns a key — a stale YAML is ignored."""
    config.filter_known_genres = ["Action"]
    config.save()
    config.attach_profile_store(db)
    config.filter_known_genres = ["Action", "Comedy"]
    config.save()
    profile_store.flush()
    profile_store.unbind()

    # A second launch: the YAML still holds the old value from before the prune.
    fresh = Config(config_dir=config.config_dir, data_dir=config.data_dir,
                   cache_dir=config.cache_dir, filter_known_genres=["Action"])
    fresh.attach_profile_store(db)

    assert fresh.filter_known_genres == ["Action", "Comedy"]


# ── the sentinels ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, [], ["Action"]])
def test_none_and_empty_survive_as_different_values(config, db, value):
    """``None`` = never configured; ``[]`` = explicitly nothing. Not the same.

    ``Config`` carries a whole schema-version migration to tell these apart. A
    store that collapsed them would silently undo an "Only"/none-selection, and
    the user would see filters they had turned off come back.
    """
    config.filter_included_genres = value
    config.save()
    config.attach_profile_store(db)
    profile_store.flush()

    assert _rows(db)["filter_included_genres"] == value

    fresh = Config(config_dir=config.config_dir, data_dir=config.data_dir,
                   cache_dir=config.cache_dir)
    fresh.attach_profile_store(db)
    assert fresh.filter_included_genres == value
    assert (fresh.filter_included_genres is None) == (value is None), \
        "None must not arrive back as [] — that is the sentinel collapsing"


def test_a_stored_none_is_owned_not_treated_as_absent(config, db):
    """A null row still marks the key as held — presence, not truthiness."""
    config.filter_included_genres = None
    config.save()
    owned = config.attach_profile_store(db)
    profile_store.flush()

    assert "filter_included_genres" in owned
    with db.session_scope(commit=False) as session:
        row = session.get(ProfileDB, "filter_included_genres")
        # Read inside the scope — session_scope expires on exit and a detached
        # row's next attribute access raises (CLAUDE.md: ORM objects must not
        # outlive their session).
        exists, value = row is not None, None if row is None else row.value
    assert exists and value is None


# ── only what changed ───────────────────────────────────────────────────────

def test_a_save_writes_only_the_keys_that_changed(config, db, monkeypatch):
    config.attach_profile_store(db)
    seen = []
    monkeypatch.setattr(profile_store, "record", lambda v: seen.append(dict(v)))

    config.filter_known_genres = ["Action"]
    config.save()

    assert seen == [{"filter_known_genres": ["Action"]}], \
        "one changed key must not write the other thirty-three"


def test_an_unchanged_profile_writes_nothing(config, db, monkeypatch):
    config.attach_profile_store(db)
    config.filter_known_genres = ["Action"]
    config.save()
    profile_store.flush()

    seen = []
    monkeypatch.setattr(profile_store, "record", lambda v: seen.append(dict(v)))
    config.save()
    config.save()

    assert seen == [], "a no-op save must not touch the database"


def test_a_settings_change_does_not_rewrite_the_profile(config, db, monkeypatch):
    """The whole point: a checkbox stops paying for 1,849 lines of user state."""
    config.filter_known_genres = ["Action"]
    config.save()
    config.attach_profile_store(db)
    profile_store.flush()

    seen = []
    monkeypatch.setattr(profile_store, "record", lambda v: seen.append(dict(v)))
    config.theme_name = "daylight"
    config.save()

    assert seen == []


def test_the_first_save_after_attach_does_not_rewrite_what_it_just_read(config, db,
                                                                       monkeypatch):
    """Attach primes the comparison, so startup is not 34 redundant rows."""
    config.filter_known_genres = ["Action"]
    config.save()
    config.attach_profile_store(db)

    seen = []
    monkeypatch.setattr(profile_store, "record", lambda v: seen.append(dict(v)))
    config.theme_name = "daylight"
    config.save()

    assert seen == []


# ── in-place mutation, the shape #641 had to defend against ─────────────────

def test_an_in_place_mutation_of_a_profile_field_is_persisted(config, db):
    """26 sites mutate a container in place — ``config.x.append(...)``.

    #641 established that a ``__setattr__`` dirty flag would never fire for
    these. The profile comparison is over ``model_dump()`` for the same reason,
    and this is the test that proves it rather than assuming it.
    """
    config.attach_profile_store(db)
    config.monitored_series.append({"series_channel_id": "s1"})
    config.save()
    profile_store.flush()

    assert _rows(db)["monitored_series"] == [{"series_channel_id": "s1"}]


def test_config_helper_methods_persist_through_the_store(config, db):
    """``add_monitored_series`` and friends keep working, unmodified."""
    config.attach_profile_store(db)
    config.add_monitored_series({"series_channel_id": "s1", "series_name": "Show"})
    profile_store.flush()

    stored = _rows(db)["monitored_series"]
    assert [e["series_channel_id"] for e in stored] == ["s1"]
    assert "monitored_series" not in _yaml_keys(config)


# ── writes are queued, not run on the caller's thread ───────────────────────

def test_the_write_does_not_run_on_the_calling_thread(config, db):
    """SQLite has one writer; a UI-thread write froze this app for 29.8 s once."""
    import threading

    config.attach_profile_store(db)
    caller = threading.get_ident()
    threads = []
    real_write = profile_store._write_now
    profile_store._write_now = lambda v: (threads.append(threading.get_ident()),
                                          real_write(v))
    try:
        config.filter_known_genres = ["Action"]
        config.save()
        assert profile_store.flush(timeout=5.0), "the queue did not drain"
    finally:
        profile_store._write_now = real_write

    assert threads and caller not in threads, \
        "the write ran on the caller's thread — the freeze is back"


def test_unbinding_returns_every_key_to_the_yaml(config, db):
    """Lose the database and the file must become authoritative again."""
    config.filter_known_genres = ["Action"]
    config.save()
    config.attach_profile_store(db)
    config.save()
    assert "filter_known_genres" not in _yaml_keys(config)

    profile_store.unbind()
    config.save()

    assert "filter_known_genres" in _yaml_keys(config)
    assert profile_store.owned_keys() == frozenset()


# ── a lost database must be loud, not silent ────────────────────────────────

def test_a_lost_profile_table_is_reported_rather_than_silently_defaulted(
        config, db):
    """Pruning makes the database the only copy. Losing it must be diagnosable.

    Nothing here can prevent the loss — the point is that ``profile_store_populated``
    stays in config.yaml, so True beside an empty table proves the rows are gone
    rather than never written. Those are different problems with different fixes,
    and without the marker they look identical.
    """
    config.filter_known_genres = ["Action"]
    config.save()
    config.attach_profile_store(db)
    assert config.profile_store_populated is True

    # The database is replaced with an empty one — a reset, a restore from a
    # backup that predates the migration, a fresh machine.
    profile_store.unbind()
    with db.session_scope() as session:
        session.query(ProfileDB).delete()

    with _captured_logs() as records:
        config.attach_profile_store(db)

    assert any("the stored selections are gone" in m for m in records), \
        "a lost profile must be reported, not quietly replaced by defaults"


def test_a_first_migration_is_not_reported_as_a_loss(config, db):
    """Non-degeneracy: the marker must not fire for everyone's first launch."""
    config.filter_known_genres = ["Action"]
    config.save()
    assert config.profile_store_populated is False

    with _captured_logs() as records:
        config.attach_profile_store(db)

    assert not any("selections are gone" in m for m in records)


# ── the self-healing config must not un-prune what moved ────────────────────

def test_rewrite_if_stale_does_not_write_the_profile_back(config, db):
    """"Absent" stopped meaning "stale" the moment settings moved elsewhere.

    ``_rewrite_if_stale`` rewrites config.yaml when a declared field is missing
    from it — sound when the file was the only home. CFG-5 then made 34 fields
    absent ON PURPOSE, and #643 did the same for the nine ``qa_`` fields, so
    without this the very next launch writes all 43 straight back and undoes
    both moves. Every launch, silently, for ever.

    Found by running it against a real migrated config rather than reasoning
    about it: the profile half was predicted, the qa_ half was not.
    """
    config.save()
    owned = config.attach_profile_store(db)
    config.theme_name = "daylight"
    config.save()                                   # prunes the profile
    profile_store.flush()

    data = yaml.safe_load((config.config_dir / "config.yaml").read_text())
    assert not [k for k in owned if k in data], "the prune did not happen"

    config._rewrite_if_stale(data, config.config_dir / "config.yaml")

    after = yaml.safe_load((config.config_dir / "config.yaml").read_text())
    assert not [k for k in owned if k in after], (
        "the self-healing rewrite put the profile back into config.yaml")
    assert not [k for k in after if k.startswith("qa_")], (
        "the self-healing rewrite put the QA sidecar's fields back too")


def test_rewrite_if_stale_still_heals_a_genuinely_old_file(config, db):
    """Non-degeneracy: excluding two families must not disable the feature.

    A version that simply returned False would pass the test above perfectly
    while removing the thing #617 added.
    """
    config.save()
    data = yaml.safe_load((config.config_dir / "config.yaml").read_text())
    data.pop("theme_name", None)                    # a real setting, really absent

    assert config._rewrite_if_stale(data, config.config_dir / "config.yaml"), (
        "a file genuinely missing a setting was not healed")
