"""RecommendedSection — sidebar VOD recommendations from the preference engine."""

from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import (
    QPushButton, QSizePolicy, QListWidget, QListWidgetItem, QWidget,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from loguru import logger

from metatv.gui import theme as _theme
from metatv.gui.chip_row import (
    CHIP_LANG, CHIP_QUALITY, CHIP_YEAR, MiddleElideLabel as _MiddleElideLabel,
    build_chip_row, media_icon_role, quality_word, sidebar_meta_line,
)
from metatv.gui.sidebar.base import SectionAction, CollapsibleSection, make_seamless

# Re-exported for callers/tests that import the title label from this module; the
# canonical definition now lives in ``metatv.gui.chip_row`` (shared by every
# sidebar content list).
__all__ = ["RecommendedSection", "_MiddleElideLabel"]

# Sentinel emitted by _bg_refresh when the background load raises, so
# _on_rec_data_ready can render a visible error row instead of leaving the
# section stuck on the "Loading recommendations…" placeholder forever.
_REC_LOAD_ERROR = object()


class RecommendedSection(CollapsibleSection):
    """Sidebar section showing top VOD recommendations from the preference engine."""
    def budgeted_list(self):
        """The rows this section fits to its height (see
        ``CollapsibleSection.apply_row_budget``)."""
        return self.__dict__.get("_list")

    def item_count(self) -> int | None:
        """Rows currently rendered — inventory, shown only when
        :meth:`news` is quiet.

        Read off the list itself rather than tracked separately, so the
        header cannot claim a number the rows disagree with. The
        ``+N more`` tail is excluded: it is chrome, not content.
        """
        lst = self.__dict__.get("_list")
        if lst is None:
            return None
        from metatv.gui.sidebar.base import _MORE_ROLE, _MORE_ROW
        from PyQt6.QtCore import Qt

        return sum(
            1 for i in range(lst.count())
            if lst.item(i).data(_MORE_ROLE) != _MORE_ROW
        )


    MIN_ROWS: int = 3

    EXPLORE_KEY = "recommended"

    itemSelected              = pyqtSignal(str, str)  # channel_id, reason
    itemDoubleClicked         = pyqtSignal(str)        # channel_id
    channelMiddleClicked      = pyqtSignal(str)        # channel_id — configured middle-click play
    channelContextMenuRequested = pyqtSignal(str, int, int)  # channel_id, gx, gy
    _rec_data_ready           = pyqtSignal(object)     # list[ScoredCandidate] | None

    def __init__(self, config, db, parent=None):
        self.db = db
        self._executor = ThreadPoolExecutor(max_workers=1)
        super().__init__("Recommended", config.preferences_icon, config, parent,
                         vector_role="recommended")
        self._rec_data_ready.connect(self._on_rec_data_ready)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def get_section_id(self):
        return "recommended"

    # No create_header override. It existed only to append a refresh button,
    # and carrying a divergent copy of the title / stretch / status / explore
    # wiring for one control is exactly what _add_header_actions exists to
    # avoid. Refresh now lives in the ⋯ overflow with every other section's
    # occasional action, so the base header serves this section unchanged.

    def overflow_actions(self):
        return [
            SectionAction(
                f"{self.config.refresh_icon} Refresh recommendations",
                "Recompute recommendations from your ratings and history",
                self.refresh, icon="refresh",
            ),
        ]

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
        make_seamless(self._list)
        self.content_layout.addWidget(self._list)
        self.set_empty(True)

    def refresh(self):
        # Capture the scroll offset BEFORE the clear that zeroes it. This section
        # is the documented BackgroundRefreshMixin exception, so it repeats the
        # mixin's three beats itself — over the shared ScrollPreservingMixin
        # helpers, not a private copy of them. Without this, every refresh bounced
        # the list to the top, including the one "show N versions separately"
        # fires: you acted on row 18 and were returned to row 1.
        self._capture_scroll(self._list)
        self._list.clear()
        # Show a loading row so the section never displays its stale empty/"rate to
        # get recommendations" state during the load window. _on_rec_data_ready clears
        # the list first, which replaces this placeholder.
        self.show_loading(self._list, "Loading recommendations…")
        self._executor.submit(self._bg_refresh)

    def _bg_refresh(self) -> None:
        from metatv.core.preference_engine import (
            RecScoringSettings, compute_weights, score_candidates, record_impressions,
            version_score,
        )
        from metatv.core.filter_utils import get_active_category_filter, keyword_exclusion_list
        from metatv.core.database import MetadataDB
        from metatv.core.repositories import RepositoryFactory
        excluded_prefixes, include_uncategorized = get_active_category_filter(self.config)
        _config = self.config
        # Same steering the Recommendations dashboard uses — one config, one engine.
        settings = RecScoringSettings.from_config(_config)
        session = self.db.get_session()
        try:
            weights = compute_weights(session, settings=settings)
            if weights.is_empty():
                self._rec_data_ready.emit(None)
                return
            recs = score_candidates(
                session, weights, limit=20,
                muted_attrs=getattr(self.config, 'muted_attributes', None),
                dedupe_overrides=set(getattr(self.config, 'rec_dedupe_overrides', [])),
                excluded_prefixes=excluded_prefixes,
                include_uncategorized=include_uncategorized,
                excluded_keywords=keyword_exclusion_list(self.config) or None,
                excluded_provider_ids=RepositoryFactory(session).providers.get_hidden_provider_ids() or None,
                version_scorer=lambda ch: version_score(ch, _config),
                diversify_people=True,
                settings=settings,
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
        # Every branch below that renders a one-line placeholder instead of rows
        # drops the captured offset: scrolling a single-row list to where a
        # 20-row list used to be would put the message off-screen.
        if data is _REC_LOAD_ERROR:
            self.show_load_error(self._list, "Couldn't load recommendations")
            self._drop_captured_scroll()
            return
        # data is (recs, year_by_id) tuple from _bg_refresh, or None for "no weights"
        if data is None:
            item = QListWidgetItem("Rate movies/series to get recommendations")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self.set_empty(True)
            self._drop_captured_scroll()
            return
        recs, year_by_id = data if isinstance(data, tuple) else (data, {})
        if not recs:
            item = QListWidgetItem("No recommendations yet — rate more content")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(item)
            self.set_empty(True)
            self._drop_captured_scroll()
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
        self._restore_scroll(self._list)
        # This section is the BackgroundRefreshMixin exception, so it does not
        # get the shared post-populate hook and has to fit its own rows.
        QTimer.singleShot(0, self.reapply_row_budget)

    def _removal_list(self) -> QListWidget:
        """This section is the BackgroundRefreshMixin exception, so it has no
        ``_refresh_list`` for the in-place mixin to default to."""
        return self._list

    def _after_rows_removed(self, list_widget) -> None:
        """"Not interested" takes exactly one recommendation off the rail; the
        remaining scores are unchanged, so nothing else needs rebuilding."""
        if list_widget.count() == 0:
            self.set_empty(True)

    def _build_rec_row(self, sc, year: str) -> QWidget:
        """Recommendation row: the title over ``"Movie · 1985 · EN · 4K"``.

        Thin wrapper over the shared :func:`~metatv.gui.chip_row.build_chip_row`
        (the one canonical row shared by every sidebar content list); this method
        only resolves the ScoredCandidate → chip-row arguments. Language is
        ``detected_prefix`` — the honest language, NOT the source ``detected_region``
        that used to leak into the title.
        """
        quality = quality_word(sc.detected_quality)
        release = sc.detected_year or year
        return build_chip_row(
            title=sc.detected_title or sc.channel_name,
            icon_role=media_icon_role(sc.media_type),
            liked=bool(sc.already_liked),
            chips=(
                (CHIP_QUALITY, quality),
                (CHIP_YEAR, release),
                (CHIP_LANG, sc.detected_prefix or ""),
            ),
            meta=sidebar_meta_line(release, sc.detected_prefix or "", quality),
            density=self._row_density(),
        )

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
