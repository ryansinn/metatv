"""PPV (Pay-Per-View) events view with responsive flow grid layout"""

from datetime import datetime
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget,
    QPushButton, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from loguru import logger

from metatv.gui.content_view import ContentView
from metatv.gui.flow_layout import FlowLayout
from metatv.core.database import ChannelDB


class PPVEventCard(QFrame):
    """Card widget for a single PPV event.

    No internal timer — PPVView owns one shared 1-second timer and calls
    update_countdown() on all cards.  This avoids N timers firing at 1 Hz
    when there are N PPV events.
    """

    play_requested = pyqtSignal(object)  # ChannelDB

    def __init__(self, channel: ChannelDB, parent=None):
        super().__init__(parent)
        self.channel = channel
        self._meta: dict = channel.event_metadata or {}
        self._setup_ui()
        self.update_countdown()

    def _setup_ui(self):
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setMaximumWidth(300)

        layout = QVBoxLayout(self)

        self.poster_label = QLabel()
        self.poster_label.setFixedSize(280, 158)
        self.poster_label.setScaledContents(True)
        self.poster_label.setStyleSheet("background-color: #2a2a2a; border-radius: 4px;")
        layout.addWidget(self.poster_label)

        event_name = self._meta.get('event_name', 'Unknown Event')
        name_label = QLabel(event_name)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(name_label)

        self.datetime_label = QLabel()
        self.datetime_label.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self.datetime_label)

        self.countdown_label = QLabel()
        self.countdown_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff6b35;")
        layout.addWidget(self.countdown_label)

        badges_layout = QHBoxLayout()
        quality = self._meta.get('quality')
        if quality:
            q = QLabel(quality)
            q.setStyleSheet(
                "background-color: #4CAF50; color: white; padding: 2px 8px; "
                "border-radius: 3px; font-size: 10px; font-weight: bold;"
            )
            badges_layout.addWidget(q)
        sport_type = self._meta.get('sport_type')
        if sport_type:
            s = QLabel(sport_type.capitalize())
            s.setStyleSheet(
                "background-color: #2196F3; color: white; padding: 2px 8px; "
                "border-radius: 3px; font-size: 10px; font-weight: bold;"
            )
            badges_layout.addWidget(s)
        badges_layout.addStretch()
        layout.addLayout(badges_layout)

        play_button = QPushButton("▶ Play")
        play_button.clicked.connect(lambda: self.play_requested.emit(self.channel))
        play_button.setStyleSheet(
            "background-color: #ff6b35; color: white; border: none; "
            "padding: 8px; border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(play_button)

    def update_countdown(self):
        if not self.channel.event_start_time:
            self.datetime_label.setText("Date/time unavailable")
            self.countdown_label.setText("")
            return

        self.datetime_label.setText(
            self.channel.event_start_time.strftime("%b %d, %Y at %I:%M %p")
        )

        now = datetime.now()
        time_until = self.channel.event_start_time - now

        if time_until.total_seconds() < 0:
            days_ago = abs(time_until.days)
            text = "Ended (replay available)" if days_ago == 0 else f"Ended {days_ago}d ago"
            self.countdown_label.setText(text)
            self.countdown_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #888;")
        else:
            days = time_until.days
            hours, remainder = divmod(time_until.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            if days > 0:
                countdown = f"In {days}d {hours}h {minutes}m"
            elif hours > 0:
                countdown = f"In {hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                countdown = f"In {minutes}m {seconds}s"
            else:
                countdown = f"Starting in {seconds}s"
            self.countdown_label.setText(countdown)
            self.countdown_label.setStyleSheet(
                "font-size: 12px; font-weight: bold; color: #ff6b35;"
            )


class PPVView(ContentView):
    """PPV events view with time-sorted grid layout."""

    play_channel_requested = pyqtSignal(object)

    def __init__(self, config, db, parent=None):
        super().__init__(config, parent)
        self.db = db
        self.event_cards: list[PPVEventCard] = []

        # One shared timer — started on activate, stopped on deactivate.
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdowns)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        header_layout = QHBoxLayout()
        title_label = QLabel("💰 Pay-Per-View Events")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setToolTip("Reload PPV events")
        refresh_btn.clicked.connect(self._load_ppv_events)
        header_layout.addWidget(refresh_btn)
        layout.addLayout(header_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_container = QWidget()
        self.grid_layout = FlowLayout(self.grid_container, spacing=15)
        scroll_area.setWidget(self.grid_container)
        layout.addWidget(scroll_area)

    def _tick_countdowns(self):
        for card in self.event_cards:
            card.update_countdown()

    def _clear_cards(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.event_cards.clear()

    def _load_ppv_events(self):
        logger.info("Loading PPV events...")
        self._clear_cards()

        session = self.db.get_session()
        try:
            ppv_channels = session.query(ChannelDB).filter(
                ChannelDB.special_view == 'ppv'
            ).all()
        finally:
            session.close()

        now = datetime.now()
        upcoming = sorted(
            [ch for ch in ppv_channels if ch.event_start_time and ch.event_start_time >= now],
            key=lambda ch: ch.event_start_time,
        )
        past = sorted(
            [ch for ch in ppv_channels if ch.event_start_time and ch.event_start_time < now],
            key=lambda ch: ch.event_start_time, reverse=True,
        )
        no_time = [ch for ch in ppv_channels if not ch.event_start_time]
        all_events = upcoming + past + no_time

        logger.info(f"Found {len(all_events)} PPV events ({len(upcoming)} upcoming, {len(past)} past)")

        for channel in all_events:
            card = PPVEventCard(channel)
            card.play_requested.connect(self._on_play_requested)
            self.event_cards.append(card)
            self.grid_layout.addWidget(card)

        self.status_message.emit(f"Loaded {len(all_events)} PPV events")

    def _on_play_requested(self, channel):
        logger.info(f"Play requested for PPV event: {channel.name}")
        self.play_channel_requested.emit(channel)

    def on_activate(self):
        self._load_ppv_events()
        self._countdown_timer.start()

    def on_deactivate(self):
        self._countdown_timer.stop()

    def get_view_name(self) -> str:
        return "PPV Events"

    def get_ppv_event_count(self) -> int:
        session = self.db.get_session()
        try:
            return session.query(ChannelDB).filter(ChannelDB.special_view == 'ppv').count()
        finally:
            session.close()
