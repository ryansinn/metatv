"""Breadcrumb trail widget for the Similar-Titles lightbox.

Displays the user's dive path through similar titles as a subtle inline breadcrumb:
``Origin › A › B › Current``. Each crumb before the current is clickable to jump
back to that point; the current is not clickable. Long trails elide in the middle
with an interactive `…` that opens the Explore trail-map view.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable

if TYPE_CHECKING:
    from metatv.core.database import Database


class _CrumbButton(QPushButton):
    """A single clickable breadcrumb that emits its channel_id when clicked."""

    crumb_clicked = pyqtSignal(str)  # channel_id

    def __init__(self, title: str, channel_id: str) -> None:
        super().__init__(title)
        self.channel_id = channel_id
        self.setFlat(True)
        _theme.style(self, "LIGHTBOX_BREADCRUMB_CRUMB")
        self.setToolTip(title)
        set_clickable(self)
        self.clicked.connect(lambda: self.crumb_clicked.emit(self.channel_id))


class LightboxBreadcrumb(QWidget):
    """Breadcrumb trail showing the dive path in the Similar-Titles lightbox.

    Tracks the user's navigation through similar titles and renders a subtle,
    muted breadcrumb line: ``Origin › A › B › Current``. Earlier crumbs are
    clickable to jump back; the current is not clickable. Long trails elide
    in the middle with a clickable `…` that opens the Explore trail-map view.
    """

    crumb_clicked = pyqtSignal(str)  # channel_id — user clicked an earlier crumb
    explore_ellipsis_clicked = pyqtSignal()  # user clicked the `…` to open Explore

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _theme.style(self, "BG_TRANSPARENT")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._layout = layout
        self._crumb_buttons: dict[str, _CrumbButton] = {}

    def update_trail(
        self,
        origin_title: str,
        origin_ids: list[str],
        nav_stack: list[str],
        current_id: str,
        titles: dict[str, str],
        lens_crumbs: list[tuple[str, str]] | None = None,
    ) -> None:
        """Update the breadcrumb with the current dive path.

        Args:
            origin_title: The human-readable name of the origin channel.
            origin_ids: The list of similar channels at the origin.
            nav_stack: The list of channel IDs walked through (dive history).
            current_id: The currently shown channel's ID.
            titles: channel_id → display title, captured by the lightbox as
                the user dives (no DB access: this runs on every navigation).
            lens_crumbs: ``(label, channel_id)`` pairs that PRECEDE the origin —
                the anchors the user was sitting on when they clicked a cast
                name or genre chip and the overlay re-seeded itself with that
                facet. Each is clickable (returning to that anchor's set);
                *origin_title* then names the lens itself ("With Nicolas Cage"),
                which is a set label, not a place, so it stays unclickable.
        """
        # Clear previous crumbs
        self._crumb_buttons.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if not nav_stack and not lens_crumbs:
            # Neither in a dive nor inside a facet lens; don't show the breadcrumb
            self.hide()
            return

        self.show()

        titles = dict(titles or {})

        # Build the trail: origin › stack items › current
        # Lens anchors first ("Adaptation. › With Nicolas Cage › …"), then the
        # origin/lens label, which is never clickable.
        trail: list[tuple[str, str]] = list(lens_crumbs or [])
        trail.append((origin_title, ""))
        for cid in nav_stack:
            trail.append((titles.get(cid) or "…", cid))
        trail.append((titles.get(current_id) or "…", current_id))

        # Decide on elision: keep first + last if long
        max_visible = 4  # e.g. "Origin › … › B › Current"
        if len(trail) > max_visible:
            # Show origin, ellipsis, and the last two (penultimate + current)
            shown = [trail[0]] + [("…", "")] + trail[-2:]
        else:
            shown = trail

        # Render breadcrumbs
        for i, (title, cid) in enumerate(shown):
            is_current = i == len(shown) - 1
            is_ellipsis = title == "…"

            if is_ellipsis:
                # Clickable ellipsis that opens Explore with the full trail
                ellipsis_btn = QPushButton("…")
                ellipsis_btn.setFlat(True)
                _theme.style(ellipsis_btn, "LIGHTBOX_BREADCRUMB_CRUMB")
                ellipsis_btn.setToolTip("Show full path in Explore")
                set_clickable(ellipsis_btn)
                ellipsis_btn.clicked.connect(self.explore_ellipsis_clicked)
                self._layout.addWidget(ellipsis_btn, 0)
            elif is_current or not cid:
                # Not a destination: the CURRENT crumb (you are already here) and
                # any crumb with no channel to go to — the origin, and a lens
                # label like "With Nicolas Cage", which names a SET rather than a
                # place. Rendering those as buttons gave them a pointing-hand
                # cursor and a click that emitted "" and did nothing.
                current_lbl = QLabel(title)
                _theme.style(current_lbl, "LIGHTBOX_BREADCRUMB_CURRENT")
                current_lbl.setToolTip(title)
                current_lbl.setMaximumWidth(150)
                self._layout.addWidget(current_lbl, 0)
            else:
                # Clickable earlier crumb
                crumb = _CrumbButton(title, cid)
                crumb.crumb_clicked.connect(self.crumb_clicked)
                crumb.setMaximumWidth(150)
                self._crumb_buttons[cid] = crumb
                self._layout.addWidget(crumb, 0)

            # Add separator between crumbs (except after last)
            if i < len(shown) - 1:
                sep = QLabel("›")
                _theme.style(sep, "LIGHTBOX_BREADCRUMB_SEP")
                self._layout.addWidget(sep, 0)

        self._layout.addStretch()
