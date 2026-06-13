"""EPG agenda widget — vertical schedule for the details pane (live channels only)."""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget
from loguru import logger

from metatv.core.database import Database
from metatv.core.epg_utils import now_utc as _now_utc, fmt_time as _fmt_time, fmt_duration as _fmt_duration, progress_pct as _progress_pct, remaining_str as _remaining_str_base
from metatv.core.repositories.epg import EpgRepository
from metatv.gui import icons as _icons


def _remaining_str(stop: datetime, now: datetime) -> str:
    return _remaining_str_base(stop, now)


class EpgAgendaWidget(QWidget):
    """Vertical schedule agenda for the details pane.

    Shows the current programme (with progress bar) and upcoming programmes
    for the selected live channel. Hidden automatically when no data is available.
    """

    now_title_changed = pyqtSignal(str)  # current show title (empty string = no data)

    def __init__(self, db: Database, config=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._pending_channel_id: str | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(False)
        self._refresh_timer.setInterval(60_000)  # refresh progress bars every minute
        self._refresh_timer.timeout.connect(self._refresh_if_visible)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)
        self._layout = layout
        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_for_channel(self, channel_db_id: str) -> None:
        """Schedule a DB fetch for the given channel on the next event loop tick."""
        self._pending_channel_id = channel_db_id
        QTimer.singleShot(0, self._do_load)

    def clear(self) -> None:
        """Remove all content and hide."""
        self._pending_channel_id = None
        self._refresh_timer.stop()
        self._clear_layout()
        self.now_title_changed.emit("")
        self.hide()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_if_visible(self) -> None:
        if self._pending_channel_id:
            QTimer.singleShot(0, self._do_load)

    def _do_load(self) -> None:
        channel_id = self._pending_channel_id
        if not channel_id:
            return
        session = self._db.get_session()
        try:
            repo = EpgRepository(session)
            now_prog = repo.get_now_for_channel(channel_id)
            upcoming = repo.get_schedule_for_channel(channel_id, hours_ahead=12)
            # Exclude the current programme from the upcoming list
            now_id = now_prog.id if now_prog else None
            upcoming = [p for p in upcoming if p.id != now_id]
        except Exception:
            logger.exception("EpgAgendaWidget: DB error")
            now_prog = None
            upcoming = []
        finally:
            session.close()

        if not now_prog and not upcoming:
            self.now_title_changed.emit("")
            self.clear()
            return

        self._render(now_prog, upcoming)

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render(self, now_prog, upcoming: list) -> None:
        self._clear_layout()
        now = _now_utc()
        self.now_title_changed.emit(now_prog.title if now_prog else "")

        # Section divider
        self._layout.addWidget(_divider())

        if now_prog:
            self._layout.addWidget(_section_label("NOW PLAYING"))
            self._layout.addWidget(self._build_now_card(now_prog, now))

        if upcoming:
            self._layout.addWidget(_section_label("UP NEXT"))
            for prog in upcoming:
                self._layout.addWidget(self._build_next_row(prog))

        self._layout.addWidget(_divider())
        self.show()
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _build_now_card(self, prog, now: datetime) -> QWidget:
        card = QWidget()
        card.setObjectName("nowCard")
        card.setStyleSheet("""
            QWidget#nowCard {
                background: rgba(255, 200, 0, 0.06);
                border-left: 3px solid #ffc800;
                border-radius: 4px;
            }
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(4)

        title_lbl = QLabel(prog.title)
        title_lbl.setWordWrap(True)
        # Ignored horizontal policy: layout skips minimumSizeHint() for this widget,
        # preventing a long show title from expanding the scroll area content width.
        title_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #f0f0f0;")
        layout.addWidget(title_lbl)

        time_str = f"{_fmt_time(prog.start_time)} — {_fmt_time(prog.stop_time)}  ·  {_fmt_duration(prog.start_time, prog.stop_time)}"
        time_lbl = QLabel(time_str)
        time_lbl.setStyleSheet("font-size: 11px; color: #999;")
        layout.addWidget(time_lbl)

        pct = _progress_pct(prog.start_time, prog.stop_time, now)
        bar = _ProgressBar(pct)
        layout.addWidget(bar)

        remaining_lbl = QLabel(f"{pct}%  ·  {_remaining_str(prog.stop_time, now)}")
        remaining_lbl.setStyleSheet("font-size: 11px; color: #aaa;")
        layout.addWidget(remaining_lbl)

        return card

    def _build_next_row(self, prog) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 3, 8, 3)
        h.setSpacing(8)

        time_lbl = QLabel(_fmt_time(prog.start_time))
        time_lbl.setFixedWidth(58)
        time_lbl.setStyleSheet("font-size: 11px; color: #777;")
        h.addWidget(time_lbl)

        title_lbl = QLabel(prog.title)
        title_lbl.setStyleSheet("font-size: 11px; color: #bbb;")
        title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        h.addWidget(title_lbl, 1)

        dur_lbl = QLabel(_fmt_duration(prog.start_time, prog.stop_time))
        dur_lbl.setStyleSheet("font-size: 11px; color: #555;")
        dur_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        h.addWidget(dur_lbl)

        if self._config is not None:
            patterns = self._config.epg_watchlist_patterns or []
            in_wl = prog.title in patterns
            bell_btn = QPushButton(_icons.watchlist_on_icon if in_wl else _icons.watchlist_off_icon)
            bell_btn.setFixedWidth(26)
            bell_btn.setCheckable(True)
            bell_btn.setChecked(in_wl)
            bell_btn.setStyleSheet("border: none; padding: 0; font-size: 11px;")
            bell_btn.setToolTip("Remove from watchlist" if in_wl else "Add to watchlist")
            bell_btn.toggled.connect(
                lambda checked, t=prog.title, b=bell_btn: self._toggle_watchlist(t, checked, b)
            )
            h.addWidget(bell_btn)

        return row

    def _toggle_watchlist(self, title: str, add: bool, btn: QPushButton) -> None:
        if self._config is None:
            return
        patterns = list(self._config.epg_watchlist_patterns or [])
        if add and title not in patterns:
            patterns.append(title)
        elif not add and title in patterns:
            patterns.remove(title)
        self._config.epg_watchlist_patterns = patterns
        self._config.save()
        btn.setText(_icons.watchlist_on_icon if add else _icons.watchlist_off_icon)
        btn.setToolTip("Remove from watchlist" if add else "Add to watchlist")


# ------------------------------------------------------------------
# Helper widgets
# ------------------------------------------------------------------

class _ProgressBar(QWidget):
    """Simple horizontal progress bar using paint."""

    def __init__(self, pct: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pct = max(0, min(100, pct))
        self.setFixedHeight(4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PyQt6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        # Track
        p.setBrush(QColor(60, 60, 60))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, 2, 2)
        # Fill
        fill_w = max(4, int(w * self._pct / 100))
        p.setBrush(QColor(255, 200, 0, 200))
        p.drawRoundedRect(0, 0, fill_w, h, 2, 2)
        p.end()


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: rgba(255,255,255,0.08);")
    return line


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "font-size: 10px; font-weight: bold; color: #555; letter-spacing: 1px;"
        " padding: 6px 10px 2px 10px;"
    )
    return lbl
