"""Behavioral tests for content-identity Slice 3 — TMDb-first content_key.

Guards the invariants that would break if the tmdb layer regressed:

1. ``valid_tmdb_id`` accepts real ids and rejects the provider sentinels.
2. ``content_key_for`` uses the tmdb id when present:
   - same tmdb + same media_type, different titles → SAME key (cross-language
     variants collapse).
   - same tmdb int, movie vs series → DIFFERENT key (media_type namespacing —
     TMDb numbers film and TV separately; a bare tmdb:{id} would wrongly merge).
   - no / invalid tmdb → falls back to the existing title/year key UNCHANGED.
3. ``convert_to_channel`` captures the raw tmdb id at ingestion.
4. ``update_detected_prefixes`` recompute is tmdb-first when detected_tmdb_id is set.
5. ``backfill_tmdb_ids`` populates detected_tmdb_id from raw_data (VOD only,
   sentinel-safe, idempotent), and the content_key recompute then keys on it.
6. ``TmdbIdBackfillTask`` version-gates and runs end-to-end.
7. **Search-through-collapse regression:** two same-tmdb rows with distinct titles
   collapse to one card, yet each title is still independently findable via
   ``name_filter`` (a wrongly-merged variant is never hidden from search).

All tests use file-backed (tmp_path) SQLite DBs per CLAUDE.md — not :memory:.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables + lightweight migrations applied."""
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'tmdb_identity.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(session, pid: str = "p1", is_active: bool = True) -> str:
    session.add(
        ProviderDB(
            id=pid,
            name=f"Provider {pid}",
            type="xtream",
            url="http://example.com",
            username="u",
            password="p",
            is_active=is_active,
        )
    )
    session.flush()
    return pid


def _channel(
    session,
    provider_id: str = "p1",
    *,
    name: str = "Test",
    media_type: str = "movie",
    detected_title: str | None = None,
    detected_year: str | None = None,
    detected_quality: str | None = None,
    detected_tmdb_id: str | None = None,
    content_key: str | None = None,
    raw_data: dict | None = None,
) -> str:
    """Insert a minimal ChannelDB row and return its id."""
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            media_type=media_type,
            detected_title=detected_title,
            detected_year=detected_year,
            detected_quality=detected_quality,
            detected_tmdb_id=detected_tmdb_id,
            content_key=content_key,
            raw_data=raw_data or {},
        )
    )
    session.flush()
    return cid


def _tag(session, channel_id: str, facet_type: str = "genre", value: str = "Drama") -> None:
    RepositoryFactory(session).tags.set_content_tags(channel_id, [(facet_type, value, "test")])
    session.flush()


# ---------------------------------------------------------------------------
# 1. valid_tmdb_id — the single source of truth
# ---------------------------------------------------------------------------


class TestValidTmdbId:
    def test_accepts_real_numeric_ids(self):
        from metatv.core.content_identity import valid_tmdb_id

        assert valid_tmdb_id("603") == "603"
        assert valid_tmdb_id(603) == "603"          # provider may ship an int
        assert valid_tmdb_id("  603  ") == "603"    # whitespace stripped

    @pytest.mark.parametrize("sentinel", ["", "0", "00", "000", "null", "None", "abc", "12x", None])
    def test_rejects_sentinels_and_nonnumeric(self, sentinel):
        from metatv.core.content_identity import valid_tmdb_id

        assert valid_tmdb_id(sentinel) is None


# ---------------------------------------------------------------------------
# 2. content_key_for — tmdb-first semantics (the core requirement)
# ---------------------------------------------------------------------------


class TestContentKeyTmdb:
    def _ch(self, **kw):
        defaults = {
            "id": str(uuid.uuid4()),
            "detected_title": "Some Title",
            "media_type": "movie",
            "detected_year": "2019",
            "detected_tmdb_id": None,
        }
        defaults.update(kw)
        return SimpleNamespace(**defaults)

    def test_same_tmdb_same_type_different_titles_same_key(self):
        """Cross-language variants (same tmdb, same media_type, different titles) collapse."""
        from metatv.core.content_identity import content_key_for

        es = self._ch(detected_title="Mision Salvar el bosque", detected_tmdb_id="12345")
        en = self._ch(detected_title="Animal Adventures", detected_tmdb_id="12345")
        assert content_key_for(es) == content_key_for(en) == "tmdb:12345|movie"

    def test_same_tmdb_int_movie_vs_series_different_key(self):
        """Namespacing guard: the SAME int across movie and series must NOT merge."""
        from metatv.core.content_identity import content_key_for

        movie = self._ch(media_type="movie", detected_tmdb_id="603", detected_title="The Host")
        series = self._ch(media_type="series", detected_tmdb_id="603", detected_title="The Continental")
        km, ks = content_key_for(movie), content_key_for(series)
        assert km == "tmdb:603|movie"
        assert ks == "tmdb:603|series"
        assert km != ks, "Same tmdb int across movie/series must produce different keys"

    def test_no_tmdb_falls_back_to_title_year_key_unchanged(self):
        """No tmdb → the exact pre-existing title/year key (behavior unchanged)."""
        from metatv.core.content_identity import content_key_for

        ch = self._ch(detected_title="Dark Star", media_type="movie",
                      detected_year="2017", detected_tmdb_id=None)
        assert content_key_for(ch) == "dark star|movie|2017"

    @pytest.mark.parametrize("bad", ["0", "", "null", "None", "notanumber"])
    def test_invalid_tmdb_falls_back_to_title_key(self, bad):
        """A sentinel/invalid tmdb is ignored — the title/year key is used."""
        from metatv.core.content_identity import content_key_for

        ch = self._ch(detected_title="Dark Star", media_type="movie",
                      detected_year="2017", detected_tmdb_id=bad)
        assert content_key_for(ch) == "dark star|movie|2017"

    def test_tmdb_key_beats_title_for_different_titles(self):
        """Two different titles with the SAME tmdb collapse (tmdb is authoritative)."""
        from metatv.core.content_identity import content_key_for

        a = self._ch(detected_title="Totally Different A", detected_tmdb_id="99")
        b = self._ch(detected_title="Totally Different B", detected_tmdb_id="99")
        assert content_key_for(a) == content_key_for(b)


# ---------------------------------------------------------------------------
# 3. Ingestion — convert_to_channel captures the raw tmdb id
# ---------------------------------------------------------------------------


class TestConvertToChannel:
    def _api(self):
        from metatv.providers.xtream import XtreamAPI

        return XtreamAPI("http://host:8080", "user", "pass")

    def test_convert_captures_valid_tmdb(self):
        api = self._api()
        ch = api.convert_to_channel(
            {"stream_id": "7", "name": "EN Dark Star", "tmdb": "603"},
            provider_id="p1",
            media_type="movie",
        )
        assert ch.detected_tmdb_id == "603"

    def test_convert_drops_sentinel_tmdb(self):
        api = self._api()
        ch = api.convert_to_channel(
            {"stream_id": "8", "name": "Some Movie", "tmdb": "0"},
            provider_id="p1",
            media_type="movie",
        )
        assert ch.detected_tmdb_id is None

    def test_convert_no_tmdb_field(self):
        api = self._api()
        ch = api.convert_to_channel(
            {"stream_id": "9", "name": "No Id Movie"},
            provider_id="p1",
            media_type="movie",
        )
        assert ch.detected_tmdb_id is None


# ---------------------------------------------------------------------------
# 4. update_detected_prefixes recompute is tmdb-first
# ---------------------------------------------------------------------------


def test_update_detected_prefixes_uses_tmdb_key(db):
    """Two rows with the same tmdb but different names collapse to one tmdb key."""
    with db.session_scope() as session:
        _provider(session)
        cid_es = _channel(session, name="ES - Mision Salvar el bosque",
                          media_type="movie", detected_tmdb_id="12345")
        cid_en = _channel(session, name="|EN| Animal Adventures",
                          media_type="movie", detected_tmdb_id="12345")

    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        k_es = session.query(ChannelDB.content_key).filter_by(id=cid_es).scalar()
        k_en = session.query(ChannelDB.content_key).filter_by(id=cid_en).scalar()

    assert k_es == "tmdb:12345|movie"
    assert k_en == "tmdb:12345|movie"
    assert k_es == k_en


# ---------------------------------------------------------------------------
# 5. backfill_tmdb_ids + content_key recompute
# ---------------------------------------------------------------------------


def test_backfill_tmdb_ids_populates_from_raw_data(db):
    """detected_tmdb_id is filled from raw_data['tmdb']; sentinels/live rows stay NULL."""
    with db.session_scope() as session:
        _provider(session)
        cid_movie = _channel(session, name="A", media_type="movie",
                             raw_data={"tmdb": "603"})
        cid_sentinel = _channel(session, name="B", media_type="movie",
                                raw_data={"tmdb": "0"})
        cid_live = _channel(session, name="C", media_type="live",
                            raw_data={"tmdb": "999"})  # live: skipped

    with db.session_scope() as session:
        filled = RepositoryFactory(session).channels.backfill_tmdb_ids()

    assert filled == 1, "Only the valid-id VOD row should be written"

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=cid_movie).scalar() == "603"
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=cid_sentinel).scalar() is None
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=cid_live).scalar() is None

    # Idempotent: second run writes nothing (movie already assigned; others have no id).
    with db.session_scope() as session:
        again = RepositoryFactory(session).channels.backfill_tmdb_ids()
    assert again == 0


def test_backfill_then_recompute_content_key_is_tmdb(db):
    """End-to-end migration order: tmdb backfill → content_key recompute keys on tmdb."""
    with db.session_scope() as session:
        _provider(session)
        cid_a = _channel(session, name="ES Peli", media_type="movie",
                         detected_title="Peli", raw_data={"tmdb": "555"})
        cid_b = _channel(session, name="EN Movie", media_type="movie",
                         detected_title="Different Movie", raw_data={"tmdb": "555"})

    # Step (a): populate detected_tmdb_id.
    with db.session_scope() as session:
        RepositoryFactory(session).channels.backfill_tmdb_ids()

    # Step (b): recompute content_key for all rows (formula-change path).
    with db.session_scope() as session:
        RepositoryFactory(session).channels.backfill_content_keys(recompute_all=True)

    with db.session_scope(commit=False) as session:
        k_a = session.query(ChannelDB.content_key).filter_by(id=cid_a).scalar()
        k_b = session.query(ChannelDB.content_key).filter_by(id=cid_b).scalar()

    assert k_a == "tmdb:555|movie"
    assert k_b == "tmdb:555|movie"
    assert k_a == k_b, "Same-tmdb rows must share a content_key after recompute"


# ---------------------------------------------------------------------------
# 6. TmdbIdBackfillTask integration
# ---------------------------------------------------------------------------


def test_tmdb_backfill_task_needs_run_and_completion(tmp_path):
    from metatv.core.config import Config
    from metatv.core.migrations.tmdb_id_backfill import TmdbIdBackfillTask, CURRENT_VERSION

    config = Config(config_dir=tmp_path / "config")
    config.tmdb_id_backfill_version = 0

    db = Database(f"sqlite:///{tmp_path / 'task.db'}")
    db.create_tables()
    task = TmdbIdBackfillTask(db)

    assert task.needs_run(config) is True
    task.on_completed(config)
    assert task.needs_run(config) is False
    assert config.tmdb_id_backfill_version == CURRENT_VERSION
    db.close()


def test_tmdb_backfill_task_run_populates(tmp_path):
    from metatv.core.migrations.tmdb_id_backfill import TmdbIdBackfillTask

    db = Database(f"sqlite:///{tmp_path / 'task_run.db'}")
    db.create_tables()

    with db.session_scope() as session:
        _provider(session)
        cid = _channel(session, name="A", media_type="movie", raw_data={"tmdb": "77"})

    TmdbIdBackfillTask(db).run(progress_cb=lambda d, t: None, is_cancelled=lambda: False)

    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB.detected_tmdb_id).filter_by(id=cid).scalar() == "77"
    db.close()


# ---------------------------------------------------------------------------
# 7. Search-through-collapse regression (the user's explicit concern)
# ---------------------------------------------------------------------------


def test_search_survives_tmdb_collapse(db):
    """Two same-tmdb rows collapse to one card, yet each title stays searchable.

    Row A ("Mision...") and Row B ("Animal Adventures...") share tmdb 12345 and
    thus one content_key.  Collapsed, they show as a single card — but because
    name_filter is applied to each row's OWN title BEFORE the window collapse,
    searching either title still returns that specific row.  This proves a
    wrongly-merged variant is never hidden from search.
    """
    with db.session_scope() as session:
        _provider(session)
        cid_es = _channel(session, name="ES - Mision Salvar el bosque", media_type="movie",
                          detected_title="Mision Salvar el bosque", detected_tmdb_id="12345")
        cid_en = _channel(session, name="|ES| Animal Adventures", media_type="movie",
                          detected_title="Animal Adventures", detected_tmdb_id="12345")
        _tag(session, cid_es)
        _tag(session, cid_en)

    # Compute content_key from the stored detected_tmdb_id (the real path).
    with db.session_scope() as session:
        RepositoryFactory(session).channels.backfill_content_keys(recompute_all=True)

    with db.session_scope(commit=False) as session:
        # Both rows carry the identical tmdb content_key.
        keys = {
            session.query(ChannelDB.content_key).filter_by(id=cid_es).scalar(),
            session.query(ChannelDB.content_key).filter_by(id=cid_en).scalar(),
        }
        assert keys == {"tmdb:12345|movie"}

        repos = RepositoryFactory(session)

        # (a) No filter → the two variants collapse to ONE card counting both.
        collapsed = repos.tags.sample_channels_by_tag_facets(
            {"genre": {"Drama"}}, collapse_variants=True
        )
        assert len(collapsed) == 1, f"Expected 1 collapsed card, got {len(collapsed)}"
        assert collapsed[0].variant_count == 2

        # (b) Searching the Spanish title still returns the Mision row.
        mision = repos.tags.sample_channels_by_tag_facets(
            {"genre": {"Drama"}}, collapse_variants=True, name_filter="Mision"
        )
        assert len(mision) == 1
        assert mision[0].channel_id == cid_es
        assert "mision" in mision[0].title.lower()

        # (c) Searching the English title still returns the Animal row —
        # the folded variant is NOT hidden from search.
        animal = repos.tags.sample_channels_by_tag_facets(
            {"genre": {"Drama"}}, collapse_variants=True, name_filter="Animal"
        )
        assert len(animal) == 1
        assert animal[0].channel_id == cid_en
        assert "animal" in animal[0].title.lower()


# ---------------------------------------------------------------------------
# 8. The writer maintains the content_key invariant on its own
# ---------------------------------------------------------------------------
#
# ``backfill_tmdb_ids`` used to write only ``detected_tmdb_id`` and lean on
# ``ContentKeyBackfillTask`` — registered *after* it in ``main_window.py`` — to
# emit the tmdb-first key.  The two tasks are independently version-gated, and
# the id backfill deliberately leaves its own version unbumped when cancelled so
# it resumes on the next launch.  By then the key task's version is current and
# it does not re-run, so every row the resumed pass filled kept a stale
# title/year key while carrying a tmdb id — it stopped being a sibling of its
# own variants.  No error, no log line, and no test could see it, which is
# exactly how the previously-shipped fix reopened.


def _stale_keyed_rows(session) -> list[str]:
    """Rows carrying a real tmdb id under a non-tmdb ``content_key``."""
    return [
        cid
        for cid, key in session.query(ChannelDB.id, ChannelDB.content_key)
        .filter(ChannelDB.detected_tmdb_id.isnot(None))
        .all()
        if not (key or "").startswith("tmdb:")
    ]


def test_backfill_tmdb_ids_writes_the_key_with_the_id(db):
    """The invariant: a row never holds a tmdb id under a stale title/year key.

    Asserted against the writer ALONE — no content_key task — because that is
    the state a resumed migration actually leaves behind.
    """
    with db.session_scope() as session:
        _provider(session)
        cid = _channel(
            session,
            name="Peli",
            media_type="movie",
            detected_title="Peli",
            content_key="peli|movie",  # the pre-enrichment title key
            raw_data={"tmdb": "603"},
        )

    with db.session_scope() as session:
        assert RepositoryFactory(session).channels.backfill_tmdb_ids() == 1

    with db.session_scope(commit=False) as session:
        key = session.query(ChannelDB.content_key).filter_by(id=cid).scalar()
        assert key == "tmdb:603|movie", (
            f"id written but key left at {key!r} — the row now carries an id its "
            "own siblings cannot match on"
        )
        assert _stale_keyed_rows(session) == []


def test_two_variants_stay_siblings_when_only_one_is_backfilled(db):
    """The consequence that matters: taste collapses on the key, so a split
    title double-counts one film's weight in the recommendation engine.

    One variant is already enriched (tmdb key); its sibling is not.  Filling the
    sibling's id must land it on the SAME key, not leave two identities.
    """
    with db.session_scope() as session:
        _provider(session)
        _channel(
            session,
            name="EN Peli",
            media_type="movie",
            detected_title="Peli",
            detected_tmdb_id="603",
            content_key="tmdb:603|movie",  # already enriched
        )
        cid_b = _channel(
            session,
            name="ES Peli 4K",
            media_type="movie",
            detected_title="Peli",
            content_key="peli|movie",  # idless sibling
            raw_data={"tmdb": "603"},
        )

    with db.session_scope() as session:
        RepositoryFactory(session).channels.backfill_tmdb_ids()

    with db.session_scope(commit=False) as session:
        keys = {k for (k,) in session.query(ChannelDB.content_key).all()}
        assert keys == {"tmdb:603|movie"}, (
            f"the two variants of one film hold {len(keys)} identities: {keys}"
        )
        assert (
            session.query(ChannelDB.content_key).filter_by(id=cid_b).scalar()
            == "tmdb:603|movie"
        )


def test_a_resumed_backfill_after_the_key_task_has_run_leaves_no_stale_key(db, tmp_path):
    """The full launch-order repro, driving both real migration tasks.

    Launch 1: the id backfill is cancelled partway, then the key task runs and
    bumps its version.  Launch 2: the id backfill resumes and completes while
    the key task is version-satisfied and skipped.  Before the fix, every row
    filled on that second pass ended up stale-keyed.
    """
    from metatv.core.migrations.content_key_backfill import ContentKeyBackfillTask
    from metatv.core.migrations.tmdb_id_backfill import TmdbIdBackfillTask
    from metatv.core.config import Config

    config = Config(config_dir=tmp_path)

    with db.session_scope() as session:
        _provider(session)
        for i in range(6):
            _channel(
                session,
                name=f"Film {i}",
                media_type="movie",
                detected_title=f"Film {i}",
                raw_data={"tmdb": str(600 + i)},
            )

    # Launch 1 — id backfill cancelled before it writes anything.
    TmdbIdBackfillTask(db).run(
        progress_cb=lambda d, t: None, is_cancelled=lambda: True
    )
    key_task = ContentKeyBackfillTask(db)
    key_task.run(progress_cb=lambda d, t: None, is_cancelled=lambda: False)
    key_task.on_completed(config)

    # Launch 2 — the key task is now version-satisfied and must not re-run.
    assert not key_task.needs_run(config), (
        "precondition: the key task has already bumped its version"
    )
    TmdbIdBackfillTask(db).run(
        progress_cb=lambda d, t: None, is_cancelled=lambda: False
    )

    with db.session_scope(commit=False) as session:
        stale = _stale_keyed_rows(session)
        assert stale == [], (
            f"{len(stale)} rows resumed into a tmdb id under a stale key, with "
            "no later pass left to repair them"
        )
