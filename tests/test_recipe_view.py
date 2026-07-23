"""Behavioral tests for RecipeView (task #56 slice 3).

These tests exercise the main-thread result slots directly — the "half that
regresses" per CLAUDE.md. The DB worker half (_load_pantry / _load_cloud /
_load_results) is trivial; what matters is how the view processes delivered
results and what state it exposes.

Coverage:
  - Pantry sidebar populates when facet summaries are delivered.
  - Selecting a facet fires a cloud load.
  - Tag click (none→include→exclude→none) cycles correctly.
  - Include ingredient adds to the correct role group in the recipe rail.
  - Exclude ingredient shows in the OMIT section.
  - _on_results_loaded updates the Now Plating strip + YIELDS.
  - clear_recipe() empties includes, excludes, and YIELDS.
  - Ingredient remove via rail chip removes from recipe state.
  - _generate_recipe_name returns a non-empty string with and without genres.
  - on_activate / on_deactivate flip _active flag.
  - Facet color token look-up returns correct theme constant.
  - Theme tokens COLOR_FACET_* are non-empty and distinct.
  - Icons recipe_* are all defined and non-empty.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Module-level qapp fixture (headless Qt)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Fake _run_query seam
# ---------------------------------------------------------------------------

class _FakeSeam:
    """Records _run_query calls and supports synchronous delivery in tests."""

    def __init__(self):
        self.calls: list[dict] = []

    def _run_query(
        self,
        query_fn: Callable,
        on_result: Callable,
        *,
        token_ref=None,
        on_error=None,
    ) -> None:
        if token_ref is not None:
            token_ref[0] += 1
        token = token_ref[0] if token_ref is not None else None
        self.calls.append(
            dict(
                query_fn=query_fn,
                on_result=on_result,
                token=token,
                token_ref=token_ref,
                on_error=on_error,
            )
        )

    def deliver_last(self, data: Any, *, stale: bool = False) -> None:
        """Deliver data to the last recorded on_result, optionally as stale."""
        entry = self.calls[-1]
        token_ref = entry["token_ref"]
        token = entry["token"]
        if stale and token_ref is not None:
            # Simulate a superseding call bumping the counter
            token_ref[0] += 1
        if token_ref is None or token_ref[0] == token:
            entry["on_result"](data)

    def deliver_by_callback(self, on_result: Callable, data: Any) -> None:
        """Deliver data to the most recent call whose on_result matches."""
        for entry in reversed(self.calls):
            if entry["on_result"] == on_result:
                entry["on_result"](data)
                return
        raise AssertionError(f"No _run_query call for {on_result!r}")


# ---------------------------------------------------------------------------
# DTOs for test data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _FacetSummaryDTO:
    facet_type: str
    distinct_values: int


@dataclass(frozen=True)
class _TagCountDTO:
    value: str
    channel_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeCard:
    """ContentCard-shaped value object for the Now-Plating strip tests.

    Carries the fields _ContentCard reads at construction; thumbnail_url is None
    so no async poster load is attempted.
    """
    channel_id: str
    title: str
    media_type: str = "movie"
    thumbnail_url: str | None = None
    rating: float | None = None
    year: int | None = None
    genre: str | None = None
    is_favorite: bool = False
    in_queue: bool = False
    already_watched: bool = False
    is_liked: bool = False
    detected_prefix: str | None = None
    progress_fraction: float = 0.0
    variant_count: int = 1


def _make_view(qapp):
    """Create a RecipeView with a fake _run_query seam."""
    from metatv.gui.recipe_view import RecipeView
    from PyQt6.QtCore import QObject, pyqtSignal

    seam = _FakeSeam()

    # Minimal stubs for db and config — RecipeView only uses them for type hints,
    # the actual DB calls go through the seam.
    class _FakeDB:
        pass

    class _FakeConfig:
        # _ContentCard / the strip read these presentation fields at build time.
        discover_zoom = 1.0
        movie_icon = "🎬"
        series_icon = "📺"
        rating_star_icon = "★"
        like_icon = "👍"
        favorite_icon = "❤"
        queue_icon = "▶"
        watched_icon = "✓"
        # _BrowseView (the "Show all" drill-down) reads these at build time.
        list_view_icon = "☰"
        grid_view_icon = "▦"

    class _FakeImageCacheQ(QObject):
        # _ContentCard.request_image() connects to these signals; they never fire
        # because thumbnail_url is None on the test cards.
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


# ---------------------------------------------------------------------------
# Pantry: load_facets populates buttons
# ---------------------------------------------------------------------------

def test_pantry_loads_facets(qapp):
    """After delivering facet summaries, pantry has one button per facet."""
    view, seam = _make_view(qapp)
    view._active = True  # simulate activated

    summaries = [
        _FacetSummaryDTO("genre", 120),
        _FacetSummaryDTO("language", 30),
        _FacetSummaryDTO("region", 75),
    ]
    view._on_pantry_loaded(summaries)

    buttons = view._pantry._facet_buttons
    assert len(buttons) == 3
    assert buttons[0].facet_type == "genre"
    assert buttons[1].facet_type == "language"
    assert buttons[2].facet_type == "region"


def test_pantry_auto_selects_first_facet(qapp):
    """Delivering facet summaries auto-selects the first facet when none was selected."""
    view, seam = _make_view(qapp)
    view._active = True

    summaries = [
        _FacetSummaryDTO("genre", 50),
        _FacetSummaryDTO("decade", 10),
    ]
    view._on_pantry_loaded(summaries)

    # A cloud load should have been submitted for "genre"
    last_call = seam.calls[-1]
    assert last_call["on_result"] == view._on_cloud_loaded


def test_pantry_inactive_view_skips_population(qapp):
    """If the view is not active, _on_pantry_loaded does nothing."""
    view, seam = _make_view(qapp)
    view._active = False

    summaries = [_FacetSummaryDTO("genre", 50)]
    initial_count = len(view._pantry._facet_buttons)
    view._on_pantry_loaded(summaries)

    # Should not have changed because view is inactive
    assert len(view._pantry._facet_buttons) == initial_count


# ---------------------------------------------------------------------------
# Facet selection: clicking a facet triggers a cloud load
# ---------------------------------------------------------------------------

def test_facet_selection_queues_cloud_load(qapp):
    """Selecting a facet emits a _run_query call for the cloud."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_facet_selected("language")

    # A cloud load should have been submitted
    last_call = seam.calls[-1]
    assert last_call["on_result"] == view._on_cloud_loaded
    assert view._selected_facet == "language"


def test_facet_selection_updates_stage_header(qapp):
    """Selecting 'decade' updates the stage header to 'Decade'."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_facet_selected("decade")
    assert "Decade" in view._stage_hdr.text()


# ---------------------------------------------------------------------------
# Tag cycling: none → include → exclude → none
# ---------------------------------------------------------------------------

def _load_cloud_with_counts(view, counts):
    """Helper: deliver tag counts to the view's cloud slot."""
    view._active = True
    view._on_cloud_loaded(counts)


def test_tag_click_none_to_include(qapp):
    """First click on a tag adds it to recipe_includes."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Drama", 1000)])

    view._on_tag_clicked("Drama")

    assert "Drama" in view.recipe_includes.get("genre", set())
    assert "Drama" not in view.recipe_excludes.get("genre", set())


def test_tag_click_include_to_exclude(qapp):
    """Second click on an included tag moves it to excludes."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Drama", 1000)])

    # First click: include
    view._on_tag_clicked("Drama")
    # Second click: exclude
    view._on_tag_clicked("Drama")

    assert "Drama" not in view.recipe_includes.get("genre", set())
    assert "Drama" in view.recipe_excludes.get("genre", set())


def test_tag_click_exclude_to_none(qapp):
    """Third click on an excluded tag removes it from the recipe entirely."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Drama", 1000)])

    view._on_tag_clicked("Drama")  # none → include
    view._on_tag_clicked("Drama")  # include → exclude
    view._on_tag_clicked("Drama")  # exclude → none

    assert "genre" not in view.recipe_includes
    assert "genre" not in view.recipe_excludes


def test_tag_click_clears_empty_facet_entry(qapp):
    """After cycling a tag back to none, the facet key is removed from dicts."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "language"
    _load_cloud_with_counts(view, [_TagCountDTO("English", 500)])

    view._on_tag_clicked("English")  # include
    view._on_tag_clicked("English")  # exclude
    view._on_tag_clicked("English")  # none

    assert "language" not in view.recipe_includes
    assert "language" not in view.recipe_excludes


def test_multiple_tags_same_facet(qapp):
    """Including two tags in the same facet results in a set with two values."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [
        _TagCountDTO("Drama", 1000),
        _TagCountDTO("Comedy", 800),
    ])

    view._on_tag_clicked("Drama")
    view._on_tag_clicked("Comedy")

    inc = view.recipe_includes.get("genre", set())
    assert "Drama" in inc
    assert "Comedy" in inc


def test_include_and_exclude_in_same_facet(qapp):
    """It is valid to include some and exclude other values in the same facet."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [
        _TagCountDTO("Drama", 1000),
        _TagCountDTO("Horror", 300),
    ])

    view._on_tag_clicked("Drama")   # include
    view._on_tag_clicked("Horror")  # include
    view._on_tag_clicked("Horror")  # exclude

    inc = view.recipe_includes.get("genre", set())
    exc = view.recipe_excludes.get("genre", set())
    assert "Drama" in inc
    assert "Horror" in exc
    assert "Horror" not in inc
    assert "Drama" not in exc


# ---------------------------------------------------------------------------
# Results strip and YIELDS
# ---------------------------------------------------------------------------

def test_results_loaded_updates_strip(qapp):
    """_on_results_loaded renders real result cards in the Now Plating strip."""
    view, seam = _make_view(qapp)
    view._active = True

    cards = [
        _FakeCard("c1", "Channel A"),
        _FakeCard("c2", "Channel B"),
        _FakeCard("c3", "Channel C"),
    ]
    view._on_results_loaded((cards, 3))

    # Strip header should mention the match count
    hdr_text = view._now_plating._hdr.text()
    assert "3" in hdr_text
    # One card widget per delivered card.
    assert len(view._now_plating._card_widgets) == 3


def test_results_loaded_inactive_skips(qapp):
    """If the view is inactive, _on_results_loaded does nothing."""
    view, seam = _make_view(qapp)
    view._active = False

    initial_hdr = view._now_plating._hdr.text()
    view._on_results_loaded(([_FakeCard("c1", "Chan X")], 1))
    # Should not have changed
    assert view._now_plating._hdr.text() == initial_hdr
    assert view._now_plating._card_widgets == []


def test_results_loaded_updates_yields(qapp):
    """_on_results_loaded updates the YIELDS label in the recipe rail."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_results_loaded(([_FakeCard("a", "Channel A"), _FakeCard("b", "Channel B")], 42))

    yields_text = view._rail._yields_lbl.text()
    assert "42" in yields_text


def test_results_zero_matches(qapp):
    """_on_results_loaded with 0 matches renders the empty state cleanly."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_results_loaded(([], 0))

    yields_text = view._rail._yields_lbl.text()
    assert "0" in yields_text
    # Empty result: no card widgets, header still shows 0 matches.
    assert view._now_plating._card_widgets == []
    assert "0" in view._now_plating._hdr.text()


def test_card_click_emits_channel_selected(qapp):
    """Single-clicking a result card emits channelSelected(channel_id)."""
    view, seam = _make_view(qapp)
    view._active = True
    captured: list[str] = []
    view.channelSelected.connect(captured.append)

    view._on_results_loaded(([_FakeCard("chan_42", "Pick Me")], 1))
    # Emit the card's clicked signal (what a left-click does).
    view._now_plating._card_widgets[0].clicked.emit("chan_42")

    assert captured == ["chan_42"]


def test_card_double_click_emits_play_requested(qapp):
    """Double-clicking a result card emits playRequested(channel_id)."""
    view, seam = _make_view(qapp)
    view._active = True
    captured: list[str] = []
    view.playRequested.connect(captured.append)

    view._on_results_loaded(([_FakeCard("chan_7", "Play Me")], 1))
    view._now_plating._card_widgets[0].doubleClicked.emit("chan_7")

    assert captured == ["chan_7"]


def test_more_label_when_total_exceeds_cards(qapp):
    """When total > delivered cards, a '+ N more…' label is appended."""
    view, seam = _make_view(qapp)
    view._active = True

    cards = [_FakeCard(f"c{i}", f"Channel {i}") for i in range(3)]
    view._on_results_loaded((cards, 50))

    # 3 card widgets; the surplus is shown as a "+ 47 more…" label, not a card.
    assert len(view._now_plating._card_widgets) == 3


# ---------------------------------------------------------------------------
# Now-Plating grid (Task 2): wrapping, vertically-scrollable card grid
# ---------------------------------------------------------------------------
#
# The strip used to be a single clipped horizontal row showing ~6 of 2,500
# results; it is now a wrapping grid that fills the space below the cloud.

from PyQt6.QtWidgets import QLabel as _QLabel  # noqa: E402


def _flow_items(view):
    """Return the widgets currently in the Now-Plating flow layout."""
    flow = view._now_plating._flow
    return list(flow._items) if flow is not None else []


def test_grid_wraps_cards_into_multiple_rows(qapp):
    """A gridful of cards wraps into >1 row when the container is narrow.

    Proven by relaying the flow at a width that fits only a few cards and
    asserting the wrapped content spans multiple distinct y-rows.
    """
    view, seam = _make_view(qapp)
    view._active = True

    cards = [_FakeCard(f"c{i}", f"Channel {i}") for i in range(12)]
    view._on_results_loaded((cards, 12))

    assert len(view._now_plating._card_widgets) == 12
    # Reflow at a narrow width (≈3 cards wide at 120px each) → must wrap.
    flow = view._now_plating._flow
    total_h = flow.relayout(400)
    rows = {w.y() for w in view._now_plating._card_widgets}
    assert len(rows) > 1, "Cards must wrap into multiple rows in a narrow grid"
    assert total_h > 0


def test_grid_more_indicator_present_when_total_exceeds_cap(qapp):
    """A '+N more … showing M of TOTAL' indicator is added when total > shown."""
    view, seam = _make_view(qapp)
    view._active = True

    cards = [_FakeCard(f"c{i}", f"Channel {i}") for i in range(5)]
    view._on_results_loaded((cards, 2500))

    labels = [w for w in _flow_items(view) if isinstance(w, _QLabel)]
    texts = " ".join(lbl.text() for lbl in labels)
    assert "more" in texts
    assert "2,495" in texts          # 2500 − 5 remainder
    assert "showing 5 of 2,500" in texts


def test_grid_no_more_indicator_when_all_shown(qapp):
    """No '+N more' indicator when the full match set fits in the grid."""
    view, seam = _make_view(qapp)
    view._active = True

    cards = [_FakeCard(f"c{i}", f"Channel {i}") for i in range(4)]
    view._on_results_loaded((cards, 4))

    labels = [w for w in _flow_items(view) if isinstance(w, _QLabel)]
    assert all("more" not in lbl.text() for lbl in labels)


def test_grid_empty_state_renders_cleanly(qapp):
    """Zero matches renders a placeholder label and no card widgets."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_results_loaded(([], 0))

    assert view._now_plating._card_widgets == []
    labels = [w for w in _flow_items(view) if isinstance(w, _QLabel)]
    assert any("No channels match" in lbl.text() for lbl in labels)


def test_grid_rebuild_replaces_previous_cards(qapp):
    """A second load (tag toggle) clears the prior cards before adding new ones."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_results_loaded(([_FakeCard("a", "A"), _FakeCard("b", "B")], 2))
    assert len(view._now_plating._card_widgets) == 2

    # Re-load with a different set — the grid rebuilds, not appends.
    view._on_results_loaded(([_FakeCard("c", "C")], 1))
    assert len(view._now_plating._card_widgets) == 1
    assert view._now_plating._card_widgets[0]._card.channel_id == "c"


def test_grid_results_card_cap_is_a_gridful(qapp):
    """The result cap is raised to a gridful (>1 row) of cards."""
    from metatv.gui.recipe_view import RecipeView
    assert RecipeView._RESULTS_CARD_CAP >= 48


def test_cloud_has_no_trailing_stretch(qapp):
    """The cloud's layout no longer ends with the dead-gap addStretch().

    The trailing stretch existed only to absorb a tall stretch=1 slot; the
    recipe host now sizes the cloud to content (Maximum vertical policy), so the
    stretch must be gone or the dead gap returns.
    """
    from metatv.gui.weighted_tag_cloud import WeightedTagCloud
    cloud = WeightedTagCloud()
    layout = cloud.layout()
    last = layout.itemAt(layout.count() - 1)
    # A stretch item has no widget and a non-None spacerItem; the last item must
    # be the "+N more" button widget, not a trailing spacer.
    assert last.widget() is not None, (
        "The cloud layout must not end with a stretch spacer (the dead-gap hack)"
    )


# ---------------------------------------------------------------------------
# clear_recipe
# ---------------------------------------------------------------------------

def test_clear_recipe_empties_includes_excludes(qapp):
    """clear_recipe() removes all includes and excludes."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Drama", 100)])

    view._on_tag_clicked("Drama")   # include
    assert view.recipe_includes

    view.clear_recipe()

    assert not view.recipe_includes
    assert not view.recipe_excludes


def test_clear_recipe_resets_yields(qapp):
    """After clear_recipe(), the YIELDS label shows 0."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Action", 200)])

    view._on_tag_clicked("Action")
    view._on_results_loaded(([_FakeCard("a", "Channel A")], 99))
    view.clear_recipe()

    yields_text = view._rail._yields_lbl.text()
    assert "0" in yields_text


# ---------------------------------------------------------------------------
# Ingredient removal via rail
# ---------------------------------------------------------------------------

def test_ingredient_remove_discards_include(qapp):
    """_on_ingredient_remove removes a value from recipe_includes."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "platform"
    _load_cloud_with_counts(view, [_TagCountDTO("Netflix", 500)])

    view._on_tag_clicked("Netflix")  # include
    assert "Netflix" in view.recipe_includes.get("platform", set())

    view._on_ingredient_remove("platform", "Netflix")

    assert "Netflix" not in view.recipe_includes.get("platform", set())


def test_ingredient_remove_discards_exclude(qapp):
    """_on_ingredient_remove removes a value from recipe_excludes."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "platform"
    _load_cloud_with_counts(view, [_TagCountDTO("Prime Video", 400)])

    view._on_tag_clicked("Prime Video")  # include
    view._on_tag_clicked("Prime Video")  # exclude
    assert "Prime Video" in view.recipe_excludes.get("platform", set())

    view._on_ingredient_remove("platform", "Prime Video")

    assert "Prime Video" not in view.recipe_excludes.get("platform", set())


def test_ingredient_remove_prunes_empty_facet(qapp):
    """After removing the last value for a facet, the facet key is removed."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "quality"
    _load_cloud_with_counts(view, [_TagCountDTO("HD", 300)])

    view._on_tag_clicked("HD")  # include
    view._on_ingredient_remove("quality", "HD")

    assert "quality" not in view.recipe_includes


# ---------------------------------------------------------------------------
# _generate_recipe_name
# ---------------------------------------------------------------------------

def test_generate_recipe_name_empty_is_placeholder():
    from metatv.gui.recipe_view import _generate_recipe_name
    name = _generate_recipe_name({}, {})
    assert name == "Your recipe is empty"


def test_generate_recipe_name_uses_genre_as_anchor():
    from metatv.gui.recipe_view import _generate_recipe_name
    name = _generate_recipe_name({"genre": {"Drama"}}, {})
    assert "Drama" in name


def test_generate_recipe_name_without_genre_uses_adjective():
    from metatv.gui.recipe_view import _generate_recipe_name
    name = _generate_recipe_name({"language": {"English"}}, {})
    # Must be non-empty and not the empty placeholder
    assert name
    assert name != "Your recipe is empty"


def test_generate_recipe_name_with_excludes_only():
    from metatv.gui.recipe_view import _generate_recipe_name
    name = _generate_recipe_name({}, {"genre": {"Horror"}})
    # Non-empty: has some ingredients (excludes)
    assert name


def test_generate_recipe_name_includes_decade():
    from metatv.gui.recipe_view import _generate_recipe_name
    name = _generate_recipe_name({"decade": {"1980s"}, "genre": {"Action"}}, {})
    assert "1980s" in name


# ---------------------------------------------------------------------------
# Lifecycle: on_activate / on_deactivate
# ---------------------------------------------------------------------------

def test_on_activate_sets_active_flag(qapp):
    """on_activate() sets _active = True and triggers a pantry load."""
    view, seam = _make_view(qapp)
    view._active = False  # reset just in case

    view.on_activate()

    assert view._active is True
    # A pantry load should have been queued
    assert any(c["on_result"] == view._on_pantry_loaded for c in seam.calls)


def test_on_deactivate_clears_active_flag(qapp):
    """on_deactivate() sets _active = False."""
    view, seam = _make_view(qapp)
    view._active = True

    view.on_deactivate()

    assert view._active is False


# ---------------------------------------------------------------------------
# reload() — re-issues data loads when Global Exclusions change (Task 1)
# ---------------------------------------------------------------------------
#
# Regression: changing Global Exclusions and clicking OK left the recipe view
# showing stale pre-exclusion data because the dialog-accept handler refreshed
# every other view but not the recipe.  reload() re-runs the same loads
# on_activate triggers (pantry → cloud), so the new exclusions take effect.

def test_reload_noop_when_never_activated(qapp):
    """reload() before the view is ever activated issues no queries."""
    view, seam = _make_view(qapp)
    view._active = False  # never activated

    view.reload()

    assert seam.calls == []


def test_reload_reissues_pantry_load(qapp):
    """reload() on an active view re-issues the pantry load (same as on_activate)."""
    view, seam = _make_view(qapp)
    view._active = True

    view.reload()

    # The pantry load is the load on_activate fires; reload must re-issue it so
    # new Global Exclusions re-resolve through _global_exclusion_sets().
    assert any(c["on_result"] == view._on_pantry_loaded for c in seam.calls)


def test_reload_reissues_results_when_recipe_in_progress(qapp):
    """reload() with an active recipe re-issues the results/YIELDS load too."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    view._recipe_includes = {"genre": {"Drama"}}

    view.reload()

    # Both pantry (→ cascades to cloud) and results must re-run so the count +
    # cards reflect the new exclusions immediately, not after a nav round-trip.
    assert any(c["on_result"] == view._on_pantry_loaded for c in seam.calls)
    assert any(c["on_result"] == view._on_results_loaded for c in seam.calls)


def test_reload_skips_results_when_recipe_empty(qapp):
    """reload() with no ingredients re-issues only the pantry (no results query)."""
    view, seam = _make_view(qapp)
    view._active = True
    # No includes/excludes set.

    view.reload()

    assert any(c["on_result"] == view._on_pantry_loaded for c in seam.calls)
    assert not any(c["on_result"] == view._on_results_loaded for c in seam.calls)


def test_global_filter_accept_reloads_recipe_view():
    """The Global-Exclusions Accepted path calls recipe_view.reload().

    Drives the real _open_global_filter_dialog handler with a mock dialog that
    returns Accepted, asserting the recipe view is refreshed alongside the other
    provider-dependent views — the wiring that fixes the stale-recipe bug.
    """
    from unittest.mock import MagicMock, patch
    from metatv.gui.main_window_nav import _NavMixin

    # Bare host exposing only what the handler touches.
    host = _NavMixin.__new__(_NavMixin)
    host.config = MagicMock()
    host.db = MagicMock()
    host._update_filter_btn_state = MagicMock()
    host.load_channels = MagicMock()
    host._refresh_recommended_section = MagicMock()
    host.recipe_view = MagicMock()
    # discover_view / preferences_view intentionally absent → hasattr() guards skip.

    accepted = object()

    class _FakeDialog:
        DialogCode = type("DC", (), {"Accepted": accepted})

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return accepted

    with patch(
        "metatv.gui.global_filter_dialog.GlobalFilterDialog", _FakeDialog
    ):
        host._open_global_filter_dialog()

    host.recipe_view.reload.assert_called_once()


# ---------------------------------------------------------------------------
# Theme tokens and icons
# ---------------------------------------------------------------------------

def test_facet_color_tokens_are_distinct():
    """Each facet has a distinct COLOR_FACET_* token — no two share the same hex."""
    from metatv.gui import theme as _theme
    colors = [
        _theme.COLOR_FACET_GENRE,
        _theme.COLOR_FACET_LANGUAGE,
        _theme.COLOR_FACET_REGION,
        _theme.COLOR_FACET_PLATFORM,
        _theme.COLOR_FACET_DECADE,
        _theme.COLOR_FACET_QUALITY,
        _theme.COLOR_FACET_COLLECTION,
    ]
    # All non-empty
    assert all(c for c in colors), "A COLOR_FACET_* token is empty"
    # All distinct
    assert len(set(colors)) == len(colors), "Two COLOR_FACET_* tokens share the same value"


def test_facet_color_tokens_are_hex():
    """All COLOR_FACET_* tokens start with '#' (valid hex color literals)."""
    from metatv.gui import theme as _theme
    tokens = {
        "COLOR_FACET_GENRE":      _theme.COLOR_FACET_GENRE,
        "COLOR_FACET_LANGUAGE":   _theme.COLOR_FACET_LANGUAGE,
        "COLOR_FACET_REGION":     _theme.COLOR_FACET_REGION,
        "COLOR_FACET_PLATFORM":   _theme.COLOR_FACET_PLATFORM,
        "COLOR_FACET_DECADE":     _theme.COLOR_FACET_DECADE,
        "COLOR_FACET_QUALITY":    _theme.COLOR_FACET_QUALITY,
        "COLOR_FACET_COLLECTION": _theme.COLOR_FACET_COLLECTION,
    }
    for name, value in tokens.items():
        assert value.startswith("#"), f"{name} = {value!r} is not a hex color"


def test_recipe_semantic_constants_non_empty():
    """All RECIPE_* semantic style constants in theme are non-empty strings."""
    import metatv.gui.theme as _theme
    constants = [
        "RECIPE_PANTRY_BG",
        "RECIPE_PANTRY_HDR",
        "RECIPE_FACET_ROW",
        "RECIPE_FACET_ROW_SELECTED",
        "RECIPE_STAGE_HDR",
        "RECIPE_STAGE_SUBTITLE",
        "RECIPE_RAIL_BG",
        "RECIPE_RAIL_HDR",
        "RECIPE_EDITORIAL_NAME",
        "RECIPE_ROLE_LABEL",
        "RECIPE_INGREDIENT_CHIP",
        "RECIPE_OMIT_CHIP",
        "RECIPE_YIELDS",
        "RECIPE_NOW_PLATING_HDR",
        "RECIPE_SAVE_BTN",
        "RECIPE_CLEAR_BTN",
    ]
    for name in constants:
        value = getattr(_theme, name, None)
        assert value, f"theme.{name} is missing or empty"


def test_recipe_icons_defined_and_non_empty():
    """All recipe_* icons in icons.py are defined and non-empty strings."""
    from metatv.gui import icons as _icons
    icon_attrs = [
        "recipe_icon",
        "recipe_check_icon",
        "recipe_omit_icon",
        "recipe_save_icon",
        "recipe_clear_icon",
        "recipe_edit_icon",
    ]
    for attr in icon_attrs:
        value = getattr(_icons, attr, None)
        assert value, f"icons.{attr} is missing or empty"


# ---------------------------------------------------------------------------
# _facet_color / _facet_display / _facet_role helpers
# ---------------------------------------------------------------------------

def test_facet_color_returns_token_for_known_facets():
    from metatv.gui.recipe_view import _facet_color
    from metatv.gui import theme as _theme
    assert _facet_color("genre") == _theme.COLOR_FACET_GENRE
    assert _facet_color("language") == _theme.COLOR_FACET_LANGUAGE
    assert _facet_color("platform") == _theme.COLOR_FACET_PLATFORM


def test_facet_color_falls_back_for_unknown():
    from metatv.gui.recipe_view import _facet_color
    from metatv.gui import theme as _theme
    # Unknown facet should fall back to COLOR_TEXT, not crash
    result = _facet_color("unknown_facet_xyz")
    assert result == _theme.COLOR_TEXT


def test_facet_display_known_and_unknown():
    from metatv.gui.recipe_view import _facet_display
    assert _facet_display("genre") == "Genre"
    assert _facet_display("decade") == "Decade"
    assert _facet_display("some_custom") == "Some_Custom"


def test_facet_role_known_and_unknown():
    from metatv.gui.recipe_view import _facet_role
    assert _facet_role("genre") == "BASE"
    assert _facet_role("language") == "IN"
    assert _facet_role("decade") == "ERA"
    assert _facet_role("unknown") == "OTHER"


# ---------------------------------------------------------------------------
# _ROLE_ORDER covers all known role labels
# ---------------------------------------------------------------------------

def test_role_order_covers_all_known_facets():
    """Every known facet's role appears in _ROLE_ORDER."""
    from metatv.gui.recipe_view import _ROLE_ORDER, _FACET_META
    for ftype, meta in _FACET_META.items():
        role = meta[2]
        assert role in _ROLE_ORDER, (
            f"Role {role!r} for facet {ftype!r} is missing from _ROLE_ORDER"
        )


# ---------------------------------------------------------------------------
# Stale-token guard: late result is dropped when a newer call supersedes it
# ---------------------------------------------------------------------------

def test_stale_result_dropped_by_token(qapp):
    """A superseded cloud load is tracked with a token_ref so stale results can be dropped.

    The _cloud_token ref is shared across successive _load_cloud calls; each call
    increments the counter, so the first call's token (1) becomes stale when the
    second call bumps the counter to 2.  We verify that the token_ref is incremented
    correctly after two consecutive calls — the seam logic that _AsyncMixin uses
    would then drop the first result at delivery time.
    """
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"

    # First cloud load — token should be 1
    view._load_cloud("genre")
    first_entry = seam.calls[-1]
    assert first_entry["token"] == 1, "First cloud load should have token 1"
    assert first_entry["on_result"] == view._on_cloud_loaded

    # Second cloud load supersedes the first — token should be 2
    view._load_cloud("language")
    second_entry = seam.calls[-1]
    assert second_entry["token"] == 2, "Second cloud load should have token 2"

    # The first entry's token_ref now points to 2 — so token 1 is stale
    assert first_entry["token_ref"][0] == 2, (
        "token_ref should reflect the latest counter value (2) so the seam can drop stale results"
    )


# ---------------------------------------------------------------------------
# Global Exclusions — RecipeView passes the user's exclusion sets to the engine
# ---------------------------------------------------------------------------
#
# Task A control-layer half: the engine just applies caller-supplied scope
# inputs (DR-0007); RecipeView resolves the sets from Config (respecting
# global_filter_paused) and threads them into every faceted read.

class _RecordingTags:
    """Stand-in for repos.tags that records the kwargs each query receives."""

    def __init__(self):
        self.calls: dict[str, dict] = {}

    def get_facet_summary(self, **kwargs):
        self.calls["facet_summary"] = kwargs
        return []

    def get_tag_counts_for_facet(self, facet_type, **kwargs):
        self.calls["tag_counts"] = kwargs
        return []

    def count_channels_by_tag_facets(self, **kwargs):
        self.calls["count"] = kwargs
        return 0

    def sample_channels_by_tag_facets(self, **kwargs):
        self.calls["sample"] = kwargs
        return []


class _RecordingProviders:
    def get_hidden_provider_ids(self):
        return ["prov_hidden"]


class _RecordingRepos:
    def __init__(self):
        self.tags = _RecordingTags()
        self.providers = _RecordingProviders()


def _set_global_filter(view, *, paused=False, categories=None, prefixes=None,
                       user_categories=None):
    """Set the global-filter config attributes the exclusion helper reads."""
    cfg = view._config
    cfg.global_filter_paused = paused
    cfg.global_filter_excluded_categories = categories or []
    cfg.global_filter_excluded_prefixes = prefixes or []
    cfg.global_filter_excluded_user_categories = user_categories or []


def test_global_exclusion_sets_unions_prefixes_and_categories(qapp):
    """_global_exclusion_sets() unions excluded_categories + excluded_prefixes
    into the prefix set, and reads user-category exclusions separately."""
    view, _seam = _make_view(qapp)
    _set_global_filter(
        view, categories=["AR"], prefixes=["KU"], user_categories=["Kids"]
    )
    prefixes, cats, content_types = view._global_exclusion_sets()
    assert prefixes == {"AR", "KU"}
    assert cats == {"Kids"}
    assert content_types == set()  # no content_type exclusions set here


def test_global_exclusion_sets_empty_when_paused(qapp):
    """When global_filter_paused is True both sets are empty (everything shows)."""
    view, _seam = _make_view(qapp)
    _set_global_filter(
        view, paused=True, categories=["AR"], prefixes=["KU"], user_categories=["Kids"]
    )
    prefixes, cats, content_types = view._global_exclusion_sets()
    assert prefixes == set()
    assert cats == set()
    assert content_types == set()


def test_load_results_threads_exclusion_sets_to_engine(qapp):
    """_load_results runs its query_fn with excluded_prefixes/categories on both
    the count and sample engine calls."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _set_global_filter(view, categories=["AR"], user_categories=["Kids"])
    view._recipe_includes = {"genre": {"Drama"}}

    view._load_results()
    query_fn = seam.calls[-1]["query_fn"]
    repos = _RecordingRepos()
    query_fn(repos)

    assert repos.tags.calls["count"]["excluded_prefixes"] == {"AR"}
    assert repos.tags.calls["count"]["excluded_categories"] == {"Kids"}
    # sample only runs when count > 0; force a non-zero count and re-run.
    repos.tags.count_channels_by_tag_facets = lambda **k: (
        repos.tags.calls.__setitem__("count", k) or 5
    )
    query_fn(repos)
    assert repos.tags.calls["sample"]["excluded_prefixes"] == {"AR"}
    assert repos.tags.calls["sample"]["excluded_categories"] == {"Kids"}


def test_load_cloud_threads_exclusion_sets_to_engine(qapp):
    """_load_cloud runs its query_fn with the exclusion sets on get_tag_counts_for_facet."""
    view, seam = _make_view(qapp)
    view._active = True
    _set_global_filter(view, prefixes=["KU"])

    view._load_cloud("genre")
    query_fn = seam.calls[-1]["query_fn"]
    repos = _RecordingRepos()
    query_fn(repos)

    assert repos.tags.calls["tag_counts"]["excluded_prefixes"] == {"KU"}
    assert repos.tags.calls["tag_counts"]["excluded_categories"] == set()


def test_load_pantry_threads_exclusion_sets_to_engine(qapp):
    """_load_pantry runs its query_fn with the exclusion sets on get_facet_summary."""
    view, seam = _make_view(qapp)
    view._active = True
    _set_global_filter(view, categories=["AR"], user_categories=["Kids"])

    view._load_pantry()
    # the pantry call is the only one queued; find it by callback.
    entry = next(c for c in seam.calls if c["on_result"] == view._on_pantry_loaded)
    repos = _RecordingRepos()
    entry["query_fn"](repos)

    assert repos.tags.calls["facet_summary"]["excluded_prefixes"] == {"AR"}
    assert repos.tags.calls["facet_summary"]["excluded_categories"] == {"Kids"}


# ---------------------------------------------------------------------------
# Instant rail render (fix: decouple rail chips from async count)
# ---------------------------------------------------------------------------
#
# Before this fix the rail chips only appeared after _on_results_loaded
# returned (5-7 s).  The fix calls update_recipe(..., None) synchronously
# inside _on_tag_clicked / _on_ingredient_remove so chips are visible
# immediately; _on_results_loaded then fills in the real YIELDS count.

class _RailSpy:
    """Records every update_recipe() call for assertion."""

    def __init__(self):
        self.calls: list[tuple] = []   # (includes_snapshot, excludes_snapshot, total)

    def update_recipe(self, includes, excludes, match_count, rating_range=None):
        # Deep-copy so later mutations don't change the recorded snapshot.
        self.calls.append(
            (
                {k: set(v) for k, v in includes.items()},
                {k: set(v) for k, v in excludes.items()},
                match_count,
            )
        )

    # Attribute stubs the view accesses on the rail.
    class _Btn:
        def clicked(self):
            pass

        def setEnabled(self, _enabled):
            # The view toggles save_btn enabled state on every rail render.
            pass
        clicked = type("_Sig", (), {"connect": lambda s, f: None})()

    clear_btn = _Btn()
    save_btn = _Btn()   # view toggles save_btn.setEnabled() on every rail render
    ingredient_remove_requested = type(
        "_Sig", (), {"connect": lambda s, f: None}
    )()


def _make_view_with_rail_spy(qapp):
    """Create a RecipeView with the real _RecipeRail replaced by a spy."""
    view, seam = _make_view(qapp)
    spy = _RailSpy()
    view._rail = spy
    return view, seam, spy


def test_tag_click_renders_rail_chips_synchronously(qapp):
    """_on_tag_clicked renders the rail instantly (before _load_results returns).

    After calling _on_tag_clicked the spy must already have received an
    update_recipe() call carrying the updated includes/excludes and a pending
    total (None) — WITHOUT _on_results_loaded having been called.
    """
    view, seam, spy = _make_view_with_rail_spy(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Drama", 1000)])

    seam.calls.clear()  # baseline — only future _run_query calls matter

    view._on_tag_clicked("Drama")

    # Rail must have been updated synchronously.
    assert spy.calls, "update_recipe was not called synchronously on tag click"
    includes_snap, excludes_snap, total = spy.calls[-1]
    assert "Drama" in includes_snap.get("genre", set()), (
        "Clicked tag must appear in includes immediately"
    )
    assert total is None, (
        "Rail total must be None (pending) before _on_results_loaded returns"
    )


def test_tag_click_rail_chips_before_results_loaded(qapp):
    """Rail chips appear synchronously; YIELDS updates only when DB result arrives.

    Simulates the timing: tag click → rail shows chips with 'pending' →
    _on_results_loaded arrives → rail shows real YIELDS.
    """
    view, seam, spy = _make_view_with_rail_spy(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Action", 500)])

    view._on_tag_clicked("Action")

    # Immediately after click — chips rendered, total pending.
    pending_includes, _, pending_total = spy.calls[-1]
    assert "Action" in pending_includes.get("genre", set())
    assert pending_total is None

    # Simulate the slow DB result arriving (bypasses debounce; drives slot directly).
    # Must put the real _RecipeRail back or use a real integer assertion
    # via the spy's second call.
    view._on_results_loaded(([_FakeCard("c1", "An Action Movie")], 123))

    # After results arrive — YIELDS updated to real count.
    # _on_results_loaded calls self._rail.update_recipe(..., total=123) on the spy.
    final_includes, _, final_total = spy.calls[-1]
    assert final_total == 123, (
        f"After _on_results_loaded, YIELDS must be 123, got {final_total}"
    )


def test_ingredient_remove_renders_rail_chips_synchronously(qapp):
    """_on_ingredient_remove updates the rail instantly (pending total)."""
    view, seam, spy = _make_view_with_rail_spy(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Drama", 1000), _TagCountDTO("Horror", 300)])

    view._on_tag_clicked("Drama")
    view._on_tag_clicked("Horror")
    spy.calls.clear()

    # Remove one ingredient via the rail chip handler.
    view._on_ingredient_remove("genre", "Horror")

    assert spy.calls, "update_recipe was not called synchronously on ingredient remove"
    includes_snap, _, total = spy.calls[-1]
    assert "Horror" not in includes_snap.get("genre", set())
    assert total is None


def test_update_recipe_pending_total_shows_counting_label(qapp):
    """_RecipeRail.update_recipe with total=None shows 'counting' in YIELDS label."""
    from metatv.gui.recipe_view import _RecipeRail

    rail = _RecipeRail()
    rail.update_recipe({"genre": {"Drama"}}, {}, None)

    yields_text = rail._yields_lbl.text()
    assert "counting" in yields_text.lower(), (
        f"YIELDS label must say 'counting' when total is None, got: {yields_text!r}"
    )


def test_update_recipe_real_total_shows_count(qapp):
    """_RecipeRail.update_recipe with a real total shows the numeric YIELDS."""
    from metatv.gui.recipe_view import _RecipeRail

    rail = _RecipeRail()
    rail.update_recipe({"genre": {"Drama"}}, {}, 42)

    yields_text = rail._yields_lbl.text()
    assert "42" in yields_text


def test_rapid_tag_clicks_coalesce_into_one_db_query(qapp):
    """N rapid tag clicks fire one _load_results after the debounce fires.

    Drives the debounce timer synchronously (zero-interval trick: set the
    interval to 0 so processEvents() drains it) and counts _run_query calls
    targeting _on_results_loaded.
    """
    from PyQt6.QtWidgets import QApplication

    view, seam, spy = _make_view_with_rail_spy(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [
        _TagCountDTO("Drama", 1000),
        _TagCountDTO("Comedy", 800),
        _TagCountDTO("Action", 600),
    ])
    # Collapse the debounce window to 0 ms so processEvents() fires it.
    view._results_debounce.setInterval(0)

    seam.calls.clear()

    # Three rapid clicks — each restarts the timer.
    view._on_tag_clicked("Drama")
    view._on_tag_clicked("Comedy")
    view._on_tag_clicked("Action")

    # Rail updated three times (once per click) — instant.
    assert len(spy.calls) == 3

    # No _load_results call yet (timer still pending after last click).
    results_calls_before = sum(
        1 for c in seam.calls if c["on_result"] == view._on_results_loaded
    )
    assert results_calls_before == 0, (
        f"_load_results must not fire before debounce expires, got {results_calls_before} calls"
    )

    # Let the debounce timer fire.
    QApplication.processEvents()

    results_calls_after = sum(
        1 for c in seam.calls if c["on_result"] == view._on_results_loaded
    )
    assert results_calls_after == 1, (
        f"Expected exactly 1 _load_results call after debounce, got {results_calls_after}"
    )


def test_on_deactivate_stops_debounce_timer(qapp):
    """on_deactivate() stops the debounce timer so it doesn't fire after nav."""
    view, seam, spy = _make_view_with_rail_spy(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [_TagCountDTO("Drama", 500)])

    view._on_tag_clicked("Drama")  # starts debounce
    assert view._results_debounce.isActive()

    view.on_deactivate()
    assert not view._results_debounce.isActive(), (
        "Debounce timer must be stopped when the view deactivates"
    )


# ---------------------------------------------------------------------------
# "Show all →" full-results browse drill-down
# ---------------------------------------------------------------------------
#
# "Show all" swaps the 3-column constructor (stack page 0) for the full-results
# browse grid (page 1, reusing Discover's _BrowseView).  The see-all query
# reuses _load_results' scoping but with limit=500 (parity with Discover's
# See-All cap).  Re-entering via on_activate / browse Back returns to page 0.

def test_show_all_button_hidden_until_matches(qapp):
    """The 'Show all' button is hidden at 0 matches and shown when matches exist."""
    view, seam = _make_view(qapp)
    view._active = True

    # No results yet → button hidden.
    assert not view._now_plating._show_all_btn.isVisible()

    view._on_results_loaded(([_FakeCard("c1", "A")], 5))
    # Visibility flag is set even on a not-yet-shown widget.
    assert view._now_plating._show_all_btn.isVisible() or \
        not view._now_plating._show_all_btn.isHidden()

    # Zero matches → button hidden again.
    view._on_results_loaded(([], 0))
    assert view._now_plating._show_all_btn.isHidden()


def test_show_all_switches_stack_to_browse_page(qapp):
    """_on_show_all switches the stack to the browse page (index 1)."""
    view, seam = _make_view(qapp)
    view._active = True
    assert view._stack.currentIndex() == 0

    view._on_results_loaded(([_FakeCard("c1", "A"), _FakeCard("c2", "B")], 2))
    view._on_show_all()

    assert view._stack.currentIndex() == 1
    assert view._stack.currentWidget() is view._browse


def test_show_all_seeds_browse_with_cached_cards(qapp):
    """_on_show_all loads the browse view instantly with the strip's cards."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_results_loaded(([_FakeCard("c1", "A"), _FakeCard("c2", "B")], 2))
    view._on_show_all()

    # The browse view got the cards already rendered in the strip (instant feedback).
    assert [c.channel_id for c in view._browse._all_cards] == ["c1", "c2"]


def test_show_all_seeds_from_teaser_without_immediate_fetch(qapp):
    """_on_show_all does ZERO new DB work for page 1: it seeds from the teaser
    cards and sets offset/total/has_more, without firing a sample query."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _set_global_filter(view, categories=["AR"], user_categories=["Kids"])
    view._recipe_includes = {"genre": {"Drama"}}

    # Teaser delivered 3 cards out of a known 7 matches.
    view._on_results_loaded(([_FakeCard("c1", "A"), _FakeCard("c2", "B"),
                              _FakeCard("c3", "C")], 7))
    seam.calls.clear()
    view._on_show_all()

    # No immediate page fetch — page 1 is the seeded teaser cards.
    assert not any(c["on_result"] == view._on_see_all_loaded for c in seam.calls), (
        "Opening 'Show all' must not fire a DB fetch — page 1 reuses teaser cards"
    )
    # Pagination seeded: offset past the 3 seeded cards, total = teaser total.
    assert view._see_all_offset == 3
    assert view._see_all_total == 7
    assert not view._see_all_loading
    # More remain (3 < 7) → browse armed to page on scroll.
    assert view._browse._has_more is True
    # Browse seeded with exactly the teaser cards.
    assert [c.channel_id for c in view._browse._all_cards] == ["c1", "c2", "c3"]


def test_load_more_see_all_pages_at_offset_with_scoping(qapp):
    """_load_more_see_all queries the next page at the current offset (with the
    same scoping kwargs and page-size limit) and advances offset on delivery."""
    from metatv.gui.recipe_view import RecipeView

    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _set_global_filter(view, categories=["AR"], user_categories=["Kids"])
    view._recipe_includes = {"genre": {"Drama"}}

    # Teaser: 3 of 200 → Show all seeds offset=3, total=200.
    view._on_results_loaded(([_FakeCard(f"c{i}", f"C{i}") for i in range(3)], 200))
    view._on_show_all()
    seam.calls.clear()

    # Near-bottom scroll asks for the next page.
    view._load_more_see_all()
    assert view._see_all_loading is True
    entry = next(c for c in seam.calls if c["on_result"] == view._on_see_all_loaded)
    repos = _RecordingRepos()
    entry["query_fn"](repos)
    sample = repos.tags.calls["sample"]
    assert sample["limit"] == RecipeView._SEE_ALL_PAGE
    assert sample["offset"] == 3, "Next page must start at the seeded offset"
    assert sample["excluded_provider_ids"] == ["prov_hidden"]
    assert sample["excluded_prefixes"] == {"AR"}
    assert sample["excluded_categories"] == {"Kids"}

    # Deliver a full page → appended (not replaced), offset advances, still more.
    page = [_FakeCard(f"p{i}", f"P{i}") for i in range(RecipeView._SEE_ALL_PAGE)]
    view._on_see_all_loaded(page)
    assert view._see_all_offset == 3 + RecipeView._SEE_ALL_PAGE
    assert view._see_all_loading is False
    assert view._browse._has_more is True
    assert len(view._browse._all_cards) == 3 + RecipeView._SEE_ALL_PAGE


def test_load_more_stops_when_offset_reaches_total(qapp):
    """Once offset >= total, _load_more_see_all fires no further query."""
    view, seam = _make_view(qapp)
    view._active = True
    view._recipe_includes = {"genre": {"Drama"}}

    # Teaser: 5 of 5 → fully covered by the seed.
    view._on_results_loaded(([_FakeCard(f"c{i}", f"C{i}") for i in range(5)], 5))
    view._on_show_all()
    assert view._see_all_offset == 5
    assert view._see_all_total == 5
    assert view._browse._has_more is False

    seam.calls.clear()
    view._load_more_see_all()
    assert not any(c["on_result"] == view._on_see_all_loaded for c in seam.calls), (
        "No page fetch when offset already covers the full match set"
    )


def test_load_more_guards_against_overlap(qapp):
    """A second _load_more_see_all while one is in flight fires no extra query."""
    view, seam = _make_view(qapp)
    view._active = True
    view._recipe_includes = {"genre": {"Drama"}}
    view._on_results_loaded(([_FakeCard(f"c{i}", f"C{i}") for i in range(3)], 500))
    view._on_show_all()
    seam.calls.clear()

    view._load_more_see_all()        # fires one
    fired = sum(1 for c in seam.calls if c["on_result"] == view._on_see_all_loaded)
    view._load_more_see_all()        # guarded — _see_all_loading is True
    still = sum(1 for c in seam.calls if c["on_result"] == view._on_see_all_loaded)
    assert fired == 1 and still == 1, "Overlapping page loads must be guarded"


def test_browse_back_returns_to_constructor(qapp):
    """backRequested → _on_browse_back switches the stack back to page 0."""
    view, seam = _make_view(qapp)
    view._active = True

    view._on_results_loaded(([_FakeCard("c1", "A")], 1))
    view._on_show_all()
    assert view._stack.currentIndex() == 1

    # Emitting the browse view's backRequested must return to the constructor.
    view._browse.backRequested.emit()
    assert view._stack.currentIndex() == 0


def test_on_activate_resets_stack_to_constructor(qapp):
    """Re-entering via the Recipe chip lands on the constructor, never browse."""
    view, seam = _make_view(qapp)
    view._active = True
    view._on_results_loaded(([_FakeCard("c1", "A")], 1))
    view._on_show_all()
    assert view._stack.currentIndex() == 1

    # Navigating away then re-activating must reset to page 0.
    view.on_deactivate()
    view.on_activate()
    assert view._stack.currentIndex() == 0


def test_on_deactivate_cancels_see_all_token(qapp):
    """on_deactivate bumps the see-all token so a late result is dropped."""
    view, seam = _make_view(qapp)
    view._active = True
    view._on_results_loaded(([_FakeCard("c1", "A")], 1))
    view._on_show_all()

    before = view._see_all_token[0]
    view.on_deactivate()
    assert view._see_all_token[0] > before, (
        "See-all token must advance on deactivate to drop in-flight loads"
    )


def test_browse_card_click_emits_channel_selected(qapp):
    """A click in the browse grid emits the SAME channelSelected signal as the strip."""
    view, seam = _make_view(qapp)
    view._active = True
    captured: list[str] = []
    view.channelSelected.connect(captured.append)

    view._browse.cardClicked.emit("chan_99")
    assert captured == ["chan_99"]


def test_browse_card_double_click_emits_play_requested(qapp):
    """A double-click in the browse grid emits the SAME playRequested signal."""
    view, seam = _make_view(qapp)
    view._active = True
    captured: list[str] = []
    view.playRequested.connect(captured.append)

    view._browse.cardDoubleClicked.emit("chan_77")
    assert captured == ["chan_77"]


def test_reload_refreshes_browse_when_showing(qapp):
    """reload() re-runs the teaser results when the browse page is showing, and
    the delivered teaser re-seeds the browse pagination from page 1."""
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    view._recipe_includes = {"genre": {"Drama"}}
    view._on_results_loaded(([_FakeCard("c1", "A")], 9))
    view._on_show_all()

    seam.calls.clear()
    view.reload()

    # reload() re-issues the teaser results load (which drives the re-seed).
    assert any(c["on_result"] == view._on_results_loaded for c in seam.calls), (
        "reload() must re-run the teaser results while the browse page is visible"
    )

    # When the fresh teaser lands, the browse re-seeds from it (offset/total reset).
    view._on_results_loaded(([_FakeCard("c2", "B"), _FakeCard("c3", "C")], 40))
    assert view._see_all_total == 40
    assert view._see_all_offset == 2
    assert [c.channel_id for c in view._browse._all_cards] == ["c2", "c3"]
    assert view._browse._has_more is True


def test_reload_skips_results_when_constructor_and_no_recipe(qapp):
    """reload() with the constructor showing and no recipe fires no results query."""
    view, seam = _make_view(qapp)
    view._active = True
    assert view._stack.currentIndex() == 0
    # No includes/excludes set.

    seam.calls.clear()
    view.reload()

    assert not any(c["on_result"] == view._on_results_loaded for c in seam.calls)


def test_see_all_page_size_is_a_screenful():
    """_SEE_ALL_PAGE is a screenful (≈the teaser cap), not the old 500 hard cap."""
    from metatv.gui.recipe_view import RecipeView
    assert RecipeView._SEE_ALL_PAGE == 60
    assert not hasattr(RecipeView, "_RECIPE_SEE_ALL_LIMIT"), (
        "The old 500-card hard cap must be gone"
    )


# ---------------------------------------------------------------------------
# Bug fixes: center facet-value filter clear affordance (#recipe-center-filter)
# ---------------------------------------------------------------------------

def test_clear_recipe_also_clears_center_cloud_filter(qapp):
    """clear_recipe() resets the center facet-value filter text so all chips reappear.

    Regression: previously clear_recipe() cleared the Pantry filter but left any
    text in the center WeightedTagCloud filter intact, so typed filter text persisted
    across a recipe clear.
    """
    view, seam = _make_view(qapp)
    view._active = True
    view._selected_facet = "genre"
    _load_cloud_with_counts(view, [
        _TagCountDTO("Drama", 100),
        _TagCountDTO("Action", 80),
        _TagCountDTO("Documentary", 60),
    ])

    # Type something in the center filter — hides all but 'Documentary'
    view._cloud._filter_edit.setText("doc")
    assert view._cloud._filter_edit.text() == "doc"

    # clear_recipe() must also clear the center filter
    view.clear_recipe()

    assert view._cloud._filter_edit.text() == "", (
        "clear_recipe() must clear the center facet-value filter text"
    )
