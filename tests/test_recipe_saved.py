"""Behavioral tests for the Recipe view's Saved-recipes round-trip.

The basic slice: save the current recipe → persist to the ``saved_recipes`` Config
field on disk → the Saved tab lists it as a card → clicking a card reloads its
includes/excludes into the builder → delete removes it.  Uses a REAL ``Config`` on
``tmp_path`` (never the user config), per the tests rule, so the persistence is
proven end-to-end (write + reload from disk).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
import yaml
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSeam:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None) -> None:
        if token_ref is not None:
            token_ref[0] += 1
        self.calls.append({"on_result": on_result, "token_ref": token_ref, "on_error": on_error})

    def deliver_to(self, on_result: Callable, data: Any) -> None:
        for entry in reversed(self.calls):
            if entry["on_result"] == on_result:
                entry["on_result"](data)
                return
        raise AssertionError(f"No _run_query for {on_result!r}")

    def deliver_last(self, data: Any) -> None:
        self.calls[-1]["on_result"](data)


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


class _FakeImageCache(QObject):
    image_loaded = pyqtSignal(str, object)
    image_failed = pyqtSignal(str, str)

    def get_image_async(self, url):
        pass


def _make_view(qapp, config):
    from metatv.gui.recipe_view import RecipeView

    seam = _FakeSeam()
    view = RecipeView(
        db=object(),
        config=config,
        run_query_fn=seam._run_query,
        image_cache=_FakeImageCache(),
        parent=None,
    )
    view._active = True
    return view, seam


def _real_config(tmp_path):
    from metatv.core.config import Config
    return Config(config_dir=tmp_path)


# ── Save → persist to disk ──────────────────────────────────────────────────

def test_save_persists_to_config_and_disk(qapp, tmp_path):
    """Saving the current recipe writes a saved_recipes entry to config.yaml."""
    config = _real_config(tmp_path)
    view, _seam = _make_view(qapp, config)

    view._recipe_includes = {"genre": {"Drama"}, "region": {"ES"}}
    view._recipe_excludes = {"quality": {"SD"}}
    view._on_save_recipe()

    # In-memory Config now holds exactly one saved recipe with the frozen shape.
    assert len(config.saved_recipes) == 1
    entry = config.saved_recipes[0]
    assert entry["includes"] == {"genre": ["Drama"], "region": ["ES"]}
    assert entry["excludes"] == {"quality": ["SD"]}
    assert entry["name"]

    # …and it is on disk (reload from the written YAML).
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert on_disk["saved_recipes"] == config.saved_recipes


def test_save_empty_recipe_is_noop(qapp, tmp_path):
    """Saving with no ingredients does nothing (nothing to persist)."""
    config = _real_config(tmp_path)
    view, _seam = _make_view(qapp, config)
    view._on_save_recipe()
    assert config.saved_recipes == []


# ── Saved tab lists persisted recipes ───────────────────────────────────────

def test_saved_tab_lists_persisted_recipes(qapp, tmp_path):
    """A persisted recipe renders as a card in the Saved tab, and its live count
    fills in once the count query lands."""
    config = _real_config(tmp_path)
    config.saved_recipes = [
        {"name": "Cold French Crime", "includes": {"genre": ["Crime"], "region": ["FR"]}, "excludes": {}},
    ]
    view, seam = _make_view(qapp, config)

    view._load_saved_recipes()

    cards = view._saved_panel.cards()
    assert len(cards) == 1
    assert cards[0]._name_edit.text() == "Cold French Crime"

    # One count query was issued; delivering it updates the card's count line.
    seam.deliver_last(2140)
    assert "2,140" in cards[0]._count_lbl.text()


# ── Reload a saved recipe into the builder ──────────────────────────────────

def test_saved_reload_restores_includes_excludes(qapp, tmp_path):
    """Clicking a saved card reloads its includes/excludes into the builder and
    returns to the Recipe tab."""
    config = _real_config(tmp_path)
    config.saved_recipes = [
        {"name": "R", "includes": {"genre": ["Drama"], "region": ["ES"]},
         "excludes": {"quality": ["SD"]}},
    ]
    view, _seam = _make_view(qapp, config)
    view._load_saved_recipes()

    # Land on the Saved tab first, then reload the card.
    view._tab_bar.set_index(1)
    view._show_tab(1)
    view._on_saved_load(0)

    assert view.recipe_includes == {"genre": {"Drama"}, "region": {"ES"}}
    assert view.recipe_excludes == {"quality": {"SD"}}
    # Back on the Recipe tab's builder.
    assert view._tab_stack.currentIndex() == 0
    assert view._stack.currentIndex() == 0


def test_saved_reload_round_trips_after_disk_reload(qapp, tmp_path):
    """Save → reload Config from disk → the recipe still reloads into the builder."""
    from metatv.core.config import Config

    # Save with one view.
    config = _real_config(tmp_path)
    view1, _s1 = _make_view(qapp, config)
    view1._recipe_includes = {"genre": {"Horror"}}
    view1._recipe_excludes = {}
    view1._on_save_recipe()

    # Fresh Config reconstructed from the written file → fresh view.
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text())
    config2 = Config(**on_disk)
    assert len(config2.saved_recipes) == 1
    view2, _s2 = _make_view(qapp, config2)
    view2._load_saved_recipes()
    view2._on_saved_load(0)
    assert view2.recipe_includes == {"genre": {"Horror"}}


# ── Rename + delete ─────────────────────────────────────────────────────────

def test_saved_rename_persists(qapp, tmp_path):
    """Renaming a saved card persists the new name to Config."""
    config = _real_config(tmp_path)
    config.saved_recipes = [{"name": "Old", "includes": {"genre": ["Drama"]}, "excludes": {}}]
    view, _seam = _make_view(qapp, config)
    view._load_saved_recipes()

    view._on_saved_rename(0, "New Name")

    assert config.saved_recipes[0]["name"] == "New Name"
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert on_disk["saved_recipes"][0]["name"] == "New Name"


def test_saved_delete_removes_and_persists(qapp, tmp_path):
    """Deleting a saved card removes it from Config and re-renders the panel."""
    config = _real_config(tmp_path)
    config.saved_recipes = [
        {"name": "A", "includes": {"genre": ["Drama"]}, "excludes": {}},
        {"name": "B", "includes": {"genre": ["Comedy"]}, "excludes": {}},
    ]
    view, _seam = _make_view(qapp, config)
    view._load_saved_recipes()
    assert len(view._saved_panel.cards()) == 2

    view._on_saved_delete(0)

    assert [r["name"] for r in config.saved_recipes] == ["B"]
    assert len(view._saved_panel.cards()) == 1
    on_disk = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert [r["name"] for r in on_disk["saved_recipes"]] == ["B"]


# ── Full round-trip in one flow ─────────────────────────────────────────────

def test_full_round_trip_save_list_reload_delete(qapp, tmp_path):
    """save → appears in Saved → reload restores → delete removes (one flow)."""
    config = _real_config(tmp_path)
    view, seam = _make_view(qapp, config)

    # Build + save.
    view._recipe_includes = {"genre": {"Drama"}, "decade": {"1990s"}}
    view._on_save_recipe()
    assert view._tab_stack.currentIndex() == 1          # jumped to Saved
    assert len(view._saved_panel.cards()) == 1

    # Clear the builder, then reload the saved recipe.
    view.clear_recipe()
    assert not view.recipe_includes
    view._on_saved_load(0)
    assert view.recipe_includes == {"genre": {"Drama"}, "decade": {"1990s"}}

    # Delete it.
    view._tab_bar.set_index(1)
    view._show_tab(1)
    view._on_saved_delete(0)
    assert config.saved_recipes == []
    assert view._saved_panel.cards() == []
