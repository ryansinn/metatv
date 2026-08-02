"""Global Exclusions — user-defined keyword axis (wave8/keyword-exclusions).

Proves the fourth Global-Exclusion axis actually hides content, stays SQL-side
(safe over the 240k-row ``channels`` table — never a per-row Python filter),
composes with the existing prefix axis, respects ``global_filter_paused``, and
is a genuine no-op when empty:

(a) Engine — ``ChannelRepository.get_all(excluded_keywords=...)`` hides a
    matching title and keeps a non-matching one; composes with the existing
    prefix-axis Python twin (``_apply_python_exclusions``) the same way the
    channel list applies both layers together.
(b) Case-insensitivity — keyword casing never matters.
(c) ``filter_utils.keyword_exclusion_list`` returns ``[]`` (bypasses the axis)
    when ``global_filter_paused`` is set, even with keywords configured.
(d) Empty list is a genuine SQL no-op — ``keyword_exclusion_criterion([], ...)``
    is a tautology and ``get_all`` adds no clause for it (identical compiled
    SQL with ``excluded_keywords=[]`` vs ``None``).
(e) ``ChannelRepository.count_keyword_matches`` returns correct per-keyword
    counts, including 0 for a keyword matching nothing (the dialog's "inert"
    signal).
(f) The reveal path (dropping ``excluded_keywords`` for one load) returns the
    hidden rows — mirror-not-cage recoverability.
(g) Discover's ``discovery_engine.get_by_genre`` honours the axis.
(h) Recommendations' ``preference_engine.score_candidates`` honours the axis.
(i) Benchmark — a few-thousand-row seed proves the query shape stays SQL-side:
    fast, and the compiled criterion is a real ``ILIKE`` clause (SQLite: a
    ``lower(...) LIKE lower(...)`` expression), not something requiring a
    Python-side row scan.

Real ``Database`` on a ``tmp_path`` file (never ``:memory:``), per the tests rule.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB, UserRatingDB
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'keyword_excl.db'}")
    db.create_tables()
    yield db
    db.close()


def _add_channel(
    session,
    name: str,
    detected_title: str | None = None,
    detected_prefix: str | None = None,
    media_type: str = "movie",
    detected_genres=None,
    raw_data=None,
    metadata_id: str | None = None,
    provider_id: str = "p1",
) -> str:
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            detected_title=detected_title,
            detected_prefix=detected_prefix,
            media_type=media_type,
            detected_genres=detected_genres,
            raw_data=raw_data,
            metadata_id=metadata_id,
        )
    )
    session.flush()
    return cid


@pytest.fixture
def seeded(file_db):
    """Four channels exercising title-fallback, prefix composition, and a plain control.

    Returns ``(wrestling_id, telenovela_fr_id, plain_id, db)``.
    """
    with file_db.session_scope() as session:
        wrestling = _add_channel(
            session, name="WWE Wrestling Special", detected_title="WWE Wrestling Special",
        )
        # No detected_title — must fall back to `name` for the keyword match.
        telenovela_fr = _add_channel(
            session, name="FR - Telenovela Amor", detected_title=None, detected_prefix="FR",
        )
        plain = _add_channel(
            session, name="Ordinary Movie", detected_title="Ordinary Movie",
        )
    return wrestling, telenovela_fr, plain, file_db


# ---------------------------------------------------------------------------
# (a) Engine — hides matching, keeps non-matching, composes with prefix axis
# ---------------------------------------------------------------------------


def test_keyword_exclusion_hides_matching_channel(seeded):
    wrestling, _telenovela_fr, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ids = {c.id for c in repos.channels.get_all(excluded_keywords=["wrestling"])}
    assert wrestling not in ids, "title matching the keyword is hidden"
    assert plain in ids, "non-matching title survives"


def test_keyword_exclusion_matches_name_fallback_when_no_detected_title(seeded):
    """A row with no detected_title (None) falls back to `name` for the match."""
    _wrestling, telenovela_fr, _plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        ids = {c.id for c in repos.channels.get_all(excluded_keywords=["telenovela"])}
    assert telenovela_fr not in ids, "name fallback matched (detected_title is None)"


def test_keyword_composes_with_prefix_exclusion(seeded):
    """The channel-list production path applies BOTH axes together: the SQL
    keyword axis (get_all) and the Python prefix-axis twin
    (_apply_python_exclusions) — a channel excluded by either one must not
    survive, and a channel excluded by neither must survive."""
    from metatv.core.filter_utils import is_channel_excluded
    from metatv.gui.main_window_channels import _apply_python_exclusions

    wrestling, telenovela_fr, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        # SQL layer: keyword axis only excludes "wrestling".
        channels = repos.channels.get_all(excluded_keywords=["wrestling"])
        assert {c.id for c in channels} == {telenovela_fr, plain}

        # Python layer: prefix axis (FR excluded) applied on top, exactly as
        # _query_channels does — telenovela_fr (detected_prefix="FR") drops too.
        survivors = _apply_python_exclusions(channels, {"FR"}, set(), None)
        survivor_ids = {c.id for c in survivors}

    assert wrestling not in survivor_ids, "hidden by the keyword axis"
    assert telenovela_fr not in survivor_ids, "hidden by the prefix axis"
    assert plain in survivor_ids, "matches neither axis — survives both layers"
    # Sanity: the prefix predicate genuinely fires for FR (not a vacuous pass).
    assert is_channel_excluded("FR", None, {"FR"}) is True


# ---------------------------------------------------------------------------
# (b) Case-insensitivity
# ---------------------------------------------------------------------------


def test_keyword_exclusion_is_case_insensitive(seeded):
    wrestling, _telenovela_fr, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        upper = {c.id for c in repos.channels.get_all(excluded_keywords=["WRESTLING"])}
        mixed = {c.id for c in repos.channels.get_all(excluded_keywords=["WreStLiNg"])}
    assert wrestling not in upper
    assert wrestling not in mixed
    assert plain in upper and plain in mixed


# ---------------------------------------------------------------------------
# (c) global_filter_paused bypasses the axis
# ---------------------------------------------------------------------------


def test_paused_config_yields_empty_keyword_list():
    from metatv.core.config import Config
    from metatv.core.filter_utils import keyword_exclusion_list

    cfg = Config()
    cfg.global_excluded_keywords = ["wrestling", "telenovela"]
    assert keyword_exclusion_list(cfg) == ["wrestling", "telenovela"]

    cfg.global_filter_paused = True
    assert keyword_exclusion_list(cfg) == [], "paused bypasses the keyword axis entirely"


def test_paused_reveals_channel_end_to_end(seeded):
    """The same list, threaded through get_all like the real control layer does,
    hides while active and reveals once paused."""
    from metatv.core.config import Config
    from metatv.core.filter_utils import keyword_exclusion_list

    wrestling, _telenovela_fr, _plain, db = seeded
    cfg = Config()
    cfg.global_excluded_keywords = ["wrestling"]

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        active_ids = {c.id for c in repos.channels.get_all(
            excluded_keywords=keyword_exclusion_list(cfg)
        )}
        cfg.global_filter_paused = True
        paused_ids = {c.id for c in repos.channels.get_all(
            excluded_keywords=keyword_exclusion_list(cfg)
        )}

    assert wrestling not in active_ids
    assert wrestling in paused_ids, "paused → keyword_exclusion_list is empty → channel reappears"


# ---------------------------------------------------------------------------
# (d) Empty list is a genuine SQL no-op
# ---------------------------------------------------------------------------


def test_empty_keywords_criterion_is_tautology():
    from sqlalchemy import true
    from metatv.core.filter_utils import keyword_exclusion_criterion

    assert str(keyword_exclusion_criterion([], ChannelDB)) == str(true())
    assert str(keyword_exclusion_criterion(None, ChannelDB)) == str(true())


def test_empty_keywords_adds_no_clause_to_get_all_sql(seeded):
    """excluded_keywords=[] must compile to the SAME SQL as excluded_keywords=None
    — the keyword axis must not append a vacuous-but-present clause."""
    _wrestling, _telenovela_fr, _plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        q_none = repos.session.query(ChannelDB)
        q_none = repos.channels._apply_channel_filters(q_none, excluded_keywords=None)
        q_empty = repos.session.query(ChannelDB)
        q_empty = repos.channels._apply_channel_filters(q_empty, excluded_keywords=[])
        assert str(q_none.statement.compile(session.get_bind())) == str(
            q_empty.statement.compile(session.get_bind())
        ), "an empty keyword list must not add any clause vs. None"


# ---------------------------------------------------------------------------
# (e) Per-keyword match counts (the dialog's live counts / inert signal)
# ---------------------------------------------------------------------------


def test_count_keyword_matches_correct_per_keyword(seeded):
    wrestling, telenovela_fr, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        counts = repos.channels.count_keyword_matches(
            ["wrestling", "telenovela", "nonexistent_zzz_typo"]
        )
    assert counts["wrestling"] == 1
    assert counts["telenovela"] == 1
    assert counts["nonexistent_zzz_typo"] == 0, "a typo'd keyword reads 0 — the inert signal"


def test_count_keyword_matches_skips_blank_entries(seeded):
    _wrestling, _telenovela_fr, _plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        assert repos.channels.count_keyword_matches([]) == {}
        assert repos.channels.count_keyword_matches(["  ", ""]) == {}


# ---------------------------------------------------------------------------
# (f) Reveal path — mirror-not-cage recoverability
# ---------------------------------------------------------------------------


def test_reveal_bypass_returns_hidden_rows(seeded):
    """Dropping excluded_keywords for one load (the _show_keyword_hidden /
    bypass_keyword_exclusions path) must surface exactly the rows the axis
    was hiding — nothing is destroyed, only held back."""
    wrestling, _telenovela_fr, _plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        hidden_ids = {c.id for c in repos.channels.get_all(excluded_keywords=["wrestling"])}
        revealed_ids = {c.id for c in repos.channels.get_all(excluded_keywords=None)}  # the bypass

    assert wrestling not in hidden_ids
    assert wrestling in revealed_ids, "reveal surfaces the exact hidden row"


# ---------------------------------------------------------------------------
# (g) Discover's genre query honours the axis
# ---------------------------------------------------------------------------


def test_discover_get_by_genre_honours_keyword_exclusion(file_db):
    from metatv.core import discovery_engine

    with file_db.session_scope() as session:
        _add_channel(
            session, name="WWE Wrestling Drama Special", detected_title="WWE Wrestling Drama Special",
            detected_genres=["Drama"], raw_data={"rating": "8.0", "genre": "Drama"},
        )
        kept_id = _add_channel(
            session, name="Great Drama Movie", detected_title="Great Drama Movie",
            detected_genres=["Drama"], raw_data={"rating": "7.5", "genre": "Drama"},
        )

    with file_db.session_scope(commit=False) as session:
        without_kw = discovery_engine.get_by_genre(session, "Drama", limit=30)
        with_kw = discovery_engine.get_by_genre(
            session, "Drama", limit=30, excluded_keywords=["wrestling"]
        )

    without_ids = {c.channel_id for c in without_kw}
    with_ids = {c.channel_id for c in with_kw}
    assert len(without_ids) == 2, "sanity: both Drama titles present without the axis"
    assert len(with_ids) == 1 and kept_id in with_ids, "wrestling title dropped by the axis"


# ---------------------------------------------------------------------------
# (h) Recommendations' score_candidates honours the axis
# ---------------------------------------------------------------------------


def test_recommendations_score_candidates_honours_keyword_exclusion(file_db):
    from metatv.core.preference_engine import compute_weights, score_candidates

    with file_db.session_scope() as session:
        meta_drama = MetadataDB(
            id=str(uuid.uuid4()), title="Great Drama", genres=["Drama"],
            director="Jane Director", year=2019, plot="a moving drama",
        )
        session.add(meta_drama)
        session.flush()

        # Liked (watched + rated) title — the taste signal.
        liked = ChannelDB(
            id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="p1",
            name="EN - Great Drama (2019)", media_type="movie",
            metadata_id=meta_drama.id, last_played=datetime(2024, 1, 1),
        )
        session.add(liked)
        session.flush()
        session.add(UserRatingDB(channel_id=liked.id, rating=1))

        # Two unwatched candidates sharing the liked genre — one matches the
        # keyword, one doesn't. Ids are pre-generated (not read back from the
        # ORM object later) so they stay usable after the session closes.
        wrestling_id = str(uuid.uuid4())
        plain_id = str(uuid.uuid4())
        session.add_all([
            ChannelDB(
                id=wrestling_id, source_id=str(uuid.uuid4()), provider_id="p1",
                name="EN - Wrestling Drama Special", detected_title="Wrestling Drama Special",
                media_type="movie", metadata_id=meta_drama.id, detected_prefix="EN",
            ),
            ChannelDB(
                id=plain_id, source_id=str(uuid.uuid4()), provider_id="p1",
                name="EN - Another Drama Film", detected_title="Another Drama Film",
                media_type="movie", metadata_id=meta_drama.id, detected_prefix="EN",
            ),
        ])

    with file_db.session_scope(commit=False) as session:
        weights = compute_weights(session)
        assert not weights.is_empty(), "sanity: the liked title produced taste weights"

        without_kw = score_candidates(session, weights, limit=30)
        with_kw = score_candidates(session, weights, limit=30, excluded_keywords=["wrestling"])

    without_ids = {sc.channel_id for sc in without_kw}
    with_ids = {sc.channel_id for sc in with_kw}
    assert wrestling_id in without_ids, "sanity: present without the axis"
    assert wrestling_id not in with_ids, "keyword axis excludes it from recommendations"
    assert plain_id in with_ids, "the non-matching candidate is unaffected"


# ---------------------------------------------------------------------------
# (i) Benchmark — query shape stays SQL-side over a few-thousand-row seed
# ---------------------------------------------------------------------------


def test_keyword_exclusion_query_shape_and_benchmark(tmp_path: Path):
    """Seeds a few-thousand-row table and proves:

    1. The criterion compiles to a real SQL ILIKE-shaped clause (SQLite:
       ``lower(coalesce(...)) LIKE lower(?)``) — the match runs IN the query,
       not via a Python loop over fetched rows.
    2. A get_all() call with the axis active returns the correct subset from
       that few-thousand-row table in well under a second — proof the
       substring match is pushed to SQL (a Python per-row scan of this size
       from the UI thread is exactly what CLAUDE.md's rule forbids).
    """
    from metatv.core.filter_utils import keyword_exclusion_criterion

    db = Database(f"sqlite:///{tmp_path / 'keyword_bench.db'}")
    db.create_tables()
    try:
        N = 3000
        WRESTLING_EVERY = 37  # deterministic, easy-to-check subset size
        expected_hidden = 0
        with db.session_scope() as session:
            for i in range(N):
                is_wrestling = (i % WRESTLING_EVERY == 0)
                if is_wrestling:
                    expected_hidden += 1
                title = f"WWE Wrestling Night {i}" if is_wrestling else f"Regular Title {i}"
                session.add(ChannelDB(
                    id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="p1",
                    name=title, detected_title=title, media_type="movie",
                ))

        # (1) Query shape — compile the criterion against SQLite and inspect the SQL text.
        from sqlalchemy.dialects import sqlite as sqlite_dialect
        compiled = str(
            keyword_exclusion_criterion(["wrestling"], ChannelDB).compile(
                dialect=sqlite_dialect.dialect()
            )
        )
        assert "like" in compiled.lower(), f"expected a LIKE-shaped clause, got: {compiled}"

        # (2) Benchmark — SQL-side substring match over N rows.
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            t0 = time.perf_counter()
            channels = repos.channels.get_all(
                excluded_keywords=["wrestling"], media_types=["movie"], limit=N,
            )
            elapsed = time.perf_counter() - t0

        assert len(channels) == N - expected_hidden
        assert elapsed < 2.0, f"keyword exclusion over {N} rows took {elapsed:.3f}s — expected SQL-side speed"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# (j) Global Exclusions dialog — Keywords section (Add / remove / save / counts)
# ---------------------------------------------------------------------------


def test_dialog_keywords_section_add_remove_and_save(seeded, qtbot):
    """The dialog's Keywords section: Add stages a row (not yet in config),
    Remove drops it, and only Save writes the staged list into config —
    matching every other section's Cancel-discards-changes contract."""
    from metatv.core.config import Config
    from metatv.gui.global_filter_dialog import GlobalFilterDialog

    _wrestling, _telenovela_fr, _plain, db = seeded
    cfg = Config()
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)

    # Nothing configured yet.
    assert dlg._keyword_list == []
    assert cfg.global_excluded_keywords == []

    # Add stages the keyword locally — config is untouched until Save.
    dlg._keyword_input.setText("wrestling")
    dlg._add_keyword()
    assert dlg._keyword_list == ["wrestling"]
    assert cfg.global_excluded_keywords == [], "not persisted until Save"
    assert len(dlg._keyword_rows) == 1
    kw, _row, count_lbl = dlg._keyword_rows[0]
    assert kw == "wrestling"

    # Adding the same keyword again (any case) is a no-op — no duplicate row.
    dlg._keyword_input.setText("WRESTLING")
    dlg._add_keyword()
    assert dlg._keyword_list == ["wrestling"]
    assert len(dlg._keyword_rows) == 1

    # Remove drops it back out.
    dlg._remove_keyword("wrestling")
    assert dlg._keyword_list == []
    assert dlg._keyword_rows == []

    # Add it back and Save — now it lands in config.
    dlg._keyword_input.setText("telenovela")
    dlg._add_keyword()
    dlg._save_and_accept()
    assert cfg.global_excluded_keywords == ["telenovela"]


def test_dialog_keyword_row_shows_live_count_and_inert_state(seeded, qtbot):
    """A keyword matching real content shows its count; one matching nothing
    is marked inert ('no matches') — the typo-catching signal."""
    from metatv.core.config import Config
    from metatv.gui.global_filter_dialog import GlobalFilterDialog

    _wrestling, _telenovela_fr, _plain, db = seeded
    cfg = Config()
    cfg.global_excluded_keywords = ["wrestling", "zzz_no_such_word"]
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)

    # The background count thread must finish before we can assert on it.
    if dlg._keyword_count_thread is not None:
        qtbot.waitUntil(lambda: not dlg._keyword_count_thread.isRunning(), timeout=5000)
    qtbot.wait(50)  # let the queued `done` signal's slot run on the main thread

    by_kw = {kw: lbl.text() for kw, _row, lbl in dlg._keyword_rows}
    assert "1 channel" in by_kw["wrestling"]
    assert by_kw["zzz_no_such_word"] == "— no matches"
