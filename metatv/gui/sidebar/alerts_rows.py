"""Row widgets the Watch Alerts section renders.

Extracted because ``alerts.py`` carries a shrink-only ratchet and an owed
split, and because these two are genuinely separable: each takes plain values
and returns a widget, touching no section state. ``_name_with_dim_suffix_html``
comes with them — it exists for ``_AlertRow``'s title.
"""

from __future__ import annotations

import html

from datetime import datetime

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from metatv.core.epg_utils import is_local_today, to_local
from metatv.gui import cursor_affordance
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.progress_paint import elapsed_pct, paint_progress
from metatv.gui.relative_time import humanize_remaining, humanize_until


#: The left slot's reserved width, and the marker size within it. 14px is the
#: sidebar's normal icon size — History's play-next button uses the same — not
#: the 11px a chip-row TYPE icon uses. That one is deliberately sized against a
#: title's cap height because it sits inline WITH text; this is a control in its
#: own column, and at 11px it read as half the size it should be.
SLOT_W = 18
SLOT_ICON_PX = 14


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


class _ProgressBar(QWidget):
    """How far through a live programme is, as a bar rather than as words.

    Owner's reasoning, and it is the whole point: "30 minutes left on a 30
    minute show is different than 30 minutes left on a 3 hour show." The words
    cannot say that; a proportion can. The remaining time moves to the tooltip,
    where it is available on demand without spending a row's width on it.

    Painting is :func:`metatv.gui.progress_paint.paint_progress` — the same
    function the EPG tree's Remaining column and the agenda strip use, so all
    three bars are one bar.
    """

    _W, _H = 44, 8

    def __init__(self, pct: float = 0.0, parent=None):
        super().__init__(parent)
        self.setFixedSize(self._W, self._H)
        self._pct = pct

    def set_pct(self, pct: float, tooltip: str = "") -> None:
        """Update the fill, repainting only when it actually moved."""
        pct = max(0.0, min(100.0, float(pct)))
        if tooltip:
            self.setToolTip(tooltip)
        if abs(pct - self._pct) < 0.5:
            return
        self._pct = pct
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(self._W, self._H)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        from PyQt6.QtGui import QPainter
        paint_progress(QPainter(self), QRect(0, 0, self.width(), self.height()),
                       self._pct)


class _AlertRow(QWidget):
    """Channel row widget for Watch Alerts: name + right-aligned time + hover play button."""

    play_clicked = pyqtSignal()
    row_clicked  = pyqtSignal()  # single click anywhere except the play button

    def __init__(self, ch_name: str, time_str: str, config, parent=None, *,
                 when: datetime | None = None, live: bool = False,
                 started_at: datetime | None = None):
        """
        Args:
            ch_name: The channel/title text for the row.
            time_str: The time text as of now — see :meth:`refresh_time`.
            config: The app config (supplies the play glyph).
            parent: Qt parent.
            when: The programme's ``stop_time`` (live rows) or ``start_time``
                (upcoming rows), UTC-naive. Kept so the row can recompute its
                own text on a clock tick; ``None`` leaves the row frozen, which
                is right for rows whose text is not time-derived.
            live: True for a row counting DOWN to a programme's end, False for
                one counting up to its start. Picks the formatter.
            started_at: The programme's start, for a live row. With ``when``
                (its end) this gives the DURATION, which is what turns "13m
                left" into a proportion. Without it the row falls back to
                words — an upcoming row has no elapsed share to show.
        """
        super().__init__(parent)
        self._when = when
        self._live = live
        self._started_at = started_at
        self._playing = False
        self._is_new = False
        self._hovered = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

        # ── the left slot ────────────────────────────────────────────────
        # ONE fixed-width column, absolute left of the title, shared by every
        # marker a row can carry. Fixed width is the point: the play affordance
        # used to be a button at the RIGHT edge that appeared on hover, so it
        # shoved the progress bar sideways whenever the pointer crossed a row.
        # A reserved column cannot reflow, whether it holds anything or not.
        self._slot = QLabel()
        self._slot.setFixedWidth(SLOT_W)
        self._slot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._slot)

        name_lbl = QLabel(ch_name)
        layout.addWidget(name_lbl, 1)

        # A live row with a known duration shows the bar; everything else keeps
        # the words. An upcoming row has no elapsed share, and a live row whose
        # provider gave no start_time has no denominator.
        self._show_bar = bool(live and when is not None and started_at is not None)

        self.time_lbl = QLabel(time_str)
        _theme.style(self.time_lbl, "CHANNEL_NAME_DIM")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time_lbl.setVisible(not self._show_bar)
        layout.addWidget(self.time_lbl)

        self.progress = _ProgressBar() if self._show_bar else None
        if self.progress is not None:
            self.progress.setToolTip(time_str)
            layout.addWidget(self.progress)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        cursor_affordance.set_clickable(self)
        self._paint_slot()

    # ── the left slot ────────────────────────────────────────────────────
    def set_playing(self, playing: bool) -> None:
        """Mark this row as the thing currently playing."""
        if playing != self._playing:
            self._playing = playing
            self._paint_slot()

    def set_new(self, is_new: bool) -> None:
        """Mark this row as new since the viewer last looked."""
        if is_new != self._is_new:
            self._is_new = is_new
            self._paint_slot()

    def _offers_play(self) -> bool:
        """Whether this row can be played at all.

        Only a LIVE row can. Offering ▶ on an upcoming programme promises
        something the app cannot do — owner: "how can it play anything in
        future... no time machine." An upcoming row's useful action is opening
        it, which the row click already does.
        """
        return self._live

    def _paint_slot(self) -> None:
        """Draw whichever marker applies, most urgent first.

        Playing beats hover beats new: what is on screen right now outranks an
        offer to start it, which outranks a note that this arrived recently.
        Only one shows, which is what lets them share one column.

        Green carries both "playing" and "new", but as different SHAPES — a
        triangle and a dot — so neither state rests on colour alone. Green for
        playing is the convention the details pane already uses
        (``DETAIL_PLAY_BTN_PLAYING``); the similarly-named
        ``COLOR_PLAYBACK_IN_PROGRESS`` is ORANGE and means *resumable*, which is
        a different claim entirely.
        """
        if self._playing:
            self._set_slot_icon("play", _theme.COLOR_OK, "Playing now")
        elif self._hovered and self._offers_play():
            self._set_slot_icon("play", _theme.COLOR_ACCENT, "Play")
        elif self._is_new:
            self._set_slot_icon("news", _theme.COLOR_OK, "New since you last looked")
        else:
            self._slot.clear()
            self._slot.setToolTip("")

    def _set_slot_icon(self, key: str, colour: str, tip: str) -> None:
        self._slot.setPixmap(
            _icon_utils.vector_pixmap(_icons.vector_key(key), colour, SLOT_ICON_PX)
        )
        self._slot.setToolTip(tip)

    def refresh_time(self, now: datetime) -> None:
        """Recompute this row's time text against ``now``.

        Called from the section's 30-second tick. The text is a pure function of
        ``now`` and a timestamp already held here, so this costs no query and no
        network — which is the whole reason the row keeps ``when`` instead of
        only the rendered string it was built with.

        A no-op when the text has not changed, so a tick over a full sidebar
        does not dirty every row and force a repaint of rows that still read
        correctly.

        Args:
            now: The current instant, UTC-naive (``epg_utils.now_utc()``).
        """
        if self._when is None:
            return
        text = (
            humanize_remaining(self._when, now) if self._live
            else humanize_until(self._when, now,
                                to_local=to_local, is_local_today=is_local_today)
        )
        if text != self.time_lbl.text():
            self.time_lbl.setText(text)
        if self.progress is not None:
            # The bar advances on the same tick, from the same instant, so the
            # fill and the tooltip can never disagree about the time.
            self.progress.set_pct(
                elapsed_pct(self._started_at, self._when, now), tooltip=text
            )

    def mousePressEvent(self, event):
        # The slot IS the play control while it is offering to play — clicking
        # the triangle starts it, clicking anywhere else selects the row.
        if self._slot.geometry().contains(event.pos()) and (
            self._playing or (self._hovered and self._offers_play())
        ):
            self.play_clicked.emit()
        else:
            self.row_clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self._paint_slot()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._paint_slot()
        super().leaveEvent(event)
