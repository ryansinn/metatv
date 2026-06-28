"""Similar Titles collapsible section for the details pane."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel, QMenu, QSizePolicy,
)
from PyQt6.QtCore import pyqtSignal, Qt

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.details_versions import ChannelVersion, resolve_category_name


# Icon-only action buttons — transparent, no border, hover brightens (single-use, token-built)
_ICON_BTN = (
    f"QPushButton {{ border: none; font-size: {_theme.FONT_LG}; padding: 0px;"
    " background: transparent; }"
    f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI}; }}"
)


class _SimilarSection(QWidget):
    """Collapsible 'Similar Titles' section showing fuzzy-matched content."""

    play_requested            = pyqtSignal(str)              # channel_id
    version_selected          = pyqtSignal(str)              # channel_id → show in details pane
    favorite_toggled          = pyqtSignal(str)              # channel_id
    queue_toggled             = pyqtSignal(str)              # channel_id
    prefix_exclude_requested  = pyqtSignal(str)              # prefix → add to global exclusions
    similar_preview_requested = pyqtSignal(list, int, str)   # (channel_ids, index, origin_title)

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
        self._toggle_btn = QPushButton(_icons.collapse_icon)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.setToolTip("Collapse Similar Titles")
        self._toggle_btn.clicked.connect(self._toggle)
        self._title_lbl = QLabel()
        self._title_lbl.setStyleSheet(
            f"font-weight: bold; color: {_theme.COLOR_TEXT};"
        )
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
            _icons.collapse_icon if self._expanded else _icons.expand_icon
        )
        self._toggle_btn.setToolTip(
            "Collapse Similar Titles" if self._expanded else "Expand Similar Titles"
        )

    # ------------------------------------------------------------------ #
    # Row builder                                                          #
    # ------------------------------------------------------------------ #

    def _make_row(self, v: ChannelVersion) -> QWidget:
        # Read stored ingestion fields — no render-time parse (CLAUDE.md ingestion-only rule).
        clean_title = v.detected_title or v.name
        year_str = v.detected_year or ""
        prefix = v.detected_prefix

        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(4)

        # 1. Play button
        play_btn = QPushButton(_icons.play_icon)
        play_btn.setFixedSize(22, 20)
        play_btn.setFlat(True)
        play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        play_btn.setStyleSheet(f"QPushButton {{ color: {_theme.COLOR_FAINT}; }} {_ICON_BTN}")
        play_btn.setToolTip(f"Play: {v.name}")
        play_btn.clicked.connect(lambda _, cid=v.channel_id: self.play_requested.emit(cid))
        row.addWidget(play_btn)

        # 2. Media type icon (🎬/📺/📡)
        type_icon = {
            "movie":  _icons.movie_icon,
            "series": _icons.series_icon,
            "live":   _icons.live_icon,
        }.get(v.media_type, "")
        if type_icon:
            type_lbl = QLabel(type_icon)
            type_lbl.setFixedWidth(18)
            type_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            type_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_MUTED};"
            )
            type_lbl.setToolTip((v.media_type or "").title())
            row.addWidget(type_lbl)

        # 3. Prefix chip — right-click opens context menu to add to global exclusions
        if prefix:
            full_name = resolve_category_name(prefix, self.config) or prefix
            chip = QPushButton(prefix)
            chip.setFixedHeight(18)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(_theme.CATEGORY_CHIP_SM)
            chip.setToolTip(full_name)
            chip.clicked.connect(lambda _, cid=v.channel_id: self.version_selected.emit(cid))
            chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            chip.customContextMenuRequested.connect(
                lambda pos, _p=prefix, _c=chip:
                    self._show_chip_menu(_c.mapToGlobal(pos), _p)
            )
            row.addWidget(chip)

        # 4. Name button — takes remaining space, shrinkable; right-click → lightbox preview
        name_btn = QPushButton(clean_title)
        name_btn.setFlat(True)
        name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        name_btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name_btn.setStyleSheet(
            f"QPushButton {{ text-align: left; color: {_theme.COLOR_TEXT};"
            f" font-size: {_theme.FONT_MD}; border: none; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI}; }}"
        )
        name_btn.setToolTip("Click: go to details  ·  Right-click: preview in lightbox")
        name_btn.clicked.connect(lambda _, cid=v.channel_id: self.version_selected.emit(cid))
        name_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        idx = self._channel_ids.index(v.channel_id)
        name_btn.customContextMenuRequested.connect(
            lambda _pos, _idx=idx: self.similar_preview_requested.emit(
                self._channel_ids, _idx, self._origin_title
            )
        )
        row.addWidget(name_btn, 1)

        # 5. Rating icon (liked / disliked — hidden when neutral)
        if v.user_rating == 1:
            rating_lbl = QLabel(_icons.like_icon)
            rating_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_ACCENT_BLUE};"
            )
            rating_lbl.setToolTip("You liked this")
            row.addWidget(rating_lbl)
        elif v.user_rating == -1:
            rating_lbl = QLabel(_icons.dislike_icon)
            rating_lbl.setStyleSheet(
                f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_ACCENT_ORANGE};"
            )
            rating_lbl.setToolTip("You disliked this")
            row.addWidget(rating_lbl)

        # 6. History indicator (previously watched)
        if v.in_history:
            hist = QLabel(_icons.history_icon)
            hist.setStyleSheet(
                f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_FAINT};"
            )
            hist.setToolTip("Previously watched")
            row.addWidget(hist)

        # 7. Year — right-aligned, fixed width so years form a column
        year_lbl = QLabel(year_str)
        year_lbl.setFixedWidth(36)
        year_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        year_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_SM}; color: {_theme.COLOR_MUTED_2};"
        )
        row.addWidget(year_lbl)

        # 8. Favorite toggle
        fav_color = _theme.COLOR_GOLD if v.is_favorite else _theme.COLOR_FAINT
        fav_btn = QPushButton(_icons.favorite_icon)
        fav_btn.setFixedSize(22, 20)
        fav_btn.setFlat(True)
        fav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fav_btn.setStyleSheet(f"QPushButton {{ color: {fav_color}; }} {_ICON_BTN}")
        fav_btn.setToolTip("Remove from Favorites" if v.is_favorite else "Add to Favorites")
        fav_btn.clicked.connect(lambda _, cid=v.channel_id: self.favorite_toggled.emit(cid))
        row.addWidget(fav_btn)

        # 9. Queue toggle — optimistic: flips icon/color on click without waiting for DB roundtrip
        q_icon = _icons.watched_icon if v.in_queue else _icons.queue_icon
        q_color = _theme.COLOR_ACCENT_BLUE if v.in_queue else _theme.COLOR_FAINT
        queue_btn = QPushButton(q_icon)
        queue_btn.setFixedSize(22, 20)
        queue_btn.setFlat(True)
        queue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        queue_btn.setStyleSheet(f"QPushButton {{ color: {q_color}; }} {_ICON_BTN}")
        queue_btn.setToolTip("Remove from Queue" if v.in_queue else "Add to Queue")

        def _on_queue_click(_checked=False, _btn=queue_btn, _v=v):
            # _checked absorbs the bool QPushButton.clicked emits — without it
            # the bool binds to the first param (_btn) and _btn.setText crashes.
            _v.in_queue = not _v.in_queue
            _btn.setText(_icons.watched_icon if _v.in_queue else _icons.queue_icon)
            _c = _theme.COLOR_ACCENT_BLUE if _v.in_queue else _theme.COLOR_FAINT
            _btn.setStyleSheet(f"QPushButton {{ color: {_c}; }} {_ICON_BTN}")
            _btn.setToolTip("Remove from Queue" if _v.in_queue else "Add to Queue")
            self.queue_toggled.emit(_v.channel_id)

        queue_btn.clicked.connect(_on_queue_click)
        row.addWidget(queue_btn)

        return row_w

    # ------------------------------------------------------------------ #
    # Context menus                                                        #
    # ------------------------------------------------------------------ #

    def _show_chip_menu(self, global_pos, prefix: str) -> None:
        full = resolve_category_name(prefix, self.config)
        header = f"{full} ({prefix})" if full else prefix

        menu = QMenu(self)
        title_act = menu.addAction(header)
        title_act.setEnabled(False)
        menu.addSeparator()
        excl_act = menu.addAction(f"Add '{prefix}' to Global Exclusions")
        excl_act.setToolTip(
            f"Hides all {prefix} content from recommendations, Similar Titles, and Discovery"
        )
        chosen = menu.exec(global_pos)
        if chosen == excl_act:
            self.prefix_exclude_requested.emit(prefix)
