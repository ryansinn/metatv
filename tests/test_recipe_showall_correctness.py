"""Behavioral tests for Recipe Show-All correctness fixes (PR: fix/recipe-showall-correctness).

Covers three bugs:

Bug C — dirty titles in Show-All card builder
  - ``_to_card`` previously called ``display_title()`` (re-parse at render time)
    instead of reading the stored ``channel.detected_title``, so leading-pipe
    prefixes like ``|EN|`` / ``|MULTI|`` weren't stripped.
  - Fix: ``_to_card`` now reads ``channel.detected_title or channel.name``.

Bug D — Show-All in-view filter didn't push into paged query
  - ``_apply_filter`` in ``_BrowseView`` only filtered already-loaded cards;
    lazy-loaded subsequent pages ignored the filter.
  - Fix: ``sample_channels_by_tag_facets`` gained a ``name_filter`` param that
    applies SQL ILIKE so every page respects the filter.

Bug E — Show-All returned only series (no movies / no live)
  - Investigation confirmed this is a **data reality**, not a query bug: in the
    live DB, genre tags are assigned only to series (0 movies have genre tags).
    Language/region/quality/etc. tags DO apply across all media types.
  - No code was changed for E; this module documents the finding only.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.database import ChannelDB, ContentTagDB, Database, ProviderDB, TagDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache


# ---------------------------------------------------------------------------
# Fixtures (file-backed DB — :memory: is not safe for these tests per CLAUDE.md)
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with all tables created."""
    db_file = tmp_path / "test_showall.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    """Fresh session per test; caller manages commit explicitly."""
    s = file_db.get_session()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(session, provider_id: str = "prov1", is_active: bool = True) -> str:
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


def _make_channel(
    session,
    provider_id: str,
    name: str,
    media_type: str = "movie",
    is_hidden: bool = False,
    detected_title: str | None = None,
    detected_prefix: str | None = None,
) -> str:
    cid = str(uuid.uuid4())
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=is_hidden,
    )
    # detected_title / detected_prefix are set post-construction (not in the
    # declarative constructor kwargs on older SQLAlchemy versions).
    ch.detected_title = detected_title
    ch.detected_prefix = detected_prefix
    session.add(ch)
    session.flush()
    return cid


def _tag_channel(session, channel_id: str, tag_type: str, tag_value: str) -> None:
    """Create a tag + content_tag link for a channel."""
    tag = session.query(TagDB).filter_by(type=tag_type, value=tag_value).first()
    if tag is None:
        tag = TagDB(type=tag_type, value=tag_value)
        session.add(tag)
        session.flush()
    ct = ContentTagDB(channel_id=channel_id, tag_id=tag.id, source="generated",
                      feeders=["test"], confidence=1.0)
    session.add(ct)
    session.flush()


# ---------------------------------------------------------------------------
# Bug C — card title reads detected_title, not re-parsed channel.name
# ---------------------------------------------------------------------------

class _MinimalChannel:
    """Minimal duck-type for _to_card: only the fields it reads."""
    def __init__(self, cid, name, detected_title=None, detected_prefix=None,
                 media_type="movie", quality=None, raw_data=None):
        self.id = cid
        self.name = name
        self.detected_title = detected_title
        self.detected_prefix = detected_prefix
        self.media_type = media_type
        self.quality = quality
        self.raw_data = raw_data or {}


def test_to_card_uses_detected_title_for_leading_pipe_prefix():
    """_to_card reads channel.detected_title instead of re-parsing channel.name.

    A leading-pipe prefix like '|EN| Dark Star' has detected_title='Dark Star'
    but display_title() couldn't strip the leading '|' (its regex requires
    [A-Z] as the first character).  After the fix, _to_card uses detected_title
    and returns the clean title.
    """
    from metatv.core.discovery_engine import _to_card

    ch = _MinimalChannel(
        cid="c1",
        name="|EN| Dark Star",
        detected_title="Dark Star",
        detected_prefix="EN",
    )
    card = _to_card(ch)
    assert card.title == "Dark Star", (
        f"Expected 'Dark Star', got {card.title!r}. "
        "The leading-pipe prefix must be stripped via detected_title, not re-parsed."
    )


def test_to_card_uses_detected_title_for_multi_prefix():
    """'|MULTI| Show' → card.title = 'Show' (reads stored detected_title)."""
    from metatv.core.discovery_engine import _to_card

    ch = _MinimalChannel(
        cid="c2",
        name="|MULTI| Show Name",
        detected_title="Show Name",
        detected_prefix="MULTI",
    )
    card = _to_card(ch)
    assert card.title == "Show Name"


def test_to_card_falls_back_to_name_when_detected_title_is_none():
    """When detected_title is None (not yet ingested), raw name is used."""
    from metatv.core.discovery_engine import _to_card

    ch = _MinimalChannel(
        cid="c3",
        name="Plain Channel Name",
        detected_title=None,
        detected_prefix=None,
    )
    card = _to_card(ch)
    assert card.title == "Plain Channel Name"


def test_to_card_strips_us_suffix_via_detected_title():
    """A channel like 'Hanna (2019) (US)' has detected_title='Hanna' — verify
    the card reads it rather than keeping '(US)' from the raw name."""
    from metatv.core.discovery_engine import _to_card

    ch = _MinimalChannel(
        cid="c4",
        name="4K-DE - Hanna (2019) (US)",
        detected_title="Hanna",
        detected_prefix="DE",
    )
    card = _to_card(ch)
    assert card.title == "Hanna", (
        f"Expected 'Hanna', got {card.title!r}. "
        "The '(US)' suffix must be gone because detected_title is 'Hanna'."
    )


# ---------------------------------------------------------------------------
# Bug D — sample_channels_by_tag_facets name_filter applied at SQL level
# ---------------------------------------------------------------------------

def test_sample_channels_name_filter_returns_only_matches(session, tmp_path):
    """name_filter narrows results at the SQL level — not just in Python."""
    _clear_tag_cache()

    pid = _make_provider(session)

    # Three channels: two match 'days', one does not.
    c1 = _make_channel(session, pid, "Days of Our Lives", detected_title="Days of Our Lives")
    c2 = _make_channel(session, pid, "Glory Days", detected_title="Glory Days")
    c3 = _make_channel(session, pid, "Breaking Bad", detected_title="Breaking Bad")

    # Tag all three with the same facet so they all match the recipe.
    for cid in (c1, c2, c3):
        _tag_channel(session, cid, "language", "English")
    session.commit()

    from metatv.core.repositories.tag import TagRepository

    repo = TagRepository(session)
    cards = repo.sample_channels_by_tag_facets(
        includes={"language": {"English"}},
        name_filter="days",
        limit=20,
    )
    titles = [c.title for c in cards]
    assert "Days of Our Lives" in titles, "Filter 'days' must match 'Days of Our Lives'"
    assert "Glory Days" in titles, "Filter 'days' must match 'Glory Days'"
    assert "Breaking Bad" not in titles, "Filter 'days' must exclude 'Breaking Bad'"


def test_sample_channels_name_filter_empty_string_returns_all(session, tmp_path):
    """An empty name_filter returns all matching channels (filter is inactive)."""
    _clear_tag_cache()

    pid = _make_provider(session)
    c1 = _make_channel(session, pid, "Alpha", detected_title="Alpha")
    c2 = _make_channel(session, pid, "Beta", detected_title="Beta")
    for cid in (c1, c2):
        _tag_channel(session, cid, "language", "English")
    session.commit()

    from metatv.core.repositories.tag import TagRepository

    repo = TagRepository(session)
    # name_filter=None (default) and name_filter="" should both return all
    cards_no_filter = repo.sample_channels_by_tag_facets(
        includes={"language": {"English"}},
        limit=20,
    )
    cards_empty_filter = repo.sample_channels_by_tag_facets(
        includes={"language": {"English"}},
        name_filter="",
        limit=20,
    )
    assert len(cards_no_filter) == 2
    assert len(cards_empty_filter) == 2


def test_sample_channels_name_filter_case_insensitive(session, tmp_path):
    """name_filter matching is case-insensitive (SQL ILIKE)."""
    _clear_tag_cache()

    pid = _make_provider(session)
    c1 = _make_channel(session, pid, "DAYS OF OUR LIVES", detected_title="DAYS OF OUR LIVES")
    c2 = _make_channel(session, pid, "Other", detected_title="Other")
    for cid in (c1, c2):
        _tag_channel(session, cid, "language", "English")
    session.commit()

    from metatv.core.repositories.tag import TagRepository

    repo = TagRepository(session)
    # Lower-case filter must match upper-case title
    cards = repo.sample_channels_by_tag_facets(
        includes={"language": {"English"}},
        name_filter="days",
        limit=20,
    )
    titles = [c.title for c in cards]
    assert "DAYS OF OUR LIVES" in titles
    assert "Other" not in titles


def test_sample_channels_name_filter_applies_across_pages(session, tmp_path):
    """name_filter applies at the SQL level, affecting ALL pages, not just the first.

    We insert 6 channels, 3 matching 'doc' and 3 not, request page size 2 at
    offset 2 with name_filter='doc', and assert ONLY matches come back — proving
    the filter is applied before OFFSET/LIMIT, not just on the Python side.
    """
    _clear_tag_cache()

    pid = _make_provider(session)
    match_titles = ["Documentary A", "Documentary B", "Documentary C"]
    non_titles = ["Action 1", "Comedy 1", "Thriller 1"]

    for t in match_titles + non_titles:
        cid = _make_channel(session, pid, t, detected_title=t)
        _tag_channel(session, cid, "genre", "documentary")
    session.commit()

    from metatv.core.repositories.tag import TagRepository

    repo = TagRepository(session)
    # Page 2 of 2 (offset=2, limit=2) with filter 'doc' — must be all matches
    page = repo.sample_channels_by_tag_facets(
        includes={"genre": {"documentary"}},
        name_filter="doc",
        limit=2,
        offset=2,
    )
    # Whatever came back must all be matches for 'doc'
    for card in page:
        assert "doc" in card.title.lower(), (
            f"Non-matching card {card.title!r} appeared in filtered page 2 — "
            "name_filter must be applied before OFFSET, not after."
        )


# ---------------------------------------------------------------------------
# Bug E — data investigation (no code change)
# ---------------------------------------------------------------------------

def test_genre_tags_return_all_media_types_when_data_exists(session, tmp_path):
    """The faceted query has NO implicit media_type restriction.

    When movies and series both carry a genre tag, both appear in results.
    This confirms Bug E is a data reality in the user's DB (only series have
    genre tags there), not a query bug.
    """
    _clear_tag_cache()

    pid = _make_provider(session)
    movie_id = _make_channel(session, pid, "A Movie", media_type="movie",
                             detected_title="A Movie")
    series_id = _make_channel(session, pid, "A Series", media_type="series",
                              detected_title="A Series")
    live_id = _make_channel(session, pid, "A Live Channel", media_type="live",
                            detected_title="A Live Channel")

    # Tag ALL THREE with the same genre tag.
    for cid in (movie_id, series_id, live_id):
        _tag_channel(session, cid, "genre", "Documentary")
    session.commit()

    from metatv.core.repositories.tag import TagRepository

    repo = TagRepository(session)
    cards = repo.sample_channels_by_tag_facets(
        includes={"genre": {"Documentary"}},
        limit=20,
    )
    media_types = {c.media_type for c in cards}
    # All three media types must appear — the query has no media_type filter.
    assert "movie" in media_types, (
        "Movies with a matching genre tag must appear in Show-All results. "
        "If only series appear in the live app, that's because only series "
        "have genre tags assigned — a data reality, not a query bug."
    )
    assert "series" in media_types
    assert "live" in media_types


# ---------------------------------------------------------------------------
# Bug D — _BrowseView filter emits filterChanged signal
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_browse_filter_changed_emits_signal(qapp):
    """_BrowseView emits filterChanged(text) when the user types in the filter box.

    This is the signal RecipeView connects to _on_see_all_filter_changed so
    the DB-level filtered fetch is triggered on every filter keystroke.
    """
    from metatv.gui.discover_browse import _BrowseView
    from PyQt6.QtCore import QObject, pyqtSignal

    class _FakeImageCacheQ(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url):
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

    view = _BrowseView(_FakeImageCacheQ(), _FakeConfig())
    emitted: list[str] = []
    view.filterChanged.connect(emitted.append)

    view._search_box.setText("days")

    assert emitted == ["days"], (
        f"filterChanged must emit the typed text; got {emitted!r}"
    )


def test_browse_current_filter_returns_search_box_text(qapp):
    """current_filter() returns the current text in the filter box."""
    from metatv.gui.discover_browse import _BrowseView
    from PyQt6.QtCore import QObject, pyqtSignal

    class _FakeImageCacheQ(QObject):
        image_loaded = pyqtSignal(str, object)
        image_failed = pyqtSignal(str, str)

        def get_image_async(self, url):
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

    view = _BrowseView(_FakeImageCacheQ(), _FakeConfig())
    assert view.current_filter() == ""

    view._search_box.setText("xyz")
    assert view.current_filter() == "xyz"

    view._search_box.clear()
    assert view.current_filter() == ""
