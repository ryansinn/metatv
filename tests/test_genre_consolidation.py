"""Behavioral tests for the #153 genre consolidation.

Covers, beyond the doc↔code parity suite (``test_genre_mapping_parity``):

* one representative fold per *class* (case / typo / noise-suffix /
  separator-variant / order-variant / translation, incl. Arabic
  presentation-forms) — exact strings copied from the sign-off chart;
* the six corrections to pre-existing ``_GENRE_NORM`` entries (three remapped,
  three now kept raw);
* the new canonicals joining ``KNOWN_GENRES``;
* a real file-backed ``Database`` backfill proving that after the version bump a
  stale generated ``genre:"Soap"`` tag becomes ``"Soap Opera"`` and ``genre:"Dram"``
  becomes ``"Drama"`` (per the CLAUDE.md tests rule — a real DB on ``tmp_path``,
  not ``:memory:``; asserts the outcome that would break).
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.config import Config
from metatv.core.database import ChannelDB, ContentTagDB, Database, TagDB
from metatv.core.filter_utils import KNOWN_GENRES, normalize_genre
from metatv.core.migrations.tag_backfill import CURRENT_TAG_BACKFILL_VERSION, TagBackfillTask
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# 1. One representative fold per class (exact strings from genre_chart.md)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected,klass", [
    ("DRAMA",              "Drama",            "case"),
    ("FAMILY",             "Family",           "case"),
    ("Dram",               "Drama",            "typo"),
    ("Thrille",            "Thriller",         "typo"),
    ("DRMA",               "Drama",            "typo"),
    ("Drama series",       "Drama",            "noise-suffix"),
    ("Reality Show",       "Reality",          "noise-suffix"),
    ("Crime. Drama",       "Drama & Crime",    "separator-variant"),
    ("Romance Drama",      "Drama & Romance",  "order-variant"),
    ("humor",              "Comedy",           "translation (es/intl)"),
    ("Liebesfilm",         "Romance",          "translation (de)"),
    ("Faroeste",           "Western",          "translation (pt)"),
    ("كرتون",              "Animation",        "translation (ar 'cartoon')"),
    ("ﺗﺸﻮﻳﻖ",              "Thriller",         "translation (ar presentation-form)"),
    ("ﺳﻴﺮﺓ ﺫاﺗﻴﺔ",         "Biography",        "translation (ar presentation-form)"),
    ("ﻛﻮﻣﻴﺪﻱ ﺩﺭاﻣﺎ",       "Drama & Comedy",   "translation (ar presentation-form compound)"),
])
def test_representative_fold_per_class(raw: str, expected: str, klass: str):
    assert normalize_genre(raw) == expected, (
        f"[{klass}] normalize_genre({raw!r}) → {normalize_genre(raw)!r}, want {expected!r}"
    )


# ---------------------------------------------------------------------------
# 2. The six corrections
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Soap",               "Soap Opera"),   # rename (was passthrough "Soap")
    ("Biografi",           "Biography"),    # was mis-mapped to History
    ("biografi",           "Biography"),    # lowercased key (same fix)
    ("tävling",            "Game Show"),    # was mis-mapped to Reality
    ("children & family",  "Family"),       # compound; was mis-mapped to Kids
])
def test_correction_remaps(raw: str, expected: str):
    assert normalize_genre(raw) == expected, (
        f"correction: normalize_genre({raw!r}) → {normalize_genre(raw)!r}, want {expected!r}"
    )


@pytest.mark.parametrize("raw", ["variety", "underhållning", "اجتماعی"])
def test_correction_now_raw(raw: str):
    """These mappings were removed (#153) — the value must pass through unchanged."""
    assert normalize_genre(raw) == raw, (
        f"{raw!r} must now be kept raw, but normalize_genre returned {normalize_genre(raw)!r}"
    )


def test_biografi_no_longer_history():
    """Explicit regression guard: the old (wrong) Biography→History fold is gone."""
    assert normalize_genre("Biografi") != "History"


# ---------------------------------------------------------------------------
# 3. New canonicals are in the vocabulary; old "Soap" left it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("canon", [
    "Adult", "Politics", "Biography", "Game Show", "Anime", "Music Show",
    "TV Movie", "Soap Opera", "Drama & Comedy", "Drama & Crime", "Drama & Romance",
])
def test_new_canonical_in_known_genres(canon: str):
    assert canon in KNOWN_GENRES


def test_old_soap_canonical_gone():
    assert "Soap" not in KNOWN_GENRES, "bare 'Soap' was renamed to 'Soap Opera'"


def test_new_canonicals_are_idempotent():
    """Feeding a canonical display name back through normalize_genre is stable."""
    for canon in ("Soap Opera", "Drama & Comedy", "Game Show", "Politics", "Anime"):
        assert normalize_genre(canon) == canon


# ---------------------------------------------------------------------------
# 4. Real-Database backfill re-tag (version bump forces re-derive)
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'genre_consolidation.db'}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def cfg(tmp_path):
    return Config(config_dir=tmp_path / "cfg")


def _add_channel(db: Database, *, genre: str) -> str:
    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id=str(uuid.uuid4()), provider_id="p",
            name=f"Chan {genre}", media_type="movie",
            raw_data={"genre": genre},
        ))
    return cid


def _genre_tags(db: Database, cid: str) -> set[str]:
    with db.session_scope(commit=False) as session:
        rows = (
            session.query(TagDB.value)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == cid, TagDB.type == "genre",
                    ContentTagDB.source == "generated")
            .all()
        )
    return {r[0] for r in rows}


def test_backfill_version_bumped_to_9():
    assert CURRENT_TAG_BACKFILL_VERSION >= 9, (
        f"CURRENT_TAG_BACKFILL_VERSION is {CURRENT_TAG_BACKFILL_VERSION}; the #153 "
        "consolidation requires a re-backfill (>= 9)."
    )


def test_backfill_retags_soap_and_dram(file_db, cfg):
    """A stale generated genre tag is rewritten to the consolidated canonical.

    Simulates a pre-#153 install: a channel whose ``raw_data`` genre is the raw
    provider string, carrying a stale generated ``genre`` tag with the OLD value.
    Running the (version-bumped) backfill must delete the stale generated tag and
    re-derive the new canonical.
    """
    soap_cid = _add_channel(file_db, genre="Soap")
    dram_cid = _add_channel(file_db, genre="Dram")

    # Plant the stale pre-#153 generated genre tags (old un-consolidated values).
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.tags.set_content_tags(soap_cid, [("genre", "Soap", "genre")], source="generated")
        repos.tags.set_content_tags(dram_cid, [("genre", "Dram", "genre")], source="generated")

    assert _genre_tags(file_db, soap_cid) == {"Soap"}
    assert _genre_tags(file_db, dram_cid) == {"Dram"}

    # Run the backfill to completion.
    task = TagBackfillTask(file_db, config=cfg)
    task.run(lambda done, total: None, is_cancelled=lambda: False)

    soap_tags = _genre_tags(file_db, soap_cid)
    dram_tags = _genre_tags(file_db, dram_cid)

    assert "Soap Opera" in soap_tags and "Soap" not in soap_tags, (
        f"stale genre:'Soap' must become 'Soap Opera'; got {soap_tags}"
    )
    assert "Drama" in dram_tags and "Dram" not in dram_tags, (
        f"stale genre:'Dram' must become 'Drama'; got {dram_tags}"
    )


def test_backfill_preserves_user_genre_tag(file_db, cfg):
    """A user-curated genre tag is never rewritten by the consolidation backfill."""
    cid = _add_channel(file_db, genre="Soap")
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.tags.set_content_tags(cid, [("genre", "Soap", "human")], source="user")

    task = TagBackfillTask(file_db, config=cfg)
    task.run(lambda done, total: None, is_cancelled=lambda: False)

    with file_db.session_scope(commit=False) as session:
        user_rows = (
            session.query(TagDB.value)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == cid, ContentTagDB.source == "user")
            .all()
        )
    assert {r[0] for r in user_rows} == {"Soap"}, "user genre:'Soap' must be untouched"
