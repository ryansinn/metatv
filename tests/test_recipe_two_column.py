"""Behavioral tests for the RecipeView two-column redesign + content-first entry.

Covers the four things the redesign changed (owner direction):

  (a) Construction yields the two-column structure — Tonight's Recipe rail sits
      in column 1 (stacked under the Pantry), and column 2 is a *vertical*
      splitter (tag cloud over the Now-Plating results area).
  (b) A preset-tag entry (``seed_facet`` — the exact seam the details-pane tag
      right-click drives) lands on the *content-first* browse page, not the
      builder, and the "Build recipe" affordance returns to the builder.
  (c) Splitter sizes persist to Config on change and restore on a fresh build.
  (d) A nav-chip entry (``on_activate`` with no preset tag) still lands on the
      builder.

The DB worker half is stubbed by a fake ``_run_query`` seam; what matters here
is the layout wiring + the stack page a given entry path lands on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QScrollArea, QSplitter


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ── Fakes ──────────────────────────────────────────────────────────────────

class _FakeSeam:
    """Records _run_query calls; supports synchronous delivery in tests."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None) -> None:
        if token_ref is not None:
            token_ref[0] += 1
        self.calls.append(dict(on_result=on_result, token_ref=token_ref, on_error=on_error))

    def deliver_to(self, on_result: Callable, data: Any) -> None:
        for entry in reversed(self.calls):
            if entry["on_result"] == on_result:
                entry["on_result"](data)
                return
        raise AssertionError(f"No _run_query for {on_result!r}")


@dataclass
class _FakeCard:
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


class _FakeConfig:
    """Duck-typed config with the presentation fields the cards/browse read.

    Splitter fields are absent so the view falls back to its defaults; a getattr
    with a default is how the view reads them, so this stays a plain object.
    """

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


class _FakeImageCache(QObject):
    image_loaded = pyqtSignal(str, object)
    image_failed = pyqtSignal(str, str)

    def get_image_async(self, url):  # noqa: D401 - stub
        pass


def _make_view(qapp, config=None):
    from metatv.gui.recipe_view import RecipeView

    seam = _FakeSeam()
    view = RecipeView(
        db=object(),
        config=config if config is not None else _FakeConfig(),
        run_query_fn=seam._run_query,
        image_cache=_FakeImageCache(),
        parent=None,
    )
    return view, seam


# ── (a) Two-column structure ────────────────────────────────────────────────

def test_two_column_structure(qapp):
    """Column 1 stacks Pantry over the Tonight's-Recipe rail; column 2 is a
    vertical splitter of cloud over the Now-Plating results area."""
    view, _seam = _make_view(qapp)

    # Main horizontal splitter has exactly two columns.
    assert isinstance(view._main_splitter, QSplitter)
    assert view._main_splitter.orientation() == Qt.Orientation.Horizontal
    assert view._main_splitter.count() == 2

    # Column 1 = vertical splitter: Pantry (top) over the recipe rail (bottom).
    assert view._main_splitter.widget(0) is view._col1_splitter
    assert view._col1_splitter.orientation() == Qt.Orientation.Vertical
    assert view._col1_splitter.widget(0) is view._pantry
    assert view._col1_splitter.widget(1) is view._rail, (
        "Tonight's Recipe rail must live UNDER the Pantry in column 1"
    )

    # Column 2 contains the vertical content splitter: cloud over Now-Plating.
    assert view._content_splitter.orientation() == Qt.Orientation.Vertical
    assert view._content_splitter.widget(1) is view._now_plating, (
        "Now Plating must occupy the bottom half of column 2's vertical splitter"
    )
    # The cloud sits in the top pane (wrapped in a scroll area so it can scroll).
    top = view._content_splitter.widget(0)
    assert isinstance(top, QScrollArea) and top.widget() is view._cloud


# ── (b) Content-first tag entry + affordance ────────────────────────────────

def test_seed_facet_lands_content_first(qapp):
    """seed_facet (the details-pane tag seam) lands on the browse page, applies
    the tag as the recipe ingredient, and fills the browse grid from the teaser."""
    view, seam = _make_view(qapp)
    view._active = True
    view.on_activate()  # nav lands on the builder first…

    view.seed_facet("genre", "Drama")

    # Content-first: on the browse page (stack index 1), NOT the builder.
    assert view._stack.currentIndex() == 1
    assert view._stack.currentWidget() is view._browse
    # The clicked tag is applied as the single recipe ingredient.
    assert view.recipe_includes == {"genre": {"Drama"}}

    # When the async results land, the browse grid is seeded with the matches.
    seam.deliver_to(view._on_results_loaded,
                    ([_FakeCard("c1", "A"), _FakeCard("c2", "B")], 2))
    assert [c.channel_id for c in view._browse._all_cards] == ["c1", "c2"]


def test_content_first_affordance_returns_to_builder(qapp):
    """The browse page carries a 'Build recipe' affordance that returns to the
    builder (stack page 0) with the seeded ingredient intact."""
    view, _seam = _make_view(qapp)
    view._active = True
    view.seed_facet("genre", "Drama")
    assert view._stack.currentIndex() == 1

    # The affordance reads as a way into the builder…
    assert "Build recipe" in view._browse._back_btn.text()
    # …and activating it returns to the builder with the ingredient still applied.
    view._browse.backRequested.emit()
    assert view._stack.currentIndex() == 0
    assert view.recipe_includes == {"genre": {"Drama"}}


# ── (c) Splitter-size persistence round-trip ────────────────────────────────

def _show(view, qapp, w=1200, h=800):
    view.resize(w, h)
    view.show()
    qapp.processEvents()


def test_splitter_moved_schedules_save(qapp):
    """Dragging a splitter schedules the debounced config write (save on change)."""
    view, _seam = _make_view(qapp)
    assert not view._layout_save_debounce.isActive()
    view._content_splitter.splitterMoved.emit(100, 1)
    assert view._layout_save_debounce.isActive(), (
        "A splitter drag must (re)start the debounced persistence timer"
    )


def test_splitter_sizes_persist_and_restore(qapp, tmp_path):
    """Change sizes → saved to Config on disk; a fresh build with that Config
    restores them (proven by the restored cloud pane being the taller one — the
    opposite of the default cloud<results split)."""
    from metatv.core.config import Config
    import yaml

    config = Config(config_dir=tmp_path)
    view1, _seam1 = _make_view(qapp, config=config)
    _show(view1, qapp)

    # Simulate a user drag: give the cloud pane the lion's share (top > bottom),
    # which is the OPPOSITE of the default (cloud 360 < results 440).
    view1._content_splitter.setSizes([700, 120])
    qapp.processEvents()
    saved = view1._content_splitter.sizes()
    assert saved[0] > saved[1]

    # Persist (the real save path) and confirm the field + on-disk write.
    view1._persist_splitter_sizes()
    assert config.recipe_content_splitter_sizes == saved
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert on_disk["recipe_content_splitter_sizes"] == saved

    # Reload the Config from disk and build a fresh view with it.
    config2 = Config(**on_disk)
    assert config2.recipe_content_splitter_sizes == saved
    view2, _seam2 = _make_view(qapp, config=config2)
    _show(view2, qapp)

    restored = view2._content_splitter.sizes()
    assert restored[0] > restored[1], (
        "A fresh view built from the saved Config must restore the cloud-heavy "
        f"split (top>bottom), got {restored}"
    )


# ── (d) Nav-chip entry lands on the builder ─────────────────────────────────

def test_nav_chip_entry_lands_on_builder(qapp):
    """Opening via the Recipe nav chip (on_activate, no preset tag) lands on the
    builder (stack page 0), not the content-first browse page."""
    view, _seam = _make_view(qapp)
    # Simulate a prior browse state to prove on_activate resets to the builder.
    view._active = True
    view._stack.setCurrentIndex(1)

    view.on_activate()

    assert view._stack.currentIndex() == 0, (
        "Nav-chip entry must land on the builder, not the content-first page"
    )
