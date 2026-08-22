"""The preview overlay's keyboard legend — the strip along the bottom of the card.

Its own module because it is a self-contained component (a list of key/meaning
pairs, no state beyond what it is labelling) and because the card it used to
live in sits at the 1000-line cap the code-health ratchet enforces.

It labels what the keys DO RIGHT NOW, which is not constant: the ← → chevrons
walk a title's similar set most of the time, but inside a facet lens they walk
that lens's results instead. Saying "browse similar" there describes something
the user is not looking at.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


class LightboxKeyHints(QWidget):
    """Bottom legend: what ← →, dive-in, Backspace and Esc currently do."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # A CUSTOM QWidget subclass does not paint a stylesheet background
        # unless it is told to, and it does not hand that fill down to its
        # children the way the plain inline QWidget this replaced did. Without
        # the attribute the bar stays transparent AND every child label falls
        # back to the app palette — which on Daylight painted light boxes
        # behind each hint, on the dark card.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _theme.style(self, "LIGHTBOX_FOOTER_BAR")

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 10, 20, 10)
        row.setSpacing(18)

        self._browse_lbl: QLabel | None = None
        for key, text in (
            (f"{_icons.nav_prev_icon} {_icons.nav_next_icon}", "browse similar"),
            (_icons.lightbox_icon, "dive in"),
            ("Backspace", "back"),
            ("Esc", "close"),
        ):
            kbd = QLabel(key)
            _theme.style(kbd, "LIGHTBOX_KBD")
            row.addWidget(kbd)
            lbl = QLabel(text)
            _theme.style(lbl, "LIGHTBOX_FOOTER_HINT")
            row.addWidget(lbl)
            if self._browse_lbl is None:
                self._browse_lbl = lbl
        row.addStretch()

    def set_lens_active(self, active: bool) -> None:
        """Relabel the ← → hint for what those keys are actually walking.

        Args:
            active: True while a facet lens is open — the chevrons page that
                lens's results, not the anchor title's similar set.
        """
        if self._browse_lbl is not None:
            self._browse_lbl.setText(
                "browse these results" if active else "browse similar"
            )

    @property
    def browse_hint(self) -> str:
        return self._browse_lbl.text() if self._browse_lbl is not None else ""
