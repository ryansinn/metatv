"""Behavioral tests for the poster-lightbox feature.

Tests pin the behaviors that would actually regress:
1. PosterLightbox.show_pixmap — widget becomes visible and holds the pixmap.
2. PosterLightbox._close / Esc — widget becomes hidden.
3. Backdrop click (outside card) — widget becomes hidden.
4. _PosterLabel.poster_clicked — emitted when a pixmap is set and user clicks;
   NOT emitted when no pixmap is set.
5. _PosterSection.poster_enlarged — emitted after display, carries the
   full-res pixmap that was passed in.
6. poster_clicked tooltip / cursor — set when pixmap loaded, unchanged when no pixmap.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt, QPointF, QSize
from PyQt6.QtGui import QPixmap, QMouseEvent
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Helper: 1×1 non-null pixmap
# ---------------------------------------------------------------------------

def _tiny_pixmap() -> QPixmap:
    pix = QPixmap(1, 1)
    pix.fill(Qt.GlobalColor.red)
    return pix


# ---------------------------------------------------------------------------
# PosterLightbox — show_pixmap, dismiss via close, Esc, backdrop click
# ---------------------------------------------------------------------------

class TestPosterLightbox:
    """Behavioural tests for PosterLightbox overlay.

    ``isVisible()`` is true only if the widget AND all its ancestors are visible.
    In headless tests the parent is never shown, so we cannot rely on
    ``isVisible()``.  Instead we inspect internal state (``_pixmap``,
    ``isHidden()``) and the widget's ``show``/``hide`` API directly.

    The hide() / show() verbs are what actually matter at the regression
    boundary: _close() must call hide(); show_pixmap() must call show().
    Both are verified by checking ``isHidden()`` *after* we know the widget
    started in the opposite state.
    """

    def _make_lightbox(self, qapp):
        """Return (parent, lightbox). Caller must keep parent alive."""
        from PyQt6.QtWidgets import QWidget
        from metatv.gui.poster_lightbox import PosterLightbox
        parent = QWidget()
        parent.resize(800, 600)
        lb = PosterLightbox(parent=parent)
        return parent, lb

    def test_show_pixmap_stores_full_pixmap(self, qapp):
        """show_pixmap() retains the supplied pixmap in the lightbox."""
        parent, lb = self._make_lightbox(qapp)
        pix = _tiny_pixmap()
        lb.show_pixmap(pix)
        assert lb._pixmap is not None
        assert not lb._pixmap.isNull()

    def test_show_pixmap_renders_into_image_label(self, qapp):
        """show_pixmap() sets a non-null pixmap on _image_lbl."""
        parent, lb = self._make_lightbox(qapp)
        lb.show_pixmap(_tiny_pixmap())
        lbl_pix = lb._image_lbl.pixmap()
        assert lbl_pix is not None
        assert not lbl_pix.isNull()

    def test_show_pixmap_calls_show(self, qapp):
        """show_pixmap() makes the widget not-hidden (calls show())."""
        parent, lb = self._make_lightbox(qapp)
        # Start explicitly hidden
        lb.hide()
        assert lb.isHidden()
        lb.show_pixmap(_tiny_pixmap())
        assert not lb.isHidden()

    def test_close_calls_hide(self, qapp):
        """_close() hides the lightbox (not-visible after close)."""
        parent, lb = self._make_lightbox(qapp)
        lb.show_pixmap(_tiny_pixmap())
        assert not lb.isHidden()   # show_pixmap called show()
        lb._close()
        assert lb.isHidden()

    def test_close_clears_pixmap(self, qapp):
        """_close() sets _pixmap to None so a stale image cannot linger."""
        parent, lb = self._make_lightbox(qapp)
        lb.show_pixmap(_tiny_pixmap())
        lb._close()
        assert lb._pixmap is None

    def test_esc_key_calls_close(self, qapp):
        """Pressing Esc hides the lightbox."""
        from PyQt6.QtGui import QKeyEvent
        parent, lb = self._make_lightbox(qapp)
        lb.show_pixmap(_tiny_pixmap())
        ev = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
        lb.keyPressEvent(ev)
        assert lb.isHidden()

    def test_non_escape_key_does_not_close(self, qapp):
        """Other keys do not close the lightbox."""
        from PyQt6.QtGui import QKeyEvent
        parent, lb = self._make_lightbox(qapp)
        lb.show_pixmap(_tiny_pixmap())
        ev = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
        )
        lb.keyPressEvent(ev)
        assert not lb.isHidden()

    def test_backdrop_click_at_zero_zero_calls_close(self, qapp):
        """Click at (0,0) — outside any centred card — hides the lightbox.

        In headless mode the card has no real layout geometry, so we verify the
        actual conditional: when the click position is NOT inside card.geometry()
        the lightbox is closed.  (0,0) is reliably outside a centred card whose
        minimum dimensions push its top-left corner away from the origin.)
        """
        from PyQt6.QtWidgets import QWidget
        from metatv.gui.poster_lightbox import PosterLightbox
        from PyQt6.QtCore import QRect

        parent = QWidget()
        parent.resize(1200, 900)
        lb = PosterLightbox(parent=parent)
        lb.show_pixmap(_tiny_pixmap())

        # Force the card geometry to a rect that excludes (0,0)
        lb._card.setGeometry(QRect(100, 100, 400, 300))

        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(0.0, 0.0),   # outside the card rect above
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        lb.mousePressEvent(ev)
        assert lb.isHidden()

    def test_click_inside_card_rect_does_not_close(self, qapp):
        """Click inside the card geometry does NOT close the lightbox."""
        from PyQt6.QtWidgets import QWidget
        from metatv.gui.poster_lightbox import PosterLightbox
        from PyQt6.QtCore import QRect

        parent = QWidget()
        parent.resize(1200, 900)
        lb = PosterLightbox(parent=parent)
        lb.show_pixmap(_tiny_pixmap())

        lb._card.setGeometry(QRect(100, 100, 400, 300))

        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(300.0, 250.0),   # inside the card rect
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        lb.mousePressEvent(ev)
        assert not lb.isHidden()


# ---------------------------------------------------------------------------
# _PosterLabel — cursor, tooltip, signal
# ---------------------------------------------------------------------------

class TestPosterLabel:
    """Tests for the clickable poster QLabel."""

    def test_no_cursor_when_no_pixmap(self, qapp):
        """Without a pixmap the label has the default cursor (not PointingHand)."""
        from metatv.gui.details_sections import _PosterLabel
        lbl = _PosterLabel()
        assert lbl.cursor().shape() != Qt.CursorShape.PointingHandCursor

    def test_pointing_hand_cursor_after_setpixmap(self, qapp):
        """After setting a real pixmap the cursor becomes PointingHand."""
        from metatv.gui.details_sections import _PosterLabel
        lbl = _PosterLabel()
        lbl.setPixmap(_tiny_pixmap())
        assert lbl.cursor().shape() == Qt.CursorShape.PointingHandCursor

    def test_cursor_reset_after_clear(self, qapp):
        """Clearing the label removes the PointingHand cursor."""
        from metatv.gui.details_sections import _PosterLabel
        lbl = _PosterLabel()
        lbl.setPixmap(_tiny_pixmap())
        assert lbl.cursor().shape() == Qt.CursorShape.PointingHandCursor
        lbl.clear()
        assert lbl.cursor().shape() != Qt.CursorShape.PointingHandCursor

    def test_poster_clicked_emitted_when_pixmap_set(self, qapp):
        """poster_clicked is emitted when the user left-clicks a loaded pixmap."""
        from metatv.gui.details_sections import _PosterLabel
        lbl = _PosterLabel()
        lbl.setPixmap(_tiny_pixmap())

        emitted: list[bool] = []
        lbl.poster_clicked.connect(lambda: emitted.append(True))

        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(0.0, 0.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        lbl.mousePressEvent(ev)
        assert emitted == [True], "poster_clicked must fire when a pixmap is loaded"

    def test_poster_clicked_not_emitted_without_pixmap(self, qapp):
        """poster_clicked is NOT emitted when no pixmap is set."""
        from metatv.gui.details_sections import _PosterLabel
        lbl = _PosterLabel()

        emitted: list[bool] = []
        lbl.poster_clicked.connect(lambda: emitted.append(True))

        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(0.0, 0.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        lbl.mousePressEvent(ev)
        assert emitted == [], "poster_clicked must NOT fire when no pixmap is set"


# ---------------------------------------------------------------------------
# _PosterSection.poster_enlarged — signal carries full-res pixmap
# ---------------------------------------------------------------------------

class TestPosterSectionEnlarged:
    """Test that _PosterSection emits poster_enlarged with the full-res pixmap."""

    def _make_section(self, qapp):
        """Construct a _PosterSection with a stub config and stub image_cache."""
        from metatv.gui.details_sections import _PosterSection

        class _FakeConfig:
            pass

        class _FakeImageCache:
            def get_image_sync(self, url):
                return None
            def get_image_async(self, url, provider_urls=None):
                pass

        return _PosterSection(_FakeConfig(), _FakeImageCache())

    def test_poster_enlarged_emitted_after_display(self, qapp):
        """poster_enlarged is emitted when the poster label is clicked after image load."""
        section = self._make_section(qapp)
        pix = _tiny_pixmap()

        received: list[QPixmap] = []
        section.poster_enlarged.connect(lambda p: received.append(p))

        # Simulate the image cache delivering the pixmap
        section._display_poster(pix)

        # Now simulate the click on the label
        section._on_poster_clicked()

        assert len(received) == 1, "poster_enlarged must fire once after click"
        assert not received[0].isNull(), "poster_enlarged pixmap must not be null"

    def test_poster_enlarged_not_emitted_before_load(self, qapp):
        """poster_enlarged is NOT emitted if the image hasn't loaded yet."""
        section = self._make_section(qapp)

        received: list[QPixmap] = []
        section.poster_enlarged.connect(lambda p: received.append(p))

        # No _display_poster called — _full_pixmap is None
        section._on_poster_clicked()

        assert received == [], "poster_enlarged must not fire before a pixmap is loaded"

    def test_clear_resets_full_pixmap(self, qapp):
        """After clear(), clicking no longer emits poster_enlarged."""
        section = self._make_section(qapp)
        pix = _tiny_pixmap()
        section._display_poster(pix)

        received: list[QPixmap] = []
        section.poster_enlarged.connect(lambda p: received.append(p))

        section.clear()
        section._on_poster_clicked()

        assert received == [], "poster_enlarged must not fire after clear()"
