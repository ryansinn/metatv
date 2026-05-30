"""Similar Titles collapsible section for the details pane."""
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
)
from PyQt6.QtCore import pyqtSignal, Qt

from metatv.gui.details_versions import ChannelVersion


class _SimilarSection(QWidget):
    """Collapsible 'Similar Titles' section showing fuzzy-matched content."""

    play_requested          = pyqtSignal(str)              # channel_id
    version_selected        = pyqtSignal(str)              # channel_id → show in details pane
    favorite_toggled        = pyqtSignal(str)              # channel_id
    queue_toggled           = pyqtSignal(str)              # channel_id
    similar_preview_requested = pyqtSignal(list, int, str) # (channel_ids, index, origin_title)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._channel_ids: list[str] = []
        self._origin_title: str = ""
        self._expanded = True
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header row
        self._header = QWidget()
        hdr = QHBoxLayout(self._header)
        hdr.setContentsMargins(0, 4, 0, 2)
        hdr.setSpacing(4)
        self._toggle_btn = QPushButton(self.config.collapse_icon)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setToolTip("Collapse Similar Titles")
        self._toggle_btn.clicked.connect(self._toggle)
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet("font-weight: bold; color: #ccc;")
        hdr.addWidget(self._toggle_btn)
        hdr.addWidget(self._title_lbl)
        hdr.addStretch()
        self._header.hide()
        layout.addWidget(self._header)

        # Body
        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(4, 0, 0, 4)
        self._body_layout.setSpacing(2)
        self._body.hide()
        layout.addWidget(self._body)

    def load(self, titles: list[ChannelVersion], origin_title: str = "") -> None:
        """Populate the section. Hides itself if titles is empty."""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if not titles:
            self._header.hide()
            self._body.hide()
            self._channel_ids = []
            return

        self._channel_ids = [v.channel_id for v in titles]
        self._origin_title = origin_title

        self._title_lbl.setText(f"Similar Titles ({len(titles)})")
        self._header.show()
        if self._expanded:
            self._body.show()

        for v in titles:
            self._body_layout.addWidget(self._make_row(v))

    def clear(self) -> None:
        self.load([])

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_btn.setText(
            self.config.collapse_icon if self._expanded else self.config.expand_icon
        )
        self._toggle_btn.setToolTip(
            "Collapse Similar Titles" if self._expanded else "Expand Similar Titles"
        )

    def _make_row(self, v: ChannelVersion) -> QWidget:
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(4)

        play_btn = QPushButton(self.config.play_icon)
        play_btn.setFixedSize(24, 20)
        play_btn.setFlat(True)
        play_btn.setToolTip(f"Play: {v.name}")
        play_btn.clicked.connect(lambda _, cid=v.channel_id: self.play_requested.emit(cid))
        row.addWidget(play_btn)

        name_btn = QPushButton(v.name)
        name_btn.setFlat(True)
        name_btn.setStyleSheet(
            "QPushButton { text-align: left; color: #ccc; font-size: 11px; border: none; }"
            "QPushButton:hover { color: #fff; }"
        )
        name_btn.setToolTip("Click: go to details  ·  Right-click: preview")
        name_btn.clicked.connect(lambda _, cid=v.channel_id: self.version_selected.emit(cid))
        name_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        idx = self._channel_ids.index(v.channel_id)
        name_btn.customContextMenuRequested.connect(
            lambda _pos, _idx=idx: self.similar_preview_requested.emit(
                self._channel_ids, _idx, self._origin_title
            )
        )
        row.addWidget(name_btn, 1)

        status_parts = []
        if v.is_favorite: status_parts.append(self.config.favorite_icon)
        if v.in_history:  status_parts.append(self.config.history_icon)
        if v.in_queue:    status_parts.append(self.config.queue_icon)
        if status_parts:
            status_lbl = QLabel(" ".join(status_parts))
            status_lbl.setStyleSheet("font-size: 10px; color: #666;")
            row.addWidget(status_lbl)

        fav_btn = QPushButton(
            self.config.favorite_icon if v.is_favorite else self.config.unfavorite_icon
        )
        fav_btn.setFixedSize(24, 20)
        fav_btn.setFlat(True)
        fav_btn.setToolTip("Remove from Favorites" if v.is_favorite else "Add to Favorites")
        fav_btn.clicked.connect(lambda _, cid=v.channel_id: self.favorite_toggled.emit(cid))
        row.addWidget(fav_btn)

        queue_icon = self.config.watched_icon if v.in_queue else self.config.queue_icon
        queue_btn = QPushButton(queue_icon)
        queue_btn.setFixedSize(24, 20)
        queue_btn.setFlat(True)
        queue_btn.setToolTip("Remove from Queue" if v.in_queue else "Add to Queue")
        queue_btn.clicked.connect(lambda _, cid=v.channel_id: self.queue_toggled.emit(cid))
        row.addWidget(queue_btn)

        return row_w
