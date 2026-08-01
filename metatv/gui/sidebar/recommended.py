"""RecommendedSection — sidebar VOD recommendations from the preference engine."""

from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import (
    QLabel, QPushButton, QSizePolicy, QListWidget, QListWidgetItem, QWidget, QHBoxLayout,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from loguru import logger

from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import CollapsibleSection

# Sentinel emitted by _bg_refresh when the background load raises, so
# _on_rec_data_ready can render a visible error row instead of leaving the
# section stuck on the "Loading recommendations…" placeholder forever.
_REC_LOAD_ERROR = object()


class _MiddleElideLabel(QLabel):
    """Single-line title label that middle-elides ('Long ti…tle') only when genuinely
    too long for its width.

    Sizes to content: ``sizeHint`` = full-text advance + a small buffer, so — laid out
    with a Preferred policy and no stretch — a title that fits is given enough width and
    is NEVER clipped. The buffer absorbs the sub-pixel layout rounding that previously
    chopped even short titles ("1983" → "1…3"). Zero contents margins + eliding against
    the label's FULL ``width()`` in ``paintEvent`` (drawing in ``rect()``, not a
    margin-shrunk ``contentsRect()``) keeps the elide threshold identical to the draw
    area, so a title exactly as wide as its box still renders in full. Only when the row
    is too narrow does the label shrink toward ``minimumSizeHint`` (width of "…") and the
    title middle-elide. Keeps the full text as the tooltip and as ``text()``; the pen
    colour comes from the ``COLOR_TEXT`` token (never a literal). Promote to a shared
    widgets module when the search-results list adopts chips.
    """

    # Slack added to the preferred width so a title that fits is never clipped by
    # sub-pixel layout rounding (guards the "1983" → "1…3" regression).
    _HINT_BUFFER_PX = 8

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text or ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setContentsMargins(0, 0, 0, 0)  # elide/draw width == the label's full width
        self.setToolTip(self._full)
        # Keep QLabel's own text set to the full string so its size-hint height stays
        # correct; the overridden paintEvent draws the elided form, so QLabel's default
        # (full-text) painter never runs.
        super().setText(self._full)

    def setText(self, text: str) -> None:  # keep _full authoritative if reused
        self._full = text or ""
        self.setToolTip(self._full)
        super().setText(self._full)  # updates height hints + text(); paintEvent re-elides

    def text(self) -> str:  # authoritative full text (not the elided paint)
        return self._full

    def minimumSizeHint(self) -> QSize:
        h = super().minimumSizeHint().height()
        return QSize(self.fontMetrics().horizontalAdvance("…"), h)

    def sizeHint(self) -> QSize:
        h = super().sizeHint().height()
        w = self.fontMetrics().horizontalAdvance(self._full) + self._HINT_BUFFER_PX
        return QSize(w, h)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setPen(QColor(_theme.COLOR_TEXT))  # token, never a literal
        elided = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideMiddle, self.width()
        )
        painter.drawText(self.rect(), int(self.alignment().value), elided)


class RecommendedSection(CollapsibleSection):
    """Sidebar section showing top VOD recommendations from the preference engine."""

    itemSelected              = pyqtSignal(str, str)  # channel_id, reason
    itemDoubleClicked         = pyqtSignal(str)        # channel_id
    channelMiddleClicked      = pyqtSignal(str)        # channel_id — configured middle-click play
    channelContextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy
    _rec_data_ready           = pyqtSignal(object)     # list[ScoredCandidate] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        self._executor = ThreadPoolExecutor(max_workers=1)
        super().__init__("Recommended", config.preferences_icon, config, parent)
        self._rec_data_ready.connect(self._on_rec_data_ready)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "recommended"

    def create_header(self):
        header = self._build_clickable_header()
        hl = header.layout()

        self.title_label = QLabel(f"{self.config.preferences_icon} <b>Recommended</b>")
        hl.addWidget(self.title_label)
        hl.addStretch()

        refresh_btn = QPushButton(self.config.refresh_icon)
        refresh_btn.setFixedSize(22, 20)
        refresh_btn.setToolTip("Refresh recommendations")
        refresh_btn.clicked.connect(self.refresh)
        hl.addWidget(refresh_btn)

        self.main_layout.addWidget(header)

    def create_content(self):
        self._list = QListWidget()
        # Rows fit the sidebar width and elide — never scroll sideways (which would
        # push the right-aligned chips off-screen behind the vertical scrollbar).
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        # Middle-click plays the user-configured action (same seam as the channel
        # list) via the shared QListWidget helper — no per-section handler copy.
        from metatv.gui.list_middle_click import install_list_middle_click
        self._list_mc = install_list_middle_click(self._list)
        self._list_mc.middleClicked.connect(self.channelMiddleClicked)
        _theme.apply_list_selection(self._list)
        self.content_layout.addWidget(self._list)
        self.set_empty(True)

    def refresh(self):
        self._list.clear()
        # Show a loading row so the section never displays its stale empty/"rate to
        # get recommendations" state during the load window. _on_rec_data_ready clears
        # the list first, which replaces this placeholder. (RecommendedSection is the
        # documented BackgroundRefreshMixin exception, so it sets this up itself.)
        self.show_loading(self._list, "Loading recommendations…")
        self._executor.submit(self._bg_refresh)

    def _bg_refresh(self) -> None:
        from metatv.core.preference_engine import (
            compute_weights, score_candidates, record_impressions, version_score,
        )
        from metatv.core.filter_utils import get_active_category_filter
        from metatv.core.database import MetadataDB
        from metatv.core.repositories import RepositoryFactory
        excluded_prefixes, include_uncategorized = get_active_category_filter(self.config)
        _config = self.config
        session = self.db.get_session()
        try:
            weights = compute_weights(session)
            if weights.is_empty():
                self._rec_data_ready.emit(None)
                return
            recs = score_candidates(
                session, weights, limit=20,
                muted_attrs=getattr(self.config, 'muted_attributes', None),
                dedupe_overrides=set(getattr(self.config, 'rec_dedupe_overrides', [])),
                excluded_prefixes=excluded_prefixes,
                include_uncategorized=include_uncategorized,
                excluded_provider_ids=RepositoryFactory(session).providers.get_hidden_provider_ids() or None,
                version_scorer=lambda ch: version_score(ch, _config),
            )
            if recs:
                record_impressions(session, [sc.channel_id for sc in recs])

            # Batch-fetch years from metadata so we can display them without
            # embedding years in channel names.
            year_by_id: dict[str, str] = {}
            if recs:
                ids = [sc.channel_id for sc in recs]
                for row in (
                    session.query(MetadataDB.id, MetadataDB.year, MetadataDB.release_date)
                    .filter(MetadataDB.id.in_(ids))
                    .all()
                ):
                    if row.year:
                        year_by_id[row.id] = str(row.year)
                    elif row.release_date and len(row.release_date) >= 4:
                        year_by_id[row.id] = row.release_date[:4]
        except Exception:
            logger.exception("RecommendedSection bg refresh error")
            # Emit an error sentinel (mirrors the no-weights path, which emits None)
            # so _on_rec_data_ready replaces the loading row with a visible error
            # instead of hanging on "Loading recommendations…" forever.
            self._rec_data_ready.emit(_REC_LOAD_ERROR)
            return
        finally:
            session.close()
        self._rec_data_ready.emit((recs, year_by_id))

    def _on_rec_data_ready(self, data) -> None:
        self._list.clear()
        # A transient background failure must be visible, not look like an empty
        # result — render a distinct error row (keeps the section expanded).
        if data is _REC_LOAD_ERROR:
            self.show_load_error(self._list, "Couldn't load recommendations")
            return
        # data is (recs, year_by_id) tuple from _bg_refresh, or None for "no weights"
        if data is None:
            item = QListWidgetItem("Rate movies/series to get recommendations")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self.set_empty(True)
            return
        recs, year_by_id = data if isinstance(data, tuple) else (data, {})
        if not recs:
            item = QListWidgetItem("No recommendations yet — rate more content")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self.set_empty(True)
            return
        for sc in recs:
            year = year_by_id.get(sc.channel_id, "")
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, sc.channel_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, sc.reason)
            item.setData(Qt.ItemDataRole.UserRole + 2, sc.variant_count)
            rating_tip = f"  {self.config.rating_star_icon}{sc.metadata_rating:.1f}/10" if sc.metadata_rating else ""
            shown_tip = f"\nShown {sc.rec_shown_count}×" if sc.rec_shown_count else ""
            variant_tip = f"\n{sc.variant_count} versions grouped" if sc.variant_count > 1 else ""
            item.setToolTip(
                f"{sc.reason}{rating_tip}{shown_tip}{variant_tip}\n"
                f"Genres: {', '.join(sc.matching_genres) or '—'}"
            )
            row = self._build_rec_row(sc, year)
            # Width 0 → the item spans the viewport width (no sideways scroll); the
            # row's own height governs the row height.
            item.setSizeHint(QSize(0, row.sizeHint().height()))
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
        self.set_empty(False)

    def _build_rec_row(self, sc, year: str) -> QWidget:
        """Recommendation row: ``[icon] Title [4K] … [Year] [Lang]``.

        Mirrors the mouse-transparent ``setItemWidget`` pattern of ``_VodAlertRow``.
        Layout, left→right: an icon, then the middle-eliding title sized to its content
        (Preferred policy, no stretch, buffered ``sizeHint`` — see ``_MiddleElideLabel``
        — so a title that fits is never clipped), then the quality badge (``QUALITY_CHIP``)
        hugging the title TEXT when present, then a stretch, then the right-aligned
        cluster: the year as a subtle bordered chip (``YEAR_CHIP``) and the audio-language
        chip (``LANG_CHIP``) as the CONSISTENT rightmost element on every row, so the
        right edge stays aligned. Only a title too long for the row elides (…), with the
        4K chip after the elided title. Language is ``detected_prefix`` — the honest
        language, NOT the source ``detected_region`` that used to leak into the title. So
        the title reads as a title, and facets read as chips.
        """
        media_icon = (
            self.config.movie_icon if sc.media_type == "movie"
            else self.config.series_icon
        )
        liked = f"{self.config.like_icon} " if sc.already_liked else ""
        title = sc.detected_title or sc.channel_name
        yr = sc.detected_year or year

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 1, 8, 1)
        layout.setSpacing(4)

        icon_lbl = QLabel(f"{liked}{media_icon}")
        layout.addWidget(icon_lbl)

        title_lbl = _MiddleElideLabel(title)
        title_lbl.setStyleSheet(_theme.VOD_ALERT_NAME)  # COLOR_TEXT — legible title
        # Preferred + no stretch: the title sizes to its content so the 4K chip can hug
        # the title TEXT. _MiddleElideLabel's buffered sizeHint keeps a title that fits
        # from being clipped; only a title too long for the row elides.
        title_lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(title_lbl)

        # Quality (4K) chip hugs the title TEXT — reuse the existing QUALITY_CHIP badge
        # (QPushButton-scoped, so a flat non-focusable QPushButton renders it as a chip).
        if sc.detected_quality:
            quality_chip = QPushButton(sc.detected_quality)
            quality_chip.setFlat(True)
            quality_chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            quality_chip.setStyleSheet(_theme.QUALITY_CHIP)
            layout.addWidget(quality_chip)

        layout.addStretch(1)  # pushes the year + language chips to the far right

        # Right-aligned cluster: the year as a subtle bordered chip (``YEAR_CHIP``) then
        # the language chip as the CONSISTENT far-right element on every row.
        if yr:
            year_lbl = QLabel(str(yr))
            year_lbl.setStyleSheet(_theme.YEAR_CHIP)  # subtle bordered chip
            layout.addWidget(year_lbl)

        # Language chip (QLabel — LANG_CHIP is label-friendly).
        if sc.detected_prefix:
            lang_chip = QLabel(sc.detected_prefix)
            lang_chip.setStyleSheet(_theme.LANG_CHIP)
            lang_chip.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(lang_chip)

        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # The item (not this widget) owns click/double-click/context-menu — let mouse
        # events pass through to the QListWidget viewport (same as _VodAlertRow).
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        return row

    def _on_double_click(self, item: QListWidgetItem) -> None:
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if channel_id:
            self.itemDoubleClicked.emit(channel_id)

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current:
            channel_id = current.data(Qt.ItemDataRole.UserRole)
            reason = current.data(Qt.ItemDataRole.UserRole + 1) or ""
            if channel_id:
                self.itemSelected.emit(channel_id, reason)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        channel_id = item.data(Qt.ItemDataRole.UserRole)
        if not channel_id:
            return
        variant_count = item.data(Qt.ItemDataRole.UserRole + 2) or 1
        gp = self._list.viewport().mapToGlobal(pos)
        if variant_count > 1:
            from PyQt6.QtCore import QPoint
            from PyQt6.QtWidgets import QMenu
            menu = QMenu(self)
            sep_action = menu.addAction(f"≠  Show {variant_count} versions separately")
            menu.addSeparator()
            more_action = menu.addAction("More options...")
            chosen = menu.exec(QPoint(gp.x(), gp.y()))
            if chosen == sep_action:
                self._on_show_separately(channel_id)
            elif chosen == more_action:
                self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())
        else:
            self.channelContextMenuRequested.emit(channel_id, gp.x(), gp.y())

    def _on_show_separately(self, channel_id: str) -> None:
        overrides: list = list(getattr(self.config, 'rec_dedupe_overrides', []))
        if channel_id not in overrides:
            overrides.append(channel_id)
            self.config.rec_dedupe_overrides = overrides
            self.config.save()
        self.refresh()
