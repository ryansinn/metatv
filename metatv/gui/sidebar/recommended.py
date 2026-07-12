"""RecommendedSection — sidebar VOD recommendations from the preference engine."""

from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import QLabel, QPushButton, QSizePolicy, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal
from loguru import logger

from metatv.gui import theme as _theme
from metatv.gui.sidebar.base import CollapsibleSection, _fmt_channel_name

# Sentinel emitted by _bg_refresh when the background load raises, so
# _on_rec_data_ready can render a visible error row instead of leaving the
# section stuck on the "Loading recommendations…" placeholder forever.
_REC_LOAD_ERROR = object()


class RecommendedSection(CollapsibleSection):
    """Sidebar section showing top VOD recommendations from the preference engine."""

    itemSelected              = pyqtSignal(str, str)  # channel_id, reason
    itemDoubleClicked         = pyqtSignal(str)        # channel_id
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
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
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
            media_icon = (
                self.config.movie_icon if sc.media_type == "movie"
                else self.config.series_icon
            )
            liked_prefix = f"{self.config.like_icon} " if sc.already_liked else ""
            year = year_by_id.get(sc.channel_id, "")
            item = QListWidgetItem(f"{liked_prefix}{media_icon} {_fmt_channel_name(sc.channel_name, year)}")
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
            self._list.addItem(item)
        self.set_empty(False)

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
