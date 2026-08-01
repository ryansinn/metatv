"""The Explore trail-map — a reusable cascading-columns adjacency browser.

Opened from the Similar-Titles lightbox (its "🧭 Explore" button).  Column 0 is the
**trail** the user walked (the lightbox nav-stack); expanding any stop shows *its*
similar titles in the next column, and clicking a similar cascades another column to
the right (Miller-column drill-down).  A bottom **detail strip** tracks the selected
title.  Titles already on the active path never reappear (no loops).

Architecture (mirrors ``similar_lightbox.py``):
- ``TrailMapView`` is a full-window overlay child of the main window, raised above
  everything.  It owns the backdrop, the columns, the detail strip, a single-worker
  executor, the per-parent similars cache and the ImageCache wiring.  It is a *thin
  orchestrator*: user intents are relayed up as signals with the channel id attached,
  to the SAME host handlers the lightbox/details pane already use.
- All DB reads run off the UI thread through ``trail_map_data`` and marshal back via
  private signals (never a worker-thread QTimer); QPixmaps are built only on the main
  thread.  Per-parent similars are cached so re-expanding is instant and never fires
  N queries on the UI thread.

Data-source-agnostic: :meth:`open` takes a *seed id list*; the seed and similars
loaders are injectable (default = the lightbox trail via ``trail_map_data``), so a
later Watch-History view seeds the SAME component with history instead.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Callable, TYPE_CHECKING

from loguru import logger
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.cursor_affordance import set_clickable
from metatv.gui.sentiment_bar import SentimentBar
from metatv.gui.sim_badges import make_sim_badges
from metatv.gui.trail_map_data import (
    TrailRowDTO, load_seed_rows, load_similar_rows, metadata_to_detail,
)
from metatv.gui.trail_map_detail import TrailDetailStrip

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.image_cache import ImageCache
    from metatv.core.metadata_manager import MetadataManager

_THUMB_W, _THUMB_H = 34, 51
_TRAIL_COL_W, _DRILL_COL_W = 292, 262
_SIMILAR_LIMIT = 18


class _ClickableThumb(QLabel):
    """A row's poster thumbnail — a *peek* target, not a select/drill target.

    A press emits :attr:`clicked` and is **consumed** (``event.accept()``, no
    ``super()`` call) so it never propagates to the parent :class:`_TrailRow`'s
    ``mousePressEvent`` — clicking the poster enlarges it, exactly like the
    details pane, while clicking the row body still selects/drills.
    """

    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()
        # Consume the press: an accepted event is not re-delivered to the parent
        # row, so the poster peek never doubles as a select/drill.
        event.accept()


class _ElidedTitleLabel(QLabel):
    """A row-title label that word-wraps to at most ``max_lines`` lines, then elides.

    A plain single-line ``QLabel`` overflows the fixed-width column; a plain
    word-wrapping one runs a long title to 3+ lines.  This keeps the full title (as
    its tooltip) and, at the label's current (layout-driven) width, lays it out as up
    to ``max_lines`` lines with the overflow ellipsized (``…``), so a title never
    exceeds the column and always signals truncation.  Recomputed on every resize.
    """

    def __init__(self, text: str, *, max_lines: int = 2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = (text or "").strip()
        self._max_lines = max_lines
        self.setWordWrap(True)
        self.setToolTip(self._full)
        super().setText(self._full)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        w = self.width()
        if w <= 0 or not self._full:
            return
        fm = self.fontMetrics()
        elide = Qt.TextElideMode.ElideRight
        words = self._full.split()
        lines: list[str] = []
        cur = ""
        idx = 0
        # Greedily fill up to max_lines; the first word on a line always goes on
        # (a lone over-wide word is elided at the end).
        while idx < len(words) and len(lines) < self._max_lines:
            word = words[idx]
            trial = f"{cur} {word}".strip()
            if not cur or fm.horizontalAdvance(trial) <= w:
                cur = trial
                idx += 1
            else:
                lines.append(cur)
                cur = ""
        if cur and len(lines) < self._max_lines:
            lines.append(cur)
            cur = ""
        # Words left unplaced (title exceeds max_lines) → elide the last line to
        # absorb the remainder with an ellipsis.
        if idx < len(words):
            rest = " ".join(words[idx:])
            base = lines[-1] if lines else ""
            merged = f"{base} {rest}".strip()
            if lines:
                lines[-1] = fm.elidedText(merged, elide, w)
            else:
                lines.append(fm.elidedText(merged, elide, w))
        # Elide any single line that itself overflows (one very long word).
        lines = [ln if fm.horizontalAdvance(ln) <= w else fm.elidedText(ln, elide, w)
                 for ln in lines]
        new_text = "\n".join(lines) if lines else self._full
        if new_text != self.text():
            super().setText(new_text)


class _TrailRow(QWidget):
    """One row in a column: thumb + title/year + badges + hover action bar.

    A dumb view — it emits :attr:`clicked` (the whole row is the expand/select
    target), :attr:`poster_clicked` (the poster thumbnail alone — enlarge/peek,
    never select) and relays its 👍👎🙅📋 bar with the row id.  The action bar
    reveals on hover (guarded against hiding when the pointer moves onto its own
    buttons).
    """

    clicked             = pyqtSignal(str)
    poster_clicked      = pyqtSignal(str)   # row id — enlarge the poster (not select)
    rating_clicked      = pyqtSignal(str, int)
    suppression_toggled = pyqtSignal(str, bool)
    queue_clicked       = pyqtSignal(str)

    def __init__(
        self, row: TrailRowDTO, *, trail_num: int | None = None,
        is_here: bool = False, selected: bool = False,
    ) -> None:
        super().__init__()
        self._id = row.id
        self.setObjectName("trailmap_row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        set_clickable(self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(8)

        if trail_num is not None:
            num = QLabel(str(trail_num))
            num.setStyleSheet(_theme.TRAILMAP_TRAIL_NUM)
            num.setFixedWidth(14)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(num)

        self.thumb = _ClickableThumb(row.title[:1] if row.title else "")
        self.thumb.setObjectName("trailmap_thumb")
        self.thumb.setFixedSize(_THUMB_W, _THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(_theme.TRAILMAP_THUMB)
        self.thumb.setToolTip("Enlarge poster")
        set_clickable(self.thumb)
        self.thumb.clicked.connect(lambda: self.poster_clicked.emit(self._id))
        lay.addWidget(self.thumb)

        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(1)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        name = _ElidedTitleLabel(row.title or "Unknown")
        name.setStyleSheet(_theme.TRAILMAP_ROW_TITLE)
        # Title fills the row's text column (stretch=1) and wraps/elides to ≤2 lines
        # so a long title never overflows the fixed-width column.  Title + year (+
        # "here") all AlignBottom → they share ONE baseline (the title's last line),
        # so the year reads on the title's baseline whether it wraps or not.
        title_row.addWidget(name, 1, Qt.AlignmentFlag.AlignBottom)
        if row.year:
            yr = QLabel(str(row.year))
            yr.setStyleSheet(_theme.TRAILMAP_ROW_YEAR)
            title_row.addWidget(yr, 0, Qt.AlignmentFlag.AlignBottom)
        if is_here:
            here = QLabel("here")
            here.setStyleSheet(_theme.TRAILMAP_HERE_TAG)
            title_row.addWidget(here, 0, Qt.AlignmentFlag.AlignBottom)
        # No trailing stretch — the title's stretch fills, pinning year/"here" to the
        # right edge on the shared baseline.
        main.addLayout(title_row)
        # The year is shown on the title line above, so suppress the shared badge
        # renderer's own year (right side of its meta line) — otherwise a trail row
        # shows the year twice. (Lightbox strip cards keep the badge year: they have
        # no separate title-line year.)
        main.addWidget(make_sim_badges(row.as_badge_item(), show_year=False))
        lay.addLayout(main, 1)

        chev = QLabel(_icons.trail_expand_icon)
        chev.setStyleSheet(_theme.TRAILMAP_ROW_CHEVRON)
        lay.addWidget(chev, 0, Qt.AlignmentFlag.AlignVCenter)

        # Hover action bar — hidden until the row (or a button in it) is hovered.
        self._actions = SentimentBar(btn_size=24)
        self._actions.set_state(
            user_rating=row.user_rating, is_suppressed=row.is_suppressed, in_queue=row.in_queue,
        )
        self._actions.rating_clicked.connect(lambda r: self.rating_clicked.emit(self._id, r))
        self._actions.suppression_toggled.connect(
            lambda on: self.suppression_toggled.emit(self._id, on)
        )
        self._actions.queue_clicked.connect(lambda: self.queue_clicked.emit(self._id))
        self._actions.hide()
        lay.addWidget(self._actions, 0, Qt.AlignmentFlag.AlignVCenter)

        self._selected = selected   # exposed for path-aware highlight assertions
        self.setStyleSheet(
            _theme.TRAILMAP_ROW_SELECTED if selected else _theme.TRAILMAP_ROW
        )

    # A press anywhere on the row that a child button did not consume selects/expands.
    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit(self._id)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._actions.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Keep the bar visible while the pointer is over one of its own buttons
        # (those are inside the row rect, so a bare Leave must not hide it).
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._actions.hide()
        super().leaveEvent(event)


class _TrailColumn(QFrame):
    """A single column: header (kicker + name) · scrollable rows · hint footer."""

    def __init__(self, kicker: str, name: str, *, is_trail: bool) -> None:
        super().__init__()
        self.setObjectName("trailmap_col")
        self.setStyleSheet(
            _theme.TRAILMAP_TRAIL_COLUMN if is_trail else _theme.TRAILMAP_COLUMN
        )
        self.setFixedWidth(_TRAIL_COL_W if is_trail else _DRILL_COL_W)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        head = QWidget()
        head.setStyleSheet(_theme.TRAILMAP_COLHEAD)
        hv = QVBoxLayout(head)
        hv.setContentsMargins(12, 9, 12, 8)
        hv.setSpacing(1)
        k = QLabel(kicker)
        k.setStyleSheet(_theme.TRAILMAP_COLHEAD_KICKER)
        hv.addWidget(k)
        n = QLabel(name)
        n.setStyleSheet(_theme.TRAILMAP_COLHEAD_NAME)
        n.setWordWrap(False)
        hv.addWidget(n)
        col.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(_theme.BG_TRANSPARENT)
        body_w = QWidget()
        body_w.setStyleSheet(_theme.BG_TRANSPARENT)
        self._body = QVBoxLayout(body_w)
        self._body.setContentsMargins(6, 6, 6, 6)
        self._body.setSpacing(2)
        self._body.addStretch()
        scroll.setWidget(body_w)
        col.addWidget(scroll, 1)

        self._hint = QLabel("")
        self._hint.setStyleSheet(_theme.TRAILMAP_COLHINT)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setContentsMargins(0, 6, 0, 6)
        col.addWidget(self._hint)

    def add_row(self, row: QWidget) -> None:
        self._body.insertWidget(self._body.count() - 1, row)  # before the trailing stretch

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)


class TrailMapView(QWidget):
    """Cascading-columns adjacency browser + detail strip.

    Two mounting modes share this one widget (no fork):

    - **Overlay** (default) — a full-window scrim + centred shell raised above the
      main window; opened from the lightbox's Explore button, dismissed on Esc / an
      outside click.  ``_close`` hides it.
    - **Embedded** (``embedded=True``) — a first-class content-stack view that fills
      its host (no scrim, no outside-click dismissal); this is the Full Watch-History
      view (seed = history).  ``_close`` emits :attr:`close_requested` so the host
      returns to Browse instead of leaving a blank pane.
    """

    # Relayed user intents (host attaches nothing — the id is already included).
    play_requested        = pyqtSignal(str)
    resume_requested      = pyqtSignal(str)
    queue_toggled         = pyqtSignal(str)
    favorite_toggled      = pyqtSignal(str)
    rating_requested      = pyqtSignal(str, int)
    suppression_requested = pyqtSignal(str, bool)
    watched_toggled       = pyqtSignal(str, bool)
    open_details_requested = pyqtSignal(str)
    recipe_requested      = pyqtSignal(str)
    poster_expand_requested = pyqtSignal(QPixmap)
    close_requested       = pyqtSignal()   # embedded mode: host returns to Browse

    # Worker → main-thread marshalling (never a QTimer from the worker).
    _seed_ready     = pyqtSignal(object)       # list[TrailRowDTO]
    _similars_ready = pyqtSignal(str, object)  # parent_id, list[TrailRowDTO]
    _detail_ready   = pyqtSignal(str, object)  # channel_id, detail dict

    def __init__(
        self,
        parent: QWidget,
        config: "Config",
        image_cache: "ImageCache",
        db: "Database",
        metadata_manager: "MetadataManager",
        *,
        seed_loader: Callable | None = None,
        similars_loader: Callable | None = None,
        embedded: bool = False,
    ) -> None:
        """Args:
            seed_loader: ``(session, ids) -> list[TrailRowDTO]`` for column 0.  The
                Full Watch-History view swaps this for a history-backed loader.
            similars_loader: ``(session, parent_id, *, excluded_provider_ids, config,
                limit) -> list[TrailRowDTO]`` for the drilled columns.
            embedded: When True, mount as a fill-the-host content view (no scrim, no
                outside-click / Esc dismissal); ``_close`` emits ``close_requested``.
        """
        super().__init__(parent)
        self._config = config
        self._image_cache = image_cache
        self._db = db
        self._metadata_manager = metadata_manager
        self._seed_loader = seed_loader or load_seed_rows
        self._similars_loader = similars_loader or load_similar_rows
        self._embedded = embedded
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trailmap")

        # State
        self._seed_ids: list[str] = []
        self._seed_rows: list[TrailRowDTO] = []
        self._drill: list[str] = []
        self._selected_id: str | None = None
        self._origin_title = ""
        # Caches
        self._row_cache: dict[str, TrailRowDTO] = {}
        self._similars_cache: dict[str, list[TrailRowDTO]] = {}
        self._detail_cache: dict[str, dict] = {}
        # Poster image routing (main thread only)
        self._poster_targets: dict[str, list[tuple[QLabel, QSize]]] = {}
        self._detail_poster_url: str | None = None
        self._detail_full_pix: QPixmap | None = None
        # A column-row poster click awaiting its (not-yet-cached) full image, so it
        # can pop the enlarged-poster overlay once the async load lands.
        self._pending_expand_url: str | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_ui()

        self._seed_ready.connect(self._on_seed_ready)
        self._similars_ready.connect(self._on_similars_ready)
        self._detail_ready.connect(self._on_detail_ready)
        self._image_cache.image_loaded.connect(self._on_image_loaded)
        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #
    def open(
        self, seed_ids: list[str], origin_title: str = "", origin_icon: str = ""
    ) -> None:
        """Open (or refresh) the trail-map seeded with *seed_ids* (the walked trail).

        Args:
            seed_ids: Column-0 channel ids, in display order.
            origin_title: Embedded mode only — the header label ("Watch History",
                "Favorites", …).  Empty keeps the default "Explore" header.
            origin_icon: Embedded mode only — the glyph shown beside *origin_title*
                (from ``icons.py``).  Defaults to the history glyph, the original
                embedded caller.
        """
        seed_ids = [s for s in (seed_ids or []) if s]
        if not seed_ids:
            return
        self._seed_ids = seed_ids
        self._origin_title = origin_title
        if self._embedded and origin_title:
            # Embedded Explore view: relabel the header per entry point (it is not
            # the generic "Explore" overlay here).
            icon = origin_icon or _icons.history_icon
            self._header_title.setText(f"{icon}  {origin_title}")
        self._seed_rows = []
        self._drill = []
        self._selected_id = None
        self._row_cache.clear()
        self._similars_cache.clear()
        self._detail_cache.clear()
        self._poster_targets.clear()
        self._detail_poster_url = None
        self._detail_full_pix = None
        self._pending_expand_url = None

        self.resize(self.parent().size())
        self._apply_shell_size()
        self.show()
        self.raise_()
        self.setFocus()
        self._subtitle.setText("Loading your trail…")
        self._render_columns()
        self._submit(self._bg_load_seed, list(seed_ids))

    def shutdown(self) -> None:
        """Stop the background executor (registered in the host's cleanup registry)."""
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._shell = QFrame()
        self._shell.setObjectName("trailmap_shell")
        self._shell.setStyleSheet(_theme.TRAILMAP_SHELL)
        self._shell.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        shell = QVBoxLayout(self._shell)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self._build_header(shell)

        cols_scroll = QScrollArea()
        cols_scroll.setWidgetResizable(True)
        cols_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cols_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cols_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        cols_scroll.setStyleSheet(_theme.BG_TRANSPARENT)
        self._cols_scroll = cols_scroll
        self._cols_w = QWidget()
        self._cols_w.setStyleSheet(_theme.BG_TRANSPARENT)
        self._cols_layout = QHBoxLayout(self._cols_w)
        self._cols_layout.setContentsMargins(0, 0, 0, 0)
        self._cols_layout.setSpacing(0)
        self._cols_layout.addStretch()
        cols_scroll.setWidget(self._cols_w)
        shell.addWidget(cols_scroll, 1)

        self._detail = TrailDetailStrip()
        self._wire_detail()
        shell.addWidget(self._detail, 0)

        outer.addWidget(self._shell)

    def _build_header(self, shell: QVBoxLayout) -> None:
        bar = QWidget()
        bar.setStyleSheet(_theme.TRAILMAP_HEADER_BAR)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 12, 10)
        row.setSpacing(10)

        title = QLabel(f"{_icons.explore_icon}  Explore")
        title.setStyleSheet(_theme.TRAILMAP_TITLE)
        self._header_title = title  # embedded mode relabels this per origin_title
        row.addWidget(title)
        self._subtitle = QLabel("")
        self._subtitle.setStyleSheet(_theme.TRAILMAP_SUBTITLE)
        row.addWidget(self._subtitle)
        row.addStretch()

        self._collapse_btn = QPushButton("Collapse branches")
        self._collapse_btn.setFlat(True)
        self._collapse_btn.setStyleSheet(_theme.TRAILMAP_LINK_BTN)
        self._collapse_btn.setToolTip("Collapse every drilled column back to the trail")
        self._collapse_btn.clicked.connect(self._collapse_branches)
        row.addWidget(self._collapse_btn)

        close_btn = QPushButton(_icons.close_icon)
        close_btn.setFlat(True)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(_theme.TRAILMAP_CLOSE_BTN)
        close_btn.setToolTip("Close Explore (Esc)")
        close_btn.clicked.connect(self._close)
        row.addWidget(close_btn)
        shell.addWidget(bar)

    def _wire_detail(self) -> None:
        d = self._detail
        d.play_requested.connect(lambda: self._emit_for_selected(self.play_requested))
        d.resume_requested.connect(lambda: self._emit_for_selected(self.resume_requested))
        d.rating_clicked.connect(lambda r: self._on_rating(self._selected_id, r))
        d.suppression_toggled.connect(lambda on: self._on_suppression(self._selected_id, on))
        d.queue_clicked.connect(lambda: self._on_queue(self._selected_id))
        d.favorite_clicked.connect(lambda: self._on_favorite(self._selected_id))
        d.watched_toggled.connect(lambda on: self._on_watched(self._selected_id, on))
        d.open_details_clicked.connect(
            lambda: self._emit_for_selected(self.open_details_requested, close=True)
        )
        d.recipe_clicked.connect(lambda: self._emit_for_selected(self.recipe_requested))
        d.poster_expand_clicked.connect(self._on_poster_expand)

    # ------------------------------------------------------------------ #
    # Background reads                                                     #
    # ------------------------------------------------------------------ #
    def _submit(self, fn, *args) -> None:
        self._executor.submit(fn, *args)

    def _bg_load_seed(self, ids: list[str]) -> None:
        try:
            with self._db.session_scope(commit=False) as session:
                rows = self._seed_loader(session, ids)
            self._seed_ready.emit(rows)
        except Exception:
            logger.exception("TrailMap seed load failed")
            self._seed_ready.emit([])

    def _bg_load_similars(self, parent_id: str) -> None:
        try:
            from metatv.core.repositories import RepositoryFactory
            with self._db.session_scope(commit=False) as session:
                excluded = set(RepositoryFactory(session).providers.get_hidden_provider_ids())
                rows = self._similars_loader(
                    session, parent_id, excluded_provider_ids=excluded,
                    config=self._config, limit=_SIMILAR_LIMIT,
                )
            self._similars_ready.emit(parent_id, rows)
        except Exception:
            logger.exception("TrailMap similars load failed for %s", parent_id)
            self._similars_ready.emit(parent_id, [])

    def _bg_load_detail(self, channel_id: str) -> None:
        detail: dict = {}
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                meta = loop.run_until_complete(
                    self._metadata_manager.get_metadata(channel_id)
                )
            finally:
                loop.close()
            detail = metadata_to_detail(meta)
        except Exception:
            logger.exception("TrailMap detail metadata fetch failed for %s", channel_id)
        self._detail_ready.emit(channel_id, detail)

    # ------------------------------------------------------------------ #
    # Worker results (main thread)                                        #
    # ------------------------------------------------------------------ #
    def _on_seed_ready(self, rows: object) -> None:
        if not self.isVisible():
            return
        rows = list(rows) if isinstance(rows, list) else []
        self._seed_rows = rows
        for r in rows:
            self._row_cache[r.id] = r
        # A single-item trail has exactly one possible next action, so the extra
        # click to drill it is pure friction: auto-drill it (fetch its similars +
        # select its detail) so the user lands on a populated adjacency view.  A
        # multi-item trail is deliberately left detail-only — auto-fetching every
        # stop of a long trail (e.g. the large Full-History seed) would fire N
        # similars queries no one asked for.
        if len(rows) == 1:
            self._select_seed_row(rows[0].id)
            return
        # Auto-select the current stop (the last walked) for the detail strip — no
        # auto-expand (that would fire a similars fetch before the user asks).
        if rows:
            self._selected_id = rows[-1].id
        self._render_columns()
        if self._selected_id:
            self._select_detail(self._selected_id)

    def _on_similars_ready(self, parent_id: str, rows: object) -> None:
        rows = list(rows) if isinstance(rows, list) else []
        self._similars_cache[parent_id] = rows
        for r in rows:
            self._row_cache.setdefault(r.id, r)
        if self.isVisible():
            self._render_columns()

    def _on_detail_ready(self, channel_id: str, detail: object) -> None:
        detail = detail if isinstance(detail, dict) else {}
        self._detail_cache[channel_id] = detail
        if self.isVisible() and channel_id == self._selected_id:
            self._detail.set_metadata(channel_id, detail)

    # ------------------------------------------------------------------ #
    # Selection + expansion                                               #
    # ------------------------------------------------------------------ #
    def _select_seed_row(self, channel_id: str) -> None:
        self._selected_id = channel_id
        self._drill = [channel_id]
        self._ensure_similars(channel_id)
        self._render_columns()
        self._select_detail(channel_id)

    def _select_drill_row(self, drill_index: int, channel_id: str) -> None:
        self._selected_id = channel_id
        self._drill = self._drill[: drill_index + 1] + [channel_id]
        self._ensure_similars(channel_id)
        self._render_columns()
        self._select_detail(channel_id)

    def _ensure_similars(self, parent_id: str) -> None:
        if parent_id not in self._similars_cache:
            self._submit(self._bg_load_similars, parent_id)

    def _select_detail(self, channel_id: str) -> None:
        row = self._row_cache.get(channel_id)
        if not row:
            return
        self._detail.populate(row)
        self._prepare_detail_poster(row.poster_url)
        cached = self._detail_cache.get(channel_id)
        if cached is not None:
            self._detail.set_metadata(channel_id, cached)
        else:
            self._submit(self._bg_load_detail, channel_id)

    def _collapse_branches(self) -> None:
        self._drill = []
        if self._seed_rows:
            self._selected_id = self._seed_rows[-1].id
        self._render_columns()
        if self._selected_id:
            self._select_detail(self._selected_id)

    # ------------------------------------------------------------------ #
    # Rendering                                                           #
    # ------------------------------------------------------------------ #
    def _render_columns(self) -> None:
        # Row thumbs are recreated here, so their pending-image targets are stale.
        self._poster_targets.clear()
        while self._cols_layout.count() > 1:  # keep the trailing stretch
            item = self._cols_layout.takeAt(0)
            if w := item.widget():
                # setParent(None) removes it from the visible hierarchy NOW; deleteLater
                # alone leaves the old column painted over the new one until the event
                # loop runs (stale-widget ghosting).
                w.setParent(None)
                w.deleteLater()

        # Path-aware highlighting (a breadcrumb, NOT a leaf-id match): each column
        # highlights the item on the PATH toward the next column, so the drilled
        # chain (root → … → leaf) is lit one-per-column and the leaf is highlighted
        # exactly once — never in every column where it happens to be a similar.
        #   • Trail column → the explored root ``_drill[0]`` while drilling, else the
        #     selected stop (``_selected_id``, == the current stop when not drilling).
        #   • Drill column ``i`` (SIMILAR TO ``_drill[i]``) → its drilled child
        #     ``_drill[i+1]``; the frontier column (``i+1 == len(_drill)``) has no
        #     selected child (``None`` → nothing highlighted).

        # -- trail column (column 0) --
        trail_col = _TrailColumn("YOUR TRAIL", "", is_trail=True)
        if not self._seed_rows:
            trail_col.set_hint("Loading…")
        else:
            trail_highlight = self._drill[0] if self._drill else self._selected_id
            n = len(self._seed_rows)
            for i, r in enumerate(self._seed_rows):
                row_w = self._make_row(
                    r, trail_num=i + 1, is_here=(i == n - 1),
                    on_click=self._select_seed_row, highlight_id=trail_highlight,
                )
                trail_col.add_row(row_w)
            trail_col.set_hint("expand any stop →")
        self._cols_layout.insertWidget(self._cols_layout.count() - 1, trail_col)

        # -- drill columns --
        for i, parent_id in enumerate(self._drill):
            parent = self._row_cache.get(parent_id)
            col = _TrailColumn("SIMILAR TO", parent.title if parent else "…", is_trail=False)
            col_highlight = self._drill[i + 1] if i + 1 < len(self._drill) else None
            raw = self._similars_cache.get(parent_id)
            if raw is None:
                col.set_hint("Finding similar titles…")
            else:
                shown = self._filter_path(raw, upto_index=i)
                for r in shown:
                    col.add_row(self._make_row(
                        r, on_click=lambda cid, idx=i: self._select_drill_row(idx, cid),
                        highlight_id=col_highlight,
                    ))
                col.set_hint(f"{len(shown)} similar" if shown else "no new similar titles")
            self._cols_layout.insertWidget(self._cols_layout.count() - 1, col)

        self._update_subtitle()
        QTimer.singleShot(0, self._scroll_columns_end)

    def _make_row(
        self, row: TrailRowDTO, *, on_click: Callable, trail_num: int | None = None,
        is_here: bool = False, highlight_id: str | None = None,
    ) -> _TrailRow:
        # Path-aware: highlight only when this row is the caller-supplied breadcrumb
        # item for its column (never a bare ``row.id == self._selected_id`` leaf
        # match, which lights a leaf up in every column it appears in).
        w = _TrailRow(
            row, trail_num=trail_num, is_here=is_here,
            selected=(row.id == highlight_id),
        )
        w.clicked.connect(on_click)
        w.poster_clicked.connect(self._on_row_poster_clicked)
        w.rating_clicked.connect(self._on_rating)
        w.suppression_toggled.connect(self._on_suppression)
        w.queue_clicked.connect(self._on_queue)
        if row.poster_url:
            self._request_poster(row.poster_url, w.thumb, QSize(_THUMB_W, _THUMB_H))
        return w

    def _filter_path(self, rows: list[TrailRowDTO], *, upto_index: int) -> list[TrailRowDTO]:
        """Drop any candidate already on the active path (id or content identity)."""
        path_ids = set(self._seed_ids) | set(self._drill[: upto_index + 1])
        path_keys = {
            self._row_cache[i].dedup_key for i in path_ids if i in self._row_cache
        }
        path_keys |= {r.dedup_key for r in self._seed_rows}
        out: list[TrailRowDTO] = []
        for r in rows:
            if r.id in path_ids or r.dedup_key in path_keys:
                continue
            out.append(r)
        return out

    def _update_subtitle(self) -> None:
        if self._drill:
            root = self._row_cache.get(self._drill[0])
            root_name = root.title if root else self._drill[0]
            self._subtitle.setText(f"exploring from “{root_name}” · {len(self._drill)} deep")
        else:
            self._subtitle.setText("pick any stop to expand its similar titles")

    def _scroll_columns_end(self) -> None:
        bar = self._cols_scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------ #
    # Action relays (attach the selected/row id + optimistic cache)       #
    # ------------------------------------------------------------------ #
    def _emit_for_selected(self, signal, *, close: bool = False) -> None:
        if self._selected_id:
            signal.emit(self._selected_id)
            if close:
                self._close()

    def _on_rating(self, channel_id: str | None, rating: int) -> None:
        if not channel_id:
            return
        self.rating_requested.emit(channel_id, rating)
        row = self._row_cache.get(channel_id)
        if row:
            new = 0 if row.user_rating == rating else rating
            self._apply_row_change(channel_id, user_rating=new, is_suppressed=False)

    def _on_suppression(self, channel_id: str | None, on: bool) -> None:
        if not channel_id:
            return
        self.suppression_requested.emit(channel_id, on)
        self._apply_row_change(
            channel_id, is_suppressed=on, **({"user_rating": 0} if on else {})
        )

    def _on_queue(self, channel_id: str | None) -> None:
        if not channel_id:
            return
        self.queue_toggled.emit(channel_id)
        row = self._row_cache.get(channel_id)
        if row:
            self._apply_row_change(channel_id, in_queue=not row.in_queue)

    def _on_favorite(self, channel_id: str | None) -> None:
        if not channel_id:
            return
        self.favorite_toggled.emit(channel_id)
        row = self._row_cache.get(channel_id)
        if row:
            self._apply_row_change(channel_id, is_favorite=not row.is_favorite)

    def _on_watched(self, channel_id: str | None, watched: bool) -> None:
        if not channel_id:
            return
        self.watched_toggled.emit(channel_id, watched)
        # Mark → completed (progress cleared, so Play-again not Resume); unmark → none.
        self._apply_row_change(
            channel_id, watch_completed=watched, watch_progress=0,
            watch_percent=(100 if watched else 0),
        )

    def _apply_row_change(self, channel_id: str, **changes) -> None:
        """Optimistically update the cached DTO so badges/detail stay consistent."""
        row = self._row_cache.get(channel_id)
        if not row:
            return
        self._row_cache[channel_id] = replace(row, **changes)
        if channel_id == self._selected_id:
            # Re-sync the detail strip (re-apply any cached metadata after populate).
            self._detail.populate(self._row_cache[channel_id])
            self._prepare_detail_poster(self._row_cache[channel_id].poster_url)
            cached = self._detail_cache.get(channel_id)
            if cached is not None:
                self._detail.set_metadata(channel_id, cached)

    def _on_poster_expand(self) -> None:
        if self._detail_full_pix and not self._detail_full_pix.isNull():
            self.poster_expand_requested.emit(self._detail_full_pix)

    def _on_row_poster_clicked(self, channel_id: str) -> None:
        """A column-row poster click enlarges that row's poster (peek) — never drills.

        Mirrors the details-pane poster-click affordance: resolve the row's full
        poster (sync cache first, else load-then-show once the async image lands)
        and emit :attr:`poster_expand_requested`.  The thumbnail consumed the press,
        so the row's normal select/drill is untouched.  A row with no poster is a
        graceful no-op.
        """
        row = self._row_cache.get(channel_id)
        url = row.poster_url if row else None
        if not url:
            return
        pix = self._image_cache.get_image_sync(url)
        if pix and not pix.isNull():
            self.poster_expand_requested.emit(pix)
        else:
            # Not cached yet — remember it and enlarge once image_loaded delivers it.
            self._pending_expand_url = url
            self._image_cache.get_image_async(url)

    # ------------------------------------------------------------------ #
    # Poster images (main thread only)                                    #
    # ------------------------------------------------------------------ #
    def _request_poster(self, url: str, label: QLabel, size: QSize) -> None:
        pix = self._image_cache.get_image_sync(url)
        if pix:
            self._set_thumb(label, pix, size)
        else:
            self._poster_targets.setdefault(url, []).append((label, size))
            self._image_cache.get_image_async(url)

    def _prepare_detail_poster(self, url: str | None) -> None:
        self._detail_poster_url = url or None
        self._detail_full_pix = None
        if not url:
            return
        pix = self._image_cache.get_image_sync(url)
        if pix:
            self._detail_full_pix = pix
            self._detail.set_poster_pixmap(pix)
        else:
            self._image_cache.get_image_async(url)

    def _on_image_loaded(self, url: str, pix: QPixmap) -> None:
        if not self.isVisible():
            return
        # A row-poster peek awaiting this image → pop the enlarged-poster overlay.
        if url == self._pending_expand_url and pix and not pix.isNull():
            self._pending_expand_url = None
            self.poster_expand_requested.emit(pix)
        if url == self._detail_poster_url and pix and not pix.isNull():
            self._detail_full_pix = pix
            self._detail.set_poster_pixmap(pix)
        for label, size in self._poster_targets.get(url, []):
            self._set_thumb(label, pix, size)

    @staticmethod
    def _set_thumb(label: QLabel, pix: QPixmap, size: QSize) -> None:
        label.setPixmap(pix.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))
        label.setText("")

    # ------------------------------------------------------------------ #
    # Dismiss + sizing                                                    #
    # ------------------------------------------------------------------ #
    def _close(self) -> None:
        # Embedded (Full History) view: don't self-hide into a blank pane — ask the
        # host to return to Browse.  Overlay: dismiss by hiding.
        if self._embedded:
            self.close_requested.emit()
        else:
            self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Outside-the-shell dismissal is an overlay affordance only; embedded fills
        # its host, so a press anywhere is just a normal press.
        if not self._embedded and not self._shell.geometry().contains(event.pos()):
            self._close()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape and not self._embedded:
            self._close()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._embedded:
            # No scrim — the opaque shell fills the whole view.
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 190))
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._apply_shell_size()

    def _apply_shell_size(self) -> None:
        if self._embedded:
            # Fill the host content area (no centred 0.9× card, no scrim margins).
            self._shell.setFixedSize(self.width(), self.height())
            return
        w = max(720, int(self.width() * 0.9))
        h = max(520, int(self.height() * 0.86))
        self._shell.setFixedSize(min(w, self.width()), min(h, self.height()))
