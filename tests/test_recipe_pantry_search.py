"""Behavioral tests for the Pantry cross-facet tag search (feature #101).

Two halves, both proving the changed path (per CLAUDE.md tests rule):

1. Repository — TagRepository.search_tag_values_across_facets() on a REAL
   file-backed Database: a case-insensitive substring search over tag VALUES
   spanning multiple facets, scoped so hidden-provider rows don't count.

2. View/cloud — RecipeView wiring: a non-empty Pantry search drives the center
   WeightedTagCloud with multi-facet matches (color-coded by facet) and sets a
   "·N" match badge on each left facet row; clicking a matched tag adds the
   ingredient under ITS OWN facet (not the selected one); an empty search clears
   the badges.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from metatv.core.database import ChannelDB, ProviderDB, Database
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import TagSearchResultDTO


# ===========================================================================
# Part 1 — Repository: search_tag_values_across_facets (real file DB)
# ===========================================================================

@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created (NOT :memory:)."""
    db_file = tmp_path / "test_pantry_search.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    s = file_db.get_session()
    yield s
    s.close()


def _make_provider(session, provider_id: str, is_active: bool = True) -> str:
    p = ProviderDB(
        id=provider_id,
        name=f"Provider {provider_id}",
        type="xtream",
        url="http://example.com",
        username="u",
        password="p",
        is_active=is_active,
    )
    session.add(p)
    session.flush()
    return p.id


def _make_channel(session, provider_id: str, is_hidden: bool = False) -> str:
    cid = str(uuid.uuid4())
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=f"Channel {cid[:8]}",
        is_hidden=is_hidden,
    )
    session.add(ch)
    session.flush()
    return cid


def _tag(session, channel_id: str, facet_type: str, value: str) -> None:
    repos = RepositoryFactory(session)
    repos.tags.set_content_tags(channel_id, [(facet_type, value, "test_feeder")])
    session.flush()


def _seed(session):
    """Seed a corpus spanning genre + collection facets across two providers."""
    p_active = _make_provider(session, "p_active", is_active=True)
    p_hidden = _make_provider(session, "p_hidden", is_active=False)  # inactive → hidden

    # genre "Comedy" — 3 active channels (matches "com")
    for _ in range(3):
        _tag(session, _make_channel(session, p_active), "genre", "Comedy")
    # genre "Dark Comedy" — 1 active channel (matches "com")
    _tag(session, _make_channel(session, p_active), "genre", "Dark Comedy")
    # genre "Drama" — 2 active channels (does NOT match "com")
    for _ in range(2):
        _tag(session, _make_channel(session, p_active), "genre", "Drama")
    # collection "Comedy Central" — 1 active channel (matches "com")
    _tag(session, _make_channel(session, p_active), "collection", "Comedy Central")
    # region "FR" — 1 active channel (does NOT match "com")
    _tag(session, _make_channel(session, p_active), "region", "FR")

    # Hidden provider: 5 "Comedy" channels — must NOT count when excluded.
    for _ in range(5):
        _tag(session, _make_channel(session, p_hidden), "genre", "Comedy")

    session.commit()
    return p_hidden


def test_search_returns_cross_facet_matches(session):
    """A substring search returns (facet_type, value, count) groups across facets."""
    _seed(session)
    repos = RepositoryFactory(session)
    hidden = repos.providers.get_hidden_provider_ids()

    results = repos.tags.search_tag_values_across_facets(
        "com", excluded_provider_ids=hidden
    )
    by_pair = {(r.facet_type, r.value): r.channel_count for r in results}

    # The three "com"-bearing values, across two different facets.
    assert by_pair[("genre", "Comedy")] == 3          # hidden provider's 5 excluded
    assert by_pair[("genre", "Dark Comedy")] == 1
    assert by_pair[("collection", "Comedy Central")] == 1
    # Non-matching values must be absent.
    assert ("genre", "Drama") not in by_pair
    assert ("region", "FR") not in by_pair


def test_search_is_case_insensitive(session):
    """Upper/lower/mixed-case queries all match the same values."""
    _seed(session)
    repos = RepositoryFactory(session)
    hidden = repos.providers.get_hidden_provider_ids()

    lower = {(r.facet_type, r.value) for r in
             repos.tags.search_tag_values_across_facets("comedy", excluded_provider_ids=hidden)}
    upper = {(r.facet_type, r.value) for r in
             repos.tags.search_tag_values_across_facets("COMEDY", excluded_provider_ids=hidden)}
    mixed = {(r.facet_type, r.value) for r in
             repos.tags.search_tag_values_across_facets("CoMeDy", excluded_provider_ids=hidden)}

    assert lower == upper == mixed
    assert ("genre", "Comedy") in lower
    assert ("collection", "Comedy Central") in lower


def test_search_excludes_hidden_provider_rows(session):
    """Hidden-provider channels do not contribute to counts when excluded."""
    _seed(session)
    repos = RepositoryFactory(session)
    hidden = repos.providers.get_hidden_provider_ids()

    scoped = {(r.facet_type, r.value): r.channel_count
              for r in repos.tags.search_tag_values_across_facets(
                  "comedy", excluded_provider_ids=hidden)}
    unscoped = {(r.facet_type, r.value): r.channel_count
                for r in repos.tags.search_tag_values_across_facets(
                    "comedy", excluded_provider_ids=None)}

    # Scoped drops the hidden provider's 5 → 3; unscoped includes them → 8.
    assert scoped[("genre", "Comedy")] == 3
    assert unscoped[("genre", "Comedy")] == 8


def test_search_sorted_by_count_desc_and_limit(session):
    """Results are ordered by channel_count DESC and bounded by limit."""
    _seed(session)
    repos = RepositoryFactory(session)
    hidden = repos.providers.get_hidden_provider_ids()

    results = repos.tags.search_tag_values_across_facets(
        "com", excluded_provider_ids=hidden
    )
    counts = [r.channel_count for r in results]
    assert counts == sorted(counts, reverse=True)
    assert results[0].value == "Comedy"   # 3 channels — the most popular match

    # limit caps the number of groups.
    limited = repos.tags.search_tag_values_across_facets(
        "com", excluded_provider_ids=hidden, limit=1
    )
    assert len(limited) == 1


def test_search_empty_query_returns_empty(session):
    """A blank/whitespace query short-circuits to []."""
    _seed(session)
    repos = RepositoryFactory(session)
    assert repos.tags.search_tag_values_across_facets("") == []
    assert repos.tags.search_tag_values_across_facets("   ") == []


def test_search_returns_frozen_dtos(session):
    """Results are frozen TagSearchResultDTO instances (no ORM crosses the boundary)."""
    _seed(session)
    repos = RepositoryFactory(session)
    results = repos.tags.search_tag_values_across_facets("com")
    assert results and all(isinstance(r, TagSearchResultDTO) for r in results)
    with pytest.raises((AttributeError, TypeError)):
        results[0].channel_count = 999  # type: ignore[misc]


# ===========================================================================
# Part 2 — View/cloud wiring (headless Qt)
# ===========================================================================

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@dataclass(frozen=True)
class _FacetSummaryDTO:
    facet_type: str
    distinct_values: int


@dataclass(frozen=True)
class _SearchDTO:
    facet_type: str
    value: str
    channel_count: int


class _FakeSeam:
    """Records _run_query calls; the view's query_fn is invoked separately."""

    def __init__(self):
        self.calls: list[dict] = []

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
        if token_ref is not None:
            token_ref[0] += 1
        self.calls.append(dict(query_fn=query_fn, on_result=on_result,
                               token_ref=token_ref, on_error=on_error))


class _RecordingTags:
    def __init__(self):
        self.search_call: dict | None = None

    def search_tag_values_across_facets(self, query, **kwargs):
        self.search_call = dict(query=query, **kwargs)
        return []


class _RecordingProviders:
    def get_hidden_provider_ids(self):
        return ["prov_hidden"]


class _RecordingRepos:
    def __init__(self):
        self.tags = _RecordingTags()
        self.providers = _RecordingProviders()


def _make_view(qapp):
    from metatv.gui.recipe_view import RecipeView
    from PyQt6.QtCore import QObject, pyqtSignal

    seam = _FakeSeam()

    class _FakeDB:
        pass

    class _FakeConfig:
        discover_zoom = 1.0
        movie_icon = "🎬"
        series_icon = "📺"
        rating_star_icon = "★"
        like_icon = "👍"
        favorite_icon = "❤"
        queue_icon = "▶"
        watched_icon = "✓"
        list_view_icon = "☰"
        grid_view_icon = "▦"
        # _global_exclusion_sets reads these (filter_utils resolvers tolerate them).
        global_filter_paused = True

    class _FakeImageCacheQ(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url):
            pass

    view = RecipeView(
        db=_FakeDB(),
        config=_FakeConfig(),
        run_query_fn=seam._run_query,
        image_cache=_FakeImageCacheQ(),
        parent=None,
    )
    return view, seam


def _load_pantry(view):
    view._on_pantry_loaded([
        _FacetSummaryDTO("genre", 100),
        _FacetSummaryDTO("collection", 20),
        _FacetSummaryDTO("region", 50),
    ])


def test_search_changed_dispatches_cross_facet_query(qapp):
    """A non-empty search runs the new repo method through the async seam."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_search_changed("comedy")

    last = seam.calls[-1]
    assert last["on_result"] == view._on_search_loaded
    # The query_fn calls search_tag_values_across_facets with the query + scoping.
    repos = _RecordingRepos()
    last["query_fn"](repos)
    assert repos.tags.search_call is not None
    assert repos.tags.search_call["query"] == "comedy"
    assert repos.tags.search_call["excluded_provider_ids"] == ["prov_hidden"]


def test_search_loaded_fills_cloud_with_multi_facet_matches(qapp):
    """_on_search_loaded drives the cloud with matches from >1 facet."""
    view, seam = _make_view(qapp)
    view._active = True
    _load_pantry(view)
    view._search_query = "comedy"

    view._on_search_loaded([
        _SearchDTO("genre", "Comedy", 300),
        _SearchDTO("genre", "Dark Comedy", 40),
        _SearchDTO("collection", "Comedy Central", 12),
    ])

    buttons = view._cloud._tag_buttons
    assert len(buttons) == 3
    # The cloud now mixes facets.
    assert {b.facet_type() for b in buttons} == {"genre", "collection"}
    # Header reflects the search term.
    assert "comedy" in view._stage_hdr.text().lower()


def test_search_cloud_colors_tags_by_facet(qapp):
    """Each matched tag renders in its OWN facet color (per-tag, not uniform)."""
    from metatv.gui import theme as _theme

    view, seam = _make_view(qapp)
    view._active = True
    _load_pantry(view)
    view._search_query = "comedy"

    view._on_search_loaded([
        _SearchDTO("genre", "Comedy", 300),
        _SearchDTO("collection", "Comedy Central", 12),
    ])

    by_facet = {b.facet_type(): b for b in view._cloud._tag_buttons}
    assert _theme.COLOR_FACET_GENRE in by_facet["genre"].styleSheet()
    assert _theme.COLOR_FACET_COLLECTION in by_facet["collection"].styleSheet()


def test_search_sets_per_facet_badges(qapp):
    """Each left facet row gets a "·N" badge = matching values in that facet."""
    view, seam = _make_view(qapp)
    view._active = True
    _load_pantry(view)
    view._search_query = "comedy"

    view._on_search_loaded([
        _SearchDTO("genre", "Comedy", 300),
        _SearchDTO("genre", "Dark Comedy", 40),
        _SearchDTO("collection", "Comedy Central", 12),
    ])

    badges = {b.facet_type: b._match_count for b in view._pantry._facet_buttons}
    assert badges["genre"] == 2
    assert badges["collection"] == 1
    assert badges["region"] == 0
    # The badge text actually shows on the matching rows.
    genre_btn = next(b for b in view._pantry._facet_buttons if b.facet_type == "genre")
    assert "·2" in genre_btn.text()


def test_empty_search_clears_badges_and_restores(qapp):
    """Clearing the search drops badges and resets the search state."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_pantry(view)
    view._search_query = "comedy"
    view._on_search_loaded([_SearchDTO("genre", "Comedy", 300)])
    assert any(b._match_count for b in view._pantry._facet_buttons)

    view._on_search_changed("")

    assert view._search_query == ""
    assert all(b._match_count == 0 for b in view._pantry._facet_buttons)


def test_search_tag_click_adds_under_its_own_facet(qapp):
    """Clicking a matched tag adds it under the tag's facet, not the selected one."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"   # deliberately DIFFERENT from the clicked facet
    _load_pantry(view)
    view._search_query = "comedy"
    view._on_search_loaded([_SearchDTO("collection", "Comedy Central", 12)])

    # Click the (only) matched tag in the cloud.
    view._cloud._tag_buttons[0].click()

    assert "Comedy Central" in view.recipe_includes.get("collection", set())
    # It must NOT have been mis-filed under the selected facet.
    assert "Comedy Central" not in view.recipe_includes.get("genre", set())


def test_search_tag_click_reflects_include_mark(qapp):
    """After clicking, the search cloud re-renders the tag with its include mark."""
    from metatv.gui import icons as _icons

    view, seam = _make_view(qapp)
    view._active = True
    _load_pantry(view)
    view._search_query = "comedy"
    view._on_search_loaded([_SearchDTO("genre", "Comedy", 300)])

    view._cloud._tag_buttons[0].click()  # none → include

    # The re-rendered button shows the include icon.
    assert _icons.tag_include_icon in view._cloud._tag_buttons[0].text()


def test_search_loaded_ignored_when_query_cleared(qapp):
    """A late search result that arrives after the box was cleared does not repaint."""
    view, seam = _make_view(qapp)
    view._active = True
    _load_pantry(view)
    view._search_query = ""   # user already cleared the box

    view._on_search_loaded([_SearchDTO("genre", "Comedy", 300)])

    # No badges, no cloud buttons painted from the stale result.
    assert all(b._match_count == 0 for b in view._pantry._facet_buttons)
    assert view._cloud._tag_buttons == []
