"""Row widgets the Watch Alerts section renders.

Extracted because ``alerts.py`` carries a shrink-only ratchet and an owed
split, and because these two are genuinely separable: each takes plain values
and returns a widget, touching no section state. ``_name_with_dim_suffix_html``
comes with them — it exists for ``_AlertRow``'s title.
"""

from __future__ import annotations

import html

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme


def _name_with_dim_suffix_html(text: str, suffix: str) -> str:
    """Rich-text ``title`` with an optional dim, smaller disambiguator suffix.

    The suffix (a collision disambiguator — see
    :func:`metatv.gui.series_alert_identity.disambiguation_suffixes`) is rendered
    in the muted/smaller theme tokens so it reads as secondary text next to the
    title.  Colour is paired with the always-on tooltip, so this is text-only (no
    colour-alone state).  Both fragments are HTML-escaped.

    Args:
        text: The (cleaned) title.
        suffix: The disambiguator suffix, or ``""`` for none.

    Returns:
        An HTML string for a rich-text ``QLabel``.
    """
    return (
        f"{html.escape(text)} "
        f'<span style="color:{_theme.COLOR_TEXT}; font-size:{_theme.FONT_SM}">'
        f"{html.escape(suffix)}</span>"
    )


class _VodAlertRow(QWidget):
    """Watch-for rule row: [type icon]  [name (legible)]  [right-aligned count].

    Mirrors :class:`_AlertRow` — a custom widget set via ``setItemWidget`` so the
    row reads cleanly (breathing room right of the type icon, no whole-row green
    tint).  Transparent for mouse events so the host ``QListWidget`` keeps
    receiving clicks / double-clicks / context-menu requests on the item.
    """

    def __init__(self, type_icon: str, text: str, count_text: str,
                 count_style: str, parent=None, *, suffix: str = ""):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(6)  # breathing room to the right of the type icon

        icon_lbl = QLabel(type_icon)
        layout.addWidget(icon_lbl)

        name_lbl = QLabel()
        _theme.style(name_lbl, "VOD_ALERT_NAME")  # COLOR_TEXT — never tinted
        if suffix:
            # Collision disambiguator: title + a dim, smaller suffix inline (rich
            # text so it flows immediately after the title, not at the far margin).
            name_lbl.setTextFormat(Qt.TextFormat.RichText)
            name_lbl.setText(_name_with_dim_suffix_html(text, suffix))
        else:
            name_lbl.setText(text)
        layout.addWidget(name_lbl, 1)

        count_lbl = QLabel(count_text)
        count_lbl.setStyleSheet(count_style)
        count_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(count_lbl)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # The item (not this widget) owns click/double-click/context-menu, so let
        # events pass through to the QListWidget viewport.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)


class _AlertRow(QWidget):
    """Channel row widget for Watch Alerts: name + right-aligned time + hover play button."""

    play_clicked = pyqtSignal()
    row_clicked  = pyqtSignal()  # single click anywhere except the play button

    def __init__(self, ch_name: str, time_str: str, config, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

        name_lbl = QLabel(ch_name)
        layout.addWidget(name_lbl, 1)

        self.time_lbl = QLabel(time_str)
        _theme.style(self.time_lbl, "CHANNEL_NAME_DIM")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.time_lbl)

        self.play_btn = QPushButton(config.play_icon)
        self.play_btn.setFixedSize(20, 18)
        self.play_btn.setFlat(True)
        self.play_btn.setToolTip("Play")
        _theme.style(self.play_btn, "PLAY_BTN_SMALL")
        self.play_btn.clicked.connect(self.play_clicked)
        self.play_btn.hide()
        layout.addWidget(self.play_btn)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        cursor_affordance.set_clickable(self)

    def mousePressEvent(self, event):
        # row_clicked fires only when clicking outside the play button area
        self.row_clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.play_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.play_btn.hide()
        super().leaveEvent(event)
