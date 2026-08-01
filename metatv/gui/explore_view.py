"""Explore views — ONE cascading-columns component, four sidebar entry points.

This is the reuse the trail-map was built data-source-agnostic for: the SAME
:class:`~metatv.gui.trail_map_view.TrailMapView` widget (in ``embedded`` mode)
mounted as a content view and seeded from a sidebar section's contents instead of a
lightbox nav-stack.  Column 0 *is* the rail, made walkable; expanding any row
cascades outward through the shared adjacency plumbing.

Four entry points, no forks — each is an :class:`ExploreSource` (title + icon + a
seed loader pair) applied to the same :class:`ExploreView` class:

===============  ======================  ==========================================
Sidebar section  Column 0 seed           Scoping
===============  ======================  ==========================================
History          recently played          record view — NOT provider-scoped
Favorites        favorited titles         record view — NOT provider-scoped
Watch Queue      queued titles, in order  record view — NOT provider-scoped
Recommended      the preference engine    forward-looking — hidden providers gated
===============  ======================  ==========================================

Record/engaged views are exempt from active-source scoping (DR-0007), so a favorite
or a queued title on a since-inactive source still appears; Recommended is
forward-looking, so its seed loader carries the ``excluded_provider_ids`` gate.  The
drilled columns are ALWAYS forward-looking discovery and always go through the scoped
``get_similar_channels`` chokepoint, whichever entry point opened the view.

Lifecycle (view-lifecycle rule): :meth:`ExploreView.on_activate` loads the ordered
seed ids off the UI thread through the host ``_run_query`` seam, then seeds the
trail-map; :meth:`~ExploreView.on_deactivate` releases it (and drops any in-flight
result); :meth:`~ExploreView.shutdown` stops the inner executor (registered in the
host's cleanup registry).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.trail_map_data import (
    EXPLORE_SEED_LIMIT,
    load_engaged_seed_rows,
    load_favorite_ids,
    load_history_ids,
    load_history_seed_rows,
    load_queue_ids,
    load_recommended_ids,
    load_seed_rows,
)
from metatv.gui.trail_map_view import TrailMapView

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.image_cache import ImageCache
    from metatv.core.metadata_manager import MetadataManager


@dataclass(frozen=True)
class ExploreSource:
    """What makes one Explore entry point different from the other three.

    Everything else — the widget, the drill plumbing, the lifecycle, the row/detail
    renderers — is shared.  Adding a fifth entry point is a new ``ExploreSource``
    here plus an ``_add_explore_link`` call in its sidebar section; never a new view.

    Attributes:
        key: Registry key, also the sidebar ``section_id`` (``history``,
            ``favorites``, ``queue``, ``recommended``).
        title: Header + stats-line label ("Watch History", "Favorites", …).
        icon: Header glyph, from ``icons.py``.
        view_mode: The host's ``view_mode`` while this view is active.  History keeps
            the original ``"history"`` value; the rest are ``explore_<key>``.
        ids_loader: ``(repos, config) -> list[str]`` — the ordered column-0 ids.
            Runs in the ``_run_query`` worker, returns plain strings.
        seed_loader: ``(session, ids) -> list[TrailRowDTO]`` — hydration for column 0,
            handed to the trail-map (it runs on the trail-map's own worker).
        loading_text / empty_text / error_text: The three transient status states.
        link_tooltip: Tooltip for the sidebar section's "Explore →" header link.
    """

    key: str
    title: str
    icon: str
    view_mode: str
    ids_loader: Callable[[Any, Any], list[str]]
    seed_loader: Callable
    loading_text: str
    empty_text: str
    error_text: str
    link_tooltip: str


def _adult_mode(config) -> str:
    return getattr(config, "filter_adult_mode", "all")


def _history_ids(repos, config) -> list[str]:
    return load_history_ids(
        repos.session, limit=EXPLORE_SEED_LIMIT, adult_mode=_adult_mode(config)
    )


def _favorite_ids(repos, config) -> list[str]:
    return load_favorite_ids(
        repos.session, limit=EXPLORE_SEED_LIMIT, adult_mode=_adult_mode(config)
    )


def _queue_ids(repos, _config) -> list[str]:
    return load_queue_ids(repos.session, limit=EXPLORE_SEED_LIMIT)


def _recommended_ids(repos, config) -> list[str]:
    return load_recommended_ids(repos.session, config)


EXPLORE_SOURCES: dict[str, ExploreSource] = {
    "history": ExploreSource(
        key="history",
        title="Watch History",
        icon=_icons.history_icon,
        view_mode="history",
        ids_loader=_history_ids,
        seed_loader=load_history_seed_rows,
        loading_text="Loading your watch history…",
        empty_text="No watch history yet.\nPlay something and it will show up here.",
        error_text="Couldn't load your watch history.",
        link_tooltip="Explore your full Watch History (cascading columns)",
    ),
    "favorites": ExploreSource(
        key="favorites",
        title="Favorites",
        icon=_icons.favorite_icon,
        view_mode="explore_favorites",
        ids_loader=_favorite_ids,
        seed_loader=load_engaged_seed_rows,
        loading_text="Loading your favorites…",
        empty_text=(
            "No favorites yet.\nRight-click any title and add it to favorites."
        ),
        error_text="Couldn't load your favorites.",
        link_tooltip="Explore your Favorites (cascading columns)",
    ),
    "queue": ExploreSource(
        key="queue",
        title="Watch Queue",
        icon=_icons.queue_icon,
        view_mode="explore_queue",
        ids_loader=_queue_ids,
        seed_loader=load_engaged_seed_rows,
        loading_text="Loading your watch queue…",
        empty_text="Your watch queue is empty.\nRight-click any title to queue it.",
        error_text="Couldn't load your watch queue.",
        link_tooltip="Explore your Watch Queue (cascading columns)",
    ),
    "recommended": ExploreSource(
        key="recommended",
        title="Recommended",
        icon=_icons.preferences_icon,
        view_mode="explore_recommended",
        ids_loader=_recommended_ids,
        # Recommendations are forward-looking, so the engaged extras ("watched N×")
        # would always be empty — the plain seed rows are the honest shape.
        seed_loader=load_seed_rows,
        loading_text="Loading your recommendations…",
        empty_text=(
            "No recommendations yet.\nRate a few movies or series to seed your taste."
        ),
        error_text="Couldn't load your recommendations.",
        link_tooltip="Explore your Recommendations (cascading columns)",
    ),
}

# Every ``view_mode`` an Explore view can put the host into — the single source of
# truth for "are the flanking panels currently auto-collapsed for Explore?", read by
# MainWindow.save_splitter_sizes' clobber guard.
EXPLORE_VIEW_MODES: frozenset[str] = frozenset(
    s.view_mode for s in EXPLORE_SOURCES.values()
)


class ExploreView(QWidget):
    """Content-stack view: one sidebar section's contents as an explorable trail-map."""

    def __init__(
        self,
        parent: QWidget | None,
        config: "Config",
        image_cache: "ImageCache",
        db: "Database",
        metadata_manager: "MetadataManager",
        run_query: Callable,
        *,
        source: ExploreSource,
    ) -> None:
        """Args:
            run_query: The host's ``_run_query`` async-read seam.
            source: Which sidebar section seeds column 0 (see :data:`EXPLORE_SOURCES`).
        """
        super().__init__(parent)
        self._config = config
        self._db = db
        self._run_query = run_query
        self._source = source
        self._token: list[int] = [0]  # stale-result guard (shared with _run_query)

        self.setObjectName("exploreView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_theme.EXPLORE_VIEW_BG)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Transient loading / empty / error message (shown while the trail-map is
        # hidden — only ever one of the two is visible).
        self._status = QLabel("", self)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(_theme.EXPLORE_STATUS)
        lay.addWidget(self._status, 1)

        self.trail_map = TrailMapView(
            self, config, image_cache, db, metadata_manager,
            seed_loader=source.seed_loader, embedded=True,
        )
        lay.addWidget(self.trail_map, 1)
        self.trail_map.hide()

    # ------------------------------------------------------------------ #
    # Introspection                                                        #
    # ------------------------------------------------------------------ #
    @property
    def source(self) -> ExploreSource:
        """The :class:`ExploreSource` this instance is bound to."""
        return self._source

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #
    def on_activate(self) -> None:
        """Load the ordered seed ids off-thread, then seed the trail-map."""
        self._show_status(f"{_icons.loading_icon}  {self._source.loading_text}")
        config = self._config
        loader = self._source.ids_loader
        self._run_query(
            lambda repos: loader(repos, config),
            self._on_seed_ids,
            token_ref=self._token,
            on_error=self._on_seed_error,
        )

    def on_deactivate(self) -> None:
        """Release the trail-map so it stops rendering / consuming image loads.

        Bumps the load token so a late seed-id result from this activation is
        dropped instead of re-seeding a now-hidden view.
        """
        self._token[0] += 1
        self.trail_map.hide()

    def shutdown(self) -> None:
        """Stop the inner trail-map's executor (host cleanup registry)."""
        self.trail_map.shutdown()

    # ------------------------------------------------------------------ #
    # Result slots (main thread)                                           #
    # ------------------------------------------------------------------ #
    def _on_seed_ids(self, ids: object) -> None:
        ids = list(ids) if ids else []
        if not ids:
            self._show_status(self._source.empty_text)
            return
        self._status.hide()
        self.trail_map.show()
        self.trail_map.open(
            ids, origin_title=self._source.title, origin_icon=self._source.icon
        )

    def _on_seed_error(self, exc: Exception) -> None:
        self._show_status(
            f"{_icons.notification_warning_icon}  {self._source.error_text}"
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    def _show_status(self, text: str) -> None:
        self.trail_map.hide()
        self._status.setText(text)
        self._status.show()
