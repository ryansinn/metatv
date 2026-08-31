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

import contextlib
import threading
import time

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

    ``add`` returns True here and did not before: the write is queued, so the
    answer is "accepted", and the failure arrives afterwards through the
    error handler (``test_a_failed_write_is_reported_…``). What must not change
    is that nothing raises, nothing is invented, and the list still reads empty
    once the queue has drained.
    """
    config.epg_watchlist_patterns = ["Mexico"]
    watchlist.bind(_BrokenDb())

    assert watchlist.patterns(config) == ()
    assert watchlist.add(config, "NRL") is True
    assert watchlist.remove(config, "Mexico") is False, "nothing to remove"
    assert watchlist.migrate_from_config(config) == 0
    assert watchlist.flush() is True
    assert watchlist.patterns(config) == ()


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


# ── the write does not run on the calling thread ─────────────────────────────

class _GatedDb:
    """A real database whose WRITE scopes wait on an event before proceeding.

    Reads are untouched: only ``session_scope(commit=True)`` is gated, which is
    what lets a test hold a write open and ask what the list says meanwhile.
    """

    def __init__(self, database, delay: float = 0.0):
        self._database = database
        self._delay = delay
        self.gate = threading.Event()
        self.threads: list[str] = []

    @contextlib.contextmanager
    def session_scope(self, commit: bool = True):
        if commit:
            self.threads.append(threading.current_thread().name)
            self.gate.wait(timeout=10)
            time.sleep(self._delay)
        with self._database.session_scope(commit=commit) as session:
            yield session


def test_a_write_never_runs_on_the_calling_thread(config, db):
    """The bug: ``_db_remove`` ran a DELETE straight from a button handler.

    SQLite has one writer and a 30 s ``busy_timeout``, so while the
    sports_reclassify pass held the lock this froze the whole app — the owner's
    watchdog logged 29.8 s, 29.9 s and 31.6 s stalls, all of them this call.
    """
    gated = _GatedDb(db)
    gated.gate.set()
    watchlist.bind(gated)

    assert watchlist.add(config, "NRL") is True
    assert watchlist.flush() is True

    assert gated.threads, "no write happened — the assertion below is vacuous"
    caller = threading.current_thread().name
    assert caller not in gated.threads, (
        f"the write ran on the calling thread ({caller})")


def test_the_call_returns_while_the_write_is_still_blocked(config, db):
    """A click must not wait on the database, however long it is locked for."""
    gated = _GatedDb(db)
    watchlist.bind(gated)
    watchlist.add(config, "Cricket")
    assert watchlist.flush(timeout=0.2) is False, "the gate did not hold the write"

    started = time.perf_counter()
    accepted = watchlist.remove(config, "cricket")
    elapsed = time.perf_counter() - started

    assert accepted is True
    assert elapsed < 1.0, (
        f"remove() blocked for {elapsed:.1f}s with the database write gated shut")

    gated.gate.set()
    assert watchlist.flush() is True


def test_the_list_reads_correctly_before_the_write_lands(config, db):
    """A queued write is replayed over the stored rows, so nothing flickers.

    Without this the row would reappear on the reload the click triggers and
    then vanish later, which is worse than the freeze it replaces.
    """
    watchlist.bind(db)
    watchlist.add(config, "Mexico")
    assert watchlist.flush() is True

    gated = _GatedDb(db)
    watchlist.bind(gated)

    assert watchlist.remove(config, "MEXICO") is True
    assert watchlist.patterns(config) == (), "the queued removal was not applied to the read"
    assert watchlist.contains(config, "Mexico") is False
    assert watchlist.count(config) == 0
    assert watchlist.remove(config, "mexico") is False, "already queued for removal"

    gated.gate.set()
    assert watchlist.flush() is True
    with db.session_scope(commit=False) as session:
        assert session.query(AlertPatternDB).count() == 0


def test_writes_land_in_the_order_they_were_made(config, db):
    """One worker, so an add followed by a remove cannot invert."""
    gated = _GatedDb(db)
    watchlist.bind(gated)

    watchlist.add(config, "NRL")
    watchlist.remove(config, "nrl")
    ops = [w.op for w in watchlist._pending]
    assert ops == ["add", "remove"], ops

    gated.gate.set()
    assert watchlist.flush() is True
    assert watchlist.patterns(config) == ()
    with db.session_scope(commit=False) as session:
        assert session.query(AlertPatternDB).count() == 0


def test_shutdown_drains_queued_writes_before_the_database_closes(config, db):
    """Registered on MainWindow's cleanup registry, which runs before db.close().

    The write is deliberately slower than the shutdown call, so a shutdown that
    did not WAIT would return with the rule still unsaved — the rule the user
    typed a moment before quitting.
    """
    gated = _GatedDb(db, delay=0.5)
    gated.gate.set()
    watchlist.bind(gated)
    assert watchlist.add(config, "Guten Morgen Österreich") is True
    watchlist.shutdown()

    with db.session_scope(commit=False) as session:
        assert session.query(AlertPatternDB).count() == 1, (
            "shutdown returned before the queued write reached the database")


def test_shutdown_gives_up_rather_than_holding_the_app_open(config, db):
    """The bound has to be real, or the freeze just moves to the quit button.

    ``ThreadPoolExecutor.shutdown(wait=True)`` waits however long the worker
    takes — which against a locked database is the full 30 s ``busy_timeout``.
    """
    gated = _GatedDb(db)
    watchlist.bind(gated)
    assert watchlist.add(config, "NRL") is True

    started = time.perf_counter()
    watchlist.shutdown(timeout=0.3)
    elapsed = time.perf_counter() - started

    assert elapsed < 3.0, f"shutdown held the app open for {elapsed:.1f}s"
    gated.gate.set()          # let the straggler finish rather than leak it


# ── failure is surfaced, not swallowed ───────────────────────────────────────

def test_a_failed_write_is_reported_and_leaves_no_trace_in_the_read(config, db):
    """The other half of the bug: the click silently did nothing.

    ``_db_remove`` logged the "database is locked" and returned ``False``, so
    the user pressed Remove, nothing happened, and nothing said why.
    """
    watchlist.bind(db)
    watchlist.add(config, "Cricket")
    assert watchlist.flush() is True

    reported = []
    watchlist.set_write_error_handler(
        lambda op, pattern, message: reported.append((op, pattern, message)))
    try:
        watchlist.bind(_BrokenDbWrites(db))
        assert watchlist.remove(config, "CRICKET") is True
        assert watchlist.flush() is True

        assert len(reported) == 1, f"the failure was swallowed: {reported}"
        op, pattern, message = reported[0]
        assert op == "remove"
        assert pattern == "CRICKET", "the user's own text, for the message they read"
        assert "locked" in message, message
    finally:
        watchlist.set_write_error_handler(None)

    watchlist.bind(db)
    assert watchlist.patterns(config) == ("Cricket",), (
        "a failed removal must not linger in the read as if it had worked")


class _BrokenDbWrites:
    """Reads work, writes raise — the shape a locked database presents."""

    def __init__(self, database):
        self._database = database

    def session_scope(self, commit: bool = True):
        if commit:
            raise RuntimeError("(sqlite3.OperationalError) database is locked")
        return self._database.session_scope(commit=commit)
