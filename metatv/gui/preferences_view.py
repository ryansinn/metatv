"""Preferences dashboard — attribute weights + recommendations from user ratings."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QSize, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QContextMenuEvent, QColor, QPalette
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QVBoxLayout, QWidget,
)
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database
from metatv.core.media_mix import format_media_share
from metatv.core.preference_engine import AttributeWeights, ScoredChannel
from metatv.gui import theme as _theme

# Debounce before a dragged mix slider is persisted + the list re-scored.
_MIX_APPLY_DELAY_MS: int = 300


class _AttrRow(QWidget):
    """Single row: label | 🙅 | progress bar | ±value."""

    muteClicked = pyqtSignal(str, str)  # attr_type, attr_name

    def __init__(self, label: str, value: float, max_abs: float,
                 attr_type: str = "", attr_name: str = "",
                 muted: bool = False, config: Config | None = None,
                 parent=None):
        super().__init__(parent)
        self._attr_type = attr_type
        self._attr_name = attr_name or label

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
        color = _theme.COLOR_OK if value >= 0 else _theme.COLOR_ERR
        bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {_theme.COLOR_BORDER}; border-radius: 3px; background: {_theme.COLOR_LINE_DARK}; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}"
        )

        sign_lbl = QLabel(f"{value:+.1f}")
        sign_lbl.setFixedWidth(46)
        sign_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        hl.addWidget(lbl)

        if config and attr_type:
            icon = config.close_icon if muted else config.not_interested_icon
            tip  = "Restore to recommendations" if muted else "Exclude from recommendations"
            mute_btn = QPushButton(icon)
            mute_btn.setFixedSize(20, 20)
            mute_btn.setFlat(True)
            mute_btn.setToolTip(tip)
            _theme.style_fn(mute_btn, lambda: "QPushButton { border: none; }"
                f"QPushButton:hover {{ background: {_theme.OVERLAY_10}; border-radius: 3px; }}")
            mute_btn.clicked.connect(
                lambda: self.muteClicked.emit(self._attr_type, self._attr_name)
            )
            hl.addWidget(mute_btn)

        hl.addWidget(bar)
        hl.addWidget(sign_lbl)

        if muted:
            gray = QColor(_theme.COLOR_MUTED_2)
            for w in (lbl, sign_lbl):
                palette = w.palette()
                palette.setColor(QPalette.ColorRole.WindowText, gray)
                w.setPalette(palette)
            _theme.style_fn(bar, lambda: f"QProgressBar {{ border: 1px solid {_theme.COLOR_LINE}; border-radius: 3px; background: {_theme.COLOR_BG_BAR}; }}"
                f"QProgressBar::chunk {{ background: {_theme.COLOR_FAINT}; border-radius: 2px; }}")


class _AttrColumn(QWidget):
    """Scrollable column of attribute rows with a header."""

    muteClicked = pyqtSignal(str, str)  # attr_type, attr_name

    def __init__(self, title: str, items: list[tuple[str, float]],
                 attr_type: str = "", muted_names: set[str] | None = None,
                 config: Config | None = None, parent=None):
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

        _muted = muted_names or set()

        if items:
            max_abs = max(abs(v) for _, v in items)
            for label, value in sorted(items, key=lambda kv: kv[1], reverse=True):
                row = _AttrRow(
                    label, value, max_abs,
                    attr_type=attr_type, attr_name=label,
                    muted=label in _muted, config=config,
                )
                row.muteClicked.connect(self.muteClicked)
                inner_vl.addWidget(row)
        else:
            inner_vl.addWidget(QLabel("No data yet"))

        inner_vl.addStretch()
        scroll.setWidget(inner)
        vl.addWidget(scroll)


def _rec_row_btn_style() -> str:
    """Style for _RecRow's dislike/not-interested buttons, re-read fresh so a
    live theme switch applies."""
    return (
        "QPushButton { border: none; border-radius: 3px; padding: 2px; }"
        f"QPushButton:checked {{ background: {_theme.OVERLAY_18}; }}"
        f"QPushButton:hover   {{ background: {_theme.OVERLAY_10}; }}"
    )


class _RecRow(QWidget):
    """Single recommendation row: label + 👍/👎 buttons + Not Interested."""

    dislikeClicked       = pyqtSignal(str)        # channel_id
    notInterestedClicked = pyqtSignal(str)        # channel_id
    middleClicked        = pyqtSignal(str)        # channel_id — configured middle-click play
    contextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy

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
        self.dislike_btn.setStyleSheet(_rec_row_btn_style())
        self.dislike_btn.clicked.connect(lambda: self.dislikeClicked.emit(self.channel_id))
        hl.addWidget(self.dislike_btn)

        self.ni_btn = QPushButton(config.not_interested_icon)
        self.ni_btn.setFixedSize(26, 26)
        self.ni_btn.setToolTip("Not interested — hide from recommendations")
        self.ni_btn.setFlat(True)
        self.ni_btn.setStyleSheet(_rec_row_btn_style())
        self.ni_btn.clicked.connect(lambda: self.notInterestedClicked.emit(self.channel_id))
        hl.addWidget(self.ni_btn)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.contextMenuRequested.emit(self.channel_id, event.globalPos().x(), event.globalPos().y())
        event.accept()

    def mousePressEvent(self, event) -> None:
        # Middle-click on a recommendation row plays the user-configured action.
        # Non-left button presses on the child buttons (Dislike / Not Interested)
        # bubble up to here, so a middle-click anywhere on the row is caught.
        if event.button() == Qt.MouseButton.MiddleButton:
            self.middleClicked.emit(self.channel_id)
            event.accept()
            return
        super().mousePressEvent(event)


class PreferencesView(QWidget):
    # (AttributeWeights, list[ScoredChannel], movie share float | None)
    _pref_data_ready = pyqtSignal(object, object, object)
    """Dashboard: rated-item attribute weights + ranked recommendations."""

    playRequested               = pyqtSignal(str)       # channel_id
    channelSelected             = pyqtSignal(str)       # channel_id — single-click → details pane
    ratingRequested             = pyqtSignal(str, int)  # channel_id, ±1
    notInterestedRequested      = pyqtSignal(str)       # channel_id — hide from recommendations
    channelMiddleClicked        = pyqtSignal(str)       # channel_id — configured middle-click play
    channelContextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy

    def __init__(self, db: Database, config: Config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._active = False
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._pref_data_ready.connect(self._on_pref_data_ready)
        self._setup_ui()

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)

        # Header row
        header_row = QHBoxLayout()
        self._header_label = QLabel("No ratings yet")
        _theme.style_fn(self._header_label, lambda: f"font-size: {_theme.FONT_XL};")
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
        self._keyword_label.setToolTip("Click any keyword to exclude it from recommendations")
        self._keyword_label.setOpenExternalLinks(False)
        self._keyword_label.linkActivated.connect(self._on_keyword_link)
        attrs_vl.addWidget(self._keyword_label)

        vl.addWidget(self._attrs_container, stretch=2)

        # Recommendations list
        rec_header = QHBoxLayout()
        rec_label = QLabel(f"<b>{self.config.discover_icon} Recommended for you</b>  "
                           "<small>(double-click to play)</small>")
        rec_label.setTextFormat(Qt.TextFormat.RichText)
        rec_header.addWidget(rec_label)
        rec_header.addStretch()
        self._build_mix_controls(rec_header)
        vl.addLayout(rec_header)

        self._rec_list = QListWidget()
        self._rec_list.itemDoubleClicked.connect(self._on_rec_double_click)
        self._rec_list.currentItemChanged.connect(self._on_rec_selection_changed)
        self._rec_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._rec_list.customContextMenuRequested.connect(self._on_rec_context_menu)
        vl.addWidget(self._rec_list, stretch=3)

        # Exclusions panel — collapsible, at the bottom
        excl_header = QHBoxLayout()
        self._excl_toggle_btn = QPushButton(f"{self.config.expand_icon} Excluded (0)")
        self._excl_toggle_btn.setFlat(True)
        _theme.style_fn(self._excl_toggle_btn, lambda: f"QPushButton {{ text-align: left; color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; border: none; padding: 2px 0; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")
        self._excl_toggle_btn.clicked.connect(self._toggle_exclusions)
        excl_header.addWidget(self._excl_toggle_btn)
        excl_header.addStretch()
        vl.addLayout(excl_header)

        self._excl_container = QWidget()
        self._excl_layout = QVBoxLayout(self._excl_container)
        self._excl_layout.setContentsMargins(4, 0, 4, 4)
        self._excl_layout.setSpacing(2)
        self._excl_container.setVisible(False)
        vl.addWidget(self._excl_container)

        # Version Preferences section
        self._setup_version_prefs_section(vl)

        # Restore collapse state
        expanded = getattr(self.config, "preferences_attributes_expanded", False)
        self._attrs_container.setVisible(expanded)
        self._toggle_attrs_btn.setText(
            self.config.collapse_icon if expanded else self.config.expand_icon
        )
        self._toggle_attrs_btn.setToolTip(
            "Hide attribute breakdown" if expanded else "Show attribute breakdown"
        )

    def _build_mix_controls(self, row: QHBoxLayout) -> None:
        """Build the movie/series mix slider + Automatic reset into ``row``.

        The slider is the user's override of the automatic (√-damped) share; the
        Automatic button hands the decision back to the engine. Both write the one
        ``rec_media_mix`` config key immediately (UI state persistence) and are
        restored from it here, with signals blocked during the restore.
        """
        self._mix_caption_lbl = QLabel("Mix")
        _theme.style(self._mix_caption_lbl, "META_HINT")
        row.addWidget(self._mix_caption_lbl)

        self._mix_slider = QSlider(Qt.Orientation.Horizontal)
        self._mix_slider.setRange(0, 100)  # value = % of slots given to movies
        self._mix_slider.setFixedWidth(120)
        self._mix_slider.setToolTip(
            "Share of movies vs series in your recommendations.\n"
            "Drag to override the automatic mix; press Automatic to hand it back."
        )
        row.addWidget(self._mix_slider)

        self._mix_label = QLabel("")
        _theme.style_fn(self._mix_label, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD};")
        self._mix_label.setToolTip("Movies : series split of the list below")
        row.addWidget(self._mix_label)

        self._mix_auto_btn = QPushButton("Automatic")
        self._mix_auto_btn.setFlat(True)
        _theme.style(self._mix_auto_btn, "INLINE_ACTION_BTN")
        self._mix_auto_btn.setToolTip(
            "Match the balance of what you actually watch (square-root damped, so the\n"
            "smaller type is never crowded out)."
        )
        row.addWidget(self._mix_auto_btn)

        # Restore persisted state with signals blocked, then wire handlers.
        saved = getattr(self.config, "rec_media_mix", None)
        self._mix_slider.blockSignals(True)
        self._mix_slider.setValue(50 if saved is None else int(round(float(saved) * 100)))
        self._mix_slider.blockSignals(False)
        self._update_mix_controls(None if saved is None else float(saved))

        self._mix_timer = QTimer(self)
        self._mix_timer.setSingleShot(True)
        self._mix_timer.timeout.connect(self._apply_mix_override)
        self._mix_slider.valueChanged.connect(self._on_mix_slider_changed)
        self._mix_auto_btn.clicked.connect(self._on_mix_automatic)

    def _on_mix_slider_changed(self, value: int) -> None:
        """Preview the dragged ratio; persist + re-score once dragging settles."""
        self._mix_label.setText(format_media_share(value / 100.0))
        self._mix_auto_btn.setEnabled(True)
        self._mix_timer.start(_MIX_APPLY_DELAY_MS)

    def _apply_mix_override(self) -> None:
        self.config.rec_media_mix = self._mix_slider.value() / 100.0
        self.config.save()
        self.refresh()

    def _on_mix_automatic(self) -> None:
        self.config.rec_media_mix = None
        self.config.save()
        self._mix_auto_btn.setEnabled(False)
        self.refresh()

    def _update_mix_controls(self, media_share: float | None) -> None:
        """Sync the mix label/slider to the effective share.

        Args:
            media_share: The share the engine actually used, or ``None`` when it
                is not known yet (pre-load) — the label then falls back to the
                saved override, or a bare "Automatic".
        """
        if "_mix_label" not in self.__dict__:
            return
        saved = getattr(self.config, "rec_media_mix", None)
        automatic = saved is None
        share = media_share if media_share is not None else saved
        if share is None:
            self._mix_label.setText("Automatic")
        else:
            ratio = format_media_share(float(share))
            self._mix_label.setText(f"Automatic ({ratio})" if automatic else ratio)
            if automatic:
                # Park the handle on the computed share so dragging starts from
                # what the user is actually seeing.
                self._mix_slider.blockSignals(True)
                self._mix_slider.setValue(int(round(float(share) * 100)))
                self._mix_slider.blockSignals(False)
        self._mix_auto_btn.setEnabled(not automatic)

    def _setup_version_prefs_section(self, vl: QVBoxLayout) -> None:
        """Build the collapsible Version Preferences section."""
        ver_hdr = QHBoxLayout()
        self._ver_prefs_toggle_btn = QPushButton(
            f"{self.config.expand_icon} Version Preferences"
        )
        self._ver_prefs_toggle_btn.setFlat(True)
        _theme.style_fn(self._ver_prefs_toggle_btn, lambda: f"QPushButton {{ text-align: left; color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; border: none; padding: 2px 0; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}")
        self._ver_prefs_toggle_btn.clicked.connect(self._toggle_version_prefs)
        ver_hdr.addWidget(self._ver_prefs_toggle_btn)
        ver_hdr.addStretch()
        vl.addLayout(ver_hdr)

        self._ver_prefs_container = QWidget()
        ver_vl = QVBoxLayout(self._ver_prefs_container)
        ver_vl.setContentsMargins(4, 2, 4, 4)
        ver_vl.setSpacing(6)

        # Preferred prefixes
        ver_vl.addWidget(QLabel(
            "<b>Preferred prefixes</b>  <small>(ordered — first match wins)</small>"
        ))

        self._ver_prefix_list = QListWidget()
        self._ver_prefix_list.setMaximumHeight(100)
        self._ver_prefix_list.setToolTip(
            "Channels whose prefix matches the top entry get the highest preference score"
        )
        ver_vl.addWidget(self._ver_prefix_list)

        prefix_btn_row = QHBoxLayout()
        self._ver_prefix_input = QLineEdit()
        self._ver_prefix_input.setClearButtonEnabled(True)
        self._ver_prefix_input.setPlaceholderText("Add prefix (e.g. EN, US)")
        self._ver_prefix_input.setMaximumWidth(140)
        self._ver_prefix_input.returnPressed.connect(self._add_version_prefix)
        prefix_btn_row.addWidget(self._ver_prefix_input)

        add_prefix_btn = QPushButton("Add")
        add_prefix_btn.setFixedWidth(48)
        add_prefix_btn.clicked.connect(self._add_version_prefix)
        prefix_btn_row.addWidget(add_prefix_btn)

        rm_prefix_btn = QPushButton(self.config.close_icon)
        rm_prefix_btn.setFixedWidth(28)
        rm_prefix_btn.setToolTip("Remove selected prefix")
        rm_prefix_btn.clicked.connect(self._remove_version_prefix)
        prefix_btn_row.addWidget(rm_prefix_btn)

        up_btn = QPushButton(self.config.move_up_icon)
        up_btn.setFixedWidth(28)
        up_btn.setToolTip("Move selected prefix up (higher priority)")
        up_btn.clicked.connect(lambda: self._move_version_prefix(-1))
        prefix_btn_row.addWidget(up_btn)

        dn_btn = QPushButton(self.config.move_down_icon)
        dn_btn.setFixedWidth(28)
        dn_btn.setToolTip("Move selected prefix down")
        dn_btn.clicked.connect(lambda: self._move_version_prefix(1))
        prefix_btn_row.addWidget(dn_btn)

        prefix_btn_row.addStretch()
        ver_vl.addLayout(prefix_btn_row)

        # Preferred quality
        qual_row = QHBoxLayout()
        qual_row.addWidget(QLabel("<b>Preferred quality:</b>"))
        self._ver_quality_combo = QComboBox()
        self._ver_quality_combo.addItems(
            ["None (no preference)", "4K", "UHD", "FHD", "1080p", "HD", "RAW"]
        )
        self._ver_quality_combo.currentTextChanged.connect(self._on_quality_changed)
        qual_row.addWidget(self._ver_quality_combo)
        qual_row.addStretch()
        ver_vl.addLayout(qual_row)

        qual_note = QLabel(
            "<small>Channels whose name contains the quality marker get a preference boost.</small>"
        )
        qual_note.setTextFormat(Qt.TextFormat.RichText)
        qual_note.setWordWrap(True)
        ver_vl.addWidget(qual_note)

        self._ver_prefs_container.setVisible(False)
        vl.addWidget(self._ver_prefs_container)

        # Populate from config
        self._refresh_version_prefs_ui()

    def _toggle_version_prefs(self) -> None:
        visible = not self._ver_prefs_container.isVisible()
        self._ver_prefs_container.setVisible(visible)
        icon = self.config.collapse_icon if visible else self.config.expand_icon
        self._ver_prefs_toggle_btn.setText(f"{icon} Version Preferences")

    def _refresh_version_prefs_ui(self) -> None:
        self._ver_prefix_list.clear()
        for p in self.config.preferred_version_prefixes:
            self._ver_prefix_list.addItem(p)
        quality = self.config.preferred_version_quality or ""
        idx = self._ver_quality_combo.findText(quality)
        if idx < 0:
            idx = 0
        self._ver_quality_combo.blockSignals(True)
        self._ver_quality_combo.setCurrentIndex(idx)
        self._ver_quality_combo.blockSignals(False)

    def _add_version_prefix(self) -> None:
        text = self._ver_prefix_input.text().strip().upper()
        if not text:
            return
        prefixes = list(self.config.preferred_version_prefixes)
        if text not in prefixes:
            prefixes.append(text)
            self.config.preferred_version_prefixes = prefixes
            self.config.save()
            self._ver_prefix_list.addItem(text)
        self._ver_prefix_input.clear()

    def _remove_version_prefix(self) -> None:
        row = self._ver_prefix_list.currentRow()
        if row < 0:
            return
        prefixes = list(self.config.preferred_version_prefixes)
        if row < len(prefixes):
            prefixes.pop(row)
            self.config.preferred_version_prefixes = prefixes
            self.config.save()
            self._ver_prefix_list.takeItem(row)

    def _move_version_prefix(self, delta: int) -> None:
        row = self._ver_prefix_list.currentRow()
        prefixes = list(self.config.preferred_version_prefixes)
        new_row = row + delta
        if row < 0 or not (0 <= new_row < len(prefixes)):
            return
        prefixes[row], prefixes[new_row] = prefixes[new_row], prefixes[row]
        self.config.preferred_version_prefixes = prefixes
        self.config.save()
        self._ver_prefix_list.clear()
        for p in prefixes:
            self._ver_prefix_list.addItem(p)
        self._ver_prefix_list.setCurrentRow(new_row)

    def _on_quality_changed(self, text: str) -> None:
        if text.startswith("None"):
            self.config.preferred_version_quality = ""
        else:
            self.config.preferred_version_quality = text
        self.config.save()

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

    def _toggle_exclusions(self) -> None:
        visible = not self._excl_container.isVisible()
        self._excl_container.setVisible(visible)
        self._update_excl_toggle_label()

    def _update_excl_toggle_label(self) -> None:
        muted = getattr(self.config, 'muted_attributes', {})
        attr_count = sum(len(v) for v in muted.values())
        dedup_count = len(getattr(self.config, 'rec_dedupe_overrides', []))

        session = self.db.get_session()
        try:
            from metatv.core.repositories.channel import ChannelRepository
            chan_count = len(ChannelRepository(session).get_rec_suppressed())
        finally:
            session.close()

        total = attr_count + chan_count + dedup_count
        arrow = self.config.collapse_icon if self._excl_container.isVisible() else self.config.expand_icon
        self._excl_toggle_btn.setText(f"{arrow} Excluded ({total})")

    def on_activate(self) -> None:
        self._active = True
        self.refresh()

    def on_deactivate(self) -> None:
        self._active = False

    def refresh_theme(self) -> None:
        """Re-apply the active palette to this view's own persistent chrome
        styled once at construction — the "Mix" caption + mix label + the
        Automatic button, and the Excluded/Version Preferences collapsible
        toggles. Called from ``MainWindow.refresh_theme()``.

        Everything else (attribute columns, recommendation rows, the
        exclusions panel) is torn down and rebuilt from current tokens on
        every ``refresh()``/``_render()`` call, so it's already live — same
        rationale as the channel-list row delegate.
        """
        _theme.style(self._mix_caption_lbl, "META_HINT")
        _theme.style_fn(self._mix_label, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD};")
        _theme.style(self._mix_auto_btn, "INLINE_ACTION_BTN")

        _toggle_style = (
            f"QPushButton {{ text-align: left; color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; border: none; padding: 2px 0; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT}; }}"
        )
        self._excl_toggle_btn.setStyleSheet(_toggle_style)
        self._ver_prefs_toggle_btn.setStyleSheet(_toggle_style)

    def refresh(self) -> None:
        # Show a loading header so the stale "No ratings yet" never displays during
        # the (often multi-second) background load. _on_pref_data_ready → _render
        # overwrites this on both the has-ratings and genuinely-no-ratings branches.
        self._header_label.setText("Loading recommendations…")
        self._executor.submit(self._bg_refresh)

    def _bg_refresh(self) -> None:
        from metatv.core.preference_engine import (
            RecScoringSettings, compute_weights, score_candidates, version_score,
        )
        from metatv.core.filter_utils import get_active_category_filter, keyword_exclusion_list
        from metatv.core.media_mix import resolve_media_share
        from metatv.core.repositories import RepositoryFactory
        excluded_prefixes, include_uncategorized = get_active_category_filter(self.config)
        _config = self.config
        settings = RecScoringSettings.from_config(_config)
        session = self.db.get_session()
        try:
            weights = compute_weights(session, settings=settings)
            # Resolve the mix here (not inside the scorer) so the dashboard can
            # show the ratio the list was actually built with.
            media_share = resolve_media_share(session, settings.media_mix)
            recs = score_candidates(
                session, weights,
                muted_attrs=getattr(self.config, 'muted_attributes', None),
                dedupe_overrides=set(getattr(self.config, 'rec_dedupe_overrides', [])),
                excluded_prefixes=excluded_prefixes,
                include_uncategorized=include_uncategorized,
                excluded_keywords=keyword_exclusion_list(self.config) or None,
                excluded_provider_ids=RepositoryFactory(session).providers.get_hidden_provider_ids() or None,
                version_scorer=lambda ch: version_score(ch, _config),
                media_mix=media_share,
                diversify_people=True,
                settings=settings,
            )
        except Exception:
            logger.exception("PreferencesView bg refresh error")
            return
        finally:
            session.close()
        self._pref_data_ready.emit(weights, recs, media_share)

    def _on_pref_data_ready(self, weights, recs, media_share=None) -> None:
        if not self._active:
            return
        self._render(weights, recs, media_share)

    def _render(self, weights: AttributeWeights, recs: list[ScoredChannel],
                media_share: float | None = None) -> None:
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

        # Show the movie/series ratio this list was actually built with.
        self._update_mix_controls(media_share)

        # Rebuild attribute columns with mute buttons
        while self._attr_layout.count():
            item = self._attr_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        muted = getattr(self.config, 'muted_attributes', {})

        for title, attr_type in (("Genres", "genres"), ("Directors", "directors"), ("Actors", "actors")):
            col = _AttrColumn(
                title, weights.top(attr_type),
                attr_type=attr_type,
                muted_names=set(muted.get(attr_type, [])),
                config=self.config,
            )
            col.muteClicked.connect(self._on_attr_mute)
            self._attr_layout.addWidget(col)

        # Keywords — rendered as clickable links; muted words shown grayed/strikethrough
        muted_kws = set(muted.get("keywords", []))
        top_pos = [k for k, v in weights.top("keywords", 20) if v > 0][:8]
        top_neg = [k for k, v in weights.top("keywords", 20) if v < 0][:5]

        def _kw_link(word: str, base_color: str) -> str:
            if word in muted_kws:
                return (f'<a href="kw:{word}" style="color:{_theme.COLOR_TEXT}; '
                        f'text-decoration:line-through; font-style:italic;">{word}</a>')
            return f'<a href="kw:{word}" style="color:{base_color}; text-decoration:none;">{word}</a>'

        parts: list[str] = []
        if top_pos:
            links = "  ".join(_kw_link(k, _theme.COLOR_OK) for k in top_pos)
            parts.append(f"+ {links}")
        if top_neg:
            links = "  ".join(_kw_link(k, _theme.COLOR_ERR) for k in top_neg)
            parts.append(f"− {links}")
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
            self._rebuild_exclusions()
            return

        for sc in recs:
            text = f"{sc.channel_name}  ·  {sc.reason}"
            rating_tip = f"\n★{sc.metadata_rating:.1f}/10" if sc.metadata_rating else ""
            shown_tip = f"\nShown {sc.rec_shown_count}×" if sc.rec_shown_count else ""
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, sc.channel_id)
            item.setData(Qt.ItemDataRole.UserRole + 2, sc.variant_count)
            variant_tip = f"\n{sc.variant_count} versions grouped" if sc.variant_count > 1 else ""
            item.setToolTip(
                f"Score: {sc.score:.2f}{rating_tip}{shown_tip}{variant_tip}\n"
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
            row.middleClicked.connect(self.channelMiddleClicked)
            row.contextMenuRequested.connect(
                lambda cid, gx, gy, vc=sc.variant_count: self._on_row_context_menu(cid, gx, gy, vc)
            )
            self._rec_list.setItemWidget(item, row)

        # Record impressions after rendering (not before — count what the user actually saw)
        session = self.db.get_session()
        try:
            from metatv.core.preference_engine import record_impressions
            record_impressions(session, [sc.channel_id for sc in recs])
        finally:
            session.close()

        self._rebuild_exclusions()

    def _rebuild_exclusions(self) -> None:
        """Repopulate the exclusions review panel."""
        while self._excl_layout.count():
            item = self._excl_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        muted = getattr(self.config, 'muted_attributes', {})

        has_content = False

        # Muted attributes — grouped by type
        for attr_type, names in muted.items():
            if not names:
                continue
            has_content = True
            type_header = QLabel(f"<b>{attr_type.capitalize()}</b>")
            _theme.style_fn(type_header, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD};")
            self._excl_layout.addWidget(type_header)
            for name in names:
                row = self._make_exclusion_row(
                    name, attr_type,
                    lambda n=name, t=attr_type: self._on_attr_mute(t, n),
                )
                self._excl_layout.addWidget(row)

        # Not-interested channel titles
        session = self.db.get_session()
        try:
            from metatv.core.repositories.channel import ChannelRepository
            suppressed = ChannelRepository(session).get_rec_suppressed()
            names_ids = [(ch.name, ch.id) for ch in suppressed]
        finally:
            session.close()

        if names_ids:
            has_content = True
            titles_header = QLabel("<b>Not Interested titles</b>")
            _theme.style_fn(titles_header, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD};")
            self._excl_layout.addWidget(titles_header)
            for name, cid in names_ids:
                row = self._make_exclusion_row(
                    name, "title",
                    lambda c=cid: self._on_restore_channel(c),
                )
                self._excl_layout.addWidget(row)

        # Dedup overrides — channels broken out of their title group
        dedup_overrides = getattr(self.config, 'rec_dedupe_overrides', [])
        if dedup_overrides:
            has_content = True
            dedup_header = QLabel("<b>Shown separately (ungrouped)</b>")
            _theme.style_fn(dedup_header, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD};")
            self._excl_layout.addWidget(dedup_header)
            session = self.db.get_session()
            try:
                from metatv.core.database import ChannelDB
                for cid in dedup_overrides:
                    ch = session.get(ChannelDB, cid)
                    name = ch.name if ch else cid
                    row = self._make_exclusion_row(
                        name, "ungrouped",
                        lambda c=cid: self._on_restore_dedup(c),
                    )
                    self._excl_layout.addWidget(row)
            finally:
                session.close()

        if not has_content:
            self._excl_layout.addWidget(QLabel("<i>Nothing excluded yet</i>"))

        self._update_excl_toggle_label()

    def _make_exclusion_row(self, name: str, type_label: str, on_restore) -> QWidget:
        """Row: '[name] · [type] — not interesting to you   Change your mind?'"""
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(6)

        singular = type_label.rstrip("s") if type_label.endswith("s") else type_label
        lbl = QLabel(
            f"<b>{name}</b> · "
            f"<span style='color:{_theme.COLOR_TEXT}'>{singular}</span>"
            f" — not interesting to you"
        )
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setWordWrap(True)
        hl.addWidget(lbl, stretch=1)

        change_btn = QPushButton("Change your mind?")
        change_btn.setFlat(True)
        _theme.style_fn(change_btn, lambda: f"QPushButton {{ color: {_theme.COLOR_ACCENT_BLUE}; text-decoration: underline; border: none; "
            f"background: transparent; padding: 0; font-size: {_theme.FONT_MD}; }}"
            f"QPushButton:hover {{ color: {_theme.COLOR_ACCENT_HOVER}; }}")
        change_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        change_btn.clicked.connect(on_restore)
        hl.addWidget(change_btn)
        return w

    def _on_keyword_link(self, href: str) -> None:
        if href.startswith("kw:"):
            self._on_attr_mute("keywords", href[3:])

    def _on_attr_mute(self, attr_type: str, attr_name: str) -> None:
        muted: list = self.config.muted_attributes.setdefault(attr_type, [])
        if attr_name in muted:
            muted.remove(attr_name)
        else:
            muted.append(attr_name)
        self.config.save()
        self.refresh()

    def _on_restore_channel(self, channel_id: str) -> None:
        from metatv.core.repositories.channel import ChannelRepository
        session = self.db.get_session()
        try:
            ChannelRepository(session).set_rec_suppressed(channel_id, False)
        finally:
            session.close()
        self.refresh()

    def _on_row_context_menu(self, channel_id: str, gx: int, gy: int, variant_count: int = 1) -> None:
        if variant_count <= 1:
            self.channelContextMenuRequested.emit(channel_id, gx, gy)
            return
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        sep_action = menu.addAction(f"≠  Show {variant_count} versions separately")
        menu.addSeparator()
        more_action = menu.addAction("More options...")
        chosen = menu.exec(QPoint(gx, gy))
        if chosen == sep_action:
            self._on_show_separately(channel_id)
        elif chosen == more_action:
            self.channelContextMenuRequested.emit(channel_id, gx, gy)

    def _on_show_separately(self, channel_id: str) -> None:
        overrides: list = list(getattr(self.config, 'rec_dedupe_overrides', []))
        if channel_id not in overrides:
            overrides.append(channel_id)
            self.config.rec_dedupe_overrides = overrides
            self.config.save()
        self.refresh()

    def _on_restore_dedup(self, channel_id: str) -> None:
        overrides: list = list(getattr(self.config, 'rec_dedupe_overrides', []))
        if channel_id in overrides:
            overrides.remove(channel_id)
            self.config.rec_dedupe_overrides = overrides
            self.config.save()
        self.refresh()

    def _on_rec_context_menu(self, pos) -> None:
        item = self._rec_list.itemAt(pos)
        if not item:
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        variant_count = item.data(Qt.ItemDataRole.UserRole + 2) or 1
        if channel_id:
            gp = self._rec_list.viewport().mapToGlobal(pos)
            self._on_row_context_menu(channel_id, gp.x(), gp.y(), variant_count)

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
