"""Behavioral tests for content-collapse Slice 2: variant collapse on browse/recipe surfaces.

Guards the following invariants:

1. ``sample_channels_by_tag_facets(collapse_variants=True)`` returns ONE card per
   content_key group.
2. The collapsed card for a 3-variant group has ``variant_count == 3``.
3. The representative is the highest-quality variant (detected_quality ranks:
   4K/UHD=best, HD=middle, NULL/SD=worst) — lower quality number = better.
4. A NULL content_key row appears as its OWN singleton card (the COALESCE guard
   — this assertion FAILS if someone drops the COALESCE).
5. ``count_channels_by_tag_facets(collapse_variants=True)`` returns
   ``COUNT(DISTINCT group_key)``, not raw rows.
6. ``collapse_variants=False`` preserves existing behaviour (raw row count + list).
7. Paging with offset/limit over collapsed results is stable: disjoint, gap-free,
   alphabetically ordered.
8. ``name_filter`` narrows BEFORE collapse so filtered pages are also deduped.

All tests use file-backed (tmp_path) SQLite DBs — not :memory: (pooled
connections each see an empty schema on :memory:).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, ContentTagDB, Database, ProviderDB, TagDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables created."""
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'collapse_test.db'}")
    d.create_tables()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _tag(session, channel_id: str, facet_type: str = "genre", value: str = "Drama") -> None:
    repos = RepositoryFactory(session)
    repos.tags.set_content_tags(channel_id, [(facet_type, value, "test")])
    session.flush()


# ---------------------------------------------------------------------------
# Core collapse behaviour
# ---------------------------------------------------------------------------

class TestCollapseBasic:
    """Invariants 1–4: one card per group, correct variant_count, correct representative,
    and the NULL-content_key COALESCE guard."""

    def test_three_variants_collapse_to_one_card(self, db):
        """3 channels sharing a content_key → 1 collapsed card."""
        with db.session_scope() as session:
            pid = _provider(session)
            key = "dark star|movie|2017"
            c1 = _channel(session, pid, name="4K - Dark Star", detected_quality="4K",
                           content_key=key, detected_title="Dark Star")
            c2 = _channel(session, pid, name="HD - Dark Star", detected_quality="HD",
                           content_key=key, detected_title="Dark Star")
            c3 = _channel(session, pid, name="SD - Dark Star", detected_quality=None,
                           content_key=key, detected_title="Dark Star")
            for cid in (c1, c2, c3):
                _tag(session, cid)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
            )

        assert len(cards) == 1, f"Expected 1 collapsed card, got {len(cards)}"

    def test_collapsed_card_variant_count_is_three(self, db):
        """The collapsed card's variant_count must be 3."""
        with db.session_scope() as session:
            pid = _provider(session)
            key = "dark star|movie|2017"
            for q in ("4K", "HD", None):
                cid = _channel(session, pid, name=f"{q or 'SD'} Dark Star",
                                detected_quality=q, content_key=key,
                                detected_title="Dark Star")
                _tag(session, cid)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
            )

        assert len(cards) == 1
        assert cards[0].variant_count == 3, (
            f"Expected variant_count=3, got {cards[0].variant_count}"
        )

    def test_representative_is_highest_quality(self, db):
        """The representative must be the 4K variant (best quality rank)."""
        with db.session_scope() as session:
            pid = _provider(session)
            key = "dark star|movie|2017"
            # Insert in worst→best order so insertion order doesn't determine the winner.
            c_sd = _channel(session, pid, name="SD Dark Star", detected_quality=None,
                             content_key=key, detected_title="Dark Star")
            c_hd = _channel(session, pid, name="HD Dark Star", detected_quality="HD",
                             content_key=key, detected_title="Dark Star")
            c_4k = _channel(session, pid, name="4K Dark Star", detected_quality="4K",
                             content_key=key, detected_title="Dark Star")
            # Tag all three so they appear in the facet match.
            _tag(session, c_sd)
            _tag(session, c_hd)
            _tag(session, c_4k)
            # Record the 4K channel's id for assertion.
            id_4k = c_4k

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
            )

        assert len(cards) == 1
        assert cards[0].channel_id == id_4k, (
            f"Representative should be the 4K channel ({id_4k}), "
            f"got {cards[0].channel_id}"
        )

    def test_null_content_key_forms_own_singleton_group(self, db):
        """A channel with NULL content_key MUST appear as its own card, not merged
        with other NULL-key channels.  This test FAILS if the COALESCE guard is
        dropped and bare PARTITION BY content_key is used instead."""
        with db.session_scope() as session:
            pid = _provider(session)
            # Shared-key group (content_key set)
            key = "dark star|movie|2017"
            for q in ("4K", "HD"):
                cid = _channel(session, pid, name=f"{q} Dark Star",
                                detected_quality=q, content_key=key,
                                detected_title="Dark Star")
                _tag(session, cid)
            # Two distinct-title channels with NULL content_key
            c_null_1 = _channel(session, pid, name="Alpha Unknown",
                                  detected_quality=None, content_key=None,
                                  detected_title="Alpha Unknown")
            c_null_2 = _channel(session, pid, name="Beta Unknown",
                                  detected_quality=None, content_key=None,
                                  detected_title="Beta Unknown")
            _tag(session, c_null_1)
            _tag(session, c_null_2)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
            )

        # Expected: 3 cards — 1 collapsed group + 2 NULL-key singletons.
        assert len(cards) == 3, (
            f"Expected 3 collapsed cards (1 keyed group + 2 NULL singletons), "
            f"got {len(cards)}: {[c.title for c in cards]}"
        )
        # The NULL-key channels must each be their own card (variant_count==1).
        null_cards = [c for c in cards if c.channel_id in (c_null_1, c_null_2)]
        assert len(null_cards) == 2, "Both NULL-key channels must appear as distinct cards"
        for nc in null_cards:
            assert nc.variant_count == 1, (
                f"NULL-key card should have variant_count=1, got {nc.variant_count}"
            )

    def test_two_distinct_keys_produce_two_cards(self, db):
        """Two different content_keys with 1 variant each → 2 cards."""
        with db.session_scope() as session:
            pid = _provider(session)
            c1 = _channel(session, pid, name="Alpha Movie", detected_quality="HD",
                           content_key="alpha|movie|2020", detected_title="Alpha Movie")
            c2 = _channel(session, pid, name="Beta Movie", detected_quality="HD",
                           content_key="beta|movie|2021", detected_title="Beta Movie")
            _tag(session, c1)
            _tag(session, c2)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
            )

        assert len(cards) == 2
        for card in cards:
            assert card.variant_count == 1


# ---------------------------------------------------------------------------
# Count with collapse_variants
# ---------------------------------------------------------------------------

class TestCollapseCount:
    """Invariants 5–6: count agrees with collapsed card list; False is unchanged."""

    def test_count_collapse_true_returns_distinct_key_count(self, db):
        """count(..., collapse_variants=True) == distinct content_key count."""
        with db.session_scope() as session:
            pid = _provider(session)
            # Group of 3 variants sharing one key
            key = "dark star|movie|2017"
            for q in ("4K", "HD", None):
                cid = _channel(session, pid, name=f"{q or 'SD'} Dark Star",
                                detected_quality=q, content_key=key,
                                detected_title="Dark Star")
                _tag(session, cid)
            # 2 distinct single-variant channels
            for title in ("Alpha Movie", "Beta Movie"):
                cid = _channel(session, pid, name=title, content_key=f"{title.lower()}|movie|",
                                detected_title=title)
                _tag(session, cid)
            # 1 NULL-key channel
            c_null = _channel(session, pid, name="Unknown Film", content_key=None,
                               detected_title="Unknown Film")
            _tag(session, c_null)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            collapsed = repos.tags.count_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
            )
            raw = repos.tags.count_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=False,
            )

        # Raw: 3 + 2 + 1 = 6 channels
        assert raw == 6, f"Expected raw count=6, got {raw}"
        # Collapsed: 1 (dark star group) + 2 (alpha, beta) + 1 (null singleton) = 4
        assert collapsed == 4, f"Expected collapsed count=4, got {collapsed}"

    def test_count_collapse_false_unchanged(self, db):
        """collapse_variants=False returns raw channel count (no regression)."""
        with db.session_scope() as session:
            pid = _provider(session)
            key = "alpha|movie|2020"
            for i in range(5):
                cid = _channel(session, pid, name=f"Alpha variant {i}",
                                content_key=key, detected_title="Alpha Movie")
                _tag(session, cid)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            count = repos.tags.count_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=False,
            )

        assert count == 5, f"Expected raw count=5, got {count}"


# ---------------------------------------------------------------------------
# Paging stability and name_filter
# ---------------------------------------------------------------------------

class TestCollapsePaging:
    """Invariants 7–8: stable alphabetical paging + name_filter narrows before collapse."""

    def test_paging_is_stable_no_overlap_no_gap(self, db):
        """offset/limit over collapsed set returns disjoint, gap-free alphabetical cards."""
        with db.session_scope() as session:
            pid = _provider(session)
            # 6 distinct productions (2 variants each) → 6 collapsed groups
            titles = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
            for t in titles:
                key = f"{t.lower()}|movie|"
                for q in ("HD", None):
                    cid = _channel(session, pid, name=f"{q or 'SD'} {t}",
                                    content_key=key, detected_title=t,
                                    detected_quality=q)
                    _tag(session, cid)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            # Fetch in two pages of 3
            page1 = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
                limit=3,
                offset=0,
            )
            page2 = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
                limit=3,
                offset=3,
            )

        assert len(page1) == 3
        assert len(page2) == 3

        ids_p1 = {c.channel_id for c in page1}
        ids_p2 = {c.channel_id for c in page2}
        assert ids_p1.isdisjoint(ids_p2), "Pages must be disjoint (no overlap)"

        # Combined = all 6 distinct productions
        all_titles = sorted([c.title for c in page1 + page2])
        expected = sorted(titles)
        assert all_titles == expected, (
            f"Pages don't cover all titles. Got {all_titles}, expected {expected}"
        )

        # Alphabetical order: page1 first 3 must come before page2's first
        combined_titles = [c.title for c in page1 + page2]
        assert combined_titles == sorted(combined_titles, key=str.upper), (
            f"Combined pages must be in alphabetical order; got {combined_titles}"
        )

    def test_name_filter_narrows_before_collapse(self, db):
        """name_filter applied before collapse → only matching titles in result."""
        with db.session_scope() as session:
            pid = _provider(session)
            # 3 matching titles (contain "Dark") × 2 variants each
            for t in ("Dark Star", "Dark Knight", "Dark Matter"):
                key = f"{t.lower().replace(' ', '')}|movie|"
                for q in ("HD", None):
                    cid = _channel(session, pid, name=f"{t} {q or 'SD'}",
                                    content_key=key, detected_title=t,
                                    detected_quality=q)
                    _tag(session, cid)
            # 2 non-matching titles × 2 variants
            for t in ("Alpha Movie", "Beta Movie"):
                key = f"{t.lower().replace(' ', '')}|movie|"
                for q in ("HD", None):
                    cid = _channel(session, pid, name=f"{t} {q or 'SD'}",
                                    content_key=key, detected_title=t,
                                    detected_quality=q)
                    _tag(session, cid)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                collapse_variants=True,
                name_filter="Dark",
            )

        assert len(cards) == 3, (
            f"name_filter='Dark' should yield 3 collapsed cards, got {len(cards)}: "
            f"{[c.title for c in cards]}"
        )
        for card in cards:
            assert "dark" in card.title.lower(), (
                f"All cards should contain 'dark' in title; got '{card.title}'"
            )
            # Each "Dark" title has 2 variants → collapsed card variant_count=2
            assert card.variant_count == 2, (
                f"Expected variant_count=2 for '{card.title}', got {card.variant_count}"
            )

    def test_collapse_false_is_backward_compatible(self, db):
        """collapse_variants=False (default) returns all raw channels, not collapsed."""
        with db.session_scope() as session:
            pid = _provider(session)
            key = "dark star|movie|2017"
            for q in ("4K", "HD", None):
                cid = _channel(session, pid, name=f"{q or 'SD'} Dark Star",
                                content_key=key, detected_title="Dark Star",
                                detected_quality=q)
                _tag(session, cid)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            # Default (False) must return all 3 raw channels.
            cards = repos.tags.sample_channels_by_tag_facets(
                {"genre": {"Drama"}},
                # collapse_variants defaults to False
            )

        assert len(cards) == 3, (
            f"collapse_variants=False (default) should return 3 raw channels; got {len(cards)}"
        )
        # All cards have variant_count==1 (the default) since no collapse was applied.
        for card in cards:
            assert card.variant_count == 1


# ---------------------------------------------------------------------------
# ContentCard.variant_count default
# ---------------------------------------------------------------------------

def test_content_card_variant_count_defaults_to_one():
    """ContentCard.variant_count defaults to 1 (no badge shown for single variants)."""
    from metatv.core.discovery_engine import ContentCard
    card = ContentCard(
        channel_id="ch-1",
        title="Test",
        media_type="movie",
        thumbnail_url=None,
        rating=None,
        year=None,
        genre=None,
    )
    assert card.variant_count == 1
