"""PLAT-1 — Discover gets a shelf per streaming platform.

A platform earns its own shelf once enough DISTINCT TITLES carry its
``platform:`` tag. Four things about that sentence are load-bearing, and each
has a test here that fails without it:

* **Distinct titles, not rows.** A library holding one film in six qualities is
  one title. Counting rows would let a handful of much-duplicated films open a
  shelf, and would put the same film on the strip six times.
* **VOD only** (owner, Q2). Discover is the VOD surface. The live fixture below
  is sized so that counting live channels would flip Tubi over the threshold —
  if the media-type gate goes, this file goes red rather than quietly gaining a
  shelf full of football.
* **The curated exclusions never qualify** (owner, Q5). "Other Streaming" is
  the biggest bucket in the fixture *on purpose*: it would be the first shelf
  the user saw if the gate were dropped.
* **Hidden sources are an absolute gate.** A platform whose entire catalogue
  sits on a deactivated source is not a platform this library has.

The threshold itself is a setting, so the last two tests prove the control
round-trips and that pressing OK actually rebuilds Discover — a number that
saves but changes nothing is the same bug as no control at all.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from metatv.core.channel_name_utils import PLATFORM_SHELF_EXCLUDED_VALUES
from metatv.core.platform_shelves import (
    PLATFORM_SHELF_MEDIA_TYPES, platform_shelf_values, representative_version,
)

# The fixture's shape, named once so the assertions below read as claims about
# the library rather than as magic numbers.
NETFLIX_TITLES = 60          # clears a 50 floor
TUBI_VOD_TITLES = 20         # below 50, above 15
TUBI_LIVE_CHANNELS = 40      # 20 + 40 = 60: enough to flip Tubi IF live counted
OTHER_STREAMING_TITLES = 80  # the biggest bucket, and permanently excluded
HIDDEN_DISNEY_TITLES = 70    # all on a deactivated source


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def platform_db(tmp_path):
    """A real file-backed library with the shape the module docstring describes.

    Never ``:memory:`` — CLAUDE.md's DB-session rule, and the collapse query
    uses window functions whose behaviour is worth exercising on a real file.
    """
    from metatv.core.database import ChannelDB, Database, ProviderDB, TagDB
    from tests.conftest import add_content_tag

    db = Database(f"sqlite:///{tmp_path / 'platform_shelves.db'}")
    db.create_tables()

    with db.session_scope() as s:
        # A real ProviderDB row per id, or get_hidden_provider_ids() reads them
        # as ORPHANED and excludes every card — the gate working correctly
        # against unrealistic fixture data.
        s.add(ProviderDB(id="p1", name="Active", type="xtream",
                         url="http://a.example", is_active=True))
        s.add(ProviderDB(id="p2", name="Deactivated", type="xtream",
                         url="http://b.example", is_active=False))
        s.flush()

        tag_ids: dict[str, int] = {}

        def tag_id(value: str) -> int:
            if value not in tag_ids:
                tag = TagDB(type="platform", value=value)
                s.add(tag)
                s.flush()
                tag_ids[value] = tag.id
            return tag_ids[value]

        def add(cid: str, platform: str, *, provider: str = "p1",
                media_type: str = "movie", title: str, key: str | None,
                added: int) -> None:
            s.add(ChannelDB(id=cid, source_id=cid, provider_id=provider,
                            name=title, detected_title=title,
                            media_type=media_type, content_key=key,
                            detected_added=added))
            add_content_tag(s, cid, tag_id(platform), source="generated")

        for i in range(NETFLIX_TITLES):
            add(f"nf-{i}", "Netflix", title=f"Netflix Title {i:03d}",
                key=f"nf:title-{i}", added=i)
        # The newest Netflix title exists as THREE versions of one content_key,
        # inside the window the shelf actually fetches — a collapse bug that
        # only showed on the oldest title would never be seen.
        for suffix in ("b", "c"):
            add(f"nf-{NETFLIX_TITLES - 1}{suffix}", "Netflix",
                title=f"Netflix Title {NETFLIX_TITLES - 1:03d}",
                key=f"nf:title-{NETFLIX_TITLES - 1}", added=NETFLIX_TITLES - 1)
        # Live Netflix channels: never counted, never carded.
        for i in range(5):
            add(f"nf-live-{i}", "Netflix", media_type="live",
                title=f"Netflix Live {i}", key=f"nf:live-{i}", added=10_000 + i)

        for i in range(TUBI_VOD_TITLES):
            add(f"tubi-{i}", "Tubi", title=f"Tubi Title {i:03d}",
                key=f"tubi:title-{i}", added=i)
        for i in range(TUBI_LIVE_CHANNELS):
            add(f"tubi-live-{i}", "Tubi", media_type="live",
                title=f"Tubi Live {i:03d}", key=f"tubi:live-{i}", added=i)

        for i in range(OTHER_STREAMING_TITLES):
            add(f"os-{i}", "Other Streaming", title=f"Other Title {i:03d}",
                key=f"os:title-{i}", added=i)

        for i in range(HIDDEN_DISNEY_TITLES):
            add(f"dis-{i}", "Disney+", provider="p2",
                title=f"Disney Title {i:03d}", key=f"dis:title-{i}", added=i)
        # Netflix rows on the deactivated source: excluded from the count AND
        # from the cards.
        for i in range(3):
            add(f"nf-hidden-{i}", "Netflix", provider="p2",
                title=f"Hidden Netflix Title {i}", key=f"nfh:title-{i}",
                added=99_000 + i)

    return db


def _config(tmp_path, **overrides):
    from metatv.core.config import Config

    cfg = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
                 cache_dir=tmp_path / "cache")
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _hidden_provider_ids(db):
    """The canonical hidden-source gate: inactive u expired sources."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as s:
        return RepositoryFactory(s).providers.get_hidden_provider_ids()


def _values(db, cfg, min_titles):
    from metatv.core.visibility_resolver import resolve_scope

    hidden = _hidden_provider_ids(db)
    with db.session_scope() as s:
        return platform_shelf_values(
            s, min_titles=min_titles,
            excluded_values=PLATFORM_SHELF_EXCLUDED_VALUES,
            scope=resolve_scope(s, cfg, excluded_provider_ids=hidden),
        )


# ---------------------------------------------------------------------------
# Which platforms qualify
# ---------------------------------------------------------------------------

def test_at_fifty_only_netflix_clears_the_floor(platform_db, tmp_path):
    """The shipped default. Netflix has 60 titles; nothing else has 50."""
    assert _values(platform_db, _config(tmp_path), 50) == [("Netflix", NETFLIX_TITLES)]


def test_lowering_the_floor_to_fifteen_lets_tubi_in(platform_db, tmp_path):
    """The setting has to actually move the answer, or it is decoration."""
    got = _values(platform_db, _config(tmp_path), 15)
    assert got == [("Netflix", NETFLIX_TITLES), ("Tubi", TUBI_VOD_TITLES)], (
        "lowering the threshold must admit Tubi, ordered by count desc"
    )


def test_other_streaming_never_qualifies_however_large(platform_db, tmp_path):
    """The curated exclusion (owner Q5) beats the count — and the fixture makes
    "Other Streaming" the BIGGEST bucket, so a dropped gate is loud."""
    for floor in (1, 15, 50):
        names = [value for value, _n in _values(platform_db, _config(tmp_path), floor)]
        assert "Other Streaming" not in names, f"excluded value admitted at {floor}"
    assert PLATFORM_SHELF_EXCLUDED_VALUES == frozenset(
        {"Other Streaming", "Pay TV", "SC", "EAR"})


def test_live_channels_are_not_counted_towards_the_floor(platform_db, tmp_path):
    """Tubi has 20 VOD titles and 40 live channels.

    60 rows would clear a 50 floor; 20 titles must not. This is the whole
    media-type gate in one assertion — Discover is the VOD surface (Q2).
    """
    names = [value for value, _n in _values(platform_db, _config(tmp_path), 50)]
    assert "Tubi" not in names, (
        "live channels were counted — Tubi's 40 live rows pushed it over 50"
    )
    assert PLATFORM_SHELF_MEDIA_TYPES == ("movie", "series")


def test_versions_of_one_title_count_once(platform_db, tmp_path):
    """60 Netflix titles across 62 rows must count as 60, not 62."""
    got = dict(_values(platform_db, _config(tmp_path), 5))
    assert got["Netflix"] == NETFLIX_TITLES, (
        "the count is rows, not distinct content_key titles"
    )


def test_a_deactivated_source_contributes_nothing(platform_db, tmp_path):
    """Disney+ has 70 titles, all on a deactivated source. A disabled source is
    an absolute gate — its content is never shown and never counted."""
    names = [value for value, _n in _values(platform_db, _config(tmp_path), 50)]
    assert "Disney+" not in names, "hidden-provider rows reached the threshold"


def test_global_exclusions_reach_the_threshold_query(platform_db, tmp_path):
    """Discover must honour Global Exclusions (#778).

    Excluding the Netflix titles by keyword drops Netflix below 50 — proof the
    scope is threaded rather than merely accepted.
    """
    cfg = _config(tmp_path, global_excluded_keywords=["Netflix Title"])
    names = [value for value, _n in _values(platform_db, cfg, 50)]
    assert "Netflix" not in names, (
        "a keyword exclusion did not reach the platform-shelf count"
    )


# ---------------------------------------------------------------------------
# What lands on the shelf
# ---------------------------------------------------------------------------

def _netflix_cards(db, cfg, limit=30):
    from metatv.gui.discover_workers import fetch_cards_for_key

    with db.session_scope() as s:
        return fetch_cards_for_key(s, cfg, "platform:Netflix", limit,
                                   sk={}, fk={}, af={}, ek={})


def test_the_shelf_shows_the_platform_and_only_vod(platform_db, tmp_path):
    cards = _netflix_cards(platform_db, _config(tmp_path))
    assert cards, "the platform: key must route to a real query"
    assert {c.media_type for c in cards} <= {"movie", "series"}
    assert not [c for c in cards if c.title.startswith("Netflix Live")], (
        "a live channel reached a Discover platform shelf"
    )


def test_the_shelf_leads_with_the_newest_title(platform_db, tmp_path):
    """``detected_added`` desc (DB-4, indexed) — "what did Netflix add"."""
    cards = _netflix_cards(platform_db, _config(tmp_path))
    assert cards[0].title == f"Netflix Title {NETFLIX_TITLES - 1:03d}"
    assert cards[1].title == f"Netflix Title {NETFLIX_TITLES - 2:03d}", (
        "the shelf is not ordered newest-first"
    )


def test_a_title_with_three_versions_is_one_card(platform_db, tmp_path):
    cards = _netflix_cards(platform_db, _config(tmp_path))
    newest = f"Netflix Title {NETFLIX_TITLES - 1:03d}"
    matching = [c for c in cards if c.title == newest]
    assert len(matching) == 1, f"three versions produced {len(matching)} cards"
    assert matching[0].variant_count == 3, (
        "the surviving card must report how many versions it stands for"
    )
    assert len({c.title for c in cards}) == len(cards), "duplicate titles on the strip"


def test_a_deactivated_source_never_reaches_the_cards(platform_db, tmp_path):
    """The hidden source's Netflix rows are the NEWEST in the library, so they
    would lead the strip if the provider gate were missing."""
    cards = _netflix_cards(platform_db, _config(tmp_path))
    assert not [c for c in cards if c.title.startswith("Hidden Netflix")], (
        "content from a deactivated source reached a platform shelf"
    )


def test_representative_version_preserves_order(platform_db, tmp_path):
    """The VP-1 seam is identity TODAY, and the contract it will keep is that it
    returns the same cards — reordered, never dropped or duplicated."""
    cards = _netflix_cards(platform_db, _config(tmp_path))
    out = representative_version(cards)
    assert [c.channel_id for c in out] == [c.channel_id for c in cards]


# ---------------------------------------------------------------------------
# Enumeration into Discover
# ---------------------------------------------------------------------------

def _shelves(db, cfg, *, pinned=frozenset()):
    from metatv.gui.discover_workers import _LoaderWorker, _ZoneSnapshot

    worker = _LoaderWorker(db, cfg, zone_snapshot=_ZoneSnapshot(
        pinned=frozenset(pinned),
        collapsed=frozenset({"recommended", "recently_added",
                             "top_movies", "top_series"}),
    ))
    out: list = []
    worker.shelfReady.connect(out.append)
    worker.run()
    return out


def test_the_loader_emits_one_shelf_per_qualifying_platform(platform_db, tmp_path, qapp):
    keys = [s.shelf_key for s in _shelves(platform_db, _config(tmp_path))]
    platform_keys = [k for k in keys if k.startswith("platform:")]
    assert platform_keys == ["platform:Netflix"], platform_keys


def test_lowering_the_setting_re_enumerates_the_shelves(platform_db, tmp_path, qapp):
    """The setting drives the ENUMERATION, not just a number in a file."""
    cfg = _config(tmp_path, discover_platform_shelf_min_titles=15)
    keys = [s.shelf_key for s in _shelves(platform_db, cfg)]
    platform_keys = [k for k in keys if k.startswith("platform:")]
    assert platform_keys == ["platform:Netflix", "platform:Tubi"], platform_keys


def test_a_pinned_platform_shelf_carries_cards_titled_by_the_value(
        platform_db, tmp_path, qapp):
    """Pinning forces the eager fetch, so this proves the shelf's title is the
    bare platform name — never the raw ``platform:Netflix`` key."""
    shelves = _shelves(platform_db, _config(tmp_path), pinned={"platform:Netflix"})
    shelf = next(s for s in shelves if s.shelf_key == "platform:Netflix")
    assert shelf.header_only is False
    assert shelf.cards, "a pinned shelf must be fetched eagerly"
    assert shelf.title == "Netflix"


def test_a_hidden_platform_shelf_is_not_emitted(platform_db, tmp_path, qapp):
    from metatv.gui.discover_workers import _LoaderWorker, _ZoneSnapshot

    worker = _LoaderWorker(platform_db, _config(tmp_path), zone_snapshot=_ZoneSnapshot(
        hidden=frozenset({"platform:Netflix"}),
    ))
    out: list = []
    worker.shelfReady.connect(out.append)
    worker.run()
    assert "platform:Netflix" not in [s.shelf_key for s in out]


# ---------------------------------------------------------------------------
# Rendered appearance — the header actually paints the platform name
# ---------------------------------------------------------------------------

def _painted_pixels(widget) -> int:
    """How many pixels the widget actually draws.

    Rendering is the point: a title label can hold the right STRING and paint
    nothing (zero-width, elided into oblivion, hidden). This counts ink.
    """
    from PyQt6.QtGui import QImage

    widget.adjustSize()
    size = widget.size()
    image = QImage(max(size.width(), 1), max(size.height(), 1),
                   QImage.Format.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 0
    )


def test_the_shelf_header_renders_the_platform_name(qtbot, tmp_path):
    """Rendered-appearance assertion (CLAUDE.md: UI slices must have one).

    Against the pre-PLAT-1 code there is no platform shelf at all, so nothing
    reaches this widget; the claim it pins going forward is that the header
    paints "Netflix" — inked, wide enough to hold the word — and never the
    internal key.
    """
    from PyQt6.QtGui import QFontMetrics

    from metatv.gui.discover_shelf import _Shelf

    shelf = _Shelf("Netflix", "platform:Netflix", [], image_cache=None,
                   config=_config(tmp_path), collapsed=False)
    qtbot.addWidget(shelf)

    label = shelf._title_lbl
    assert "Netflix" in label.text()
    assert "platform:" not in label.text(), (
        "the header is showing the internal shelf key, not the platform"
    )
    assert label.isVisibleTo(shelf)

    advance = QFontMetrics(label.font()).horizontalAdvance("Netflix")
    assert label.sizeHint().width() >= advance > 0
    assert label.sizeHint().height() > 0
    assert _painted_pixels(label) > 0, "the header label paints nothing"

    # The control: an empty header paints nothing, so the count above is
    # measuring ink rather than measuring "a widget exists".
    blank = _Shelf("", "platform:", [], image_cache=None,
                   config=_config(tmp_path), collapsed=False)
    qtbot.addWidget(blank)
    assert _painted_pixels(blank._title_lbl) == 0


def test_see_all_titles_the_browse_view_with_the_platform_name():
    """The drill-down header must not leak the key either.

    ``DiscoverView._on_see_all`` now asks this one function, so the heading in
    the browse grid and the heading on the strip cannot disagree.
    """
    from metatv.gui.discover_workers import browse_title_for_key

    assert browse_title_for_key("platform:Netflix") == "Netflix"
    assert browse_title_for_key("platform:Apple TV+") == "Apple TV+"
    # The families that already worked must keep working — this function is an
    # extraction of the chain that lived inline, not a rewrite of it.
    assert browse_title_for_key("genre:Action") == "Action"
    assert browse_title_for_key("decade:1990") == "1990s"
    assert browse_title_for_key("actor:Toni Collette") == "Featuring Toni Collette"
    assert browse_title_for_key("collection:Apple+ Kids") == "Apple+ Kids"
    assert browse_title_for_key("recently_added") == "Recently Added"
    assert browse_title_for_key("top_movies") == "Top Rated Movies"
    assert browse_title_for_key("top_series") == "Top Rated Series"
    # And an unknown namespace still falls back to the key rather than raising.
    assert browse_title_for_key("something_new") == "something_new"


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------

def test_the_threshold_defaults_to_fifty(tmp_path):
    assert _config(tmp_path).discover_platform_shelf_min_titles == 50


def test_the_settings_spin_round_trips_through_config(qapp):
    """Load from config, save back to it — using the REAL SettingsDialog, so
    the Content tab actually builds and the conftest factory cannot drift."""
    from metatv.gui.settings_dialog import SettingsDialog
    from tests.conftest import settings_config_double

    cfg = settings_config_double(discover_platform_shelf_min_titles=120)
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._platform_shelf_min_spin.value() == 120, (
            "the spin did not load the stored threshold"
        )
        assert dlg._platform_shelf_min_spin.minimum() == 5
        assert dlg._platform_shelf_min_spin.maximum() == 1000
        assert dlg._platform_shelf_min_spin.singleStep() == 5
        assert dlg._platform_shelf_min_spin.suffix() == " titles"
        assert dlg._platform_shelf_min_spin.toolTip(), "every control needs a tooltip"

        dlg._platform_shelf_min_spin.setValue(35)
        dlg._save_values()
        assert cfg.discover_platform_shelf_min_titles == 35, (
            "the spin did not save back to config"
        )
    finally:
        dlg.close()


def test_applying_settings_rebuilds_discover():
    """A threshold that saves but never rebuilds the shelves is no control.

    Runs the REAL handler off ``MainWindow``, through the REAL
    ``settings_apply.run`` list, so a rename in either place fails here.
    """
    from metatv.gui import settings_apply
    from metatv.gui.main_window import MainWindow

    assert "_apply_discover_reload_setting" in settings_apply.HANDLERS

    reloads: list[str] = []
    host = SimpleNamespace(
        load_channels=lambda: None,
        discover_view=SimpleNamespace(reload=lambda: reloads.append("reload")),
    )
    for name in settings_apply.HANDLERS:
        if name != "_apply_discover_reload_setting":
            setattr(host, name, lambda: None)
    host._apply_discover_reload_setting = (
        MainWindow._apply_discover_reload_setting.__get__(host)
    )

    settings_apply.run(host)
    assert reloads == ["reload"], "OK did not rebuild the Discover shelves"
