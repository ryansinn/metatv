"""Preferences dashboard — attribute weights + recommendations from user ratings."""

from __future__ import annotations

from PyQt6.QtCore import QSize, pyqtSignal, Qt, QPoint
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.preference_engine import AttributeWeights, ScoredChannel


class _AttrRow(QWidget):
    """Single row: label | progress bar | ±value."""

    def __init__(self, label: str, value: float, max_abs: float, parent=None):
        super().__init__(parent)
        hl = QHBoxLayout(self)
        hl.setContentsMargins(2, 1, 4, 1)
        hl.setSpacing(6)

        lbl = QLabel()
        fm = lbl.fontMetrics()
        lbl.setText(fm.elidedText(label, Qt.TextElideMode.ElideRight, 140))
        lbl.setToolTip(label)
        lbl.setFixedWidth(140)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(abs(value) / max_abs * 100) if max_abs > 0 else 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setMinimumWidth(40)
        bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        color = "#4caf50" if value >= 0 else "#f44336"
        bar.setStyleSheet(
            "QProgressBar { border: 1px solid #444; border-radius: 3px; background: #2a2a2a; }"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
        )

        sign_lbl = QLabel(f"{value:+.1f}")
        sign_lbl.setFixedWidth(46)
        sign_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        hl.addWidget(lbl)
        hl.addWidget(bar)
        hl.addWidget(sign_lbl)


class _AttrColumn(QWidget):
    """Scrollable column of attribute rows with a header."""

    def __init__(self, title: str, items: list[tuple[str, float]], parent=None):
        super().__init__(parent)
        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        header = QLabel(f"<b>{title}</b>")
        vl.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner_vl = QVBoxLayout(inner)
        inner_vl.setContentsMargins(0, 0, 0, 0)
        inner_vl.setSpacing(1)

        if items:
            max_abs = max(abs(v) for _, v in items)
            for label, value in sorted(items, key=lambda kv: kv[1], reverse=True):
                inner_vl.addWidget(_AttrRow(label, value, max_abs))
        else:
            inner_vl.addWidget(QLabel("No data yet"))

        inner_vl.addStretch()
        scroll.setWidget(inner)
        vl.addWidget(scroll)


class _RecRow(QWidget):
    """Single recommendation row: label + 👍/👎 buttons + Not Interested."""

    dislikeClicked       = pyqtSignal(str)        # channel_id
    notInterestedClicked = pyqtSignal(str)        # channel_id
    contextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy

    _BTN_STYLE = (
        "QPushButton { border: none; border-radius: 3px; padding: 2px; }"
        "QPushButton:checked { background: rgba(255,255,255,0.18); }"
        "QPushButton:hover   { background: rgba(255,255,255,0.10); }"
    )

    def __init__(self, channel_id: str, text: str, config: Config,
                 already_liked: bool = False, parent=None):
        super().__init__(parent)
        self.channel_id = channel_id
        hl = QHBoxLayout(self)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(4)

        if already_liked:
            liked_lbl = QLabel(config.like_icon)
            liked_lbl.setFixedWidth(18)
            hl.addWidget(liked_lbl)

        lbl = QLabel(text)
        lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(lbl)

        self.dislike_btn = QPushButton(config.dislike_icon)
        self.dislike_btn.setFixedSize(26, 26)
        self.dislike_btn.setToolTip("Dislike")
        self.dislike_btn.setFlat(True)
        self.dislike_btn.setStyleSheet(self._BTN_STYLE)
        self.dislike_btn.clicked.connect(lambda: self.dislikeClicked.emit(self.channel_id))
        hl.addWidget(self.dislike_btn)

        self.ni_btn = QPushButton(config.not_interested_icon)
        self.ni_btn.setFixedSize(26, 26)
        self.ni_btn.setToolTip("Not interested — hide from recommendations")
        self.ni_btn.setFlat(True)
        self.ni_btn.setStyleSheet(self._BTN_STYLE)
        self.ni_btn.clicked.connect(lambda: self.notInterestedClicked.emit(self.channel_id))
        hl.addWidget(self.ni_btn)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.contextMenuRequested.emit(self.channel_id, event.globalPos().x(), event.globalPos().y())
        event.accept()


class PreferencesView(QWidget):
    """Dashboard: rated-item attribute weights + ranked recommendations."""

    playRequested               = pyqtSignal(str)       # channel_id
    channelSelected             = pyqtSignal(str)       # channel_id — single-click → details pane
    ratingRequested             = pyqtSignal(str, int)  # channel_id, ±1
    notInterestedRequested      = pyqtSignal(str)       # channel_id — hide from recommendations
    channelContextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy

    def __init__(self, db: Database, config: Config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)

        # Header row
        header_row = QHBoxLayout()
        self._header_label = QLabel("No ratings yet")
        self._header_label.setStyleSheet("font-size: 13px;")
        header_row.addWidget(self._header_label)
        header_row.addStretch()

        self._toggle_attrs_btn = QPushButton(self.config.expand_icon)
        self._toggle_attrs_btn.setFixedSize(24, 24)
        self._toggle_attrs_btn.setToolTip("Show attribute breakdown")
        self._toggle_attrs_btn.clicked.connect(self._toggle_attributes)
        header_row.addWidget(self._toggle_attrs_btn)

        refresh_btn = QPushButton(self.config.refresh_icon)
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(refresh_btn)
        vl.addLayout(header_row)

        # Collapsible container: attribute columns + keywords
        self._attrs_container = QWidget()
        attrs_vl = QVBoxLayout(self._attrs_container)
        attrs_vl.setContentsMargins(0, 0, 0, 4)
        attrs_vl.setSpacing(4)

        self._attr_area = QWidget()
        self._attr_layout = QHBoxLayout(self._attr_area)
        self._attr_layout.setContentsMargins(0, 0, 0, 0)
        self._attr_layout.setSpacing(8)
        attrs_vl.addWidget(self._attr_area, stretch=1)

        kw_label = QLabel("<b>Keywords from your ratings</b>")
        attrs_vl.addWidget(kw_label)
        self._keyword_label = QLabel("")
        self._keyword_label.setWordWrap(True)
        self._keyword_label.setTextFormat(Qt.TextFormat.RichText)
        attrs_vl.addWidget(self._keyword_label)

        vl.addWidget(self._attrs_container, stretch=2)

        # Recommendations list
        rec_label = QLabel(f"<b>{self.config.discover_icon} Recommended for you</b>  "
                           "<small>(double-click to play)</small>")
        rec_label.setTextFormat(Qt.TextFormat.RichText)
        vl.addWidget(rec_label)

        self._rec_list = QListWidget()
        self._rec_list.itemDoubleClicked.connect(self._on_rec_double_click)
        self._rec_list.currentItemChanged.connect(self._on_rec_selection_changed)
        self._rec_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._rec_list.customContextMenuRequested.connect(self._on_rec_context_menu)
        vl.addWidget(self._rec_list, stretch=3)

        # Restore collapse state
        expanded = getattr(self.config, "preferences_attributes_expanded", False)
        self._attrs_container.setVisible(expanded)
        self._toggle_attrs_btn.setText(
            self.config.collapse_icon if expanded else self.config.expand_icon
        )
        self._toggle_attrs_btn.setToolTip(
            "Hide attribute breakdown" if expanded else "Show attribute breakdown"
        )

    def _toggle_attributes(self) -> None:
        expanded = not self._attrs_container.isVisible()
        self._attrs_container.setVisible(expanded)
        self._toggle_attrs_btn.setText(
            self.config.collapse_icon if expanded else self.config.expand_icon
        )
        self._toggle_attrs_btn.setToolTip(
            "Hide attribute breakdown" if expanded else "Show attribute breakdown"
        )
        self.config.preferences_attributes_expanded = expanded
        self.config.save()

    def on_activate(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        from metatv.core.preference_engine import compute_weights, score_candidates

        session = self.db.get_session()
        try:
            weights = compute_weights(session)
            recs = score_candidates(session, weights)
        finally:
            session.close()

        self._render(weights, recs)

    def _render(self, weights: AttributeWeights, recs: list[ScoredChannel]) -> None:
        # Header
        if weights.is_empty():
            self._header_label.setText(
                "No ratings yet — right-click movies or series and choose "
                f"{self.config.like_icon} Like or {self.config.dislike_icon} Dislike"
            )
        else:
            self._header_label.setText(
                f"{weights.rated_count} rated  ·  "
                f"{self.config.like_icon} {weights.liked_count}  "
                f"{self.config.dislike_icon} {weights.disliked_count}"
            )

        # Rebuild attribute columns
        while self._attr_layout.count():
            item = self._attr_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._attr_layout.addWidget(_AttrColumn("Genres",    weights.top("genres")))
        self._attr_layout.addWidget(_AttrColumn("Directors", weights.top("directors")))
        self._attr_layout.addWidget(_AttrColumn("Actors",    weights.top("actors")))

        # Keywords
        top_pos = [k for k, v in weights.top("keywords", 20) if v > 0][:8]
        top_neg = [k for k, v in weights.top("keywords", 20) if v < 0][:5]
        parts: list[str] = []
        if top_pos:
            words = "  ".join(top_pos)
            parts.append(f'<span style="color:#4caf50">+ {words}</span>')
        if top_neg:
            words = "  ".join(top_neg)
            parts.append(f'<span style="color:#f44336">− {words}</span>')
        self._keyword_label.setText(
            "  |  ".join(parts) if parts else "<i>Rate more content to see keywords</i>"
        )

        # Recommendations
        self._rec_list.clear()
        if not recs:
            if weights.is_empty():
                self._rec_list.addItem("Rate some movies or series to get recommendations")
            else:
                self._rec_list.addItem("No matching unrated content found — try rating more items")
            return

        for sc in recs:
            text = f"{sc.channel_name}  ·  {sc.reason}"
            rating_tip = f"\n★{sc.metadata_rating:.1f}/10" if sc.metadata_rating else ""
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, sc.channel_id)
            item.setToolTip(
                f"Score: {sc.score:.2f}{rating_tip}\n"
                f"Genres: {', '.join(sc.matching_genres) or '—'}\n"
                f"Keywords: {', '.join(sc.matching_keywords) or '—'}"
            )
            item.setSizeHint(QSize(0, 32))
            self._rec_list.addItem(item)
            row = _RecRow(sc.channel_id, text, self.config, already_liked=sc.already_liked)
            row.dislikeClicked.connect(
                lambda cid=sc.channel_id: self.ratingRequested.emit(cid, -1)
            )
            row.notInterestedClicked.connect(
                lambda cid=sc.channel_id: self.notInterestedRequested.emit(cid)
            )
            row.contextMenuRequested.connect(self.channelContextMenuRequested)
            self._rec_list.setItemWidget(item, row)

    def _on_rec_context_menu(self, pos) -> None:
        item = self._rec_list.itemAt(pos)
        if not item:
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            gp = self._rec_list.viewport().mapToGlobal(pos)
            self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())

    def _on_rec_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current:
            channel_id = current.data(Qt.ItemDataRole.UserRole)
            if channel_id:
                self.channelSelected.emit(channel_id)

    def _on_rec_double_click(self, item: QListWidgetItem) -> None:
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            logger.debug(f"Preferences: play requested for {channel_id}")
            self.playRequested.emit(channel_id)
