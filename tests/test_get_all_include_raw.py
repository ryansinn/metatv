"""Behavioral tests for ``ChannelRepository.get_all(include_raw=...)`` (DB-3 follow-up, #762).

``get_all()`` has deferred ``raw_data`` unconditionally since #618 (measured -29%
wall clock / -25% peak memory on the analogous ``preference_engine`` query). DB-4
landed ``detected_rating``/``detected_added`` as stored columns, removing the last
reason any current caller would need the blob — this slice makes that opt-in
explicit via ``include_raw=False`` (default) / ``True``, so a FUTURE caller that
does need ``.raw_data`` has a real lever instead of silently eating a per-row N+1.

Both tests drive a real file-backed ``Database`` on ``tmp_path`` (never
``:memory:``, per CLAUDE.md) with a real 500-row corpus whose ``raw_data`` is a
non-trivial JSON blob, and capture the actual emitted SQL via the shared
``capture_sql_statements`` helper (``tests/conftest.py``) rather than asserting on
parsed data or mocked internals.

1. ``test_...`` drives the REAL caller path (``_ChannelListMixin._query_channels``,
   the worker ``main_window_channels.py``'s channel-list load runs off-thread) and
   proves: the emitted SELECT never mentions ``raw_data``; the statement count does
   not scale with corpus size (5 rows vs 500 — no N+1); and the DTOs it returns can
   be read after the session that produced them has closed with no
   ``DetachedInstanceError`` (they are frozen dataclasses, never ORM rows crossing
   the boundary — a regression here is exactly the failure mode CLAUDE.md's
   ORM-to-DTO-boundary rule exists to prevent).
2. ``test_...`` drives ``ChannelRepository.get_all(include_raw=True)`` directly and
   proves ``raw_data`` DOES appear in the one emitted SELECT, with no additional
   statement fired when the returned rows' ``.raw_data`` is read afterward (still
   inside the session) — proving it was loaded eagerly, not merely left available
   for a transparent lazy load.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.channel import ChannelRepository
from metatv.gui.main_window_channels import _ChannelListMixin
from tests.conftest import capture_sql_statements


def _sizeable_raw_data(i: int) -> dict:
    """~1 KB of realistic provider payload — big enough that an accidental
    per-row load would be measurable, not just structurally present."""
    return {
        "tmdb": i,
        "genre": "Drama",
        "plot": "A very long provider-supplied synopsis. " * 20,
        "cast": [f"Actor {n}" for n in range(10)],
        "rating": "7.5",
        "added": "1690000000",
    }


@pytest.fixture()
def file_db(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'get_all_include_raw.db'}")
    db.create_tables()
    yield db
    db.close()


def _seed_channels(session, n: int, *, provider_id: str = "p1", start: int = 0) -> None:
    for i in range(start, start + n):
        session.add(ChannelDB(
            id=str(uuid.uuid4()), source_id=f"s{i}", provider_id=provider_id,
            name=f"Channel {i}", media_type="movie",
            raw_data=_sizeable_raw_data(i),
        ))


def _params(**overrides) -> dict:
    """A full params dict shaped like ``load_channels`` builds for a normal load
    (mirrors ``test_filter_transparency.py``'s ``_params`` — same real caller)."""
    base = {
        "provider_id": None,
        "media_types": ["live", "movie", "series"],
        "language_prefixes": None,
        "region_prefixes": None,
        "quality_prefixes": None,
        "platform_prefixes": None,
        "genre_filters": None,
        "invert_prefix_filters": False,
        "include_untagged": True,
        "include_untagged_quality": True,
        "adult_mode": "all",
        "force_adult_ids": [],
        "tag_includes": None,
        "source_categories": None,
        "excluded_prefixes": set(),
        "excluded_user_categories": set(),
        "bypass_global_exclusions": False,
        "search_query": None,
        "strict_genre_filter": None,
        "person_filter": None,
        "context_tag_filter": None,
        "context_category_filter": None,
        "context_id_filter": None,
        "id_filter_show_all": False,
        "page_size": 1000,
        "show_provider_icon": False,
        "provider_icon_map": {},
        "given_provider_id": None,
        "hidden_only": False,
        "bypassing_tier1": False,
        "hide_watched": False,
    }
    base.update(overrides)
    return base


def test_real_channel_list_load_defers_raw_data_without_n_plus_1(file_db):
    """The real channel-list load (_query_channels) never selects raw_data, its
    statement count doesn't scale with corpus size, and its DTOs survive the
    session closing — no DetachedInstanceError."""
    session = file_db.get_session()
    session.add(ProviderDB(
        id="p1", name="Test Source", type="xtream", url="http://example",
        is_active=True, account_status="Active",
    ))
    _seed_channels(session, 5)
    session.commit()

    repos = RepositoryFactory(session)
    with capture_sql_statements(file_db.engine) as small_stmts:
        small_dtos, _ = _ChannelListMixin._query_channels(repos, _params())
    assert len(small_dtos) == 5

    _seed_channels(session, 495, start=5)  # corpus is now 500 rows
    session.commit()

    with capture_sql_statements(file_db.engine) as big_stmts:
        big_dtos, _ = _ChannelListMixin._query_channels(repos, _params())
    assert len(big_dtos) == 500

    # get_all()'s OWN list SELECT must never mention raw_data. Excludes the
    # count()-derived statements (repos.channels.count() and the has_adult
    # probe both wrap an UNDEFERRED ChannelDB query as a count(*) subquery,
    # a separate, pre-existing gap logged as REFACTOR_PLAN.md ledger F38 —
    # out of this slice's scope, and not something get_all()'s defer touches).
    list_select_stmts = [
        s for s in big_stmts if not s.strip().upper().startswith("SELECT COUNT")
    ]
    assert not any("raw_data" in s.lower() for s in list_select_stmts), (
        "raw_data must never appear in get_all()'s own emitted SELECT"
    )
    assert len(big_stmts) == len(small_stmts), (
        "statement count must not scale with row count (500 vs 5) — a per-row "
        "raw_data lazy load would show up here as an N+1"
    )

    session.close()  # the session that produced these DTOs is now gone

    # Reading every field the render path touches must not raise
    # DetachedInstanceError — proof no ORM row crossed the boundary.
    for d in big_dtos:
        _ = (d.id, d.name, d.detected_title, d.detected_year, d.plot, d.poster_url,
             d.content_key, d.variant_count)


def test_get_all_include_raw_true_loads_raw_data_in_the_one_select(file_db):
    """include_raw=True puts raw_data in the SAME single SELECT, loaded eagerly
    (not left for a transparent per-row lazy load)."""
    session = file_db.get_session()
    session.add(ProviderDB(
        id="p1", name="Test Source", type="xtream", url="http://example",
        is_active=True, account_status="Active",
    ))
    _seed_channels(session, 500)
    session.commit()

    repo = ChannelRepository(session)
    with capture_sql_statements(file_db.engine) as stmts:
        rows = repo.get_all(limit=1000, include_raw=True)
        assert len(rows) == 500
        before = len(stmts)
        # Touching .raw_data must fire ZERO additional statements — it was
        # already materialized by the one SELECT above.
        touched = [r.raw_data for r in rows]
    assert len(stmts) == before, "reading .raw_data fired an extra query — not eager"
    assert all(t is not None and t.get("genre") == "Drama" for t in touched)
    assert any("raw_data" in s.lower() for s in stmts), (
        "include_raw=True must select raw_data in the emitted SQL"
    )
    session.close()
