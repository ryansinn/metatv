"""Behavioral tests for detected_region coverage at ingestion.

Pins the fill-empty-only fallbacks added to
``ChannelRepository.update_detected_prefixes`` so a region surfaces as the
list-row left ``[XX]`` chip even when the channel NAME carries no region token:

1. **Own provider-category code** — a row whose name lacks a region but whose
   ``category`` is an explicit bracketed code (e.g. ``"|FR|"``) gets
   ``detected_region == "FR"`` (reusing the tag_decomposer region extraction).
2. **Bare "XX| REST" category code** (#582) — a DIFFERENT provider convention
   with no leading pipe (e.g. ``"AR| BEIN SPORTS NX"``), covering codes step 1
   misses because ``CODE_FACETS`` classifies them as language-only (``AR`` =
   Arabic, never a region facet — #138). Via
   :func:`~metatv.core.channel_name_utils.split_category_prefix`, which ALSO
   fills ``detected_prefix`` — the field Global Exclusions checks first.
3. **content_key sibling propagation** — a still-empty row inherits a region
   from a sibling sharing its (real) ``content_key``.

Precedence is fill-empty-only and NEVER overwrites: name > own category >
sibling.  Sibling disagreements resolve to the most-common region, ties broken
alphabetically.

Also asserts ``channel_list_model`` composes the ``[FR]`` left chip once the
column is populated, and that user-curated data is untouched.

All DB tests use a file-backed (tmp_path) SQLite DB per CLAUDE.md — not
:memory:, whose pooled connections each get an empty schema.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.channel_name_utils import split_category_prefix


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(
    session,
    *,
    name: str,
    category: str = "",
    provider_id: str = "p1",
    media_type: str = "movie",
    is_favorite: bool = False,
    user_category: str | None = None,
) -> str:
    """Insert a minimal ChannelDB row (category included) and return its id."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            category=category,
            media_type=media_type,
            is_favorite=is_favorite,
            user_category=user_category,
        )
    )
    return cid


def _region_of(db, cid: str) -> str | None:
    from metatv.core.database import ChannelDB

    with db.session_scope(commit=False) as session:
        return session.query(ChannelDB.detected_region).filter_by(id=cid).scalar()


def _prefix_of(db, cid: str) -> str | None:
    from metatv.core.database import ChannelDB

    with db.session_scope(commit=False) as session:
        return session.query(ChannelDB.detected_prefix).filter_by(id=cid).scalar()


def _run(db, **kwargs) -> None:
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes(**kwargs)


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables and migrations applied."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 1. Own provider-category code fills an empty region  (+ list chip appears)
# ---------------------------------------------------------------------------


def test_category_code_fills_empty_region(db):
    """A name with no region but a ``|FR|`` category yields detected_region == 'FR'."""
    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="No Chains No Masters",  # no region token in the name
            category="|FR|",
            media_type="movie",
        )

    _run(db)

    assert _region_of(db, cid) == "FR", (
        "An empty name-region must be filled from the explicit |FR| provider category"
    )


def test_filled_region_renders_left_chip(db, qapp):
    """Once detected_region is populated, channel_list_model composes a [FR] left chip."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories.dtos import ChannelListDTO
    from metatv.gui.channel_list_model import ChannelListModel

    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="No Chains No Masters",
            category="|FR|",
            media_type="movie",
        )

    _run(db)

    # Build the list DTO the model consumes from the ingested row.
    with db.session_scope(commit=False) as session:
        ch = session.query(ChannelDB).filter_by(id=cid).one()
        dto = ChannelListDTO.from_orm(ch)

    assert dto.detected_region == "FR"
    model = ChannelListModel()
    text = model._compose_display_text(dto)
    assert "[FR]" in text, (
        f"Model must compose the [FR] left chip from detected_region; got {text!r}"
    )


def test_free_text_category_yields_no_region(db):
    """A free-text category word ('Action') must NOT invent a region."""
    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="Some Plain Title",
            category="Action",
            media_type="movie",
        )

    _run(db)

    assert _region_of(db, cid) is None, (
        "Region must come only from an explicit code, never a free-text category word"
    )


# ---------------------------------------------------------------------------
# 2. Own category beats a disagreeing sibling
# ---------------------------------------------------------------------------


def test_own_category_beats_sibling(db):
    """Two same-content_key rows each keep their OWN category's region code."""
    # Same title/media/year → same content_key; different category codes.
    with db.session_scope() as session:
        cid_fr = _make_channel(session, name="Shared Title (2020)", category="|FR|")
        cid_de = _make_channel(session, name="Shared Title (2020)", category="|DE|")

    _run(db)

    assert _region_of(db, cid_fr) == "FR", "Row keeps its own |FR| code, not the sibling's"
    assert _region_of(db, cid_de) == "DE", "Row keeps its own |DE| code, not the sibling's"


# ---------------------------------------------------------------------------
# 3. A name-derived region is never overwritten by category OR sibling
# ---------------------------------------------------------------------------


def test_name_region_not_overwritten(db):
    """Name region 'US' survives despite a |FR| category and a |DE| sibling."""
    with db.session_scope() as session:
        # Name carries a trailing (US) qualifier → detected_region from the name.
        cid_named = _make_channel(session, name="Hero (US)", category="|FR|", media_type="movie")
        # Sibling shares content_key ("hero|movie|") and carries a different region.
        cid_sibling = _make_channel(session, name="Hero", category="|DE|", media_type="movie")

    _run(db)

    assert _region_of(db, cid_named) == "US", (
        "Name-derived region must win over both the |FR| category and the |DE| sibling"
    )
    # Sanity: the sibling still got its own category code.
    assert _region_of(db, cid_sibling) == "DE"


# ---------------------------------------------------------------------------
# 4. Sibling propagation fills only when name AND category lack a region
# ---------------------------------------------------------------------------


def test_sibling_propagation_fills_empty(db):
    """An empty row (no name/category region) inherits a same-content_key sibling's region."""
    with db.session_scope() as session:
        # Empty: no region in name, free-text category.
        cid_empty = _make_channel(
            session, name="Mystery Title (2019)", category="Drama", media_type="movie"
        )
        # Sibling shares content_key and carries a region via its category.
        cid_region = _make_channel(
            session, name="Mystery Title (2019)", category="|FR|", media_type="movie"
        )

    _run(db)

    assert _region_of(db, cid_region) == "FR"
    assert _region_of(db, cid_empty) == "FR", (
        "Empty row must inherit the region from its same-content_key sibling"
    )


def test_sibling_disagreement_resolves_most_common_then_alpha(db):
    """When siblings disagree, the most-common region wins; ties break alphabetically."""
    with db.session_scope() as session:
        # Three same-content_key rows carry a region (2× DE, 1× FR via category);
        # one empty row must inherit the most common (DE).
        _make_channel(session, name="Tied Show (2021)", category="|DE|")
        _make_channel(session, name="Tied Show (2021)", category="|DE|")
        _make_channel(session, name="Tied Show (2021)", category="|FR|")
        cid_empty = _make_channel(session, name="Tied Show (2021)", category="Drama")

    _run(db)

    assert _region_of(db, cid_empty) == "DE", (
        "Most-common sibling region (DE: 2 vs FR: 1) must win"
    )


# ---------------------------------------------------------------------------
# 5. No cross-content_key contamination
# ---------------------------------------------------------------------------


def test_no_cross_content_key_contamination(db):
    """An empty row stays empty when no SAME-content_key sibling has a region."""
    with db.session_scope() as session:
        # Different titles → different content_keys.
        cid_empty = _make_channel(session, name="Alpha Movie (2001)", category="", media_type="movie")
        cid_other = _make_channel(session, name="Beta Movie (2002)", category="|FR|", media_type="movie")

    _run(db)

    assert _region_of(db, cid_other) == "FR"
    assert _region_of(db, cid_empty) is None, (
        "A region must never leak across different content_keys"
    )


# ---------------------------------------------------------------------------
# 6. User-curated data is untouched by the region fills
# ---------------------------------------------------------------------------


def test_user_curated_data_untouched(db):
    """The fills write only detected_region; favorite + user_category survive."""
    from metatv.core.database import ChannelDB

    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="Curated Pick",
            category="|FR|",
            media_type="movie",
            is_favorite=True,
            user_category="My Shelf",
        )

    _run(db)

    with db.session_scope(commit=False) as session:
        ch = session.query(ChannelDB).filter_by(id=cid).one()
        assert ch.detected_region == "FR", "Region still fills from the category"
        assert ch.is_favorite is True, "User favorite flag must be preserved"
        assert ch.user_category == "My Shelf", "User-curated category must be preserved"


# ---------------------------------------------------------------------------
# 7. split_category_prefix — pure function (channel_name_utils.py)
# ---------------------------------------------------------------------------


class TestSplitCategoryPrefix:
    """A bare 'XX| REST' category (no leading pipe) splits into a validated
    region code plus the trimmed remainder — distinct from parse_category_marker's
    '|XX| REST' (leading-pipe) shape."""

    def test_two_letter_code_splits(self):
        assert split_category_prefix("AR| BEIN SPORTS NX") == ("AR", "BEIN SPORTS NX")

    def test_two_letter_code_splits_us(self):
        assert split_category_prefix("US| FLO NETWORK") == ("US", "FLO NETWORK")

    def test_three_letter_alias_normalizes(self):
        # "USA" is an alias for "US" (normalize_region_code) — the returned
        # code is the NORMALIZED form, not the raw provider token.
        assert split_category_prefix("USA| FLO SPORTS") == ("US", "FLO SPORTS")

    def test_non_region_leading_token_yields_no_code(self):
        # No pipe at all: the whole string is the remainder, no region guessed.
        code, rest = split_category_prefix("4K UHD 3840P")
        assert code is None
        assert rest == "4K UHD 3840P"

    def test_non_region_token_before_pipe_yields_no_code(self):
        # A quality/format token before a pipe must not be mistaken for a region.
        code, rest = split_category_prefix("RAW| Some Feed")
        assert code is None
        assert rest == "Some Feed"

    def test_empty_category_returns_none_none(self):
        assert split_category_prefix("") == (None, None)
        assert split_category_prefix(None) == (None, None)


# ---------------------------------------------------------------------------
# 8. Bare "XX| REST" category (no leading pipe) fills BOTH detected_prefix
#    and detected_region at ingestion — #582
# ---------------------------------------------------------------------------


def test_bare_category_code_fills_prefix_and_region(db):
    """A beIN-style category with no leading pipe fills detected_prefix."""
    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="BEIN SPORTS ENGLISH 1",  # no region/prefix token in the name
            category="AR| BEIN SPORTS NX",
            media_type="live",
        )

    _run(db)

    assert _prefix_of(db, cid) == "AR", (
        "A bare 'AR| REST' category must fill detected_prefix when the name yields none"
    )
    assert _region_of(db, cid) == "AR", "detected_region is also filled from the same code"


def test_name_prefix_wins_over_bare_category_code(db):
    """A channel's own name-derived prefix is NEVER overwritten by the category."""
    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="UK| SKY SPORTS F1",  # name carries its own prefix
            category="AR| BEIN SPORTS NX",
            media_type="live",
        )

    _run(db)

    assert _prefix_of(db, cid) == "UK", (
        "The channel's own name-derived prefix must win over the category's code"
    )


def test_non_region_category_token_stays_null(db):
    """A category whose leading token isn't a known region never invents one."""
    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="Some Random Channel",
            category="4K UHD 3840P",
            media_type="live",
        )

    _run(db)

    assert _prefix_of(db, cid) is None
    assert _region_of(db, cid) is None


def test_bare_category_fill_excluded_by_visibility_scope(db):
    """Integration: once the category fill runs, Global Exclusions on 'AR'
    hides the beIN row via channel_visibility.apply() — closing the leak
    where a channel's region lived only in its category, never its name."""
    from metatv.core.channel_visibility import VisibilityScope, apply as apply_visibility
    from metatv.core.database import ChannelDB

    with db.session_scope() as session:
        cid_bein = _make_channel(
            session,
            name="BEIN SPORTS ENGLISH 1",
            category="AR| BEIN SPORTS NX",
            media_type="live",
        )
        cid_other = _make_channel(
            session,
            name="Some Unrelated Channel",
            category="US| FLO NETWORK",
            media_type="live",
        )

    _run(db)

    with db.session_scope(commit=False) as session:
        scope = VisibilityScope(excluded_prefixes={"AR"})
        result_ids = {
            row.id for row in apply_visibility(session.query(ChannelDB), scope).all()
        }

    assert cid_bein not in result_ids, (
        "A channel whose region lived only in its category must be excluded "
        "once AR is in the user's Global Exclusions"
    )
    assert cid_other in result_ids, "An unrelated (US) channel must remain visible"
