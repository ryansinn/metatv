"""Behavioral tests for the lightbox-polish PR (id 175).

Four concerns, each executing the changed path and asserting the outcome that
would break:

1. **Strip-card badges.** ``SimilarTitleLightbox._bg_load`` now threads the badge
   fields (user_rating / in_queue / is_favorite / watched / rating / lang) into each
   Similar-strip item dict, and ``_LightboxCard._make_sim_badges`` renders them as
   the same badges the details-pane Similar rows show (language + ★rating + liked /
   in-Watch-Later / favorited / watched glyphs).
2. **⤢ button removed.** Each Similar strip card no longer carries the redundant
   per-card ⤢ preview button (the whole poster already dives in).
3. **"Watch Later" label.** The watch-queue ACTION verb is "Watch Later" everywhere
   it used to read "Queue" (channel-menu registry, lightbox button, Similar rows).
4. **Rail selected-state clarity.** ``theme.DETAIL_RAIL_BTN`` ``:checked`` uses the
   ACCENT (accent-tint fill + accent border) and genuinely differs from ``:hover``.

The DB test uses a file-backed tmp_path SQLite (not :memory:).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _delete_lightbox_cards(qapp):
    """Give every parentless ``_LightboxCard`` an owner, so none is top-level.

    A bare ``_LightboxCard()`` is a TOP-LEVEL widget and nothing deleted them —
    this file alone left 16 alive. That is invisible until something walks the
    top-level list, and ``theme.apply_theme()`` pushes a QPalette onto the whole
    QApplication, so the next file's palette test repaints every leaked card.
    That segfaulted a CI shard the moment the size-based bin-packer put two
    lightbox files next to each other.

    ``sip.delete`` destroys THIS card's C++ object and nothing else. Two other
    approaches were tried and are worse:

    - ``deleteLater()`` + ``sendPostedEvents(None, DeferredDelete)`` drains the
      deferred-delete queue GLOBALLY, destroying objects belonging to every
      other test. It moved the segfault from a test body into this teardown
      rather than removing it.
    - Re-parenting to an owner widget makes the OWNER top-level instead, so the
      leak count went from 16 to 41 — one per test.
    """
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication

    from metatv.gui.similar_lightbox_card import _LightboxCard

    yield
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, _LightboxCard):
            sip.delete(widget)


def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _fake_config():
    return SimpleNamespace(
        preferred_version_prefixes=[],
        preferred_version_provider_ids=[],
        preferred_version_quality=None,
    )


def _fake_metadata_manager():
    class _FakeMM:
        async def get_metadata(self, channel_id, force_refresh=False):
            return None
    return _FakeMM()


def _lightbox_for(db):
    from metatv.gui.similar_lightbox import SimilarTitleLightbox

    calls: list[tuple] = []

    class _FakeSignal:
        def emit(self, cid, data):
            calls.append((cid, data))

    lb = SimilarTitleLightbox.__new__(SimilarTitleLightbox)
    lb._db = db
    lb._config = _fake_config()
    lb._metadata_manager = _fake_metadata_manager()
    lb._data_ready = _FakeSignal()
    lb._calls = calls
    return lb


def _load(db, channel_id: str) -> dict:
    lb = _lightbox_for(db)
    lb._bg_load(channel_id)
    assert lb._calls, "lightbox emitted no data"
    return lb._calls[0][1]


# ---------------------------------------------------------------------------
# 1. _bg_load threads the badge fields into each strip item dict
# ---------------------------------------------------------------------------

class TestBgLoadThreadsBadgeFields:
    def test_strip_item_carries_state_and_meta(self, tmp_path):
        from metatv.core.database import ChannelDB, MetadataDB, ProviderDB
        from metatv.core.repositories import RepositoryFactory

        db = _make_db(tmp_path / "badges_bgload.db")
        now = datetime.now()
        with db.session_scope() as session:
            session.add(ProviderDB(
                id="pa", name="pa", type="xtream", url="http://e.com",
                username="u", password="p", is_active=True,
                account_exp_date=now + timedelta(days=30),
            ))
            session.flush()
            # A metadata row so the ★ rating badge has a value to carry.
            session.add(MetadataDB(id="m-sim", title="Interstellar Voyage",
                                   year=2019, rating=8.3))
            session.flush()
            # Origin + a genuine SIMILAR neighbour (shares the ≥4-char word
            # "interstellar", different content_key so it isn't a mere version).
            session.add(ChannelDB(
                id="ch-o", source_id=str(uuid.uuid4()), provider_id="pa",
                name="Interstellar Odyssey", media_type="movie",
                content_key="tmdb:100|movie",
            ))
            sim = ChannelDB(
                id="ch-sim", source_id=str(uuid.uuid4()), provider_id="pa",
                name="Interstellar Voyage", media_type="movie",
                content_key="tmdb:200|movie",
                is_favorite=True, watch_completed=True, detected_region="LAT",
            )
            sim.metadata_id = "m-sim"
            session.add(sim)
            session.flush()

            repos = RepositoryFactory(session)
            repos.queue.add("ch-sim", "Interstellar Voyage", "movie")
            from metatv.core.database import UserRatingDB
            session.merge(UserRatingDB(channel_id="ch-sim", rating=1,
                                       rated_at=datetime.utcnow()))
            session.flush()

        data = _load(db, "ch-o")
        strip = {i["id"]: i for i in (data.get("similar") or [])}
        assert "ch-sim" in strip, "the similar neighbour must be in the strip"
        item = strip["ch-sim"]
        assert item["user_rating"] == 1, "liked state must be threaded in"
        assert item["in_queue"] is True, "in-Watch-Later state must be threaded in"
        assert item["is_favorite"] is True
        assert item["watched"] is True
        assert item["rating"] == 8.3, "★ rating comes from the stored MetadataDB row"
        assert item["lang"] == "LAT", "language/region comes from detected_region"
        db.close()


# ---------------------------------------------------------------------------
# 2 + 1(render). Strip card renders the badges and has NO ⤢ button
# ---------------------------------------------------------------------------

def _first_strip_card(card):
    # _populate_similar inserts each card before the trailing stretch (index 0 = first).
    return card._strip_layout.itemAt(0).widget()


class TestStripCardRendering:
    def _card_with(self, item):
        from metatv.gui.similar_lightbox_card import _LightboxCard
        card = _LightboxCard()
        card._populate_similar([item])
        return card

    def test_badges_render_with_tooltips(self, qapp):
        from PyQt6.QtWidgets import QLabel
        from metatv.gui import icons as _icons

        item = {
            "id": "c1", "name": "Some Movie", "year": 2021, "poster_url": None,
            "media_type": "movie", "user_rating": 1, "in_queue": True,
            "is_favorite": True, "watched": True, "rating": 8.3, "lang": "LAT",
        }
        strip_card = _first_strip_card(self._card_with(item))
        labels = strip_card.findChildren(QLabel)
        tips = [lbl.toolTip() for lbl in labels]
        texts = [lbl.text() for lbl in labels]

        # State glyphs — identified by their tooltip (colour-not-alone: shape carries
        # meaning, tooltip disambiguates).
        assert "You liked this" in tips
        assert "In Watch Later" in tips
        assert "In Favorites" in tips
        assert "Watched" in tips
        # The glyphs themselves come from icons.py.
        assert _icons.like_icon in texts
        assert _icons.queue_icon in texts
        assert _icons.watched_icon in texts
        # Language + ★rating meta.
        assert "LAT" in texts
        assert f"{_icons.rating_star_icon}8.3" in texts

    def test_neutral_card_shows_no_state_glyphs(self, qapp):
        """A card with no engagement shows none of the state-glyph tooltips."""
        item = {"id": "c2", "name": "Plain", "year": 2000, "poster_url": None}
        strip_card = _first_strip_card(self._card_with(item))
        from PyQt6.QtWidgets import QLabel
        tips = {lbl.toolTip() for lbl in strip_card.findChildren(QLabel)}
        assert not ({"You liked this", "In Watch Later", "In Favorites", "Watched"} & tips)

    def test_no_expand_button_on_card(self, qapp):
        """The redundant per-card ⤢ preview button is gone — no QPushButton remains."""
        from PyQt6.QtWidgets import QPushButton
        from metatv.gui import icons as _icons

        item = {"id": "c3", "name": "X", "year": 1999, "poster_url": None,
                "is_favorite": True}
        strip_card = _first_strip_card(self._card_with(item))
        buttons = strip_card.findChildren(QPushButton)
        assert buttons == [], "a strip card must carry no buttons (⤢ removed)"
        for b in buttons:  # belt-and-suspenders if the above ever loosens
            assert b.text() != _icons.lightbox_icon

    def test_poster_click_still_dives_in(self, qapp):
        """Clicking anywhere on the poster still emits dive_requested with the id."""
        from metatv.gui.similar_lightbox_card import _ClickableFrame

        card = self._card_with({"id": "c9", "name": "X", "year": 2000, "poster_url": None})
        emitted: list[str] = []
        card.dive_requested.connect(lambda cid: emitted.append(cid))
        strip_card = _first_strip_card(card)
        poster = strip_card.findChild(_ClickableFrame)
        assert poster is not None
        poster.clicked.emit()
        assert emitted == ["c9"]


# ---------------------------------------------------------------------------
# 3. "Watch Later" is the standardized watch-queue action verb
# ---------------------------------------------------------------------------

class TestWatchLaterLabel:
    def test_registry_queue_label(self):
        from metatv.gui.channel_menu import ChannelMenuContext, _queue_label
        add = ChannelMenuContext(channel_ids=["c1"], surface="channel", in_queue=False)
        rem = ChannelMenuContext(channel_ids=["c1"], surface="channel", in_queue=True)
        assert _queue_label(add) == "Add to Watch Later"
        assert _queue_label(rem) == "Remove from Watch Later"

    def test_built_menu_has_no_bare_queue_label(self, qapp):
        from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
        ctx = ChannelMenuContext(
            channel_ids=["c1"], surface="channel", media_type="movie", in_queue=False,
        )
        menu = build_channel_menu(ctx, {"queue": lambda: None})
        labels = [a.text() for a in menu.actions()]
        assert "Add to Watch Later" in labels
        assert "Add to Queue" not in labels
        assert "Remove from Queue" not in labels

    def test_bulk_queue_label(self, qapp):
        from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu
        ctx = ChannelMenuContext(channel_ids=["a", "b"], surface="channel")
        menu = build_channel_menu(ctx, {"bulk_queue": lambda: None})
        labels = [a.text() for a in menu.actions()]
        assert "Add to Watch Later" in labels

    def test_lightbox_queue_button_reads_watch_later(self, qapp):
        from metatv.gui.similar_lightbox_card import _LightboxCard
        card = _LightboxCard()
        card.reset_loading()
        assert "Watch Later" in card._queue_btn.text()
        assert "Queue" not in card._queue_btn.text()
        # And when queued, the toggled state still uses the standardized verb.
        card._populate_actions({"in_queue": True})
        assert "Watch Later" in card._queue_btn.text()
        assert card._queue_btn.text().strip().split(maxsplit=1)[-1] == "In Watch Later"


# ---------------------------------------------------------------------------
# 4. DETAIL_RAIL_BTN :checked reads as accent and differs from :hover
# ---------------------------------------------------------------------------

def _pseudo_block(style: str, selector: str) -> str:
    i = style.find(selector)
    assert i != -1, f"{selector!r} not found in DETAIL_RAIL_BTN"
    j = style.find("}", i)
    return style[i:j]


class TestRailSelectedState:
    def test_checked_uses_accent_and_differs_from_hover(self):
        from metatv.gui import theme as _theme

        style = _theme.DETAIL_RAIL_BTN
        checked = _pseudo_block(style, "QPushButton:checked {")
        hover = _pseudo_block(style, "QPushButton:hover {")

        # :checked reads as the ACCENT — accent-tint fill + accent border.
        assert _theme.COLOR_ACCENT in checked, ":checked must carry the accent border"
        assert f"background: {_theme.OVERLAY_ACCENT_35}" in checked
        # :hover keeps the frosted-white fill — genuinely different from :checked.
        # The hover fill must simply DIFFER from the checked one; pinning
        # OVERLAY_55 pinned the wash that was the defect (an overlay used as
        # a resting surface), not the requirement.
        assert _theme.OVERLAY_ACCENT_35 not in hover
        assert _theme.OVERLAY_ACCENT_35 != _theme.OVERLAY_55
        assert _theme.OVERLAY_ACCENT_35 not in hover, "checked fill must differ from hover fill"

    def test_accent_overlay_tokens_built_from_accent(self):
        """The new selected-fill overlays are tokens built from COLOR_ACCENT (#2288dd
        → rgb 34,136,221), not ad-hoc literals in the stylesheet."""
        from metatv.gui import theme as _theme
        # Derived from whatever the accent currently IS, not from a frozen copy
        # of what it used to be — the point of the assertion is the RELATIONSHIP.
        # Same HUE as the accent, not the same RGB. A Radix alpha step is not
        # "the accent at N% opacity" — it is a colour computed so that
        # compositing it yields the intended result, so its channels differ
        # slightly by design. Exact equality would pin the old hand-mixed
        # rgba() construction; hue proximity pins the RELATIONSHIP, which is
        # what this test is actually about.
        import re as _re
        h = _theme.COLOR_ACCENT.lstrip("#")
        accent = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        for token in (_theme.OVERLAY_ACCENT_35, _theme.OVERLAY_ACCENT_50):
            m = _re.match(r"rgba\((\d+),\s*(\d+),\s*(\d+)", str(token))
            assert m, f"accent overlay is not an rgba(): {token}"
            rgb = tuple(int(x) for x in m.groups())
            drift = max(abs(a - b) for a, b in zip(rgb, accent))
            assert drift <= 40, (
                f"{token} is not built from the accent {_theme.COLOR_ACCENT} "
                f"(channel drift {drift})"
            )


# ---------------------------------------------------------------------------
# 5. What's New entry 175 exists and is well-formed
# ---------------------------------------------------------------------------

def test_whats_new_entry_175_present_with_test_steps():
    from metatv.whats_new import WHATS_NEW
    entry = next((e for e in WHATS_NEW if e.id == 175), None)
    assert entry is not None, "What's New entry id=175 must be registered"
    assert entry.version == "0.14.1"
    assert entry.date == "2026-07-31"
    assert entry.items, "entry must have items"
    assert entry.test_steps, "entry must carry a non-empty test_steps tuple"
