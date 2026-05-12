"""PPV (Pay-Per-View) events view with time-based grid layout"""

from datetime import datetime
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget,
    QGridLayout, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from loguru import logger

from metatv.gui.content_view import ContentView
from metatv.core.database import ChannelDB


class PPVEventCard(QFrame):
    """Card widget for a single PPV event"""
    
    play_requested = pyqtSignal(object)  # channel object
    
    def __init__(self, channel: ChannelDB, parent=None):
        super().__init__(parent)
        self.channel = channel
        self.setup_ui()
        
        # Update countdown every second
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)
    
    def setup_ui(self):
        """Setup card UI"""
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)
        self.setMaximumWidth(300)
        
        layout = QVBoxLayout(self)
        
        # Event poster/icon
        self.poster_label = QLabel()
        self.poster_label.setFixedSize(280, 158)  # 16:9 ratio
        self.poster_label.setScaledContents(True)
        self.poster_label.setStyleSheet("background-color: #2a2a2a; border-radius: 4px;")
        layout.addWidget(self.poster_label)
        
        # Event name
        event_name = self.channel.event_metadata.get('event_name', 'Unknown Event') if self.channel.event_metadata else 'Unknown Event'
        self.name_label = QLabel(event_name)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.name_label)
        
        # Date/time and countdown
        self.datetime_label = QLabel()
        self.datetime_label.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self.datetime_label)
        
        self.countdown_label = QLabel()
        self.countdown_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff6b35;")
        layout.addWidget(self.countdown_label)
        
        # Quality and sport type badges
        badges_layout = QHBoxLayout()
        
        if self.channel.event_metadata:
            quality = self.channel.event_metadata.get('quality')
            if quality:
                quality_badge = QLabel(quality)
                quality_badge.setStyleSheet(
                    "background-color: #4CAF50; color: white; padding: 2px 8px; "
                    "border-radius: 3px; font-size: 10px; font-weight: bold;"
                )
                badges_layout.addWidget(quality_badge)
            
            sport_type = self.channel.event_metadata.get('sport_type')
            if sport_type:
                sport_badge = QLabel(sport_type.capitalize())
                sport_badge.setStyleSheet(
                    "background-color: #2196F3; color: white; padding: 2px 8px; "
                    "border-radius: 3px; font-size: 10px; font-weight: bold;"
                )
                badges_layout.addWidget(sport_badge)
        
        badges_layout.addStretch()
        layout.addLayout(badges_layout)
        
        # Play button
        self.play_button = QPushButton("▶ Watch")
        self.play_button.clicked.connect(lambda: self.play_requested.emit(self.channel))
        self.play_button.setStyleSheet(
            "background-color: #ff6b35; color: white; border: none; "
            "padding: 8px; border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(self.play_button)
        
        self.update_countdown()
    
    def update_countdown(self):
        """Update countdown timer"""
        if not self.channel.event_start_time:
            self.datetime_label.setText("Date/time unavailable")
            self.countdown_label.setText("")
            return
        
        # Format date/time
        dt_str = self.channel.event_start_time.strftime("%b %d, %Y at %I:%M %p")
        self.datetime_label.setText(dt_str)
        
        # Calculate time until event
        now = datetime.now()
        time_until = self.channel.event_start_time - now
        
        if time_until.total_seconds() < 0:
            # Event has passed
            days_ago = abs(time_until.days)
            if days_ago == 0:
                self.countdown_label.setText("Ended (replay available)")
            else:
                self.countdown_label.setText(f"Ended {days_ago} day{'s' if days_ago != 1 else ''} ago")
            self.countdown_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #888;")
        else:
            # Event is upcoming
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
            self.countdown_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #ff6b35;")


class PPVView(ContentView):
    """PPV events view with time-sorted grid layout"""
    
    play_channel_requested = pyqtSignal(object)  # channel object
    
    def __init__(self, config, db, parent=None):
        super().__init__(config, parent)
        self.db = db
        self.event_cards = []
        self.setup_ui()
    
    def setup_ui(self):
        """Setup PPV view UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header
        header_layout = QHBoxLayout()
        
        title_label = QLabel("💰 Pay-Per-View Events")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Refresh button
        refresh_button = QPushButton("🔄 Refresh")
        refresh_button.clicked.connect(self.refresh_events)
        header_layout.addWidget(refresh_button)
        
        layout.addLayout(header_layout)
        
        # Scroll area for event grid
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(15)
        
        scroll_area.setWidget(self.grid_container)
        layout.addWidget(scroll_area)
    
    def load_ppv_events(self):
        """Load PPV events from database"""
        logger.info("Loading PPV events...")
        
        # Clear existing cards
        for card in self.event_cards:
            card.deleteLater()
        self.event_cards.clear()
        
        # Query PPV channels
        with self.db.get_session() as session:
            ppv_channels = session.query(ChannelDB).filter(
                ChannelDB.special_view == 'ppv'
            ).all()
        
            # Sort by event start time (upcoming first, then past events)
            now = datetime.now()
            upcoming = [ch for ch in ppv_channels if ch.event_start_time and ch.event_start_time >= now]
            past = [ch for ch in ppv_channels if ch.event_start_time and ch.event_start_time < now]
            no_time = [ch for ch in ppv_channels if not ch.event_start_time]
            
            upcoming.sort(key=lambda ch: ch.event_start_time)
            past.sort(key=lambda ch: ch.event_start_time, reverse=True)
            
            all_events = upcoming + past + no_time
            
            logger.info(f"Found {len(all_events)} PPV events ({len(upcoming)} upcoming, {len(past)} past)")
        
            # Create grid of event cards (3 columns)
            row = 0
            col = 0
            for channel in all_events:
                card = PPVEventCard(channel)
                card.play_requested.connect(self.on_play_requested)
                self.event_cards.append(card)
                
                self.grid_layout.addWidget(card, row, col)
                
                col += 1
                if col >= 3:
                    col = 0
                    row += 1
            
            # Add stretch to push cards to top
            self.grid_layout.setRowStretch(row + 1, 1)
        
        self.status_message.emit(f"Loaded {len(all_events)} PPV events")
    
    def refresh_events(self):
        """Refresh PPV events"""
        self.load_ppv_events()
    
    def on_play_requested(self, channel):
        """Handle play button click"""
        logger.info(f"Play requested for PPV event: {channel.name}")
        self.play_channel_requested.emit(channel)
    
    def on_activate(self):
        """Load events when view becomes active"""
        self.load_ppv_events()
    
    def get_view_name(self) -> str:
        return "PPV Events"
    
    def get_ppv_event_count(self) -> int:
        """Get count of PPV events (for badge on toggle button)"""
        with self.db.get_session() as session:
            count = session.query(ChannelDB).filter(
                ChannelDB.special_view == 'ppv'
            ).count()
            return count
