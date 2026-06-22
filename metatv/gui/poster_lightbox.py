"""Full-window poster lightbox — enlarges the details-pane poster image.

Clicking the poster in the details pane opens this overlay: the full-res
cached image is displayed centred on a dimmed backdrop. Esc and backdrop
clicks both dismiss it.

Architecture mirrors SimilarTitleLightbox (``similar_lightbox.py``):
- ``PosterLightbox`` is a child ``QWidget`` of the main window, raised above
  all other widgets via ``raise_()``. It covers the full main-window area.
- ``paintEvent`` draws a semi-transparent backdrop. Clicks on the backdrop
  (outside the image frame) dismiss it.
- ``QPixmap`` is always supplied by the caller on the main thread (never
  created here from a thread), per the Qt-threading rule.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPainter, QColor, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

# Fraction of the window dimension used as margin on each side
_MARGIN_FRACTION = 0.08


class PosterLightbox(QWidget):
    """Full-window dimmed overlay that shows an enlarged poster image.

    Usage::

        lightbox = PosterLightbox(parent=main_window)
        lightbox.show_pixmap(pixmap)   # called from the main thread

    Dismiss: Esc key or click outside the image frame.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def show_pixmap(self, pixmap: QPixmap) -> None:
        """Display *pixmap* in the lightbox.  Must be called from the main thread."""
        self._pixmap = pixmap
        self.resize(self.parent().size())
        self._refresh_image()
        self.show()
        self.raise_()
        self.setFocus()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Card — centred frame that holds the image
        self._card = QFrame()
        self._card.setObjectName("poster_lightbox_card")
        self._card.setStyleSheet(
            f"#poster_lightbox_card {{ background: {_theme.COLOR_LIGHTBOX_BG};"
            f" border-radius: 8px; border: 1px solid {_theme.COLOR_BORDER}; }}"
        )

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # Close button — top-right corner
        btn_row_widget = QWidget()
        btn_row_widget.setStyleSheet(
            f"background: {_theme.COLOR_LIGHTBOX_HEADER}; border-radius: 8px 8px 0 0;"
        )
        from PyQt6.QtWidgets import QHBoxLayout
        btn_row = QHBoxLayout(btn_row_widget)
        btn_row.setContentsMargins(10, 4, 6, 4)

        hint = QLabel("Click outside or press Esc to close")
        hint.setStyleSheet(
            f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM}; background: transparent;"
        )
        btn_row.addWidget(hint, 1)

        close_btn = QPushButton(_icons.close_icon)
        close_btn.setFlat(True)
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            f"QPushButton {{ color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_2XL};"
            " border: none; background: transparent; }"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI}; }}"
        )
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self._close)
        btn_row.addWidget(close_btn)

        card_layout.addWidget(btn_row_widget)

        # Image label
        self._image_lbl = QLabel()
        self._image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_lbl.setStyleSheet(
            f"background: {_theme.COLOR_BG_DEEP}; border-radius: 0 0 8px 8px;"
        )
        card_layout.addWidget(self._image_lbl)

        outer.addWidget(self._card)

    # ------------------------------------------------------------------ #
    # Dismiss                                                              #
    # ------------------------------------------------------------------ #

    def _close(self) -> None:
        self._pixmap = None
        self.hide()

    def mousePressEvent(self, event) -> None:
        if not self._card.geometry().contains(event.pos()):
            self._close()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._close()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------ #
    # Backdrop rendering                                                   #
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 180))
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_image()
        # Keep card size in sync with window size minus margins
        w = self.width()
        h = self.height()
        margin_h = int(w * _MARGIN_FRACTION)
        margin_v = int(h * _MARGIN_FRACTION)
        max_w = w - margin_h * 2
        max_h = h - margin_v * 2
        self._card.setMaximumSize(max_w, max_h)

    # ------------------------------------------------------------------ #
    # Image scaling                                                        #
    # ------------------------------------------------------------------ #

    def _refresh_image(self) -> None:
        """Scale the stored pixmap to fit inside the card and display it."""
        if not self._pixmap or self._pixmap.isNull():
            self._image_lbl.clear()
            return

        w = self.width()
        h = self.height()
        margin_h = int(w * _MARGIN_FRACTION)
        margin_v = int(h * _MARGIN_FRACTION)
        # Reserve some vertical space for the header bar (~32px)
        available_w = max(100, w - margin_h * 2)
        available_h = max(100, h - margin_v * 2 - 32)

        scaled = self._pixmap.scaled(
            QSize(available_w, available_h),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_lbl.setPixmap(scaled)
        self._image_lbl.setFixedSize(scaled.size())
        self._card.adjustSize()
