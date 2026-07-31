"""The Full Watch-History view — the Explore trail-map mounted as a content view.

This is the reuse the trail-map was built data-source-agnostic for: the SAME
:class:`~metatv.gui.trail_map_view.TrailMapView` widget (in ``embedded`` mode)
seeded with your **watch history** instead of a lightbox nav-stack.

- Column 0 is your recently-watched titles, most-recent first.  History is a
  RECORD view, so it is **not** provider-scoped — a title you watched on a source
  that later went inactive still appears (DR-0007 record-view exemption); the seed
  loader (``load_history_seed_rows``) carries that exemption.
- Expanding any stop drills into its *similar* titles via the SAME provider-scoped
  ``get_similar_channels`` chokepoint the lightbox uses (forward-looking discovery
  keeps its ``excluded_provider_ids`` gate — the trail-map's own similars loader).

Lifecycle (view-lifecycle rule): :meth:`on_activate` loads the ordered history ids
off the UI thread through the host ``_run_query`` seam, then seeds the trail-map;
:meth:`on_deactivate` releases it (and drops any in-flight result); :meth:`shutdown`
stops the inner executor (registered in the host's cleanup registry).
"""
from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.trail_map_data import (
    HISTORY_SEED_LIMIT, load_history_ids, load_history_seed_rows,
)
from metatv.gui.trail_map_view import TrailMapView

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.image_cache import ImageCache
    from metatv.core.metadata_manager import MetadataManager


class FullHistoryView(QWidget):
    """Content-stack view: your entire watch history as an explorable trail-map."""

    def __init__(
        self,
        parent: QWidget,
        config: "Config",
        image_cache: "ImageCache",
        db: "Database",
        metadata_manager: "MetadataManager",
        run_query: Callable,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._db = db
        self._run_query = run_query
        self._token: list[int] = [0]  # stale-result guard (shared with _run_query)

        self.setObjectName("fullHistoryView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_theme.FULL_HISTORY_VIEW_BG)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Transient loading / empty / error message (shown while the trail-map is
        # hidden — only ever one of the two is visible).
        self._status = QLabel("", self)
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(_theme.FULL_HISTORY_STATUS)
        lay.addWidget(self._status, 1)

        self.trail_map = TrailMapView(
            self, config, image_cache, db, metadata_manager,
            seed_loader=load_history_seed_rows, embedded=True,
        )
        lay.addWidget(self.trail_map, 1)
        self.trail_map.hide()

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #
    def on_activate(self) -> None:
        """Load the ordered history ids off-thread, then seed the trail-map."""
        self._show_status(f"{_icons.loading_icon}  Loading your watch history…")
        adult_mode = getattr(self._config, "filter_adult_mode", "all")
        self._run_query(
            lambda repos: load_history_ids(
                repos.session, limit=HISTORY_SEED_LIMIT, adult_mode=adult_mode
            ),
            self._on_history_ids,
            token_ref=self._token,
            on_error=self._on_history_error,
        )

    def on_deactivate(self) -> None:
        """Release the trail-map so it stops rendering / consuming image loads.

        Bumps the load token so a late history-id result from this activation is
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
    def _on_history_ids(self, ids: object) -> None:
        ids = list(ids) if ids else []
        if not ids:
            self._show_status(
                "No watch history yet.\nPlay something and it will show up here."
            )
            return
        self._status.hide()
        self.trail_map.show()
        self.trail_map.open(ids, origin_title="Watch History")

    def _on_history_error(self, exc: Exception) -> None:
        self._show_status(
            f"{_icons.notification_warning_icon}  Couldn't load your watch history."
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    def _show_status(self, text: str) -> None:
        self.trail_map.hide()
        self._status.setText(text)
        self._status.show()
