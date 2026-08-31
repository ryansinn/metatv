"""Sports view — the sport → league cascade over ``special_view = 'sports'``.

``sports_filter_bar.py`` has been 430 finished lines with zero importers, and
``ChannelRepository.get_sports_channels`` had zero callers. What was missing was
never the widget: the queries behind it showed every channel from every source,
including the 16,715 sports rows belonging to a provider the owner had switched
off. That is fixed in ``channel_stats._special_content_query``; this view is what
finally calls it.

Rows are built by ``chip_row.build_chip_row`` — the one row builder — rather
than a second renderer, so a change to row grammar reaches Sports the same day
it reaches History and Favorites.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.chip_row import (
    CHIP_QUALITY, CHIP_YEAR, build_chip_row, media_icon_role,
)
from metatv.gui.content_view import ContentView
from metatv.gui.sports_filter_bar import SportsFilterBar

#: Item data role carrying the channel id, so a click can resolve the row.
_ROLE_CHANNEL_ID = Qt.ItemDataRole.UserRole


class SportsView(ContentView):
    """Sport/league cascade over the classified sports channels.

    Signals mirror ``DiscoverView``'s names exactly, so the host wires this the
    same way it wires every other content view — the seam is the point, not the
    view.
    """

    channelSelected            = pyqtSignal(str)   # channel_id
    playRequested              = pyqtSignal(str)   # channel_id
    channelMiddleClicked       = pyqtSignal(str)   # channel_id
    # (channel_id, global x, global y) — the shape _on_rec_channel_context_menu
    # takes. It is three args, not a QPoint, and connecting the wrong shape
    # fails only when someone actually right-clicks.
    channelContextMenuRequested = pyqtSignal(str, int, int)

    def __init__(self, db, config, run_query: Callable, parent=None) -> None:
        """
        Args:
            db: Database instance (held for nothing but symmetry with siblings;
                every read goes through *run_query*).
            config: Live ``Config`` — the control layer resolves exclusions from
                it before the worker ever sees a scope (DR-0007).
            run_query: ``MainWindow._run_query``, the single async-read seam.
            parent: Qt parent.
        """
        super().__init__(config, parent)
        self._db = db
        self._run_query = run_query
        #: Stale-result token. A fast sport→league→sport click sequence issues
        #: three queries; only the newest may render.
        self._token: list[int] = [0]
        #: Set when the taxonomy query is SUBMITTED, not when it returns —
        #: two rapid activations would otherwise both see 'not loaded' and
        #: issue the same whole-corpus scan twice.
        self._taxonomy_requested = False
        self._setup_ui()

    # ------------------------------------------------------------------ #
    # Construction                                                        #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.filter_bar = SportsFilterBar(self)
        self.filter_bar.filter_changed.connect(self._reload_channels)
        layout.addWidget(self.filter_bar)

        self.count_label = QLabel("", self)
        # ITEM_COUNT is the existing role for a "{n} things" label — the
        # filter groups use it, so this reads the same as the rest.
        _theme.style(self.count_label, "ITEM_COUNT")
        layout.addWidget(self.count_label)

        self.channel_list = QListWidget(self)
        self.channel_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.channel_list.itemClicked.connect(self._on_item_clicked)
        self.channel_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.channel_list.customContextMenuRequested.connect(self._on_context_menu)
        # Middle-click-to-play is an app-wide affordance, and QListWidget has no
        # signal for it — the filter is how the other lists get it too.
        self.channel_list.viewport().installEventFilter(self)
        layout.addWidget(self.channel_list, 1)

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def on_activate(self) -> None:
        """Load the taxonomy once, then the channels for the current filter."""
        if not self._taxonomy_requested:
            self._taxonomy_requested = True
            self._load_taxonomy()
        self._reload_channels()

    def on_deactivate(self) -> None:
        """Drop any in-flight result.

        Symmetric with ``on_activate`` (CLAUDE.md: a view with one must have the
        other). Bumping the token is the cancel: the worker still finishes, but
        its result is discarded instead of painting over whatever view the user
        switched to.
        """
        self._token[0] += 1

    def get_view_name(self) -> str:
        return "sports"

    # ------------------------------------------------------------------ #
    # Loading                                                             #
    # ------------------------------------------------------------------ #

    def _load_taxonomy(self) -> None:
        """Fill the cascade dropdowns from the classified corpus."""
        config = self.config

        def query(repos) -> dict:
            scope = _visibility_scope(repos, config)
            return {
                "taxonomy": repos.channels.get_sports_taxonomy(scope),
                "counts": repos.channels.get_sports_counts(scope),
            }

        self._run_query(
            query,
            self._on_taxonomy_loaded,
            on_error=lambda exc: self._on_taxonomy_loaded(None),
        )

    def _on_taxonomy_loaded(self, data: Any) -> None:
        if not data:
            # Let the next activation retry rather than leaving the dropdowns
            # empty for the rest of the session.
            self._taxonomy_requested = False
            self._show_error("Couldn't load the sport list")
            return
        self.filter_bar.load_taxonomy(data["taxonomy"], data["counts"])

    def _reload_channels(self) -> None:
        """Re-query for the current cascade selection."""
        state = self.filter_bar.get_filter_state()
        config = self.config

        def query(repos) -> list:
            scope = _visibility_scope(repos, config)
            return repos.channels.get_sports_channels(
                scope,
                sport_types=state.get("sport_types") or None,
                league_names=state.get("league_names") or None,
            )

        self._run_query(
            query,
            self._on_channels_loaded,
            token_ref=self._token,
            on_error=lambda exc: self._show_error("Couldn't load these channels"),
        )

    def _on_channels_loaded(self, rows: Any) -> None:
        """Render the result, or a visible error — never a silent empty list."""
        if rows is None:
            self._show_error("Couldn't load these channels")
            return
        self.channel_list.clear()
        for dto in rows:
            self._add_row(dto)
        self.count_label.setText(
            f"{len(rows):,} channel{'' if len(rows) == 1 else 's'}")

    # ------------------------------------------------------------------ #
    # Rendering                                                           #
    # ------------------------------------------------------------------ #

    def _add_row(self, dto) -> None:
        """Append one channel as the shared chip row.

        The title is the TEAM when the classifier found one: "Calgary Flames"
        is what the owner is looking for, and the raw name is
        "NHL-TEAM| CALGARY FLAMES HD" — which repeats the league and the quality
        that are already chips beside it.

        Chips carry league, sport and quality. League and sport BOTH use
        ``CHIP_YEAR`` — the family's neutral outline chip — rather than one of
        them taking ``CHIP_LANG``: that role is documented in ``chip_roles`` as
        "the only chip in the family that is a CONTROL", accent-blue because
        blue already means interactive everywhere else. Neither of these is
        clickable, so neither may look it.

        Args:
            dto: A ``SportsChannelDTO``.
        """
        item = QListWidgetItem()
        item.setData(_ROLE_CHANNEL_ID, dto.id)
        # The chip row is mouse-transparent, so the tooltip must live on the
        # ITEM. It shows the provider's raw name, which the title deliberately
        # replaced.
        item.setToolTip(dto.name)

        row = build_chip_row(
            title=(dto.team_name or dto.detected_title or dto.name),
            icon_role=media_icon_role(dto.media_type),
            chips=(
                (CHIP_QUALITY, (dto.detected_quality or "").upper()),
                (CHIP_YEAR, dto.league_name or ""),
                (CHIP_YEAR, (dto.sport_type or "").title()),
            ),
        )
        # Width 0 → the item spans the viewport (no sideways scroll); the row's
        # own height governs the row height. Same as every other chip-row list.
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        self.channel_list.addItem(item)
        self.channel_list.setItemWidget(item, row)

    # ------------------------------------------------------------------ #
    # Interaction                                                         #
    # ------------------------------------------------------------------ #

    def _channel_id(self, item) -> str:
        return item.data(_ROLE_CHANNEL_ID) if item else ""

    def _on_item_clicked(self, item) -> None:
        if (cid := self._channel_id(item)):
            self.channelSelected.emit(cid)

    def _on_item_double_clicked(self, item) -> None:
        if (cid := self._channel_id(item)):
            self.playRequested.emit(cid)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt override)
        """Route a middle-click on a row to ``channelMiddleClicked``.

        Args:
            obj: The watched object (the list viewport).
            event: The Qt event.

        Returns:
            False always — the event is observed, never consumed, so normal
            selection and scrolling are untouched.
        """
        from PyQt6.QtCore import QEvent

        if (obj is self.channel_list.viewport()
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.MiddleButton):
            item = self.channel_list.itemAt(event.position().toPoint())
            if (cid := self._channel_id(item)):
                self.channelMiddleClicked.emit(cid)
        return super().eventFilter(obj, event)

    def _on_context_menu(self, pos) -> None:
        item = self.channel_list.itemAt(pos)
        if (cid := self._channel_id(item)):
            gpos = self.channel_list.viewport().mapToGlobal(pos)
            self.channelContextMenuRequested.emit(cid, gpos.x(), gpos.y())

    # ------------------------------------------------------------------ #
    # Failure                                                             #
    # ------------------------------------------------------------------ #

    def _show_error(self, message: str) -> None:
        """Render a visible, non-selectable error row.

        CLAUDE.md's async-read rule: a failed background load must never look
        like a silently-empty result — never ``clear(); return``.
        """
        logger.warning("SportsView: {}", message)
        self.channel_list.clear()
        item = QListWidgetItem(f"{_icons.notification_warning_icon} {message}")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.channel_list.addItem(item)
        self.count_label.setText("")


def _visibility_scope(repos, config):
    """Resolve every exclusion axis, in the worker, from already-read settings.

    The control layer decides WHAT is excluded and the scope only encodes HOW
    (DR-0007), which is why this reads ``config`` here rather than handing a
    ``Config`` to the repository.

    Args:
        repos: A ``RepositoryFactory`` bound to the worker's session.
        config: Live ``Config``.

    Returns:
        A fully-resolved ``VisibilityScope``.
    """
    from metatv.core.channel_visibility import VisibilityScope
    from metatv.core.filter_utils import global_exclusion_sets

    prefixes, categories, content_types, keywords = global_exclusion_sets(config)
    return VisibilityScope(
        excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
        excluded_prefixes=set(prefixes or []),
        excluded_categories=set(categories or []),
        excluded_content_types=set(content_types or []),
        excluded_keywords=set(keywords or []),
    )
