"""The watch list has one home, and moving it to the database keeps the rules.

Twenty-four sites across nine modules read ``config.epg_watchlist_patterns``
directly, each re-deciding the same small questions differently: three
lowercased and six did not, four de-duplicated on add and one did not, and
every membership test was case-SENSITIVE — so "NRL" and "nrl" were two rules
matching the same programmes.

These tests pin the seam's answers, and then that swapping the STORE behind it
changes none of them. The owner's six real alerts go through this code, so the
migration is written to be un-losable: it copies rather than moves, and the
config list stays as a plain-text backup.
"""

from __future__ import annotations

import pytest

from metatv.core.config import Config
from metatv.core.database import AlertPatternDB, Database
from metatv.core import watchlist


@pytest.fixture
def config(tmp_path):
    return Config(config_dir=tmp_path)


@pytest.fixture(autouse=True)
def _unbound():
    """Every test starts on the config store; those that want the database bind."""
    watchlist.unbind()
    yield
    watchlist.unbind()


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'wl.db'}")
    database.create_tables()
    return database


# ── the seam's answers, on the config store ─────────────────────────────────

def test_a_blank_or_missing_list_reads_as_empty(config):
    assert watchlist.patterns(config) == ()
    config.epg_watchlist_patterns = None
    assert watchlist.patterns(config) == ()
    assert watchlist.count(config) == 0


def test_blanks_and_duplicates_are_dropped_on_read(config):
    """Six modules used `or []` and three did not; none filtered blanks."""
    config.epg_watchlist_patterns = ["NRL", "", None, "  ", "nrl", " NRL ", "Cricket"]
    assert watchlist.patterns(config) == ("NRL", "Cricket")


def test_adding_is_case_insensitive(config):
    """The direct-config sites compared with `not in`, which is case-SENSITIVE.

    So "NRL" and "nrl" were two rules that matched exactly the same programmes,
    and both fired.
    """
    assert watchlist.add(config, "NRL") is True
    assert watchlist.add(config, "nrl") is False
    assert watchlist.add(config, "  NrL  ") is False
    assert watchlist.patterns(config) == ("NRL",)


def test_blank_additions_are_a_no_op_not_an_error(config):
    """The caller is a text field with an Add button; empty is a misfire."""
    assert watchlist.add(config, "") is False
    assert watchlist.add(config, "   ") is False
    assert watchlist.patterns(config) == ()


def test_removing_is_case_insensitive_and_idempotent(config):
    watchlist.add(config, "Cricket")
    assert watchlist.remove(config, "cricket") is True
    assert watchlist.remove(config, "cricket") is False, "already gone is not an error"


def test_the_read_cannot_be_mutated_by_a_caller(config):
    """`config.epg_watchlist_patterns.append(...)` used to write through.

    It changed the in-memory list without saving, so the rule survived until
    the next restart and then vanished.
    """
    watchlist.add(config, "NRL")
    assert isinstance(watchlist.patterns(config), tuple)


def test_lowered_casefolds_rather_than_lowers(config):
    """The list holds names like "Guten Morgen Österreich"."""
    watchlist.add(config, "Guten Morgen ÖSTERREICH")
    assert watchlist.lowered(config) == ("guten morgen österreich",)


def test_user_order_is_preserved(config):
    """Rules are added in the order they are thought of; the list is short."""
    for term in ("Mexico", "ATP/WTA Cincinnati", "Two and a Half Men"):
        watchlist.add(config, term)
    assert watchlist.patterns(config) == (
        "Mexico", "ATP/WTA Cincinnati", "Two and a Half Men")


# ── the same answers, on the database store ─────────────────────────────────

def test_the_migration_copies_rather_than_moves(config, db):
    """The owner's real alerts go through this.

    A migration that deletes its own source has no way back if the destination
    turns out wrong — and the YAML doubles as the plain-text backup.
    """
    config.epg_watchlist_patterns = ["Mexico", "Guten Morgen Österreich"]
    watchlist.bind(db)

    assert watchlist.migrate_from_config(config) == 2
    assert watchlist.patterns(config) == ("Mexico", "Guten Morgen Österreich")
    assert config.epg_watchlist_patterns == ["Mexico", "Guten Morgen Österreich"], (
        "the config list must survive as a backup"
    )


def test_migrating_twice_does_not_duplicate(config, db):
    config.epg_watchlist_patterns = ["Mexico"]
    watchlist.bind(db)
    watchlist.migrate_from_config(config)
    assert watchlist.migrate_from_config(config) == 0
    assert watchlist.patterns(config) == ("Mexico",)


def test_rules_survive_a_restart(config, db, tmp_path):
    """The point of the move, in one assertion."""
    watchlist.bind(db)
    watchlist.add(config, "NRL")

    reopened = Database(f"sqlite:///{tmp_path / 'wl.db'}")
    watchlist.bind(reopened)
    assert watchlist.patterns(config) == ("NRL",)


def test_the_migration_defaults_preserve_what_a_bare_string_meant(config, db):
    """Every config string matched anything, anywhere, always on."""
    config.epg_watchlist_patterns = ["Mexico"]
    watchlist.bind(db)
    watchlist.migrate_from_config(config)

    with db.session_scope(commit=False) as session:
        row = session.query(AlertPatternDB).one()
        assert row.pattern_value == "Mexico"
        assert row.pattern_type == watchlist.PATTERN_TYPE
        assert row.applies_to == "all"
        assert row.is_enabled is True


@pytest.mark.parametrize("scenario", ["config", "database"])
def test_the_seam_behaves_identically_on_either_store(config, db, scenario):
    """Swapping the store must change no answer the twenty-four callers see."""
    if scenario == "database":
        watchlist.bind(db)

    assert watchlist.add(config, "NRL") is True
    assert watchlist.add(config, "nrl") is False
    assert watchlist.contains(config, "NrL") is True
    assert watchlist.count(config) == 1
    assert watchlist.lowered(config) == ("nrl",)
    assert watchlist.remove(config, "NRL") is True
    assert watchlist.patterns(config) == ()


# ── failure ─────────────────────────────────────────────────────────────────

class _BrokenDb:
    def session_scope(self, **_kw):
        raise RuntimeError("database is locked")


def test_a_database_failure_degrades_instead_of_raising(config):
    """A watch list that cannot load should show empty and recover next read.

    Raising would take down the EPG view that asked for it — and this project
    has just spent a day on a database that really does become unavailable
    mid-session.
    """
    config.epg_watchlist_patterns = ["Mexico"]
    watchlist.bind(_BrokenDb())

    assert watchlist.patterns(config) == ()
    assert watchlist.add(config, "NRL") is False
    assert watchlist.remove(config, "Mexico") is False
    assert watchlist.migrate_from_config(config) == 0


def test_unbound_falls_back_to_config(config):
    """Tests and any headless path have no database; nothing may require one."""
    config.epg_watchlist_patterns = ["Mexico"]
    watchlist.unbind()
    assert watchlist.patterns(config) == ("Mexico",)


def test_no_module_reads_the_config_key_directly():
    """Drift guard: the seam is only a seam while everyone goes through it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "metatv"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name in {"config.py", "watchlist.py"}:
            continue
        if "epg_watchlist_patterns" in path.read_text():
            offenders.append(str(path.relative_to(root.parent)))
    assert not offenders, (
        "read the watch list through metatv.core.watchlist, not config directly: "
        + ", ".join(offenders)
    )
