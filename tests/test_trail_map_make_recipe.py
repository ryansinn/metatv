"""'Make recipe' from the Explore trail map must arrive with an ingredient.

Owner, 2026-08-27: "the 'Make a recipe' from the Explore/Collapsible Columns
doesn't do anything". It was wired the whole way —
``trail_map_detail.py:225`` builds the button, ``trail_map_view.py:538``
re-emits it as ``recipe_requested(channel_id)``, ``main_window.py`` handles it
— but the handler switched to Recipe and DISCARDED the channel_id, so you
landed in an empty builder. Its own docstring admitted it: "Seeding the pantry
from channel_id's genres/tags is a follow-up".

An empty builder after clicking "Make recipe" on a specific title is
indistinguishable from a dead button, which is exactly how it was reported.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.gui.main_window import MainWindow


@pytest.fixture
def host(tmp_path):
    """A MainWindow skeleton with just the collaborators this path touches.

    ``__new__``: constructing a real MainWindow per test leaves ~22 top-level
    widgets alive, and this exercises two methods and a query.
    """
    db = Database(f"sqlite:///{tmp_path}/recipe.db")
    db.create_tables()
    with db.session_scope() as session:
        session.add(ProviderDB(id="p1", name="S", type="xtream", url="u",
                               is_active=True, account_status="Active"))
        for cid, genre in (("with-genre", "Drama"), ("no-genre", None),
                           ("blank-genre", "   ")):
            session.add(ChannelDB(
                id=cid, source_id=str(uuid.uuid4()), provider_id="p1",
                name=cid, media_type="movie", is_hidden=False,
                detected_genre=genre,
            ))

    win = MainWindow.__new__(MainWindow)
    win.db = db  # the read goes through ChannelRepository.get_detected_genre
    seeded: list[tuple[str, str]] = []
    switched: list[bool] = []
    win._on_tag_discover_requested = lambda ft, v: seeded.append((ft, v))
    win.switch_to_recipe_view = lambda: switched.append(True)
    yield win, seeded, switched
    db.close()


def test_the_recipe_is_seeded_with_the_title_s_genre(host):
    """The whole bug: the channel_id arrived and was thrown away."""
    win, seeded, switched = host

    MainWindow._on_trail_recipe_requested(win, "with-genre")

    assert seeded == [("genre", "Drama")], (
        "Make recipe did not seed the builder — it opens empty, which is "
        f"what 'doesn't do anything' looked like (seeded={seeded})"
    )
    assert not switched, "seeding already switches the view; do not switch twice"


def test_a_title_with_no_genre_still_opens_the_builder(host):
    """Swallowing the click would be worse than an empty builder."""
    win, seeded, switched = host

    MainWindow._on_trail_recipe_requested(win, "no-genre")

    assert seeded == [], "there is nothing honest to seed with"
    assert switched == [True], "the click must still open Recipe, not vanish"


def test_a_whitespace_genre_counts_as_no_genre(host):
    """`"   "` is truthy in Python; seeding it would build a recipe on nothing."""
    win, seeded, switched = host

    MainWindow._on_trail_recipe_requested(win, "blank-genre")

    assert seeded == []
    assert switched == [True]


def test_an_unknown_channel_does_not_raise(host):
    """The trail map can outlive a refresh that removed the row."""
    win, seeded, switched = host

    MainWindow._on_trail_recipe_requested(win, "gone")

    assert seeded == []
    assert switched == [True]


def test_only_the_genre_is_seeded(host):
    """Seeding every facet gives a recipe that returns the title you started from.

    Genre is the widest useful start; language, decade and region are one click
    away in the builder you have just been dropped into. Asserted so a later
    "improvement" that seeds more has to argue with this.
    """
    win, seeded, _ = host

    MainWindow._on_trail_recipe_requested(win, "with-genre")

    assert len(seeded) == 1, f"expected exactly one ingredient, got {seeded}"
    assert seeded[0][0] == "genre"
