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
        session.add(ContentTagDB(channel_id="c1", tag_id=1, source="generated"))
        session.add(ContentTagDB(channel_id="c2", tag_id=2, source="generated"))

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
            session.add(ContentTagDB(channel_id=f"ch{n}", tag_id=(n % 3) + 1,
                                     source="generated"))

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        tag_ids = {t.id for t in session.query(TagDB).all()}
        dangling = [
            ct.tag_id for ct in session.query(ContentTagDB).all()
            if ct.tag_id not in tag_ids
        ]
        assert not dangling, f"content_tags point at deleted tags: {dangling}"
        assert session.query(ContentTagDB).count() == 6, "channel links were lost"


def test_a_tag_nothing_references_is_pruned(db):
    """288 of the owner's genre tags had zero channels — ordinary debris."""
    with db.session_scope() as session:
        session.add(TagDB(id=1, type="genre", value="Used"))
        session.add(TagDB(id=2, type="genre", value="Orphan"))
        _channel(session, "c1")
        session.flush()
        session.add(ContentTagDB(channel_id="c1", tag_id=1, source="generated"))

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        assert [t.value for t in session.query(TagDB).all()] == ["Used"]


def test_running_it_twice_changes_nothing(db):
    """Migrations get re-run; the second pass must be a no-op."""
    with db.session_scope() as session:
        session.add(TagDB(id=1, type="genre", value="Drama"))
        session.add(TagDB(id=2, type="genre", value="DRAMA"))
        _channel(session, "c1")
        session.flush()
        session.add(ContentTagDB(channel_id="c1", tag_id=2, source="generated"))

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
        session.add(ContentTagDB(channel_id="c0", tag_id=1, source="generated"))
        for n in (1, 2, 3):
            session.add(ContentTagDB(channel_id=f"c{n}", tag_id=2, source="generated"))

    TagCaseMergeTask(db).run(lambda a, b: None, lambda: False)

    with db.session_scope() as session:
        rows = session.query(TagDB).all()
        assert len(rows) == 1 and rows[0].value == "Rare"
