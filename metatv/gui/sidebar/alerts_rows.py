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
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from metatv.core.epg_utils import is_local_today, to_local
from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui.progress_paint import elapsed_pct, paint_progress
from metatv.gui.relative_time import humanize_remaining, humanize_until


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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

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
        # row_clicked fires only when clicking outside the play button area
        self.row_clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.play_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.play_btn.hide()
        super().leaveEvent(event)
