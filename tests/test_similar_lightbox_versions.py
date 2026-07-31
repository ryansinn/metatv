"""Behavioral tests for the COMPACT "Other Versions" chips in the Similar-Titles lightbox.

The old row rendered each content_key sibling as a full-width pill repeating the
identical ``<token> <title> (<year>) · <source>`` N× — pure wasted space when the
title/year/source are the same across every version. The redesign renders each
version as a compact chip carrying ONLY the distinguishing token (+ the source's
icon glyph / colour as a badge), moves them into the hero's upper-right, and puts
the full "<name> · <source>" detail in the tooltip.

Four concerns, each asserting the outcome that would break the old code:

1. **Compact chip text.** A chip's VISIBLE text is the token (not the repeated
   ``<title> (<year>) · <source>`` string); the full name + source live in the tooltip.
2. **Source badge threaded from the chokepoint.** ``get_content_key_siblings`` returns
   each sibling's ``provider_icon``/``provider_color`` (real Database on tmp_path with a
   provider that has icon + colour set) — the single query, not a second hand-rolled one.
3. **Overlay passes the badge through.** ``_bg_load`` carries ``provider_icon``/
   ``provider_color`` into each ``versions`` dict.
4. **Click still dives.** Clicking a chip emits ``dive_requested`` with the sibling id.

All DB tests use a file-backed tmp_path SQLite (not :memory:).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


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


def _make_provider(session, pid, *, is_active=True, exp=None, icon="", color=""):
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active, account_exp_date=exp,
        icon=icon, color=color,
    ))
    session.flush()


def _make_channel(session, *, cid, name, provider_id, content_key,
                  media_type="movie", detected_quality=None, detected_region=None):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=cid, source_id=str(uuid.uuid4()), provider_id=provider_id,
        name=name, media_type=media_type, content_key=content_key,
        detected_quality=detected_quality, detected_region=detected_region,
    )
    session.add(ch)
    session.flush()
    return ch


def _lightbox_for(db):
    """A SimilarTitleLightbox with only the attrs ``_bg_load`` touches (no Qt tree)."""
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


# ---------------------------------------------------------------------------
# 1. Friendly version rows — "<source> · <token>" text + full-detail tooltip
# ---------------------------------------------------------------------------

class TestVersionRow:
    def _rows(self, card):
        from PyQt6.QtWidgets import QPushButton
        return [
            card._versions_list.itemAt(i).widget()
            for i in range(card._versions_list.count())
            if isinstance(card._versions_list.itemAt(i).widget(), QPushButton)
        ]

    def _card_with_version(self, v):
        from metatv.gui.similar_lightbox_card import _LightboxCard
        card = _LightboxCard()
        card._populate_versions([v])
        return card

    def test_visible_text_is_friendly_source_and_token(self, qapp):
        v = {
            "id": "v1", "name": "September 5 (2024)", "tag": "4K",
            "provider_name": "TREX Shared", "provider_icon": "🔥", "provider_color": "#e0563a",
        }
        card = self._card_with_version(v)
        rows = self._rows(card)
        assert len(rows) == 1
        text = rows[0].text()

        # Friendly, readable label — the source name AND the distinguishing token,
        # never a bare 2-char code.
        assert "TREX Shared" in text, f"the row must show the friendly source name; got {text!r}"
        assert "4K" in text, f"the row must show its distinguishing token; got {text!r}"
        # The identical-across-versions raw title/year is NOT repeated on the row.
        assert "September 5" not in text, f"the repeated title must not be on the row; got {text!r}"
        assert "(2024)" not in text, f"the repeated year must not be on the row; got {text!r}"

    def test_tooltip_carries_full_name_and_source(self, qapp):
        v = {
            "id": "v1", "name": "September 5 (2024)", "tag": "4K",
            "provider_name": "TREX Shared", "provider_icon": "🔥", "provider_color": "#e0563a",
        }
        card = self._card_with_version(v)
        tip = self._rows(card)[0].toolTip()
        assert "September 5 (2024)" in tip, f"tooltip must carry the full name; got {tip!r}"
        assert "TREX Shared" in tip, f"tooltip must carry the source; got {tip!r}"

    def test_source_icon_glyph_shown_on_row(self, qapp):
        v = {"id": "v1", "name": "X (2024)", "tag": "AR",
             "provider_name": "ProSat", "provider_icon": "⭐", "provider_color": "#4a8fe0"}
        card = self._card_with_version(v)
        text = self._rows(card)[0].text()
        assert "⭐" in text, f"the source icon glyph must appear on the row; got {text!r}"
        assert "ProSat" in text
        assert "AR" in text

    def test_color_source_tints_left_border_badge(self, qapp):
        """A provider colour is injected as a left-border source badge; the friendly
        text is always present, so the row never distinguishes by colour alone."""
        v = {"id": "v1", "name": "X (2024)", "tag": "DE",
             "provider_name": "Zeus", "provider_icon": "", "provider_color": "#8a5ad0"}
        card = self._card_with_version(v)
        row = self._rows(card)[0]
        assert row.text() == "Zeus · DE", "friendly label = source · token (never colour alone)"
        assert "#8a5ad0" in row.styleSheet(), "provider colour must tint the row as a source badge"
        assert "border-left" in row.styleSheet()

    def test_no_badge_source_shows_plain_row(self, qapp):
        v = {"id": "v1", "name": "X (2024)", "tag": "HD",
             "provider_name": "Bare", "provider_icon": "", "provider_color": ""}
        card = self._card_with_version(v)
        row = self._rows(card)[0]
        assert row.text() == "Bare · HD"
        assert "border-left" not in row.styleSheet(), "no colour → no accent border"

    def test_header_counts_versions_and_column_visible(self, qapp):
        from metatv.gui.similar_lightbox_card import _LightboxCard
        card = _LightboxCard()
        card._populate_versions([
            {"id": f"v{i}", "name": "Same (2024)", "tag": t, "provider_name": "P",
             "provider_icon": "", "provider_color": ""}
            for i, t in enumerate(["4K", "AR", "DE"])
        ])
        assert card._versions_hdr.text() == "OTHER VERSIONS (3)"
        assert len(self._rows(card)) == 3, "one row per version"
        assert card._versions_col_w.isVisible() or not card._versions_col_w.isHidden()

    def test_empty_versions_hides_column(self, qapp):
        from metatv.gui.similar_lightbox_card import _LightboxCard
        card = _LightboxCard()
        card._populate_versions([])
        assert card._versions_col_w.isHidden(), "no versions → the whole column is hidden"


# ---------------------------------------------------------------------------
# 2. Source badge threaded through the single sibling chokepoint
# ---------------------------------------------------------------------------

class TestSiblingChokepointCarriesBadge:
    def test_siblings_include_provider_icon_and_color(self, tmp_path):
        from metatv.core.repositories import RepositoryFactory

        db = _make_db(tmp_path / "sib_badge.db")
        ck = "tmdb:63|movie"
        with db.session_scope() as session:
            _make_provider(session, "p-src", icon="🔥", color="#e0563a")
            _make_channel(session, cid="ch-origin", name="12 Monkeys",
                          provider_id="p-src", content_key=ck)
            _make_channel(session, cid="sib", name="12 Monos (LATINO)",
                          provider_id="p-src", content_key=ck, detected_region="LAT")

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            siblings = repos.channels.get_content_key_siblings(ck, "ch-origin")

        assert siblings, "expected one sibling"
        s = siblings[0]
        assert s["id"] == "sib"
        assert s.get("provider_icon") == "🔥", "the chokepoint must carry the provider icon glyph"
        assert s.get("provider_color") == "#e0563a", "the chokepoint must carry the provider colour"
        db.close()

    def test_siblings_default_badge_fields_when_unset(self, tmp_path):
        """A provider with no icon/colour yields empty strings (never missing keys / None)."""
        from metatv.core.repositories import RepositoryFactory

        db = _make_db(tmp_path / "sib_nobadge.db")
        ck = "tmdb:7|movie"
        with db.session_scope() as session:
            _make_provider(session, "p-bare")  # no icon/color
            _make_channel(session, cid="o", name="Origin", provider_id="p-bare", content_key=ck)
            _make_channel(session, cid="sib2", name="Origin 4K", provider_id="p-bare",
                          content_key=ck, detected_quality="4K")

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            s = repos.channels.get_content_key_siblings(ck, "o")[0]

        assert s.get("provider_icon") == ""
        assert s.get("provider_color") == ""
        db.close()


# ---------------------------------------------------------------------------
# 3. The overlay threads the badge into each versions dict
# ---------------------------------------------------------------------------

class TestOverlayThreadsBadge:
    def test_bg_load_versions_carry_icon_and_color(self, tmp_path):
        db = _make_db(tmp_path / "bg_badge.db")
        ck = "tmdb:63|movie"
        now = datetime.now()
        with db.session_scope() as session:
            _make_provider(session, "p-a", is_active=True, exp=now + timedelta(days=30),
                           icon="⭐", color="#4a8fe0")
            _make_channel(session, cid="ch-origin", name="12 Monkeys",
                          provider_id="p-a", content_key=ck)
            _make_channel(session, cid="sib", name="12 Monos (LATINO)",
                          provider_id="p-a", content_key=ck, detected_region="LAT")

        lb = _lightbox_for(db)
        lb._bg_load("ch-origin")
        data = lb._calls[0][1]
        versions = data.get("versions") or []
        assert versions, "expected one scoped version"
        v = versions[0]
        assert v["id"] == "sib"
        assert v.get("provider_icon") == "⭐", "overlay must thread the provider icon into the chip dict"
        assert v.get("provider_color") == "#4a8fe0", "overlay must thread the provider colour"
        assert v.get("tag") == "LAT"
        db.close()


# ---------------------------------------------------------------------------
# 4. Clicking a chip still dives to that version
# ---------------------------------------------------------------------------

class TestChipClickNavigates:
    def test_click_emits_dive_with_channel_id(self, qapp):
        from metatv.gui.similar_lightbox_card import _LightboxCard

        card = _LightboxCard()
        card._populate_versions([
            {"id": "v1", "name": "September 5 (2024)", "tag": "4K",
             "provider_name": "TREX", "provider_icon": "🔥", "provider_color": "#e0563a"},
            {"id": "v2", "name": "September 5 (2024)", "tag": "ES",
             "provider_name": "ProSat", "provider_icon": "⭐", "provider_color": "#4a8fe0"},
        ])

        emitted: list[str] = []
        card.dive_requested.connect(emitted.append)

        # The second row must dive to "v2".
        row2 = card._versions_list.itemAt(1).widget()
        row2.click()

        assert emitted == ["v2"], f"clicking a version row must dive to its id; got {emitted}"
