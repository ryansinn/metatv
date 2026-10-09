"""Content section widgets for the details pane: poster, metadata, plot, technical, cast."""
import html
import re

from loguru import logger

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap

from metatv.core.channel_name_utils import normalize_region_code
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.details_section_header import CollapsibleHeader, CollapsibleMixin
from metatv.gui.details_versions import _CHANNEL_PREFIX_RE, resolve_category_name
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.qt_size_utils import no_width_force as _no_width_force
from metatv.gui.qt_text_utils import escape_mnemonic
from metatv.metadata_providers.base import MetadataResult


def _is_stale_polluted_title(clean_title: str, metadata_title: str) -> bool:
    """True when ``metadata_title`` is a stale provider-fallback copy of an older,
    less-clean detected_title — the clean base plus a trailing ``(YYYY) CAST`` (e.g.
    clean=``From Dusk Till Dawn``, metadata=``From Dusk Till Dawn 4K (1996) HARVEY
    KEITEL, …``). In that one case the details pane keeps the clean detected_title
    instead of the polluted metadata.title. A genuine distinct provider/TMDb title
    never embeds a (19xx)/(20xx) after the clean base, so real titles are unaffected.
    This SELECTS an already-stored field — it never re-parses the name.
    """
    if not clean_title or metadata_title == clean_title:
        return False
    # Trailing pollution: the clean base plus "(YYYY) CAST…".
    if (metadata_title.startswith(clean_title)
            and re.search(r"\((?:19|20)\d{2}\)", metadata_title)):
        return True
    # Leading pollution: separator residue before the clean base ("|MULTI|. Title"
    # cached ". Title" into metadata.title before the v0.16-v0.18 re-parses fixed
    # detected_title; same punctuation-run-plus-whitespace class the ingestion
    # parser strips). A real alternate title never differs ONLY by leading
    # punctuation, so genuine provider/TMDb titles are unaffected.
    if re.sub(r"^[.\-:|,;]+\s+", "", metadata_title) == clean_title:
        return True
    return False


class _ClickableLabel(QLabel):
    """QLabel that copies its stored channel_id to clipboard on click."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.channel_id = None
        cursor_affordance.set_clickable(self)

    def mousePressEvent(self, event):
        if self.channel_id and event.button() == Qt.MouseButton.LeftButton:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.channel_id)
            self.clicked.emit()
        super().mousePressEvent(event)


class _PosterLabel(QLabel):
    """QLabel that emits ``poster_clicked`` when the user left-clicks a loaded poster.

    Also surfaces hover and resize events (``hover_changed`` / ``resized``) so an
    overlaid corner widget — the clickable Watched badge — can reveal itself on
    poster hover and keep itself pinned to the lower-right corner on layout changes.
    """

    poster_clicked = pyqtSignal()
    hover_changed = pyqtSignal(bool)   # True on enter, False on leave
    resized = pyqtSignal()             # geometry changed — reposition overlays

    def __init__(self, parent=None):
        super().__init__(parent)
        self._has_pixmap: bool = False
        self._apply_content_state()

    def setPixmap(self, pixmap: QPixmap) -> None:  # type: ignore[override]
        super().setPixmap(pixmap)
        self._has_pixmap = not (pixmap is None or pixmap.isNull())
        self._apply_content_state()

    def clear(self) -> None:
        super().clear()
        self._has_pixmap = False
        self._apply_content_state()

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(text)
        # Clearing the image via text also clears the pixmap state
        self._has_pixmap = False
        self._apply_content_state()

    def _apply_content_state(self) -> None:
        """Re-derive everything that depends on "is there an image here?".

        Both properties below are content-dependent, and both used to be set
        once at construction or per call site, which is how the alignment got
        stuck. Deriving them in one place means a caller cannot set a pixmap
        and forget the pair.
        """
        cursor_affordance.set_clickable(self, self._has_pixmap)
        # Poster ART is CENTRED in the space the rail leaves (the label is
        # already inset by _RAIL_W), so the art can never slide under the rail
        # and the icons read on plain card rather than over whatever the poster
        # happens to be bright with. This reverses the previous left-hug, which
        # existed to put the rail ON the art; the V3 render puts it beside.
        #
        # Placeholder text centres for the same reason, so both states now
        # agree and this branch is about intent rather than geometry.
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event) -> None:
        if self._has_pixmap and event.button() == Qt.MouseButton.LeftButton:
            self.poster_clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_changed.emit(False)
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()


class _WatchedBadge(QPushButton):
    """Small clickable corner badge overlaid on the poster (Plex/Jellyfin convention).

    Two visual states (driven by ``_PosterSection``): a persistent SOLID check when
    watched (click → unmark) and a FAINT check revealed on poster hover when
    unwatched (click → mark watched).  Emits ``hover_changed`` so the parent can
    keep the faint badge visible while the cursor is over the badge itself (avoiding
    the parent-leave/child-enter flicker loop).
    """

    hover_changed = pyqtSignal(bool)

    def enterEvent(self, event) -> None:
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_changed.emit(False)
        super().leaveEvent(event)


def _pref_signal(name: str, weights, attr: str) -> str:
    """Return HTML indicator for a person based on their preference weight."""
    d = getattr(weights, attr, {})
    score = d.get(name, 0.0)
    if score > 0.3:
        return f'<span style="color:{_theme.COLOR_OK}">▲ </span>'
    if score < -0.3:
        return f'<span style="color:{_theme.COLOR_ERR}">▼ </span>'
    return ''


# ---------------------------------------------------------------------------
# _PosterSection
# ---------------------------------------------------------------------------

class _PosterSection(QWidget):
    """Poster image (VOD) and live-channel logo/header (logo + country info).

    Also hosts the two poster-adjacent action surfaces:
    * the **primary action row** (full-size Play / Resume) directly below the poster;
    * the clickable two-state **Watched badge** overlaid on the poster corner
      (VOD only) — ``watched_toggled`` carries the new state to the orchestrator.
    """

    # Emitted when the user clicks an enlarged poster (carries the full-res QPixmap)
    poster_enlarged = pyqtSignal(QPixmap)
    # Emitted when the user clicks the poster Watched badge (carries the NEW state)
    watched_toggled = pyqtSignal(bool)

    # Poster area metrics.  A live channel LOGO now occupies the SAME footprint as a
    # VOD poster (the tall _POSTER_MIN_H/_POSTER_MAX_H box) — scaled KeepAspectRatio
    # and centered on the poster-card background, so a logo no longer renders as a
    # tiny strip with a big void beneath it.  Small/low-res logos upscale only up to
    # _LOGO_UPSCALE_CEILING× their native size (then center) so they don't pixelate.
    _POSTER_GUTTER: int = 4   # right inset on the poster card — protects a hard right gutter
    _POSTER_MIN_H: int = 400
    _POSTER_MAX_H: int = 600
    # The poster area is a HARD FIXED height so the Play/Resume row below it never moves
    # between titles.  The poster is fit INSIDE this box (KeepAspectRatio) and LEFT-aligned
    # (see poster_label's alignment) so the slim action rail, which floats over the box's
    # left edge, always overlays the poster itself rather than the gray card margin.  Its
    # width can never exceed the card (a hard right boundary) and its height never exceeds
    # the box; a portrait 2:3 poster fits to the box height and leaves side padding on the
    # RIGHT — padding is acceptable, overflow is not.  0.75× the former fill-the-card height:
    # a deliberately shorter poster so the details pane isn't poster-dominated.
    _POSTER_FIXED_H: int = int(575 * 0.75)
    _LOGO_UPSCALE_CEILING: float = 2.5
    _BADGE_SIZE: int = 26
    _BADGE_MARGIN: int = 8

    # Rail spacing (structural px).  G = the Monitor↔Hide gap; the top pair
    # (Favorite↔Monitor) is G/2, so the whole rail group (Favorite · Monitor/Watchlist
    # · Hide) reads as one tight cluster bracketed by stretches.  The sentiment trio
    # no longer lives here — it graduated to the right end of the secondary
    # ("Watch Later") row below the poster, so the old Hide↔sentiment drop gap is
    # gone with it.
    _RAIL_GAP: int = 20
    _RAIL_W: int = 48   # slim icon rail in the left gutter; poster content is inset by this
    # Secondary row: [Watch Later …] ⟶ stretch ⟶ [👍][🙅][👎].  The sentiment chips
    # keep the rail's 48px footprint so they read as the same control set, just
    # relocated.  Watch Later absorbs all slack and yields it back first, so the row's
    # minimum is (3 × chip) + spacing — never the button's text width.
    _SECONDARY_ROW_SPACING: int = 6
    _SENTIMENT_BTN_W: int = _RAIL_W

    def __init__(self, config, image_cache, parent=None):
        super().__init__(parent)
        self.config = config
        self._image_cache = image_cache
        self._poster_url: str | None = None
        self._logo_url: str | None = None
        self._provider_urls: list = []
        self._full_pixmap: QPixmap | None = None   # full-res image for the lightbox
        self._is_live_logo: bool = False           # poster area is showing a live logo
        # The deferred re-fit is a timer OWNED by this widget: a bare
        # QTimer.singleShot(0, bound_method) outlives a section torn down in the
        # same event-loop turn and fires into the dead widget.
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.timeout.connect(self._refit_deferred)
        self._logo_src: QPixmap | None = None      # retained original logo for resize re-fit
        self._rescaling: bool = False              # guards the resize→rescale re-entrancy loop
        # Watched-badge state (VOD only)
        self._is_live: bool = False
        self._watched: bool = False
        self._poster_hovered: bool = False
        self._badge_hovered: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Poster area: a full-width gray card with the slim action rail FLOATING over its
        # LEFT edge.  Previously the rail was a side-by-side COLUMN that shrank the gray
        # card by its own 48px (so the card never reached the pane width); now the card
        # (poster_frame/poster_label) fills the full content width and the rail OVERLAYS
        # the card's left edge via a QGridLayout cell overlap — both occupy cell (0,0) and
        # the rail is left-aligned, so it no longer claims a column.  The poster (VOD) /
        # logo (live) is centred in the full-width card; the live header (live) shows in
        # row 1 beneath it.  Play/Resume + Watch Later are NOT in the rail — they graduate
        # to full-width rows in the OUTER column below this block (see end of _setup).
        self._content_col = QWidget()
        cc_layout = QGridLayout(self._content_col)
        cc_layout.setContentsMargins(0, 0, 0, 0)
        cc_layout.setSpacing(0)

        # Poster label (VOD) — the gray card.  Fills grid cell (0, 0) so its gray
        # background spans the full content width (no longer shrunk by a rail column).
        self._poster_frame = QWidget()
        pf_layout = QVBoxLayout(self._poster_frame)
        # Inset the poster content by the rail width so the poster image (and its gray
        # card) starts to the RIGHT of the action rail — the rail sits in the left gutter
        # BESIDE the poster, no longer overlaying the poster art.  _rescale_current_image
        # subtracts the same _RAIL_W from the label's max-width so the right gutter holds.
        pf_layout.setContentsMargins(self._RAIL_W, 0, 0, 0)

        self.poster_label = _PosterLabel()
        # Alignment is NOT set here — _PosterLabel derives it from whether it is
        # currently holding an image (left-aligned art so the floating action
        # rail overlays the poster, centred text for the empty-card message).
        # Setting it once here is what pinned "No poster available" to the left
        # border of an otherwise empty frame.
        self.poster_label.setFixedHeight(self._POSTER_FIXED_H)  # hard height — buttons never move
        # The poster must SUBORDINATE to the pane width, never drive it.  A QLabel
        # holding a pixmap reports minimumSizeHint().width() == pixmap width with a
        # Preferred policy; inside the width-resizable, h-scroll-off details
        # QScrollArea that floors the whole content column at the pixmap width, so
        # every section below was laid out wider than the viewport and the genre /
        # cast / version chips clipped off the right edge.  Ignoring the horizontal
        # hint lets the column shrink to the pane width; _rescale_current_image()
        # keeps the pixmap fitted to whatever width the layout grants.
        _poster_sp = self.poster_label.sizePolicy()
        _poster_sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.poster_label.setSizePolicy(_poster_sp)
        _theme.style_fn(self.poster_label, lambda: f"QLabel {{ background-color: {_theme.OVERLAY_BLACK_30}; border-radius: 8px;"
            f" color: {_theme.COLOR_TEXT_HI}; font-size: {_theme.FONT_SM}; }}")
        self.poster_label.setScaledContents(False)
        self.poster_label.setText("No poster available")
        self.poster_label.setToolTip(f"{_icons.zoom_poster_icon} Click to enlarge")
        self.poster_label.poster_clicked.connect(self._on_poster_clicked)
        self.poster_label.hover_changed.connect(self._on_poster_hover)
        self.poster_label.resized.connect(self._rescale_current_image)
        self.poster_label.resized.connect(self._reposition_watched_badge)
        pf_layout.addWidget(self.poster_label)

        # Watched badge — a clickable corner overlay on the poster (VOD only).
        # Child of poster_label so it floats over the image; positioned lower-right
        # and shown/hidden by _update_watched_badge() per watch + hover state.
        self._watched_badge = _WatchedBadge(_icons.watched_icon, self.poster_label)
        self._watched_badge.setFixedSize(self._BADGE_SIZE, self._BADGE_SIZE)
        self._watched_badge.clicked.connect(self._on_watched_badge_clicked)
        self._watched_badge.hover_changed.connect(self._on_badge_hover)
        self._watched_badge.hide()

        # Action rail — floats over the card's LEFT edge (same grid cell, left-aligned).
        # A subtle scrim keeps the icons legible over bright posters.  Top/bottom margins
        # are 0 and spacing is 0: set_action_buttons() brackets the button group with a
        # leading+trailing stretch and lays out every inter-button gap explicitly (see
        # _RAIL_GAP / _RAIL_TRIO_GAP / _RAIL_SENTIMENT_GAP).  The top group stays tight
        # while the large Hide↔sentiment gap drops the trio low — no implicit per-item
        # spacing to fight that geometry.  Visible for ALL channel types — per-button
        # visibility is _ActionBar's job.  Buttons are reparented in via
        # set_action_buttons() after both _PosterSection and _ActionBar exist.
        self._action_rail = QWidget()
        self._action_rail.setObjectName("posterActionRail")
        self._action_rail.setFixedWidth(self._RAIL_W)
        self._action_rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Dark-gray gutter panel (not pitch black) beside the poster; the individual
        # button fills (DETAIL_RAIL_BTN, ~40% light) read as frosted chips on top of it.
        _theme.style_fn(self._action_rail, lambda: f"#posterActionRail {{ background-color: {_theme.COLOR_BG_CARD};"
            f" border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}")
        self._action_rail_layout = QVBoxLayout(self._action_rail)
        # Symmetric margins so the fixed-size buttons center horizontally in the rail.
        self._action_rail_layout.setContentsMargins(0, 0, 0, 0)
        self._action_rail_layout.setSpacing(0)
        self._action_rail_layout.addStretch()   # placeholder until set_action_buttons()
        self._action_rail.hide()   # stays hidden until a channel is shown (set_mode)

        # Live header: country info text.  The channel LOGO (when present) is shown
        # in the poster card above (load_live_logo); the header carries the
        # category/country line beneath it (grid row 1).
        self._live_header = QWidget()
        live_layout = QHBoxLayout(self._live_header)
        live_layout.setContentsMargins(0, 4, 0, 4)
        live_layout.setSpacing(8)

        self._country_info_lbl = QLabel()
        _theme.style_fn(self._country_info_lbl, lambda: f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_DISABLED}; font-style: italic;")
        self._country_info_lbl.setWordWrap(True)
        _no_width_force(self._country_info_lbl)
        self._country_info_lbl.hide()
        live_layout.addWidget(self._country_info_lbl, 1)

        self._live_header.hide()

        # Assemble: the poster card fills cell (0,0); the rail OVERLAYS its left edge in
        # the SAME cell (left-aligned, so it doesn't claim a column); the live header sits
        # beneath it (row 1); a trailing stretch row keeps the block top-aligned.  The
        # rail is added AFTER the card so it paints on top of the poster's left edge.
        cc_layout.addWidget(self._poster_frame, 0, 0)
        cc_layout.addWidget(self._action_rail, 0, 0, Qt.AlignmentFlag.AlignLeft)
        cc_layout.addWidget(self._live_header, 1, 0)
        cc_layout.setRowStretch(2, 1)
        self._action_rail.raise_()   # keep the rail above the poster's left edge

        layout.addWidget(self._content_col)

        # Primary action row — full-size Play / Resume.  It lives in the OUTER column
        # (below the poster+rail block), NOT inside _content_col, so it spans the full
        # pane width and LEFT-ALIGNS with the title/metadata below — reclaiming the dead
        # space under the rail rather than indenting under the poster's left edge.  The
        # rail's last button is centered well above this row, so nothing sits to its
        # left to collide with.  Buttons are reparented in by set_action_buttons(); both
        # get equal stretch so they split 50/50 when both show, and Play takes the full
        # width when Resume is hidden (Qt skips the hidden item's stretch).  Hidden until
        # a channel is shown (set_mode).
        self._primary_action_row = QWidget()
        self._primary_row_layout = QHBoxLayout(self._primary_action_row)
        self._primary_row_layout.setContentsMargins(0, 6, 0, 0)
        self._primary_row_layout.setSpacing(6)
        self._primary_action_row.hide()
        layout.addWidget(self._primary_action_row)

        # Trailer row — its OWN full-width line between Play/Resume and Watch
        # Later.  Moved off the secondary row: pinned there it ate Watch Later's
        # slack down to a sliver at the owner's ~307px pane (reported 2026-09-03).
        # Zero margins/spacing so a hidden trailer button leaves zero height.
        self._trailer_action_row = QWidget()
        self._trailer_row_layout = QHBoxLayout(self._trailer_action_row)
        self._trailer_row_layout.setContentsMargins(0, 0, 0, 0)
        self._trailer_row_layout.setSpacing(0)
        self._trailer_action_row.hide()
        layout.addWidget(self._trailer_action_row)

        # Secondary action row — ONE line, split by position:
        #
        #     [ 📋 Watch Later ..................... ] [👍] [🙅] [👎]
        #
        # LEFT = the collection action, RIGHT = the judgment cluster — position
        # does the separating, so neither side needs a caption.  The trio used
        # to sit at the BOTTOM of the rail as unlabelled chips, present but
        # reported as MISSING; MOVED here (never duplicated), hiding for live
        # channels (_ActionBar.set_mode) and leaving Watch Later the whole row.
        self._secondary_action_row = QWidget()
        self._secondary_row_layout = QHBoxLayout(self._secondary_action_row)
        self._secondary_row_layout.setContentsMargins(0, 6, 0, 0)
        self._secondary_row_layout.setSpacing(self._SECONDARY_ROW_SPACING)
        self._secondary_action_row.hide()
        layout.addWidget(self._secondary_action_row)

    def set_mode(self, is_live: bool) -> None:
        # set_mode runs only when a channel is actually being shown (via
        # _configure_for), so this is where the rail first becomes visible — it
        # stays hidden in the empty/no-selection state so action icons don't appear
        # with nothing selected.  The rail is shown for ALL channel types; only the
        # content beside it switches (poster for VOD, live header for live).
        # Per-button visibility (sentiment/watchlist/alert) is managed by
        # _ActionBar.set_mode()/set_monitorable().
        self._action_rail.setVisible(True)
        self._live_header.setVisible(is_live)
        # Primary row (Play/Resume) + trailer row + secondary "Watch Later"
        # line show for ALL channel types.  The trailer row self-collapses to
        # zero height with no trailer; the secondary line's rating chips gate
        # themselves (VOD-only, _ActionBar.set_mode), leaving Watch Later the row.
        self._primary_action_row.setVisible(True)
        self._trailer_action_row.setVisible(True)
        self._secondary_action_row.setVisible(True)
        # Watched badge is a VOD-only affordance — track mode and refresh visibility.
        self._is_live = is_live
        if is_live:
            # Default live layout: poster area hidden, live header shown.  When the
            # channel has a logo, load_live_logo() reveals the poster area and shows
            # the logo in it (occupying the same footprint as a VOD poster).
            self._poster_frame.setVisible(False)
        else:
            self._is_live_logo = False
            self._poster_frame.setVisible(True)
        # The poster box is now the SAME tall footprint for both VOD posters and live
        # logos, so always restore the full metrics (no short live-logo box).
        self._restore_poster_metrics()
        self._update_watched_badge()

    def set_action_buttons(
        self,
        *,
        favorite,
        play,
        resume,
        queue,
        trailer,
        like,
        not_interested,
        dislike,
        watchlist,
        monitor,
        clear_epg_link,
        hide,
    ) -> None:
        """Reparent action buttons into their tiered visual slots.

        Called once from details_pane._setup_ui() after both _PosterSection and
        _ActionBar have been constructed.  The buttons are owned by _ActionBar
        (signals/state/sync live there); we just reparent them into the right slot.

        * **Primary row** (below the poster): play + resume, full-size and labeled,
          each with equal stretch (50/50 when both show; Play full-width when Resume
          is hidden).  Resume is the dominant one when present.
        * **Trailer row** (its own full-width line, between primary and secondary):
          present ONLY when the provider sent a trailer (114,308 of 785k channels) —
          moved off the secondary row, where it ate Watch Later's slack at a narrow
          pane (owner-reported 2026-09-03).
        * **Secondary row** (one line under the trailer row): the labeled "Watch
          Later" (queue) button absorbing all slack, then the like · not-interested ·
          dislike trio right-aligned — collection left, judgment right, so neither
          side needs a caption.  The trio was promoted out of the rail so it sits
          legibly in the main column instead of over the poster art — only ONE set,
          moved not duplicated.
        * **Rail** (slim icon column, top→bottom): favorite · Alert/Monitor (Watchlist
          shares this slot) · Clear EPG link (live only) · hide.  Bracketed by a
          leading + trailing stretch and kept tight (favorite↔monitor = G/2,
          monitor/watchlist↔clear_epg_link = G/2, clear_epg_link↔hide = G).

        Mode-conditional buttons (resume=has-progress, sentiment=VOD, watchlist=live,
        alert=series) keep their slot but are shown/hidden by _ActionBar.
        """
        # Primary row: full-size Play / Resume, equal stretch.
        prow = self._primary_row_layout
        while prow.count():
            prow.takeAt(0)
        prow.addWidget(play, 1)
        prow.addWidget(resume, 1)

        # Trailer row: its own full-width line — stretch 1, whole row is free.
        trow = self._trailer_row_layout
        while trow.count():
            trow.takeAt(0)
        trow.addWidget(trailer, 1)

        # Secondary row, ONE line: "Watch Later" on the left, the sentiment trio
        # right-aligned.  Position separates them — collection action left, judgment
        # cluster right — so neither side carries a caption.
        #
        # WIDTH DISCIPLINE (docs/DETAILS_PANE_DESIGN.md → "Width discipline"): a
        # QHBoxLayout's minimum is the SUM of its children's, so a naive row would
        # floor the pane at (Watch Later's text width + 3 chips).  The queue button
        # opts OUT via horizontal policy Ignored (same escape hatch no_width_force()
        # uses) — 0 minimum, absorbs all slack, yields it back FIRST as the pane
        # narrows.  Row's true minimum: 3 × 48px + spacing ≈ 162px, well under 300px.
        srow = self._secondary_row_layout
        while srow.count():
            srow.takeAt(0)
        q_policy = queue.sizePolicy()
        q_policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        queue.setSizePolicy(q_policy)
        srow.addWidget(queue, 1)            # stretch 1 — takes every spare pixel
        for btn in (like, not_interested, dislike):
            btn.setFixedWidth(self._SENTIMENT_BTN_W)
            srow.addWidget(btn, 0)          # no stretch — pinned to the right edge

        # Rail: the infrequent icon-only set (queue and the sentiment trio both
        # graduated to the secondary row).  Order top→bottom: favorite ·
        # Alert/Monitor (+Watchlist in the same slot) · Clear EPG link (live only,
        # admin tier) · hide.  Leading + trailing stretch bracket the group and it
        # stays tight (Favorite↔Monitor = G/2, Monitor/Watchlist↔Clear-EPG-link =
        # G/2, Clear-EPG-link↔Hide = G).
        layout = self._action_rail_layout
        while layout.count():
            layout.takeAt(0)

        gap = self._RAIL_GAP

        layout.addStretch()                 # leading stretch — bracket the group
        layout.addWidget(favorite)
        layout.addSpacing(gap // 2)         # Favorite ↔ Monitor = G/2 (tight top pair)
        layout.addWidget(monitor)
        layout.addWidget(watchlist)         # Watchlist shares Monitor's slot (exclusive)
        layout.addSpacing(gap // 2)         # Monitor/Watchlist ↔ Clear-EPG-link = G/2
        layout.addWidget(clear_epg_link)
        layout.addSpacing(gap)              # Clear-EPG-link ↔ Hide = G
        layout.addWidget(hide)
        layout.addStretch()                 # trailing stretch — bracket the group
        # NOTE: the rail + primary/secondary rows are left hidden here — they're
        # revealed by set_mode() when a channel is shown, so action controls don't
        # appear in the empty/no-selection state.

    def set_provider_urls(self, urls: list) -> None:
        self._provider_urls = urls

    def load_poster(self, url: str, provider_urls: list | None = None) -> None:
        """Start loading a poster URL (sync-first, async fallback)."""
        if provider_urls is not None:
            self._provider_urls = provider_urls
        self._poster_url = url
        self.poster_label.setPixmap(QPixmap())
        self.poster_label.setText(f"{_icons.loading_icon} Loading poster...")
        pix = self._image_cache.get_image_sync(url)
        if pix:
            self._display_poster(pix)
        else:
            self._image_cache.get_image_async(url, self._provider_urls)

    def load_live_logo(self, url: str) -> None:
        """Show a live channel's LOGO in the poster area (sync-first, async fallback).

        The logo occupies the SAME footprint as a VOD poster (the tall poster box);
        _display_live_logo scales it KeepAspectRatio and centers it on the card,
        upscaling a small logo only up to a sane ceiling so it doesn't pixelate.
        Reuses the async image-loading path; the QPixmap is built on the main thread
        (image_cache emits the path; the slot constructs the pixmap).  If the logo
        can't be loaded, the poster area hides and the live header (country info)
        remains as the fallback.
        """
        self._is_live_logo = True
        self._poster_url = url   # route the loaded image through on_image_loaded
        self._restore_poster_metrics()   # full poster footprint, not a short strip
        self._poster_frame.setVisible(True)
        self.poster_label.setText(f"{_icons.loading_icon} Loading logo...")
        pix = self._image_cache.get_image_sync(url)
        if pix:
            self._display_live_logo(pix)
        else:
            self._image_cache.get_image_async(url, self._provider_urls)

    def _restore_poster_metrics(self) -> None:
        """Restore the hard fixed poster-box height (keeps the Play row from moving)."""
        self.poster_label.setFixedHeight(self._POSTER_FIXED_H)

    def set_country_info(self, channel_name: str) -> None:
        """Extract and display category/country prefix from a channel name."""
        m = _CHANNEL_PREFIX_RE.match(channel_name)
        if not m:
            self._country_info_lbl.setText("Category: unknown  ·  no prefix detected")
            self._country_info_lbl.show()
            return
        raw = m.group(1)
        delimiter = "★" if m.group(2) == "★" else "|"
        code = normalize_region_code(raw)
        # Canonical human name (region OR language — e.g. AR → Arabic, a language, not
        # "Argentina") via the single shared resolver also used by the version chips.
        full = resolve_category_name(raw, self.config)
        text = (
            f"Category: {full} ({code})  ·  via {delimiter} prefix"
            if full
            else f"Category: {code}  ·  via {delimiter} prefix (unrecognized)"
        )
        self._country_info_lbl.setText(text)
        self._country_info_lbl.show()

    def on_image_loaded(self, url: str, pixmap: QPixmap) -> None:
        if url == self._poster_url and not pixmap.isNull():
            if self._is_live_logo:
                self._display_live_logo(pixmap)
            else:
                self._display_poster(pixmap)

    def on_image_failed(self, url: str, error: str) -> None:
        if url == self._poster_url:
            if self._is_live_logo:
                # Logo unavailable — fall back to the live header alone.
                self._poster_frame.setVisible(False)
            else:
                self.poster_label.setText("Failed to load poster")
            logger.debug(f"Poster/logo load failed: {error}")

    def clear(self) -> None:
        self._poster_url = None
        self._logo_url = None
        self._full_pixmap = None
        self._logo_src = None
        self._is_live_logo = False
        self._restore_poster_metrics()
        self.poster_label.setPixmap(QPixmap())
        self.poster_label.setText("No poster available")
        self._country_info_lbl.hide()
        # Reset the Watched badge so a reused pane never shows stale watch state.
        self._watched = False
        self._poster_hovered = False
        self._badge_hovered = False
        self._update_watched_badge()

    # ------------------------------------------------------------------ #
    # Watched badge (VOD only)                                            #
    # ------------------------------------------------------------------ #

    def set_watched(self, is_watched: bool) -> None:
        """Reflect the stored VOD watch_completed state on the poster badge."""
        self._watched = is_watched
        self._update_watched_badge()

    def _on_watched_badge_clicked(self) -> None:
        """Optimistically flip the badge, then let the host persist the new state."""
        new_state = not self._watched
        self.set_watched(new_state)
        self.watched_toggled.emit(new_state)

    def _on_poster_hover(self, hovered: bool) -> None:
        self._poster_hovered = hovered
        self._update_watched_badge()

    def _on_badge_hover(self, hovered: bool) -> None:
        self._badge_hovered = hovered
        self._update_watched_badge()

    def _update_watched_badge(self) -> None:
        """Apply the two-state badge convention.

        Live → never shown.  Watched → persistent SOLID check (click = unmark).
        Unwatched → FAINT check shown only while the poster (or the badge itself)
        is hovered (click = mark watched) so unwatched posters stay uncluttered.
        """
        if self._is_live:
            self._watched_badge.hide()
            return

        if self._watched:
            _theme.style(self._watched_badge, "POSTER_WATCHED_BADGE")
            self._watched_badge.setToolTip("Watched — click to mark as unwatched")
            visible = True
        else:
            _theme.style(self._watched_badge, "POSTER_UNWATCHED_BADGE")
            self._watched_badge.setToolTip("Mark as watched")
            visible = self._poster_hovered or self._badge_hovered

        self._watched_badge.setVisible(visible)
        if visible:
            self._reposition_watched_badge()
            self._watched_badge.raise_()

    def _reposition_watched_badge(self) -> None:
        """Pin the badge to the rendered poster's TOP-right corner.

        Top rather than bottom: the bottom of a poster is where its title
        artwork usually is, and the badge was landing on it. The top-right is
        the corner posters keep clear, and it is where the V3 render puts it.

        Anchor to the PIXMAP's rect, not the label's. The art is centred and
        usually narrower than the card (a pillarboxed portrait fits to height),
        so the label's right edge is out in the card margin — a badge pinned
        there floats beside the poster rather than on it. Falls back to the
        label bounds when there is no pixmap (the empty-card placeholder).
        """
        lbl = self.poster_label
        pix = lbl.pixmap()
        if pix is not None and not pix.isNull():
            right = (lbl.width() + pix.width()) // 2
            top = (lbl.height() - pix.height()) // 2
        else:
            right = lbl.width()
            top = 0
        x = right - self._watched_badge.width() - self._BADGE_MARGIN
        y = top + self._BADGE_MARGIN
        self._watched_badge.move(max(0, x), max(0, y))

    def _display_poster(self, pixmap: QPixmap) -> None:
        if not pixmap or pixmap.isNull():
            self.poster_label.setText("No poster available")
            return
        self._full_pixmap = pixmap   # retain original for lightbox + resize re-fit
        self._is_live_logo = False
        self._apply_scaled_poster()
        self._refit_timer.start(0)   # width can be stale mid-navigation: re-fit once settled

    def _refit_deferred(self) -> None:
        """One settled-width re-fit for whichever image the box is showing."""
        if self._is_live_logo:
            self._apply_scaled_logo()
        else:
            self._apply_scaled_poster()

    def _apply_scaled_poster(self) -> None:
        """Fit the retained VOD poster INSIDE the fixed-height box (KeepAspectRatio).

        The box height is hard-fixed (``_POSTER_FIXED_H``) so the Play/Resume row below it
        never moves between titles.  The poster is fit within (card width, fixed height)
        and centred, so its width can never exceed the card — a hard right boundary — while
        its height never exceeds the box.  Side padding is acceptable; overflow is not.
        """
        if self._rescaling or self._is_live_logo:
            return
        if not self._full_pixmap or self._full_pixmap.isNull():
            return
        w = min(self.poster_label.width(), self.poster_label.maximumWidth())
        if w <= 1:
            return  # not laid out yet — the resize / deferred pass will re-fit
        self._rescaling = True
        try:
            self.poster_label.setPixmap(
                self._full_pixmap.scaled(
                    w,
                    self._POSTER_FIXED_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        finally:
            self._rescaling = False

    def _display_live_logo(self, pixmap: QPixmap) -> None:
        """Show a live channel logo on the poster-card footprint, centered.

        Unlike a VOD poster, a logo does NOT fill the card — it is fit (KeepAspectRatio)
        inside the fixed box and centred, with a small-logo upscale ceiling so it doesn't
        pixelate.  Retains the original so resize can re-fit cleanly.
        """
        if not pixmap or pixmap.isNull():
            self._poster_frame.setVisible(False)
            return
        self._full_pixmap = None   # live logos aren't enlargeable via the lightbox
        self._logo_src = pixmap    # retain the ORIGINAL so resize can re-fit cleanly
        self._restore_poster_metrics()   # logo keeps the fixed 400-600 box (no fill cap)
        self._apply_scaled_logo()
        self._refit_timer.start(0)

    def _apply_scaled_logo(self) -> None:
        """Fit the retained logo inside the current box (centered, with upscale ceiling)."""
        if self._rescaling or not self._is_live_logo:
            return
        if not self._logo_src or self._logo_src.isNull():
            return
        pix = self._logo_src
        avail_w = self.poster_label.width() or (self.minimumWidth() or 300)
        avail_h = self.poster_label.height() or self._POSTER_MIN_H
        avail_w = max(1, avail_w - self._POSTER_GUTTER)   # mirror the poster right gutter
        # Upscale ceiling: a tiny logo grows to at most ceiling× native, then centers.
        ceil_w = int(pix.width() * self._LOGO_UPSCALE_CEILING)
        ceil_h = int(pix.height() * self._LOGO_UPSCALE_CEILING)
        self._rescaling = True
        try:
            scaled = pix.scaled(
                max(1, min(avail_w, ceil_w)), max(1, min(avail_h, ceil_h)),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.poster_label.setPixmap(scaled)
        finally:
            self._rescaling = False

    def _rescale_current_image(self) -> None:
        """Re-fit the current image to the poster label's size on resize.

        Dispatches to the right scaler — a VOD poster fits the fixed-height box; a live
        logo fits the box too.  Both are self-guarded against the setPixmap→relayout→resize
        loop.

        The width cap is the boundary enforcement: a portrait poster under KeepAspectRatio
        fits to WIDTH first, so if the width handed to ``scaled()`` exceeds the poster's
        natural width Qt fits to height instead and the pixmap bleeds past the right edge.
        Capping the label's maximumWidth to (frame − gutter) makes the layout enforce the
        ceiling BEFORE the pixmap is drawn, so ``scaled()`` hits that ceiling and reduces
        height rather than overflowing — and it protects a hard right gutter.
        """
        frame_w = self._poster_frame.width()
        if frame_w > 1:
            # The poster content is inset by _RAIL_W (rail sits in the left gutter), so the
            # label's usable width — and its right-boundary cap — is frame minus the rail.
            self.poster_label.setMaximumWidth(frame_w - self._RAIL_W - self._POSTER_GUTTER)
        if self._is_live_logo:
            self._apply_scaled_logo()
        else:
            self._apply_scaled_poster()

    def _on_poster_clicked(self) -> None:
        """Emit poster_enlarged with the full-res pixmap when the poster is clicked."""
        if self._full_pixmap and not self._full_pixmap.isNull():
            self.poster_enlarged.emit(self._full_pixmap)


# ---------------------------------------------------------------------------
# _PlotSection
# ---------------------------------------------------------------------------

class _PlotSection(CollapsibleMixin, QWidget):
    """Overview header + plot text + loading indicator.

    Collapsible since the section-header component existed to make it cheap.
    It was the one section with the most text and no way to fold it away —
    not by decision, but because collapsing it would have meant a fifth copy
    of the toggle code. No ``set_summary()`` — nothing to count (CHV-2).
    """

    COLLAPSE_KEY = "overview"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_live: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = CollapsibleHeader("Overview")
        layout.addWidget(self._header)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)
        layout.addWidget(self._content)

        self.plot_label = QLabel()
        self.plot_label.setWordWrap(True)
        self.plot_label.setTextFormat(Qt.TextFormat.PlainText)
        _theme.style(self.plot_label, "DETAIL_TEXT")
        _no_width_force(self.plot_label)
        content_layout.addWidget(self.plot_label)

        self.plot_loading = QLabel("Loading description...")
        _theme.style(self.plot_loading, "LOADING_TEXT")
        self.plot_loading.hide()
        content_layout.addWidget(self.plot_loading)

        self._wire_header()

    def set_mode(self, is_live: bool) -> None:
        self._is_live = is_live
        self._apply_visibility()

    def load(self, plot: str | None, loading_icon: str = "") -> None:
        if plot:
            self.plot_label.setText(plot)
        else:
            self.plot_label.clear()
        self.plot_loading.hide()
        self._apply_visibility()

    def show_loading(self, loading_icon: str = "") -> None:
        self.plot_loading.setText(f"{loading_icon} Loading metadata..." if loading_icon else "Loading metadata...")
        self.plot_loading.show()
        self._apply_visibility()

    def clear(self) -> None:
        self.plot_label.clear()
        self.plot_loading.hide()
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """Hide the whole section (header + body) when live, or when there is no
        overview text and nothing is loading — so a plot-less title shows no empty
        'Overview' box.  Re-shown automatically when a reused pane lands on a title
        that does have a plot."""
        has_content = bool(self.plot_label.text()) or not self.plot_loading.isHidden()
        self.setVisible(not self._is_live and has_content)


# ---------------------------------------------------------------------------
# _TechnicalSection
# ---------------------------------------------------------------------------

class _TechnicalSection(CollapsibleMixin, QWidget):
    """Collapsible Technical Details section. No set_summary(): 0-or-1 fields (CHV-2)."""

    COLLAPSE_KEY = "technical"

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = CollapsibleHeader("Technical Details")
        self._header_widget = self._header      # kept: existing callers use this name
        layout.addWidget(self._header)

        # Content
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 0, 0, 0)
        self.tech_details_label = QLabel()
        self.tech_details_label.setWordWrap(True)
        self.tech_details_label.setTextFormat(Qt.TextFormat.RichText)
        _theme.style(self.tech_details_label, "DETAIL_TEXT")
        _no_width_force(self.tech_details_label)
        content_layout.addWidget(self.tech_details_label)
        layout.addWidget(self._content)
        self._wire_header()

    def set_mode(self, is_live: bool) -> None:
        if is_live:
            self.hide()
        else:
            self._apply_collapsed()

    def load(self, metadata: MetadataResult, weights=None) -> bool:
        """Populate section. Returns True if there is anything to display."""
        parts = []
        if metadata.release_date:
            parts.append(f"<b>Release Date:</b> {metadata.release_date}")
        self.tech_details_label.setText("<br>".join(parts))
        has_content = bool(parts)
        self.setVisible(has_content)
        return has_content

    def clear(self) -> None:
        self.tech_details_label.clear()
        self.hide()


# ---------------------------------------------------------------------------
# _CastSection
# ---------------------------------------------------------------------------

class _CastSection(CollapsibleMixin, QWidget):
    """Collapsible Cast & Crew section."""

    COLLAPSE_KEY = "cast"

    person_clicked = pyqtSignal(str)  # emits the person's name when clicked

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._collapsed: bool = False
        self._is_live: bool = False
        self._has_content: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = CollapsibleHeader("Cast")
        self._header_widget = self._header
        layout.addWidget(self._header)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 0, 0, 0)
        content_layout.setSpacing(4)

        self._director_lbl = QLabel()
        self._director_lbl.setWordWrap(True)
        self._director_lbl.setTextFormat(Qt.TextFormat.RichText)
        _theme.style(self._director_lbl, "DETAIL_TEXT")
        self._director_lbl.setOpenExternalLinks(False)
        self._director_lbl.linkActivated.connect(
            lambda url: self.person_clicked.emit(url)
        )
        _no_width_force(self._director_lbl)
        self._director_lbl.hide()
        content_layout.addWidget(self._director_lbl)

        self.cast_label = QLabel()
        self.cast_label.setWordWrap(True)
        self.cast_label.setTextFormat(Qt.TextFormat.RichText)
        _theme.style(self.cast_label, "DETAIL_TEXT")
        self.cast_label.setOpenExternalLinks(False)
        self.cast_label.linkActivated.connect(
            lambda url: self.person_clicked.emit(url)
        )
        _no_width_force(self.cast_label)
        content_layout.addWidget(self.cast_label)
        layout.addWidget(self._content)
        self._wire_header()

    def restore_collapse_state(self, collapsed_sections: list[str]) -> None:
        self._header.set_collapsed("cast" in (collapsed_sections or []))
        self._apply_collapsed()

    def set_mode(self, is_live: bool) -> None:
        self._is_live = is_live
        if not is_live:
            self._apply_collapsed()
        self._apply_visibility()

    def load(self, cast: list, director: str | None = None, weights=None) -> None:
        link_col = _theme.COLOR_ACCENT_BLUE_2

        if director:
            from metatv.core.preference_engine import _split_directors
            names = _split_directors(director)
            dir_parts = []
            for d in names:
                sig = _pref_signal(d, weights, 'directors') if weights else ""
                href = html.escape(d, quote=True)
                link = (
                    f'{sig}<a href="{href}" style="color:{link_col};'
                    f' text-decoration:none;">{html.escape(d)}</a>'
                )
                dir_parts.append(link)
            self._director_lbl.setText(f"<b>Director:</b> {', '.join(dir_parts)}")
            self._director_lbl.show()
        else:
            self._director_lbl.hide()

        if cast:
            parts = []
            for actor in cast[:10]:
                name = actor.get("name", "Unknown") if isinstance(actor, dict) else str(actor)
                sig = _pref_signal(name, weights, "actors") if weights else ""
                href = html.escape(name, quote=True)
                parts.append(
                    f'{sig}<a href="{href}" style="color:{link_col};'
                    f' text-decoration:none;">{html.escape(name)}</a>'
                )
            self.cast_label.setText(", ".join(parts))
        else:
            self.cast_label.clear()

        self._header.set_summary(str(n) if (n := len(cast)) else "", f"{n} cast member{'s'*(n!=1)}")
        # A director alone OR any cast is enough to show the section.
        self._has_content = bool(director) or bool(cast)
        self._apply_visibility()

    def clear(self) -> None:
        self._header.set_summary("")
        self._director_lbl.hide()
        self.cast_label.clear()
        self._has_content = False
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """Hide the whole Cast & Crew section (header + body) when live, or when
        there is no cast and no crew — so a credit-less title shows no empty box.
        Re-shown when a reused pane lands on a title that has people."""
        self.setVisible(not self._is_live and self._has_content)



# ---------------------------------------------------------------------------
# _TagsSection
# ---------------------------------------------------------------------------

# Canonical display order for facet groups in the Tags section.
# "category" sits immediately before "genre" — both are content descriptors;
# category is the live-channel variant (Sports/News/Kids…).
_FACET_DISPLAY_ORDER: list[str] = [
    "language", "subtitle", "dub", "format",
    "region", "category", "genre", "platform", "quality", "decade", "collection",
]

# Human-readable label for each facet type.
_FACET_LABELS: dict[str, str] = {
    "language":    "Language",
    "subtitle":    "Subtitle",
    "dub":         "Dub",
    "format":      "Audio Format",
    "region":      "Region",
    "category":    "Category",
    "genre":       "Genre",
    "platform":    "Platform",
    "quality":     "Quality",
    "decade":      "Decade",
    "collection":  "Collection",
    "content_type": "Content Type",
    # Named in the provider's filename, NOT verified credits — the label says so
    # because this facet sits a few inches from the authoritative Cast & Crew
    # section and the two must never read as the same claim. A provider typo
    # ("Denzel Washigton") lands here honestly; it must not look like a credit.
    "person":      "Named in Title",
}

# Confidence threshold below which a chip is styled as low-confidence.
_LOW_CONF_THRESHOLD: float = 0.5


class _TagsSection(CollapsibleMixin, QWidget):
    """Collapsible 'Tags' section showing stored content_tags, grouped by facet.

    Each tag renders as a chip labeled with:
    - Provenance: solid border = source-given; dashed border = inferred.
    - Confidence: dimmed chip text for tags with confidence < 0.5.
    - Tooltip: feeder names + provenance label + confidence value.

    DR-0006: all tags are shown regardless of confidence — confidence is
    ranking + prune-priority only, never a suppression gate.

    Chips are interactive (clickable Tags/Collections):
    - **Left-click** → ``tag_filter_clicked(facet_type, value)``: activates the
      strict context-filter chip for that EXACT tag facet (no hierarchy rollup).
    - **Right-click** → ``tag_discover_clicked(facet_type, value)``: opens the
      tag-cloud Recipe view seeded with that one ingredient (poster shelf).
    The host (MainWindow) resolves the COLLECTION facet specially — see
    ``_on_tag_filter_requested`` — to the curated provider category membership,
    not a re-derived query on the lossy 'collection' residual.
    """

    COLLAPSE_KEY = "tags"

    # (facet_type, value) — left-click: strict exact-tag context filter
    tag_filter_clicked = pyqtSignal(str, str)
    # (facet_type, value) — right-click: seed Discover/Recipe with this one tag
    tag_discover_clicked = pyqtSignal(str, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup()

    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Collapsible header
        self._header = CollapsibleHeader(f"{_icons.tag_section_icon} Tags")
        self._header_widget = self._header
        layout.addWidget(self._header)

        # Scrollable content area — chips can wrap into many rows
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 0, 0, 6)
        self._content_layout.setSpacing(6)
        layout.addWidget(self._content)
        self._wire_header()

        # Initially hidden until tags are loaded
        self.hide()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def load(self, tags: list) -> None:
        """Populate section from a list of ChannelTagDTO objects.

        Args:
            tags: List of ``ChannelTagDTO`` — must not be ORM objects.
                  Renders all tags grouped by facet in display order.
        """
        self._clear_content()

        if not tags:
            self._header.set_summary("")
            self.hide()
            return

        # Group by facet type, preserving DR-0006 "capture all" principle.
        grouped: dict[str, list] = {}
        for tag in tags:
            grouped.setdefault(tag.facet_type, []).append(tag)

        # Sort within each facet: source-given first, then by confidence desc, then value.
        for facet_tags in grouped.values():
            facet_tags.sort(key=lambda t: (not t.source_given, -t.confidence, t.value))

        # Render in canonical display order; any unknown facets appended at the end.
        ordered_facets: list[str] = [
            f for f in _FACET_DISPLAY_ORDER if f in grouped
        ]
        ordered_facets.extend(
            f for f in sorted(grouped) if f not in _FACET_DISPLAY_ORDER
        )

        for facet in ordered_facets:
            self._render_facet_group(facet, grouped[facet])

        self._header.set_summary(str(n := len(tags)), f"{n} tag{'s'*(n != 1)}")
        self._apply_collapsed()
        self.show()

    def clear(self) -> None:
        """Clear all chips and hide the section."""
        self._header.set_summary("")
        self._clear_content()
        self.hide()

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _clear_content(self) -> None:
        """Remove all child widgets from the content layout."""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render_facet_group(self, facet: str, tags: list) -> None:
        """Render a labeled chip row for one facet group."""
        label_text = _FACET_LABELS.get(facet, facet.replace("_", " ").title())

        # Facet label (e.g. "LANGUAGE")
        lbl = QLabel(label_text.upper())
        _theme.style(lbl, "TAG_FACET_LABEL")
        self._content_layout.addWidget(lbl)

        # Chip row — a wrapping FlowLayout, NEVER a QHBoxLayout.  A facet with many
        # chips (a long GENRE or LANGUAGE list) must wrap onto additional rows at the
        # panel width; a non-wrapping QHBoxLayout instead crushes every chip below its
        # text width (center-elided "tion & Adver", "Animatio") to fit one row.  A flow
        # packs left-to-right and left-aligns on its own, so no trailing stretch.
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        row_layout = FlowLayout(row, h_spacing=4, v_spacing=4)

        for tag in tags:
            chip = self._make_chip(tag)
            row_layout.addWidget(chip)

        self._content_layout.addWidget(row)

    def _make_chip(self, tag) -> QPushButton:
        """Build a single QPushButton chip for a ChannelTagDTO."""
        # Provenance prefix: ■ = source-given, □ = inferred
        prov_icon = (
            _icons.tag_source_given_icon if tag.source_given
            else _icons.tag_inferred_icon
        )
        # content_type values are stored slugs (e.g. "ai_generated"); render the
        # friendly label via the single display chokepoint.  The click identity
        # (tag.value) below is unchanged — display only.
        if tag.facet_type == "content_type":
            from metatv.core.channel_name_utils import content_type_display
            display_value = content_type_display(tag.value)
        else:
            display_value = tag.value
        label = f"{prov_icon} {display_value}"

        # Escape "&" for display — a facet value like "Kids & Family" or a
        # collection name would otherwise render its "&" as a mnemonic
        # underscore.  tag.value (captured above) stays raw for the emit.
        chip = QPushButton(escape_mnemonic(label))
        chip.setFlat(True)
        chip.setFixedHeight(22)

        # Provenance style: source-given = solid border; inferred = dashed border.
        # Low-confidence = extra dimming on top of provenance style.
        if tag.source_given:
            _theme.style(chip, "TAG_CHIP_SOURCE")
        else:
            _theme.style(chip, "TAG_CHIP_INFERRED")

        # Interactivity: left-click → strict context filter for this exact facet;
        # right-click → seed Discover/Recipe with this one tag.  Default-arg
        # capture pins each chip's own (facet_type, value).
        _ftype, _val = tag.facet_type, tag.value
        chip.clicked.connect(
            lambda _checked=False, ft=_ftype, v=_val: self.tag_filter_clicked.emit(ft, v)
        )
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda _pos, ft=_ftype, v=_val: self.tag_discover_clicked.emit(ft, v)
        )

        # Tooltip: feeder list + provenance label + confidence value + actions.
        prov_label = "Given by source" if tag.source_given else "Inferred by MetaTV"
        feeder_str = ", ".join(tag.feeders) if tag.feeders else "unknown"
        conf_pct = round(tag.confidence * 100)
        conf_note = "" if tag.confidence >= _LOW_CONF_THRESHOLD else " (low confidence)"
        if _ftype == "collection":
            action_hint = (
                "Click: show this collection's channels  ·  "
                "Right-click: Discover this collection"
            )
        else:
            action_hint = (
                "Click: filter to this tag  ·  Right-click: Discover this tag"
            )
        chip.setToolTip(
            f"{tag.facet_type}: {display_value}\n"
            f"Provenance: {prov_label}\n"
            f"Feeder(s): {feeder_str}\n"
            f"Confidence: {conf_pct}%{conf_note}\n"
            f"{action_hint}"
        )

        return chip


