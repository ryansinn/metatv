""""Drama" and "DRAMA" are one genre, not two.

Owner: *"DRAMA and Drama shelves are separate."*

``get_or_create_tag`` matched ``(type, value)`` EXACTLY, so every casing a
provider used minted its own row. Measured on the owner's library:

    genre tags                       654
      case/space-variant collisions   27   (36 surplus rows)
      tags with ZERO channels        288   (49% of the low-count tail)

Worth being precise about the symptom, because it is not what it looks like:
for ``drama`` the duplicates carried **no channels at all** — 92,811 sat on
``Drama`` and zero on the other two — so what showed was an empty shelf beside
a full one, not split content. Exactly ONE collision genuinely split content:
``Talk Show تاک شو`` (10) against ``TALK SHOW تاک شو`` (2).

Two halves, and both are needed:

* the CHOKEPOINT stops new variants being created (case-folded cache key and a
  case-insensitive lookup, keeping whatever display text was seen first);
* the MIGRATION merges the rows already written, because tags are created at
  ingestion and a lookup fix never reaches them — the same trap as
  ``detected_restricted``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, ContentTagDB, Database, TagDB
from metatv.core.migrations.tag_case_merge import TagCaseMergeTask
from metatv.core.repositories.tag import TagRepository, _clear_tag_cache
from tests.conftest import add_content_tag


@pytest.fixture
def db(tmp_path: Path):
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'tags.db'}")
    d.create_tables()
    yield d
    d.close()
    _clear_tag_cache()


def _channel(session, cid: str) -> None:
    session.add(ChannelDB(id=cid, source_id="s", provider_id="p",
                          name=cid, media_type="movie"))


# ── the chokepoint ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("variants", [
    ("Drama", "DRAMA", "drama"),
    ("Talk Show", "TALK SHOW", "talk show"),
    ("Sci-Fi", "SCI-FI"),
    ("Comedy", "  Comedy  "),
])
def test_casing_and_spacing_resolve_to_one_tag(db, variants):
    """THE assertion. Each of these minted its own row before."""
    # The cache is cleared between variants ON PURPOSE. There are two layers
    # here — a case-folded cache key and a case-insensitive SQL lookup — and
    # the cache alone is enough to make this pass. The first version of this
    # test did not clear, so restoring the old exact-match SQL left it GREEN:
    # a guard that could not see the bug it is named for.
    ids = set()
    for v in variants:
        _clear_tag_cache()
        with db.session_scope() as session:
            ids.add(TagRepository(session).get_or_create_tag("genre", v).id)

    assert len(ids) == 1, f"{variants} produced {len(ids)} rows"


@pytest.mark.parametrize("variants", [("Drama", "DRAMA"), ("Kids", "kids")])
def test_the_cache_alone_also_resolves_them(db, variants):
    """The other layer, exercised on its own: no clear between calls."""
    with db.session_scope() as session:
        repo = TagRepository(session)
        ids = {repo.get_or_create_tag("genre", v).id for v in variants}

    assert len(ids) == 1


def test_the_first_spelling_seen_is_the_one_displayed(db):
    """Matching is case-insensitive; STORAGE keeps the provider's own text.

    Folding the stored value would turn "Drama" into "drama" on screen, which
    fixes the duplicate by breaking the display.
    """
    with db.session_scope() as session:
        repo = TagRepository(session)
        repo.get_or_create_tag("genre", "Drama")
        # Read INSIDE the block: session_scope expires on commit, and this
        # project's own rule is that an ORM object must not outlive its
        # session. The first draft of these tests broke it and got
        # DetachedInstanceError, which is the rule earning its keep.
        value = repo.get_or_create_tag("genre", "DRAMA").value

    assert value == "Drama"


def test_different_genres_are_still_different(db):
    """The fix must not over-merge."""
    with db.session_scope() as session:
        repo = TagRepository(session)
        a_id = repo.get_or_create_tag("genre", "Drama").id
        b_id = repo.get_or_create_tag("genre", "Comedy").id

    assert a_id != b_id


def test_the_same_text_under_a_different_type_is_a_different_tag(db):
    """Collision is per (type, value), not per value."""
    with db.session_scope() as session:
        repo = TagRepository(session)
        a_id = repo.get_or_create_tag("genre", "Action").id
        b_id = repo.get_or_create_tag("mood", "Action").id

    assert a_id != b_id


# ── the migration ───────────────────────────────────────────────────────────

def test_existing_variants_are_merged_and_channels_repointed(db):
    """A lookup fix never reaches rows already written at ingestion."""
    with db.session_scope() as session:
        for i, v in enumerate(("Drama", "DRAMA", "drama"), start=1):
            session.add(TagDB(id=i, type="genre", value=v))
        _channel(session, "c1")
        _channel(session, "c2")
        session.flush()
        add_content_tag(session, "c1", 1, source="generated")
        add_content_tag(session, "c2", 2, source="generated")

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        tags = session.query(TagDB).filter_by(type="genre").all()
        assert len(tags) == 1, f"expected one Drama row, got {[t.value for t in tags]}"
        assert tags[0].value == "Drama", "the most-referenced spelling should survive"
        assert session.query(ContentTagDB).filter_by(tag_id=tags[0].id).count() == 2, (
            "a channel was left pointing at a deleted tag"
        )


def test_no_channel_is_orphaned_by_the_merge(db):
    """Every content_tags row must still point at a tag that exists."""
    with db.session_scope() as session:
        for i, v in enumerate(("Kids", "KIDS", "kids"), start=1):
            session.add(TagDB(id=i, type="genre", value=v))
        for n in range(6):
            _channel(session, f"ch{n}")
        session.flush()
        for n in range(6):
            add_content_tag(session, f"ch{n}", (n % 3) + 1, source="generated")

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        tag_ids = {t.id for t in session.query(TagDB).all()}
        dangling = [
            ct.tag_id for ct in session.query(ContentTagDB).all()
            if ct.tag_id not in tag_ids
        ]
        assert not dangling, f"content_tags point at deleted tags: {dangling}"
        assert session.query(ContentTagDB).count() == 6, "channel links were lost"


def test_a_tag_nothing_references_survives_the_merge(db):
    """TAG-2: a zero-link tag that was never part of a collision is not this
    merge's business.

    Before TAG-2 this task ended with a second, unscoped pass —
    ``DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM
    content_tags)`` — that deleted EVERY unreferenced tag, not merely the
    losers of the case merge it had just performed. "Orphan" here was never a
    duplicate of anything ("Used" is a different value entirely, so they are
    not in the same casefold group) — it is ordinary standalone debris under
    today's "tags are observed provider values" model, but under the
    CONCEPT-1 proposal (``tags`` rows become curated aliases with a
    ``concept_id``) a zero-link row can be deliberately-retained vocabulary.
    A case-merge migration must not make that call. On pre-fix code this
    assertion is RED: "Orphan" was deleted.
    """
    with db.session_scope() as session:
        session.add(TagDB(id=1, type="genre", value="Used"))
        session.add(TagDB(id=2, type="genre", value="Orphan"))
        _channel(session, "c1")
        session.flush()
        add_content_tag(session, "c1", 1, source="generated")

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        values = {t.value for t in session.query(TagDB).all()}
        assert values == {"Used", "Orphan"}, (
            f"expected the unrelated orphan to survive, got {values}"
        )


def test_running_it_twice_changes_nothing(db):
    """Migrations get re-run; the second pass must be a no-op."""
    with db.session_scope() as session:
        session.add(TagDB(id=1, type="genre", value="Drama"))
        session.add(TagDB(id=2, type="genre", value="DRAMA"))
        _channel(session, "c1")
        session.flush()
        add_content_tag(session, "c1", 2, source="generated")

    task = TagCaseMergeTask(db)
    task.run(lambda a, b: None, lambda: False)
    with db.session_scope() as session:
        first = [(t.id, t.value) for t in session.query(TagDB).all()]

    task.run(lambda a, b: None, lambda: False)
    with db.session_scope() as session:
        second = [(t.id, t.value) for t in session.query(TagDB).all()]

    assert first == second and len(first) == 1


def test_the_survivor_is_the_most_used_spelling(db):
    """Stable and sensible: keep the row the library actually uses."""
    with db.session_scope() as session:
        session.add(TagDB(id=1, type="genre", value="rare"))
        session.add(TagDB(id=2, type="genre", value="Rare"))
        for n in range(4):
            _channel(session, f"c{n}")
        session.flush()
        add_content_tag(session, "c0", 1, source="generated")
        for n in (1, 2, 3):
            add_content_tag(session, f"c{n}", 2, source="generated")

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        rows = session.query(TagDB).all()
        assert len(rows) == 1 and rows[0].value == "Rare"


def test_a_channel_carrying_both_variants_does_not_duplicate_or_lose_its_link(db):
    """DB-9 risk #6: ``UPDATE OR IGNORE ... SET tag_id`` now updates a PRIMARY
    KEY column of a WITHOUT ROWID table (``channel_key, tag_id, source``).

    A channel that already carries BOTH the keeper's and a loser's tag makes
    the repoint collide with a row that already exists for that channel under
    the keeper's tag_id — the collision ``OR IGNORE`` exists to absorb. Must
    survive with exactly ONE link to the surviving tag, never two (a
    duplicate) and never zero (an orphaned channel).
    """
    with db.session_scope() as session:
        session.add(TagDB(id=1, type="genre", value="Horror"))
        session.add(TagDB(id=2, type="genre", value="HORROR"))
        session.add(TagDB(id=3, type="genre", value="horror"))
        _channel(session, "both")     # carries every variant — the collision case
        _channel(session, "c1")
        _channel(session, "c2")
        session.flush()
        add_content_tag(session, "both", 1, source="generated")
        add_content_tag(session, "both", 2, source="generated")
        add_content_tag(session, "both", 3, source="generated")
        add_content_tag(session, "c1", 1, source="generated")
        add_content_tag(session, "c2", 1, source="generated")

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        tags = session.query(TagDB).filter_by(type="genre").all()
        assert len(tags) == 1, f"expected one Horror row, got {[t.value for t in tags]}"
        keeper_id = tags[0].id

        both_key = (
            session.query(ChannelDB.channel_key)
            .filter(ChannelDB.id == "both").scalar()
        )
        both_links = (
            session.query(ContentTagDB)
            .filter(ContentTagDB.channel_key == both_key).all()
        )
        assert len(both_links) == 1, (
            f"'both' must have exactly one surviving link, not {len(both_links)} "
            "(the collision must be absorbed, never duplicated)"
        )
        assert both_links[0].tag_id == keeper_id, (
            "'both' must still point at the surviving tag, not be silently dropped"
        )


# ── v2: vocabulary — other-language genre spellings, language codes as regions ─
# Owner, 2026-10-20: "dozens of arabic drama and comedy" in the filter list,
# and "Hindi isn't a region, it's a language". Folds only the obvious.

def _tags_of(session, cid: str) -> set[tuple[str, str]]:
    key = session.query(ChannelDB.channel_key).filter_by(id=cid).scalar()
    return {(t.type, t.value) for t in session.query(TagDB)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_key == key)}


def _run(db):
    _clear_tag_cache()
    TagCaseMergeTask(db).run(lambda *_: None, lambda: False)


def test_a_mixed_language_genre_folds_onto_its_canonical_genres(db):
    with db.session_scope() as session:
        _channel(session, "a")
        _channel(session, "b")
        repo = TagRepository(session)
        alias = repo.get_or_create_tag("genre", "Drama خانوادگی").id
        drama = repo.get_or_create_tag("genre", "Drama").id
        session.flush()
        add_content_tag(session, "a", alias)
        add_content_tag(session, "a", drama)          # already has Drama: no duplicate
        add_content_tag(session, "b", alias)
    _run(db)
    with db.session_scope(commit=False) as session:
        assert _tags_of(session, "a") == {("genre", "Drama"), ("genre", "Family")}
        assert _tags_of(session, "b") == {("genre", "Drama"), ("genre", "Family")}
        assert session.query(TagDB).filter_by(value="Drama خانوادگی").count() == 0


@pytest.mark.parametrize("value", ["Teen Drama", "Social", "اجتماعي", "GAİN"])
def test_anything_not_obvious_is_left_alone(db, value):
    with db.session_scope() as session:
        _channel(session, "a")
        tid = TagRepository(session).get_or_create_tag("genre", value).id
        session.flush()
        add_content_tag(session, "a", tid)
    _run(db)
    with db.session_scope(commit=False) as session:
        assert _tags_of(session, "a") == {("genre", value)}


def test_a_language_code_leaves_the_region_facet(db):
    with db.session_scope() as session:
        _channel(session, "hi")
        _channel(session, "il")
        repo = TagRepository(session)
        hi, il = repo.get_or_create_tag("region", "HI").id, repo.get_or_create_tag("region", "IL").id
        session.flush()
        add_content_tag(session, "hi", hi)
        add_content_tag(session, "il", il)
    _run(db)
    with db.session_scope(commit=False) as session:
        assert _tags_of(session, "hi") == {("language", "Hindi")}
        assert _tags_of(session, "il") == {("region", "IL")}, "a real country stays a region"


def test_the_row_lists_stored_genres_are_refolded(db):
    with db.session_scope() as session:
        session.add(ChannelDB(id="a", source_id="s", provider_id="p", name="a",
                              media_type="movie", detected_genre="Comedy طنز",
                              detected_genres=["Comedy طنز", "دراما"]))
    _run(db)
    with db.session_scope(commit=False) as session:
        ch = session.query(ChannelDB).filter_by(id="a").one()
        assert ch.detected_genres == ["Comedy", "Drama"]
        assert ch.detected_genre == "Comedy"


@pytest.mark.parametrize("raw,expected", [
    ("Comedy طنز اجتماعی", ["Comedy"]),
    ("دراما ﺗﺸﻮﻳﻖ ﻭﺇﺛﺎﺭﺓ", ["Drama", "Thriller"]),     # presentation forms + joined "and"
    ("Comedy | Drama | Romance", ["Comedy", "Drama", "Romance"]),
    ("Biograf", ["Biography"]),
    ("Teen Drama", ["Teen Drama"]),
    ("Action & Adventure", ["Action & Adventure"]),
])
def test_resolve_genres(raw, expected):
    from metatv.core.filter_utils import resolve_genres
    assert resolve_genres(raw) == expected


def test_ticking_one_country_matches_every_code_it_has(db):
    """Israel arrives as IL and ISR; the filter list shows one Israel."""
    from sqlalchemy import select

    from metatv.core.filter_utils import facet_include_criterion

    with db.session_scope() as session:
        _channel(session, "isr")
        tid = TagRepository(session).get_or_create_tag("region", "ISR").id
        session.flush()
        add_content_tag(session, "isr", tid)
    with db.session_scope(commit=False) as session:
        hits = session.execute(select(ChannelDB.id).where(
            facet_include_criterion("region", {"IL"}, allow_untagged=False))).scalars().all()
        assert hits == ["isr"]


def test_the_region_list_shows_one_row_per_country():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from metatv.core.region_codes import REGION_FULL_NAMES
    from metatv.gui.filter_panel_sections import build_region

    sec = MagicMock()
    sec.get_selected_keys.return_value = []
    panel = SimpleNamespace(
        config=SimpleNamespace(filter_regional_groups={"Middle East": ["IL", "ISR", "AE"]}),
        _region_label=lambda c: REGION_FULL_NAMES.get(c, c), _region_sec=sec)
    build_region(panel, {"region": {"IL": 139, "ISR": 591, "AE": 17}}, lambda *a: None)
    (groups,), _ = sec.set_grouped_items.call_args
    (_name, total, children), = groups
    assert total == 747
    assert [(label, n) for _key, label, n in children] == [("Israel", 730), (REGION_FULL_NAMES["AE"], 17)]
