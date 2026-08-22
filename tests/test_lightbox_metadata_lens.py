"""Cast, crew and genres in the lightbox are clickable — and the click stays put.

The gap this closes: the details pane has had clickable Cast & Crew and genres
for a long time (``details_sections._CastSection.person_clicked`` →
``_on_person_filter_requested``), while the lightbox rendered the same data as a
dead flat string (``"A, B, C · dir. D"`` in one ``QLabel``) and static genre
chips. Same data, one surface wired, one not.

The design decision these tests pin down
----------------------------------------
A metadata click inside the lightbox does **not** punch through to the channel
list. That list is invisible behind the overlay, so filtering it would give the
user no feedback at click time and would cost them the trail (Back / Esc /
breadcrumb) the overlay exists to preserve. The click instead re-seeds the
overlay with that facet's titles — a *lens* — and the only way out to the list
is the lens strip's explicit "See all in Search".

So two things must hold, and both are asserted here:
- clicking a name emits the lens intent and NOT the search hand-off, and
- when the user does take the hand-off, it lands on the same set the lens was
  paging (both route through ``_person_match_predicate`` /
  ``_strict_genre_predicate``, so they cannot drift into two answers).

Appearance, not just wiring
---------------------------
Per the UI-slice rule, the rendered result is asserted, not the token table:
the link colour is parsed back out of the HTML the label actually renders and
measured for WCAG contrast against the lightbox's own fixed-dark surface AND
for distinctness from the plain cast text around it — a link the same colour as
its neighbours is not a link. Both fail against the pre-fix code, which
rendered no anchors at all.

Real file-backed SQLite + real ``Config`` for every query test.
"""

from __future__ import annotations

import re
import uuid

import pytest
from PyQt6.QtCore import Qt

from metatv.gui import theme as _theme


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _config(tmp_path):
    from metatv.core.config import Config
    return Config(config_dir=tmp_path)


def _make_provider(session, pid="p1", active=True):
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=active,
    ))
    session.flush()


def _make_channel(session, *, cid, name, provider_id="p1", media_type="movie",
                  content_key=None, metadata_id=None, detected_genres=None,
                  raw_data=None, detected_title=None, is_hidden=False):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        detected_title=detected_title or name,
        media_type=media_type,
        content_key=content_key,
        metadata_id=metadata_id,
        detected_genres=detected_genres,
        raw_data=raw_data,
        is_hidden=is_hidden,
    )
    session.add(ch)
    session.flush()
    return ch


def _make_metadata(session, *, mid, title, cast=None, director=None, genres=None):
    from metatv.core.database import MetadataDB
    meta = MetadataDB(
        id=mid, title=title, cast=cast or [], director=director, genres=genres or [],
    )
    session.add(meta)
    session.flush()
    return meta


def _card(qapp):
    from metatv.gui.similar_lightbox_card import _LightboxCard
    return _LightboxCard()


def _base_data(**over) -> dict:
    data = {
        "id": "c1", "name": "Adaptation.", "media_type": "movie",
        "provider_name": "ProSat", "provider_active": True,
        "is_favorite": False, "is_hidden": False, "in_queue": False,
        "user_rating": 0, "is_suppressed": False,
        "poster_url": None, "year": 2002, "rating": 7.7, "runtime": 114,
        "genres": ["Comedy", "Drama"],
        "plot": "A screenwriter develops a bad case of writer's block.",
        "cast": [
            {"name": "Nicolas Cage", "role": "cast"},
            {"name": "Meryl Streep", "role": "cast"},
            {"name": "Spike Jonze", "role": "director"},
        ],
        "versions": [], "version_count": 0, "similar": [],
    }
    data.update(over)
    return data


# WCAG 2.1 relative luminance / contrast (same maths as the sibling chip tests).

def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hexstr: str) -> float:
    h = hexstr.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _rgb_distance(a: str, b: str) -> float:
    """Euclidean distance in RGB — "are these two colours actually different"."""
    def _rgb(h):
        h = h.strip().lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b))) ** 0.5


def _chips(card):
    """The genre chips currently in the card's flow layout."""
    flow = card._genres_flow
    return [flow.itemAt(i).widget() for i in range(flow.count())]


# ---------------------------------------------------------------------------
# 1. The card renders cast/crew as links (appearance)
# ---------------------------------------------------------------------------

def test_every_cast_and_crew_name_renders_as_its_own_link(qapp):
    """FAILS pre-fix: cast arrived pre-joined as one string and rendered dead."""
    card = _card(qapp)
    card.populate(_base_data())

    html_text = card._cast_lbl.text()
    for name in ("Nicolas Cage", "Meryl Streep", "Spike Jonze"):
        assert f'href="{name}"' in html_text, (
            f"{name} must be its own link into that person's lens; got: {html_text}"
        )
    # The director keeps its label — the crew name is linked, "dir." is not.
    assert "dir. " in html_text
    assert card._cast_lbl.textFormat() == Qt.TextFormat.RichText


@pytest.mark.parametrize("palette", ["Midnight", "Graphite", "Daylight"])
def test_cast_link_colour_is_legible_in_every_palette(qapp, palette):
    """The rendered link colour, measured, in each theme — not the token table.

    Rich-text link colours are baked into the label's HTML, so NO stylesheet
    conformance test can see them; this is the only thing that would.

    Two ways a "clickable" name fails to read as clickable, both checked here:
    unreadable on the card's own surface, or indistinguishable from the plain
    text beside it. The first attempt at this feature used the palette-tuned
    accent, which is chosen for the light APP surface and lands at 2.9:1 on the
    lightbox's fixed-dark card in Daylight.

    FAILS pre-fix: no anchors are rendered, so there is no colour to parse.
    """
    previous = _theme.current_theme()
    try:
        _theme.apply_theme(palette)
        card = _card(qapp)
        card.populate(_base_data())

        colours = re.findall(r"color:\s*(#[0-9a-fA-F]{3,6})", card._cast_lbl.text())
        assert colours, "no link colour rendered — the names are not links"
        link = colours[0]

        # The card is a deliberately fixed-dark "cinema" surface in every theme.
        surface = _theme.COLOR_LIGHTBOX_BG
        assert _contrast(link, surface) >= 4.5, (
            f"[{palette}] cast link {link} on the lightbox surface {surface} is "
            f"{_contrast(link, surface):.2f}:1 — below the 4.5:1 floor"
        )

        # LIGHTBOX_CAST is the surrounding (non-link) cast text. Luminance alone
        # is the wrong yardstick for a blue against a grey of similar weight, so
        # distinctness is measured as real channel separation too.
        plain = re.search(
            r"color:\s*(#[0-9a-fA-F]{3,6})", _theme.LIGHTBOX_CAST
        ).group(1)
        assert _rgb_distance(link, plain) >= 40, (
            f"[{palette}] link {link} is indistinguishable from the plain cast "
            f"text {plain} — colour has to carry the affordance here"
        )
    finally:
        _theme.apply_theme(previous)


# ---------------------------------------------------------------------------
# 2. Clicking stays in the overlay (the design decision)
# ---------------------------------------------------------------------------

def test_clicking_a_name_opens_the_lens_and_does_not_filter_the_list(qapp):
    """A metadata click re-seeds the overlay; it never reaches the channel list.

    The list is invisible behind the overlay — a click that filtered it would
    give no feedback and would destroy the trail.
    """
    card = _card(qapp)
    card.populate(_base_data())

    people: list[str] = []
    searches: list[tuple] = []
    card.person_clicked.connect(people.append)
    card.lens_search_requested.connect(lambda *a: searches.append(a))

    card._cast_lbl.linkActivated.emit("Nicolas Cage")

    assert people == ["Nicolas Cage"]
    assert searches == [], "a cast click must NOT hand off to the channel list"


def test_genre_chips_are_clickable_with_cursor_and_tooltip(qapp):
    """FAILS pre-fix: chips were bare QLabels — no signal, no cursor, no tooltip."""
    card = _card(qapp)
    card.populate(_base_data())

    chips = _chips(card)
    assert [c.text() for c in chips] == ["Comedy", "Drama"]
    for chip in chips:
        assert chip.cursor().shape() == Qt.CursorShape.PointingHandCursor, (
            f"{chip.text()} chip has no pointing-hand affordance"
        )
        assert chip.toolTip(), f"{chip.text()} chip has no tooltip"

    genres: list[str] = []
    card.genre_clicked.connect(genres.append)
    chips[1].clicked.emit()
    assert genres == ["Drama"]


def test_the_exit_to_search_exists_only_inside_a_lens(qapp):
    """The hand-off is offered where the lens is NAMED — the header — and only
    while a lens is actually open."""
    card = _card(qapp)
    card.populate(_base_data())
    assert not card._lens.exit_button.isVisibleTo(card), "no lens open — no exit"

    card.set_lens("person", "Nicolas Cage")
    assert card._lens.exit_button.isVisibleTo(card)

    searches: list[tuple] = []
    card.lens_search_requested.connect(lambda *a: searches.append(a))
    card._lens.exit_button.click()
    assert searches == [("person", "Nicolas Cage")]

    card.clear_lens()
    assert not card._lens.exit_button.isVisibleTo(card)


def test_the_lens_name_is_not_repeated_below_the_header(qapp):
    """Regression: an earlier cut put the lens name in a full-width bordered
    strip under the header, which repeated the header verbatim AND read as a
    disabled text input. The header names the lens; nothing else should."""
    card = _card(qapp)
    card.populate(_base_data())
    card.set_header("With Nicolas Cage", lens=True)
    card.set_lens("person", "Nicolas Cage")

    assert card._title_lbl.text() == "With Nicolas Cage"
    assert not card._lens.notice.isVisibleTo(card), (
        "a successful lens needs no notice — the re-seeded card IS the feedback"
    )


def test_an_empty_click_says_so_on_the_card(qapp):
    """The one facet click with no navigation to act as its own feedback."""
    card = _card(qapp)
    card.populate(_base_data())

    card.show_notice("Nothing else with Obscure Person")
    assert card._lens.notice.isVisibleTo(card)
    assert card._lens.notice.text == "Nothing else with Obscure Person"

    # Any navigation supersedes it, so it never becomes furniture.
    card.set_lens("person", "Someone Else")
    assert not card._lens.notice.isVisibleTo(card)


def test_a_display_string_still_renders_unlinked(qapp):
    """A caller with only a display line gets text, not links to fragments."""
    card = _card(qapp)
    card.populate(_base_data(cast="Bruce Willis, Brad Pitt · dir. Terry Gilliam"))
    assert "<a href" not in card._cast_lbl.text()
    assert "Bruce Willis" in card._cast_lbl.text()


def test_the_keyboard_legend_says_what_the_arrows_are_actually_walking(qapp):
    """In a lens the chevrons page the LENS results, not the anchor's similar set.

    FAILS pre-fix: the legend was built once and read "browse similar"
    everywhere, describing a list the user is not looking at.
    """
    card = _card(qapp)
    card.populate(_base_data())
    assert card._keyhints.browse_hint == "browse similar"

    card.set_lens("person", "Nicolas Cage")
    assert card._keyhints.browse_hint == "browse these results"

    card.clear_lens()
    assert card._keyhints.browse_hint == "browse similar"


# ---------------------------------------------------------------------------
# 3. The lens query (real DB)
# ---------------------------------------------------------------------------

def _repo(session):
    from metatv.core.repositories import RepositoryFactory
    return RepositoryFactory(session).channels


def test_person_lens_finds_enriched_cast_channel_name_and_raw_blob(tmp_path):
    """All three ways a person is recorded resolve to the same lens.

    The enriched MetadataDB row (what the card displays), the channel NAME (the
    curated "BS| NICOLAS CAGE COLLECTION" categories providers ship, and the
    trailing performer the parser folds into the title), and the raw provider
    blob for the ~99.8% of rows never enriched.
    """
    db = _make_db(tmp_path / "lens_person.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_metadata(s, mid="m1", title="Con Air", cast=[{"name": "Nicolas Cage"}])
        _make_channel(s, cid="enriched", name="Con Air", metadata_id="m1",
                      content_key="k-con|movie")
        _make_channel(s, cid="named", name="BS| NICOLAS CAGE COLLECTION",
                      content_key="k-coll|movie")
        _make_channel(s, cid="raw", name="Face/Off",
                      raw_data={"cast": "John Travolta, Nicolas Cage"},
                      content_key="k-face|movie")
        _make_channel(s, cid="other", name="Unrelated Film",
                      content_key="k-other|movie")

    with db.session_scope(commit=False) as s:
        got = {c.id for c in _repo(s).get_lens_channels("person", "Nicolas Cage")}
    assert got == {"enriched", "named", "raw"}
    db.close()


def test_person_lens_finds_the_director(tmp_path):
    db = _make_db(tmp_path / "lens_dir.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_metadata(s, mid="m1", title="Adaptation.", director="Spike Jonze")
        _make_channel(s, cid="c1", name="Adaptation.", metadata_id="m1",
                      content_key="k-ad|movie")
        _make_channel(s, cid="c2", name="Something Else", content_key="k-se|movie")

    with db.session_scope(commit=False) as s:
        got = {c.id for c in _repo(s).get_lens_channels("person", "Spike Jonze")}
    assert got == {"c1"}
    db.close()


def test_person_lens_and_the_channel_list_filter_resolve_the_same_titles(tmp_path):
    """"See all in Search" must land on the set the lens was paging.

    Both route through ``_person_match_predicate``; this is the test that goes
    red if either grows a private rule.
    """
    db = _make_db(tmp_path / "lens_parity.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_metadata(s, mid="m1", title="Con Air", cast=[{"name": "Nicolas Cage"}])
        _make_channel(s, cid="a", name="Con Air", metadata_id="m1",
                      content_key="k-con|movie")
        _make_channel(s, cid="b", name="EN - Adaptation. 4K (2002) NICOLAS CAGE",
                      content_key="k-ad|movie")
        _make_channel(s, cid="c", name="Face/Off",
                      raw_data={"cast": "Nicolas Cage"}, content_key="k-face|movie")
        _make_channel(s, cid="d", name="Nothing To Do With Him",
                      content_key="k-no|movie")

    with db.session_scope(commit=False) as s:
        repo = _repo(s)
        lens_keys = {
            c.content_key for c in repo.get_lens_channels("person", "Nicolas Cage")
        }
        chip_keys = {
            c.content_key
            for c in repo.get_all(person_filter="Nicolas Cage", include_hidden=False)
        }
    assert lens_keys == chip_keys
    assert "k-no|movie" not in lens_keys
    db.close()


def test_genre_lens_matches_the_canonical_genre(tmp_path):
    """A click on a provider's localized genre finds the canonicalised rows.

    ``detected_genres`` stores the canonical English label at ingestion, so the
    lens has to canonicalise the clicked value the same way the channel-list
    genre chip does — otherwise a French "Drame" click finds nothing.
    """
    db = _make_db(tmp_path / "lens_genre.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_channel(s, cid="c1", name="Sad Film", detected_genres=["Drama"],
                      content_key="k-sad|movie")
        _make_channel(s, cid="c2", name="Funny Film", detected_genres=["Comedy"],
                      content_key="k-fun|movie")

    with db.session_scope(commit=False) as s:
        repo = _repo(s)
        assert {c.id for c in repo.get_lens_channels("genre", "Drama")} == {"c1"}
        assert {c.id for c in repo.get_lens_channels("genre", "Drame")} == {"c1"}
    db.close()


def test_lens_honours_the_absolute_gate_and_per_channel_hide(tmp_path):
    """Content from a disabled/expired source never surfaces in a lens (DR-0007)."""
    db = _make_db(tmp_path / "lens_gate.db")
    with db.session_scope() as s:
        _make_provider(s, pid="good")
        _make_provider(s, pid="dead", active=False)
        _make_metadata(s, mid="m1", title="A", cast=[{"name": "Nicolas Cage"}])
        _make_metadata(s, mid="m2", title="B", cast=[{"name": "Nicolas Cage"}])
        _make_metadata(s, mid="m3", title="C", cast=[{"name": "Nicolas Cage"}])
        _make_channel(s, cid="visible", name="A", provider_id="good",
                      metadata_id="m1", content_key="k-a|movie")
        _make_channel(s, cid="from_dead_source", name="B", provider_id="dead",
                      metadata_id="m2", content_key="k-b|movie")
        _make_channel(s, cid="hidden_row", name="C", provider_id="good",
                      metadata_id="m3", content_key="k-c|movie", is_hidden=True)

    with db.session_scope(commit=False) as s:
        got = {
            c.id for c in _repo(s).get_lens_channels(
                "person", "Nicolas Cage", excluded_provider_ids={"dead"},
            )
        }
    assert got == {"visible"}
    db.close()


def test_lens_collapses_variants_of_one_title(tmp_path):
    """Six copies of one film are one entry, not six stops to page through."""
    db = _make_db(tmp_path / "lens_collapse.db")
    with db.session_scope() as s:
        _make_provider(s)
        for i, name in enumerate(["Con Air", "Con Air 4K", "Con Air (LATINO)"]):
            _make_metadata(s, mid=f"m{i}", title=name, cast=[{"name": "Nicolas Cage"}])
            _make_channel(s, cid=f"c{i}", name=name, metadata_id=f"m{i}",
                          content_key="tmdb:1701|movie")

    with db.session_scope(commit=False) as s:
        got = _repo(s).get_lens_channels("person", "Nicolas Cage")
    assert len(got) == 1, f"expected one collapsed title, got {[c.id for c in got]}"
    db.close()


def test_unknown_lens_returns_nothing_rather_than_everything(tmp_path):
    db = _make_db(tmp_path / "lens_unknown.db")
    with db.session_scope() as s:
        _make_provider(s)
        _make_channel(s, cid="c1", name="A", content_key="k-a|movie")

    with db.session_scope(commit=False) as s:
        repo = _repo(s)
        assert repo.get_lens_channels("colour", "blue") == []
        assert repo.get_lens_channels("person", "   ") == []
    db.close()


# ---------------------------------------------------------------------------
# 4. Lens navigation inside the overlay
# ---------------------------------------------------------------------------

class _StubCard:
    """Records the card calls the nav path makes (no Qt tree needed)."""

    def __init__(self):
        self.lens = None
        self.lens_cleared = 0
        self.notice = None
        self.header = None
        self.back_visible = None
        self.breadcrumb = None
        self.counter = None

    def set_lens(self, lens, value):
        self.lens = (lens, value)
        self.notice = None

    def clear_lens(self):
        self.lens = None
        self.notice = None
        self.lens_cleared += 1

    def show_notice(self, text):
        self.notice = text

    def set_header(self, title, lens=False):
        self.header = (title, lens)

    def set_back_visible(self, visible):
        self.back_visible = visible

    def set_counter(self, text):
        self.counter = text

    def update_breadcrumb(self, *args):
        self.breadcrumb = args

    def reset_loading(self):
        pass


class _StubChevron:
    """The overlay's prev/next chevron — ``_update_nav_state`` enables these.

    A skeleton host that omits them makes the guard itself explode with
    ``RuntimeError`` (PyQt, not AttributeError), which is exactly why the fix
    belongs in this factory rather than a ``hasattr`` in the overlay.
    """

    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = value


def _nav_lightbox():
    """A ``SimilarTitleLightbox`` with only the nav state the lens path touches."""
    from metatv.gui.similar_lightbox import SimilarTitleLightbox

    lb = SimilarTitleLightbox.__new__(SimilarTitleLightbox)
    lb._card = _StubCard()
    lb._prev_chev = _StubChevron()
    lb._next_chev = _StubChevron()
    lb._origin_ids = ["c1", "cX"]
    lb._origin_idx = 0
    lb._origin_title = "Adaptation."
    lb._nav_stack = []
    lb._nav_titles = {"c1": "Adaptation."}
    lb._current_id = "c1"
    lb._lens = None
    lb._lens_stack = []
    lb._pending_lens = None
    lb.loaded: list[str] = []
    lb._load_channel = lb.loaded.append
    lb.isVisible = lambda: True
    return lb


def test_a_lens_reseeds_the_overlay_and_names_itself():
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")

    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air"), ("c3", "Face/Off")])

    assert lb._origin_ids == ["c2", "c3"]
    assert lb._origin_title == "With Nicolas Cage"
    assert lb._lens == ("person", "Nicolas Cage")
    assert lb._card.lens == ("person", "Nicolas Cage")
    assert lb._card.header == ("With Nicolas Cage", True)
    assert lb._card.back_visible is True
    assert lb.loaded == ["c2"], "the lens opens on its first title"


def test_back_out_of_a_lens_restores_the_anchor_exactly():
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")
    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air")])
    lb._current_id = "c2"

    lb._go_back()

    assert lb._origin_ids == ["c1", "cX"], "the anchor's own set is back"
    assert lb._origin_title == "Adaptation."
    assert lb._lens is None
    assert lb._card.lens_cleared >= 1
    assert lb._card.header == ("Adaptation.", False)
    assert lb.loaded[-1] == "c1", "and it lands on the title you left"


def test_lenses_nest_and_unwind_one_step_at_a_time():
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")
    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air")])
    lb._current_id = "c2"
    lb._nav_titles["c2"] = "Con Air"
    lb._pending_lens = ("genre", "Action")
    lb._apply_lens("genre", "Action", [("c9", "Speed")])
    lb._current_id = "c9"

    assert lb._origin_title == "Action titles"
    lb._go_back()
    assert lb._lens == ("person", "Nicolas Cage")
    assert lb._card.header == ("With Nicolas Cage", True)
    lb._go_back()
    assert lb._lens is None
    assert lb._origin_title == "Adaptation."


def test_an_empty_lens_says_so_instead_of_navigating_nowhere():
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Obscure Person")

    lb._apply_lens("person", "Obscure Person", [])

    assert lb.loaded == [], "nothing to show — stay on the title we are on"
    assert lb._origin_ids == ["c1", "cX"]
    assert lb._card.notice == "Nothing else with Obscure Person"


def test_a_stale_lens_result_is_ignored():
    """The user clicked, then navigated away before the query returned."""
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")
    lb._pending_lens = None  # navigated away

    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air")])

    assert lb.loaded == []
    assert lb._origin_ids == ["c1", "cX"]


def test_the_breadcrumb_carries_the_lens_anchor():
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")
    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air")])
    lb._current_id = "c2"

    lb._update_nav_state()

    *_, lens_crumbs = lb._card.breadcrumb
    assert lens_crumbs == [("Adaptation.", "c1")]


def test_the_chevrons_page_through_the_lens_set():
    """A lens is a set you walk, so ← → must stay live inside it."""
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")
    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air"), ("c3", "Face/Off")])

    lb._update_nav_state()

    assert lb._card.counter == "1 of 2"
    assert lb._next_chev.enabled is True
    assert lb._prev_chev.enabled is False


def test_clicking_the_anchor_crumb_leaves_the_lens():
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")
    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air")])
    lb._current_id = "c2"

    lb._on_breadcrumb_crumb_clicked("c1")

    assert lb._lens is None
    assert lb.loaded[-1] == "c1"


def test_closing_the_overlay_forgets_every_lens():
    lb = _nav_lightbox()
    lb._pending_lens = ("person", "Nicolas Cage")
    lb._apply_lens("person", "Nicolas Cage", [("c2", "Con Air")])
    lb.hide = lambda: None

    lb._close()

    assert lb._lens_stack == []
    assert lb._lens is None
    assert lb._card.lens is None


# ---------------------------------------------------------------------------
# 5. The breadcrumb renders the lens trail
# ---------------------------------------------------------------------------

def test_breadcrumb_renders_anchor_then_lens_then_current(qapp):
    """FAILS pre-fix: ``update_trail`` had no lens crumbs and hid itself with an
    empty nav stack, so a lens hop left no trail at all."""
    from PyQt6.QtWidgets import QLabel
    from metatv.gui.lightbox_breadcrumb import LightboxBreadcrumb

    bc = LightboxBreadcrumb()
    bc.update_trail(
        "With Nicolas Cage", ["c2"], [], "c2", {"c2": "Con Air"},
        [("Adaptation.", "c1")],
    )

    rendered = [
        bc._layout.itemAt(i).widget().text()
        for i in range(bc._layout.count())
        if bc._layout.itemAt(i).widget() is not None
    ]
    assert rendered == ["Adaptation.", "›", "With Nicolas Cage", "›", "Con Air"]

    # The anchor is the way back and must be clickable; the lens LABEL is a set,
    # not a place, so it stays plain text.
    widgets = [
        bc._layout.itemAt(i).widget()
        for i in range(bc._layout.count())
        if bc._layout.itemAt(i).widget() is not None
    ]
    assert not isinstance(widgets[0], QLabel), "the anchor crumb must be clickable"
    assert isinstance(widgets[2], QLabel), "the lens label is not a destination"

    clicked: list[str] = []
    bc.crumb_clicked.connect(clicked.append)
    widgets[0].click()
    assert clicked == ["c1"]


# ---------------------------------------------------------------------------
# 6. The hand-off out
# ---------------------------------------------------------------------------

def test_see_all_in_search_routes_into_the_existing_strict_filters():
    """The hand-off reuses the details-pane chokepoints, not a third path."""
    from metatv.gui.main_window_nav import _NavMixin

    class _Host:
        def __init__(self):
            self.person = []
            self.genre = []

        def _on_person_filter_requested(self, name):
            self.person.append(name)

        def _on_genre_filter_requested(self, genre):
            self.genre.append(genre)

    host = _Host()
    _NavMixin._on_lightbox_lens_search(host, "person", "Nicolas Cage")
    _NavMixin._on_lightbox_lens_search(host, "genre", "Drama")

    assert host.person == ["Nicolas Cage"]
    assert host.genre == ["Drama"]
