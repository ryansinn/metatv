"""Behavioral tests for the channel-LIST variant collapse (wave7/channel-dedup).

Guards ``ChannelRepository.get_all(collapse_variants=True)`` — the list-view
sibling of the already-tested Discover/recipe collapse (see
tests/test_content_collapse.py for the TagRepository side):

1. Variants of one work (shared content_key) collapse to a single row and
   carry the group size as a transient ``_variant_count`` attribute.
2. The representative is the highest quality-tier variant
   (``channel_name_utils.quality_tier_rank`` — the lookup-table single source
   of truth).
3. Pagination stays exact with collapse on: offset/limit apply to GROUPS, so
   pages come back full-sized and disjoint (never ragged from a post-fetch
   Python collapse).
4. ``collapse_variants=False`` (the default) is unchanged — every raw row.
5. A work whose best-quality copy sits on a hidden/expired provider never
   picks that copy as the representative — the visible copy does, because
   the hidden provider is excluded from the candidate set entirely (the same
   ``excluded_provider_ids``/``get_hidden_provider_ids()`` contract every
   other ``get_all()`` caller already uses — DR-0007).
6. A movie and a series sharing a title never collapse together (content_key
   already encodes media_type).

All tests use a file-backed (tmp_path) SQLite ``Database`` — never
``:memory:`` (pooled connections each see an empty schema on ``:memory:``,
per CLAUDE.md's Tests rule).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables created."""
    d = Database(f"sqlite:///{tmp_path / 'channel_list_collapse_test.db'}")
    d.create_tables()
    yield d
    d.close()


def _provider(session, pid: str = "p1", is_active: bool = True) -> str:
    p = ProviderDB(
        id=pid,
        name=f"Provider {pid}",
        type="xtream",
        url="http://example.com",
        username="u",
        password="p",
        is_active=is_active,
    )
    session.add(p)
    session.flush()
    return pid


def _channel(
    session,
    provider_id: str,
    *,
    name: str = "Test",
    detected_title: str | None = None,
    detected_quality: str | None = None,
    content_key: str | None = None,
    media_type: str = "movie",
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
            detected_quality=detected_quality,
            content_key=content_key,
        )
    )
    session.flush()
    return cid


# ---------------------------------------------------------------------------
# 1 & 2 — collapse to one row, variant_count, best-quality representative
# ---------------------------------------------------------------------------

def test_variants_collapse_to_one_row_carrying_variant_count(db):
    """Three quality variants of one work → one row with _variant_count == 3."""
    with db.session_scope() as session:
        pid = _provider(session)
        key = "dark star|movie|2017"
        _channel(session, pid, name="SD Dark Star", detected_quality="SD",
                 content_key=key, detected_title="Dark Star")
        _channel(session, pid, name="HD Dark Star", detected_quality="HD",
                 content_key=key, detected_title="Dark Star")
        _channel(session, pid, name="4K Dark Star", detected_quality="4K",
                 content_key=key, detected_title="Dark Star")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        rows = repos.channels.get_all(collapse_variants=True)

        assert len(rows) == 1, f"Expected 1 collapsed row, got {len(rows)}"
        assert rows[0]._variant_count == 3, (
            f"Expected _variant_count=3, got {rows[0]._variant_count}"
        )


def test_representative_is_highest_quality_tier(db):
    """The representative must be the 4K variant (best quality_tier_rank), not
    whichever row happens to be inserted first."""
    with db.session_scope() as session:
        pid = _provider(session)
        key = "dark star|movie|2017"
        # Insert worst-to-best so insertion order can't accidentally pick the winner.
        _channel(session, pid, name="SD Dark Star", detected_quality="SD",
                 content_key=key, detected_title="Dark Star")
        _channel(session, pid, name="HD Dark Star", detected_quality="HD",
                 content_key=key, detected_title="Dark Star")
        id_4k = _channel(session, pid, name="4K Dark Star", detected_quality="4K",
                          content_key=key, detected_title="Dark Star")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        rows = repos.channels.get_all(collapse_variants=True)

        assert len(rows) == 1
        assert rows[0].id == id_4k, (
            f"Representative should be the 4K channel ({id_4k}), got {rows[0].id}"
        )


def test_null_content_key_forms_own_singleton(db):
    """A NULL content_key row must never merge with other NULL-key rows (the
    COALESCE(content_key, 'id:' || id) guard)."""
    with db.session_scope() as session:
        pid = _provider(session)
        key = "dark star|movie|2017"
        _channel(session, pid, name="4K Dark Star", detected_quality="4K",
                 content_key=key, detected_title="Dark Star")
        _channel(session, pid, name="HD Dark Star", detected_quality="HD",
                 content_key=key, detected_title="Dark Star")
        _channel(session, pid, name="Alpha Unknown", content_key=None,
                 detected_title="Alpha Unknown")
        _channel(session, pid, name="Beta Unknown", content_key=None,
                 detected_title="Beta Unknown")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        rows = repos.channels.get_all(collapse_variants=True)

        # 1 collapsed "Dark Star" group + 2 NULL-key singletons = 3 rows.
        assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}: {[r.name for r in rows]}"
        singleton_counts = {r._variant_count for r in rows if r.content_key is None}
        assert singleton_counts == {1}, "NULL-key rows must each have _variant_count == 1"


# ---------------------------------------------------------------------------
# 3 — pagination stays exact (offset/limit over GROUPS)
# ---------------------------------------------------------------------------

def test_pagination_is_full_and_disjoint_with_collapse_on(db):
    """6 collapsed groups (2 variants each); limit=3 pages must be full-sized,
    disjoint, and together cover every group — never ragged."""
    titles = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
    with db.session_scope() as session:
        pid = _provider(session)
        for t in titles:
            key = f"{t.lower()}|movie|2020"
            _channel(session, pid, name=f"{t} HD", detected_quality="HD",
                     content_key=key, detected_title=t)
            _channel(session, pid, name=f"{t} SD", detected_quality="SD",
                     content_key=key, detected_title=t)

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        page1 = repos.channels.get_all(collapse_variants=True, limit=3, offset=0)
        page2 = repos.channels.get_all(collapse_variants=True, limit=3, offset=3)

        assert len(page1) == 3, f"Page 1 should be full (3 rows), got {len(page1)}"
        assert len(page2) == 3, f"Page 2 should be full (3 rows), got {len(page2)}"

        ids1 = {r.id for r in page1}
        ids2 = {r.id for r in page2}
        assert ids1.isdisjoint(ids2), "Pages must not overlap"

        all_titles = sorted(r.detected_title for r in (page1 + page2))
        assert all_titles == sorted(titles), (
            f"Combined pages must cover every group exactly once; got {all_titles}"
        )
        for r in page1 + page2:
            assert r._variant_count == 2


# ---------------------------------------------------------------------------
# 4 — collapse_variants=False (default) is unchanged
# ---------------------------------------------------------------------------

def test_collapse_off_restores_every_row(db):
    """Default (collapse_variants=False) must return every raw row, uncollapsed."""
    with db.session_scope() as session:
        pid = _provider(session)
        key = "dark star|movie|2017"
        _channel(session, pid, name="SD Dark Star", detected_quality="SD",
                 content_key=key, detected_title="Dark Star")
        _channel(session, pid, name="HD Dark Star", detected_quality="HD",
                 content_key=key, detected_title="Dark Star")
        _channel(session, pid, name="4K Dark Star", detected_quality="4K",
                 content_key=key, detected_title="Dark Star")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        # collapse_variants omitted — must default to False (opt-in, off by default).
        rows = repos.channels.get_all()

        assert len(rows) == 3, f"Expected all 3 raw rows with collapse off, got {len(rows)}"
        # No collapse ran, so the transient attribute was never set — every
        # caller (ChannelListDTO.from_orm) must fall back to variant_count=1.
        for r in rows:
            assert getattr(r, "_variant_count", 1) == 1


# ---------------------------------------------------------------------------
# 5 — hidden-provider variant never becomes the representative
# ---------------------------------------------------------------------------

def test_hidden_provider_copy_never_wins_representative(db):
    """The best-quality copy sits on an inactive (hidden) provider; the only
    OTHER copy sits on a visible provider. With the real
    ProviderRepository.get_hidden_provider_ids() passed through as
    excluded_provider_ids (exactly how every real get_all() caller scopes
    forward-looking views, DR-0007), the hidden copy must never surface as —
    or hide behind — the representative: the visible copy must be the sole
    surviving row."""
    with db.session_scope() as session:
        _provider(session, pid="hidden_src", is_active=False)
        _provider(session, pid="visible_src", is_active=True)
        key = "dark star|movie|2017"
        _channel(session, "hidden_src", name="4K Dark Star (hidden source)",
                 detected_quality="4K", content_key=key, detected_title="Dark Star")
        id_visible = _channel(session, "visible_src", name="HD Dark Star",
                               detected_quality="HD", content_key=key,
                               detected_title="Dark Star")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        hidden_ids = repos.providers.get_hidden_provider_ids()
        assert "hidden_src" in hidden_ids

        rows = repos.channels.get_all(
            collapse_variants=True,
            excluded_provider_ids=hidden_ids or None,
        )

        assert len(rows) == 1, f"Expected exactly 1 surviving row, got {len(rows)}"
        assert rows[0].id == id_visible, (
            "The visible provider's copy must be the sole survivor — the "
            "hidden provider's higher-quality copy must never be shown as "
            "(or hide behind) the representative."
        )
        assert rows[0]._variant_count == 1


# ---------------------------------------------------------------------------
# 6 — movies and series never merge, even with the identical title
# ---------------------------------------------------------------------------

def test_movie_and_series_same_title_never_merge(db):
    """A movie and a series sharing a title carry DIFFERENT content_keys
    (media_type is baked into the key) — they must appear as two separate
    rows, never collapsed into one."""
    with db.session_scope() as session:
        pid = _provider(session)
        movie_id = _channel(
            session, pid, name="Dark Star (Movie)", detected_quality="HD",
            content_key="dark star|movie|2017", detected_title="Dark Star",
            media_type="movie",
        )
        series_id = _channel(
            session, pid, name="Dark Star (Series)", detected_quality="HD",
            content_key="dark star|series", detected_title="Dark Star",
            media_type="series",
        )

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        rows = repos.channels.get_all(
            collapse_variants=True, media_types=["movie", "series"],
        )

        ids = {r.id for r in rows}
        assert ids == {movie_id, series_id}, (
            f"Movie and series content_key groups must never merge; got {ids}"
        )
        for r in rows:
            assert r._variant_count == 1
