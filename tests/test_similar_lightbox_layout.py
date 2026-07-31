"""Behavioral tests for the responsive, grow-to-content Similar-Titles lightbox.

Two concerns, each asserting the outcome that would break against the old code
(``_LightboxCard.setFixedWidth(820)`` + a stock ``QScrollArea`` body whose
size-hint clamps to ~400px):

1. **Responsive width.** The card width scales with the overlay width, clamped to
   ``[CARD_MIN_W, CARD_MAX_W]`` — a wider window gives a wider card, a narrow one
   the floor. It is never the old constant 820, and the overlay's ``resizeEvent``
   drives it.

2. **Grow-to-content height.** With rich content and a tall window, the card grows
   to show every section with NO forced vertical scrollbar; the scrollbar only
   appears once the window is genuinely too small to hold the content.

Layout-dependent assertions build the card inside an overlay-like container (a
centered ``QVBoxLayout`` → ``QHBoxLayout`` holding the card), exactly how the real
overlay hosts it, and let Qt size the card from its own size-hint.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractScrollArea, QHBoxLayout, QVBoxLayout, QWidget,
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _rich_data() -> dict:
    """A fully-populated title — every section present (poster, plot, cast, four
    genres, three Other Versions, six Similar)."""
    return {
        "id": "c", "name": "12 Monkeys", "media_type": "movie",
        "provider_name": "ProSat (Ottcst)", "provider_active": True,
        "is_favorite": False, "is_hidden": False, "in_queue": False,
        "user_rating": 1, "is_suppressed": False,
        "poster_url": None, "year": 1995, "rating": 8.0, "runtime": 129,
        "genres": ["Sci-Fi", "Thriller", "Time Travel", "Dystopia"],
        "plot": ("In a future ravaged by a man-made plague, a convict is sent back "
                 "in time to gather information about the virus responsible for "
                 "wiping out most of the human population."),
        "cast": ("Bruce Willis, Madeleine Stowe, Brad Pitt, Christopher Plummer "
                 "· dir. Terry Gilliam"),
        "versions": [
            {"id": "v1", "name": "Mision: Salvar el bosque", "tag": "ES", "provider_name": "ProSat"},
            {"id": "v2", "name": "12 Monkeys 4K", "tag": "4K", "provider_name": "TREX"},
            {"id": "v3", "name": "12 Monos (LATINO)", "tag": "LAT", "provider_name": "ProSat"},
        ],
        "version_count": 7,
        "similar": [
            {"id": f"s{i}", "name": n, "year": y, "poster_url": None, "media_type": "movie"}
            for i, (n, y) in enumerate([
                ("The Twelve Kingdoms", 1997), ("Looper", 2012), ("Primer", 2004),
                ("Twelve Monkeys (series)", 2015), ("12:01", 1993), ("La Jetee", 1962),
            ])
        ],
    }


def _built_card(qapp, overlay_w: int, overlay_h: int):
    """Return (card, container): a populated card hosted like the real overlay."""
    from metatv.gui.similar_lightbox_card import _LightboxCard

    card = _LightboxCard()
    card.set_header("12 Monos (LATINO)")
    card.set_counter("3 of 18")
    card.populate(_rich_data())

    container = QWidget()
    container.resize(overlay_w, overlay_h)
    v = QVBoxLayout(container)
    v.setContentsMargins(0, 0, 0, 0)
    v.setAlignment(Qt.AlignmentFlag.AlignCenter)
    row = QHBoxLayout()
    row.setAlignment(Qt.AlignmentFlag.AlignCenter)
    row.addWidget(card, 0, Qt.AlignmentFlag.AlignVCenter)
    v.addLayout(row)

    card.apply_overlay_size(overlay_w, overlay_h)
    container.show()
    for _ in range(15):
        qapp.processEvents()
    return card, container


# ---------------------------------------------------------------------------
# 1. Responsive width
# ---------------------------------------------------------------------------

class TestResponsiveWidth:
    def test_apply_overlay_size_scales_and_clamps(self, qapp):
        from metatv.gui.similar_lightbox_card import (
            _LightboxCard, CARD_MIN_W, CARD_MAX_W,
        )

        card = _LightboxCard()

        card.apply_overlay_size(2000, 1000)
        wide = card.width()
        card.apply_overlay_size(1200, 1000)
        mid = card.width()
        card.apply_overlay_size(700, 900)
        narrow = card.width()

        assert wide == CARD_MAX_W, "a huge window caps the card at CARD_MAX_W (readability)"
        assert mid == int(1200 * 0.82), "a mid window scales the card to the width fraction"
        assert narrow == CARD_MIN_W, "a small window floors the card at CARD_MIN_W (never collapses)"
        assert wide > mid > narrow, "wider window → wider card (monotonic)"
        assert 820 not in (wide, mid, narrow), "the card is no longer hard-fixed at the old 820"

    def test_overlay_resizeEvent_drives_card_width(self, qapp, tmp_path):
        """Resizing the real overlay recomputes the card width (not a constant)."""
        from metatv.core.config import Config
        from metatv.core.database import Database
        from metatv.core.image_cache import ImageCache
        from metatv.gui.similar_lightbox import SimilarTitleLightbox
        from metatv.gui.similar_lightbox_card import CARD_MAX_W, CARD_MIN_W

        db = Database(f"sqlite:///{tmp_path / 'lb.db'}")
        db.create_tables()

        def _expected(overlay_w: int) -> int:
            return min(CARD_MAX_W, max(CARD_MIN_W, int(overlay_w * 0.82)))

        parent = QWidget()
        parent.resize(1600, 1000)
        parent.show()
        ic = ImageCache(cache_dir=str(tmp_path / "imgcache"))
        lb = SimilarTitleLightbox(parent, Config(), ic, db)
        lb.show()  # a shown widget delivers resizeEvent deterministically
        qapp.processEvents()
        try:
            # A window where the width fraction (not the cap) governs. Assert against
            # the overlay's ACTUAL width (the card's fixed width sets the overlay's
            # minimum, so a requested size may be clamped) — robust, and still proves
            # the resizeEvent recomputes from the window width, not a constant.
            lb.resize(1320, 850)
            qapp.processEvents()
            mid = lb._card.width()
            assert mid == _expected(lb.width()), "resizeEvent sizes the card off the window width"
            assert mid != 820, "the card is no longer hard-fixed at the old 820"

            # A larger window → a wider card, up to the readability cap.
            lb.resize(1600, 850)
            qapp.processEvents()
            wide = lb._card.width()
            assert wide == _expected(lb.width())
            assert wide >= mid, "a wider window gives a wider (or capped) card"
            assert wide == CARD_MAX_W, "a large window reaches the width cap"
        finally:
            lb.deleteLater()
            parent.deleteLater()
            qapp.processEvents()
            db.close()


# ---------------------------------------------------------------------------
# 2. Grow-to-content height (scroll only on genuine overflow)
# ---------------------------------------------------------------------------

class TestGrowToContent:
    def test_body_scroll_uses_adjust_to_contents(self, qapp):
        from metatv.gui.similar_lightbox_card import _LightboxCard

        card = _LightboxCard()
        assert (
            card._body_scroll.sizeAdjustPolicy()
            == QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        ), "the body scroll area must adjust its size-hint to its content"

    def test_grows_to_show_all_sections_without_scroll(self, qapp):
        """On a tall window every section fits: the card grows well past the stock
        ~400px scroll cap and the vertical scrollbar is not needed."""
        card, container = _built_card(qapp, 1600, 1200)
        try:
            sb = card._body_scroll.verticalScrollBar()
            # Grew far past the old ~408px stock QScrollArea size-hint cap (which
            # pinned the whole card near ~500px and folded sections below a scroll).
            assert card.height() > 700, (
                f"card should grow to its content height; got {card.height()}"
            )
            # Every section is visible in one frame — no forced vertical scroll.
            assert sb.maximum() == 0, (
                f"a large window must show all content without scrolling; "
                f"scrollbar range={sb.maximum()}"
            )
            # And it hugs content rather than over-growing to the cap (no dead space).
            assert card.height() < card.maximumHeight(), (
                "card should hug its content, not stretch to the 0.9×window cap"
            )
        finally:
            container.deleteLater()
            qapp.processEvents()

    def test_scroll_appears_only_when_window_too_small(self, qapp):
        """The same rich content on a genuinely small window DOES scroll — proving
        the scrollbar is content-driven, not simply disabled."""
        card, container = _built_card(qapp, 900, 540)
        try:
            sb = card._body_scroll.verticalScrollBar()
            assert card.height() <= card.maximumHeight() + 1, "card respects the height cap"
            assert sb.maximum() > 0, (
                "content taller than a small window must produce a scrollbar"
            )
        finally:
            container.deleteLater()
            qapp.processEvents()
