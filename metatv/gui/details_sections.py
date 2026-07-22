"""Content section widgets for the details pane: poster, metadata, plot, technical, cast."""
import html
import re

from loguru import logger

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QSizePolicy, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap

from metatv.core.channel_name_utils import (
    normalize_region_code, REGION_FULL_NAMES, QUALITY_TOKENS,
)
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.details_versions import _CHANNEL_PREFIX_RE, resolve_category_name, _FlowLayout
from metatv.metadata_providers.base import MetadataResult


def _no_width_force(label: QLabel) -> None:
    """Let a word-wrapped label wrap/break to the available width instead of forcing
    the details column wider than the viewport.

    A wrapping ``QLabel`` reports ``minimumSizeHint().width()`` equal to its longest
    *unbreakable* word, because word-wrap only breaks at spaces.  A scene-release-style
    token (e.g. ``A.Very.Long.Release.Name.1998.1080p.BluRay.x265-GROUP``) or a URL has
    no spaces, so the label's minimum width becomes that whole token — and inside the
    width-resizable, horizontal-scrollbar-off details ``QScrollArea`` that floors the
    *entire* content column at that width, clipping every other section off the right
    edge (see docs/DETAILS_PANE_DESIGN.md → "Width discipline").

    Ignoring the horizontal hint (the same trick ``title_label`` uses) lets the layout
    shrink the label to the pane width; Qt then breaks the long token at a character
    boundary instead of widening the pane.
    """
    sp = label.sizePolicy()
    sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    label.setSizePolicy(sp)


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

    def setPixmap(self, pixmap: QPixmap) -> None:  # type: ignore[override]
        super().setPixmap(pixmap)
        self._has_pixmap = not (pixmap is None or pixmap.isNull())
        self._update_cursor()

    def clear(self) -> None:
        super().clear()
        self._has_pixmap = False
        self._update_cursor()

    def setText(self, text: str) -> None:  # type: ignore[override]
        super().setText(text)
        # Clearing the image via text also clears the pixmap state
        self._has_pixmap = False
        self._update_cursor()

    def _update_cursor(self) -> None:
        cursor_affordance.set_clickable(self, self._has_pixmap)

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
    # (Favorite↔Monitor) is G/2.  The TOP group (Favorite · Monitor/Watchlist · Hide)
    # stays tight, but Hide↔sentiment is a much LARGER gap (_RAIL_SENTIMENT_GAP) so the
    # sentiment trio (Like/Not-Interested/Dislike) drops LOW — down near the Play/Resume
    # row — instead of bunching under Hide.  The trio itself stays a tight, equal cluster.
    _RAIL_GAP: int = 20
    _RAIL_TRIO_GAP: int = 4
    _RAIL_SENTIMENT_GAP: int = 80   # 4×G — pushes the sentiment trio down toward Play
    _RAIL_W: int = 48   # slim icon rail in the left gutter; poster content is inset by this

    def __init__(self, config, image_cache, parent=None):
        super().__init__(parent)
        self.config = config
        self._image_cache = image_cache
        self._poster_url: str | None = None
        self._logo_url: str | None = None
        self._provider_urls: list = []
        self._full_pixmap: QPixmap | None = None   # full-res image for the lightbox
        self._is_live_logo: bool = False           # poster area is showing a live logo
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
        # Left-aligned (not centered): a pillarboxed portrait poster hugs the box's LEFT
        # edge so the action rail floating over that edge always overlays the poster itself,
        # never the gray card margin; the side padding falls entirely on the RIGHT.
        self.poster_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
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
        self.poster_label.setStyleSheet(
            f"QLabel {{ background-color: {_theme.OVERLAY_BLACK_30}; border-radius: 8px;"
            f" color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM}; }}"
        )
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
        self._action_rail.setStyleSheet(
            f"#posterActionRail {{ background-color: {_theme.COLOR_BG_CARD};"
            f" border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}"
        )
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
        self._country_info_lbl.setStyleSheet(f"font-size: {_theme.FONT_MD}; color: {_theme.COLOR_DISABLED}; font-style: italic;")
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

        # Secondary action row — full-width "Watch Later" (queue), directly under the
        # primary Play/Resume row and likewise full-width / title-aligned.  Promoted out
        # of the rail (it is the most-likely "not right now" follow-up).  The queue
        # button is reparented in by set_action_buttons(); hidden until a channel is
        # shown (set_mode).
        self._secondary_action_row = QWidget()
        self._secondary_row_layout = QVBoxLayout(self._secondary_action_row)
        self._secondary_row_layout.setContentsMargins(0, 6, 0, 0)
        self._secondary_row_layout.setSpacing(0)
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
        # Primary action row (Play / Resume) + secondary "Watch Later" show for ALL
        # channel types.
        self._primary_action_row.setVisible(True)
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
        like,
        not_interested,
        dislike,
        watchlist,
        monitor,
        hide,
    ) -> None:
        """Reparent action buttons into their tiered visual slots.

        Called once from details_pane._setup_ui() after both _PosterSection and
        _ActionBar have been constructed.  The buttons are owned by _ActionBar
        (signals/state/sync live there); we just reparent them into the right slot.

        * **Primary row** (below the poster): play + resume, full-size and labeled,
          each with equal stretch (50/50 when both show; Play full-width when Resume
          is hidden).  Resume is the dominant one when present.
        * **Secondary row** (under the primary row): the full-width labeled "Watch
          Later" (queue) button.
        * **Rail** (slim icon column, top→bottom): favorite · Alert/Monitor (Watchlist
          shares this slot) · hide · like · not-interested · dislike.  The group is
          bracketed by a leading + trailing stretch; the TOP group (favorite ·
          monitor/watchlist · hide) is tight, then a much LARGER Hide↔sentiment gap
          drops the sentiment trio LOW (near the Play/Resume row), so the trio no longer
          bunches under Hide.  The trio itself stays a tight cluster.

        Mode-conditional buttons (resume=has-progress, sentiment=VOD, watchlist=live,
        alert=series) keep their slot but are shown/hidden by _ActionBar.
        """
        # Primary row: full-size Play / Resume, equal stretch.
        prow = self._primary_row_layout
        while prow.count():
            prow.takeAt(0)
        prow.addWidget(play, 1)
        prow.addWidget(resume, 1)

        # Secondary row: full-width "Watch Later" (queue).
        srow = self._secondary_row_layout
        while srow.count():
            srow.takeAt(0)
        srow.addWidget(queue)

        # Rail: the infrequent icon-only set (queue is NOT here — it graduated to the
        # secondary row above).  Order top→bottom: favorite · Alert/Monitor (+Watchlist
        # in the same slot) · hide · like · not-interested · dislike.  Leading + trailing
        # stretch bracket the group; the TOP group is tight (Favorite↔Monitor = G/2,
        # Monitor/Watchlist↔Hide = G), then a much LARGER Hide↔sentiment gap
        # (_RAIL_SENTIMENT_GAP ≫ G) drops the sentiment trio low — near the Play/Resume
        # row — instead of bunching it under Hide.  The trio stays a tight equal cluster.
        layout = self._action_rail_layout
        while layout.count():
            layout.takeAt(0)

        gap = self._RAIL_GAP
        trio = self._RAIL_TRIO_GAP
        sentiment_gap = self._RAIL_SENTIMENT_GAP

        layout.addStretch()                 # leading stretch — bracket the group
        layout.addWidget(favorite)
        layout.addSpacing(gap // 2)         # Favorite ↔ Monitor = G/2 (tight top pair)
        layout.addWidget(monitor)
        layout.addWidget(watchlist)         # Watchlist shares Monitor's slot (exclusive)
        layout.addSpacing(gap)              # Monitor/Watchlist ↔ Hide = G
        layout.addWidget(hide)
        layout.addSpacing(sentiment_gap)    # Hide ↔ sentiment ≫ G — drops the trio LOW
        layout.addWidget(like)
        layout.addSpacing(trio)             # tight sentiment trio
        layout.addWidget(not_interested)
        layout.addSpacing(trio)
        layout.addWidget(dislike)
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
            self._watched_badge.setStyleSheet(_theme.POSTER_WATCHED_BADGE)
            self._watched_badge.setToolTip("Watched — click to mark as unwatched")
            visible = True
        else:
            self._watched_badge.setStyleSheet(_theme.POSTER_UNWATCHED_BADGE)
            self._watched_badge.setToolTip("Mark as watched")
            visible = self._poster_hovered or self._badge_hovered

        self._watched_badge.setVisible(visible)
        if visible:
            self._reposition_watched_badge()
            self._watched_badge.raise_()

    def _reposition_watched_badge(self) -> None:
        """Pin the badge to the *rendered poster's* lower-right corner (near the play zone,
        where the eye lands after the poster).

        The poster is left-aligned + v-centered and usually narrower than the card (a
        pillarboxed portrait fits to height), so the visible image ends well left of the
        card's right edge.  Anchor to the pixmap's actual rect — its right edge is
        ``pixmap.width()`` (left-aligned at x=0) and its bottom is v-centered — so the badge
        lands ON the poster, not out in the gray margin.  Falls back to the label bounds when
        no pixmap is set (e.g. the "No poster available" placeholder).
        """
        lbl = self.poster_label
        pix = lbl.pixmap()
        if pix is not None and not pix.isNull():
            right = pix.width()
            bottom = (lbl.height() + pix.height()) // 2
        else:
            right = lbl.width()
            bottom = lbl.height()
        x = right - self._watched_badge.width() - self._BADGE_MARGIN
        y = bottom - self._watched_badge.height() - self._BADGE_MARGIN
        self._watched_badge.move(max(0, x), max(0, y))

    def _display_poster(self, pixmap: QPixmap) -> None:
        if not pixmap or pixmap.isNull():
            self.poster_label.setText("No poster available")
            return
        self._full_pixmap = pixmap   # retain original for lightbox + resize re-fit
        self._is_live_logo = False
        self._apply_scaled_poster()
        # During rapid navigation the label width can be stale when the poster loads, so a
        # one-shot deferred pass re-fits at the settled width.
        QTimer.singleShot(0, self._apply_scaled_poster)

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
        QTimer.singleShot(0, self._apply_scaled_logo)

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
# _MetadataSection
# ---------------------------------------------------------------------------

class _MetadataSection(QWidget):
    """Title, year, rating, genres, source badge, adult indicator, rec reason."""

    genre_clicked = pyqtSignal(str)  # emits the genre name when user clicks a genre chip

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Title bar: [title ···] [chip] [year]
        title_bar = QWidget()
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(0, 0, 0, 0)
        title_bar_layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setStyleSheet(_theme.DETAIL_TITLE)
        title_bar_layout.addWidget(self.title_label, 1)

        self._prefix_chip = QPushButton()
        self._prefix_chip.setFlat(True)
        self._prefix_chip.setStyleSheet(_theme.CATEGORY_CHIP)
        self._prefix_chip.setFixedHeight(24)
        self._prefix_chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._prefix_chip.hide()
        title_bar_layout.addWidget(self._prefix_chip)

        self._quality_chip = QPushButton()
        self._quality_chip.setFlat(True)
        self._quality_chip.setStyleSheet(_theme.QUALITY_CHIP)
        self._quality_chip.setFixedHeight(24)
        self._quality_chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._quality_chip.hide()
        title_bar_layout.addWidget(self._quality_chip)

        self._name_year_lbl = QLabel()
        self._name_year_lbl.setStyleSheet(
            f"font-size: {_theme.FONT_LG}; color: {_theme.COLOR_MUTED}; font-weight: bold;"
        )
        self._name_year_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._name_year_lbl.hide()
        title_bar_layout.addWidget(self._name_year_lbl)

        layout.addWidget(title_bar)

        # Tagline — italic subtitle line, shown when metadata provides it
        self._tagline_lbl = QLabel()
        self._tagline_lbl.setWordWrap(True)
        self._tagline_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED}; font-style: italic; font-size: {_theme.FONT_LG};"
        )
        _no_width_force(self._tagline_lbl)
        self._tagline_lbl.hide()
        layout.addWidget(self._tagline_lbl)

        # Media type row: [icon Type] [runtime] [IMDb xxx] [TMDb xxx] [PG-13] [★★★ X of 10]
        # A WRAPPING flow layout — never a QHBoxLayout.  A non-wrapping row would sum
        # its children's widths into a wide minimumSizeHint that pushes the whole
        # _MetadataSection past the ~500px details viewport (which has the horizontal
        # scrollbar off), so the genre flow below was handed a too-wide rectangle and
        # the genres ran off the edge instead of wrapping.  A _FlowLayout's minimum
        # width is its widest single chip, so the section stays within the viewport and
        # the badges + genres wrap on their own.
        self._media_row = QWidget()
        self._media_row.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        media_row_layout = _FlowLayout(self._media_row, h_spacing=8, v_spacing=4)

        self._media_type_lbl = QLabel()
        self._media_type_lbl.setStyleSheet(_theme.META_DIM)
        media_row_layout.addWidget(self._media_type_lbl)

        self.runtime_label = QLabel()
        self.runtime_label.setStyleSheet(_theme.META_DIM)
        self.runtime_label.hide()
        media_row_layout.addWidget(self.runtime_label)

        self._imdb_lbl = QLabel()
        self._imdb_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_SM};"
        )
        self._imdb_lbl.hide()
        media_row_layout.addWidget(self._imdb_lbl)

        self._tmdb_lbl = QLabel()
        self._tmdb_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED_2}; font-size: {_theme.FONT_SM};"
        )
        self._tmdb_lbl.hide()
        media_row_layout.addWidget(self._tmdb_lbl)

        # PG-13 / content-rating badge — right of the IDs, left of the stars
        self._content_rating_lbl = QLabel()
        self._content_rating_lbl.setStyleSheet(
            f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_SM};"
            f" border: 1px solid {_theme.COLOR_BORDER}; border-radius: 3px; padding: 1px 4px;"
        )
        self._content_rating_lbl.hide()
        media_row_layout.addWidget(self._content_rating_lbl)

        # Star rating — rightmost, hidden when no rating present (no empty gap)
        self.rating_label = QLabel()
        self.rating_label.setStyleSheet(f"color: {_theme.COLOR_GOLD}; font-weight: bold;")
        self.rating_label.hide()
        media_row_layout.addWidget(self.rating_label)

        layout.addWidget(self._media_row)

        # Source badge + adult indicator row
        badge_row = QHBoxLayout()
        self.source_label = _ClickableLabel()
        self.source_label.setStyleSheet(f"color: {_theme.COLOR_MUTED}; font-size: {_theme.FONT_MD};")
        self.source_label.hide()
        badge_row.addWidget(self.source_label)
        self.adult_indicator = QLabel("🔞 Adult")
        self.adult_indicator.setStyleSheet(
            f"color: {_theme.COLOR_ERR_2}; font-size: {_theme.FONT_MD}; font-weight: 600;"
            f" background: {_theme.OVERLAY_ERR2_15}; border-radius: 3px; padding: 1px 5px;"
        )
        self.adult_indicator.hide()
        badge_row.addWidget(self.adult_indicator)
        badge_row.addStretch()
        layout.addLayout(badge_row)

        # Genres — flow-layout row of clickable chip buttons; wraps cleanly at panel width.
        # _genres_loading_lbl is shown while metadata is loading; _genres_container replaces
        # it once genres arrive.  Both start hidden; load_basic() shows the loading label;
        # load_metadata() hides it and populates the flow container.
        self._genres_loading_lbl = QLabel()
        self._genres_loading_lbl.setStyleSheet(
            f"color: {_theme.COLOR_DIM}; font-size: {_theme.FONT_MD};"
        )
        self._genres_loading_lbl.hide()
        layout.addWidget(self._genres_loading_lbl)

        self._genres_container = QWidget()
        self._genres_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        self._genres_layout = _FlowLayout(self._genres_container, h_spacing=4, v_spacing=4)
        self._genres_container.hide()
        layout.addWidget(self._genres_container)

        # Watch-completion state is shown in the action rail (Watched toggle +
        # Resume button), not as a text line here.

        # Recommendation reason
        self.rec_reason_label = QLabel()
        self.rec_reason_label.setStyleSheet(f"color: {_theme.COLOR_DIM}; font-size: {_theme.FONT_MD}; font-style: italic;")
        self.rec_reason_label.setWordWrap(True)
        _no_width_force(self.rec_reason_label)
        self.rec_reason_label.hide()
        layout.addWidget(self.rec_reason_label)

    def set_mode(self, is_live: bool) -> None:
        self._media_row.setVisible(not is_live)
        if is_live:
            self._genres_loading_lbl.hide()
            self._genres_container.hide()
        if is_live:
            self.title_label.setStyleSheet(f"font-size: {_theme.FONT_4XL}; font-weight: bold;")
            self._tagline_lbl.hide()
            # rating_label and _content_rating_lbl live on _media_row which is
            # already hidden above via self._media_row.setVisible(not is_live)
        else:
            self.title_label.setStyleSheet(_theme.DETAIL_TITLE)

    def load_basic(self, channel, provider_map: dict | None = None) -> None:
        """Tier-1 display: channel attributes only, no metadata.

        Reads stored detected_* fields written at ingestion time — never calls
        parse_channel_name() here (ingestion-only rule, CLAUDE.md).
        """
        # Title — use stored detected_title (prefix/suffix already stripped at ingestion).
        clean_title = getattr(channel, "detected_title", None) or channel.name
        self.title_label.setText(clean_title)
        self.title_label.setToolTip(channel.name)

        # Prefix chip — shows detected category code (EN, NF, D+, etc.).
        # Quality tokens (4K, HD, etc.) are not region/platform chips; skip them.
        # Priority: detected_prefix (separator prefix) > detected_region (parenthetical origin)
        prefix = (
            getattr(channel, "detected_prefix", None)
            or getattr(channel, "detected_region", None)
            or ""
        )
        if prefix and prefix.upper() not in QUALITY_TOKENS:
            name = resolve_category_name(prefix, self.config)
            # Show the human name + code (e.g. "Arabic (AR)") — a language/region is
            # never rendered as a bare, ambiguous code.  Raw code only when unresolved.
            self._prefix_chip.setText(f"{name} ({prefix})" if name else prefix)
            self._prefix_chip.setToolTip(name or prefix)
            self._prefix_chip.show()
        else:
            self._prefix_chip.hide()

        # Quality chip — shows detected quality (4K, UHD, HD, etc.) next to language chip.
        quality = getattr(channel, "detected_quality", None)
        if quality:
            self._quality_chip.setText(quality.upper())
            self._quality_chip.setToolTip(f"{quality.upper()} quality")
            self._quality_chip.show()
        else:
            self._quality_chip.hide()

        # Year from channel name — shown to the right of the title
        year = getattr(channel, "detected_year", None)
        if year:
            self._name_year_lbl.setText(year)
            self._name_year_lbl.show()
        else:
            self._name_year_lbl.hide()

        media_icon = {
            "live":   _icons.live_icon,
            "movie":  _icons.movie_icon,
            "series": _icons.series_icon,
        }.get(channel.media_type or "", _icons.unknown_icon)
        self._media_type_lbl.setText(f"{media_icon} {(channel.media_type or 'unknown').title()}")
        self.runtime_label.hide()

        provider_id = getattr(channel, "provider_id", None)
        if provider_id is not None:
            provider_info = (provider_map or {}).get(provider_id)
            if provider_info:
                icon = provider_info.get("icon", "")
                name = provider_info.get("name", "")
                badge = f"{icon} {name}".strip() if icon else name
                label_text = f"Source: {badge}" if badge else f"Source: {provider_id}"
            else:
                label_text = f"Source: (source removed) [{provider_id}]"
            self.source_label.setText(label_text)
            # Store channel ID for click-to-copy and add tooltip
            self.source_label.channel_id = channel.id
            self.source_label.setToolTip(f"ID: {channel.id}\n(Click to copy)")
            self.source_label.show()

        if getattr(channel, "is_adult", False):
            self.adult_indicator.show()
        else:
            self.adult_indicator.hide()

        # Watch-completion state is surfaced in the action rail (the Watched toggle
        # and the Resume button), not as a text line here — see details_pane.

        # Show rating from raw_data immediately (don't wait for metadata).
        # rating_label lives on the media-type row so no separate row to show/hide.
        # A rating of 0 / "0" / "0.0" means "unrated" — hide it (don't show "0.0 of 10").
        raw_rating = channel.raw_data.get("rating") if channel.raw_data else None
        try:
            rating_val = float(raw_rating) if raw_rating not in (None, "") else 0.0
        except (ValueError, TypeError):
            rating_val = 0.0
        if rating_val > 0:
            rating_val = min(10.0, rating_val)  # clamp upper bound
            stars = self.config.rating_star_icon * int(rating_val / 2)
            self.rating_label.setText(f"{stars} {rating_val:.1f} of 10")
            self.rating_label.show()
        else:
            self.rating_label.hide()

        # Show loading indicator for categories (will be populated by load_metadata).
        # LIVE channels have no metadata genres — hide the area; the version chips
        # (set_versions) handle their category display instead.
        if getattr(channel, "media_type", None) == "live":
            self._genres_loading_lbl.hide()
            self._genres_container.hide()
        else:
            self._genres_container.hide()
            self._genres_loading_lbl.setText(f"{_icons.loading_icon} Loading categories...")
            self._genres_loading_lbl.show()

    def load_metadata(self, metadata: MetadataResult) -> None:
        """Tier-2/3 display: enrich with metadata fields."""
        if metadata.title:
            # Display the metadata title verbatim — never re-parse it at render
            # (ingestion-only rule, CLAUDE.md; see load_basic). Stripping via
            # parse_channel_name() can also mangle a legit title ending in a
            # parenthetical or (YYYY). The year label is sourced from the stored
            # metadata.year field below.
            self.title_label.setText(metadata.title)

        if metadata.tagline:
            self._tagline_lbl.setText(metadata.tagline)
            self._tagline_lbl.show()

        if metadata.year:
            self._name_year_lbl.setText(str(metadata.year))
            self._name_year_lbl.show()

        if metadata.rating:
            count_str = (
                f" by {metadata.rating_count:,} votes" if metadata.rating_count else ""
            )
            stars = self.config.rating_star_icon * int(metadata.rating / 2)
            self.rating_label.setText(f"{stars} {metadata.rating:.1f} of 10{count_str}")
            self.rating_label.show()

        if metadata.content_rating:
            self._content_rating_lbl.setText(metadata.content_rating)
            self._content_rating_lbl.show()

        if metadata.runtime:
            h, m = divmod(metadata.runtime, 60)
            self.runtime_label.setText(f"{h}h {m}m" if h else f"{m}m")
            self.runtime_label.show()

        if metadata.imdb_id:
            self._imdb_lbl.setText(f"IMDb {metadata.imdb_id}")
            self._imdb_lbl.show()

        if metadata.tmdb_id:
            self._tmdb_lbl.setText(f"TMDb {metadata.tmdb_id}")
            self._tmdb_lbl.show()

        self._genres_loading_lbl.hide()
        if metadata.genres:
            # Split combined genre strings into one chip each so they wrap cleanly
            # in the flow layout.  Providers deliver genres inconsistently: a real
            # list (["Action", "Drama"]), a slash-joined string ("Action / Drama"),
            # or a single comma-joined string ("Action, Adventure, Sci-Fi").  An
            # un-split comma string renders as one over-wide chip whose minimum
            # width pushes the whole details panel wider (e87956eb).  Split on both
            # ',' and '/'; never '&' — "Sci-Fi & Fantasy" / "Action & Adventure"
            # are single TMDB genres.  De-dupe (case-insensitive) so merged
            # multi-provider metadata doesn't yield duplicate chips.
            genres: list[str] = []
            seen: set[str] = set()
            for g in metadata.genres:
                parts = re.split(r"\s*[/,]\s*", g) if isinstance(g, str) else [g]
                for p in parts:
                    name = p.strip() if isinstance(p, str) else p
                    if not name:
                        continue
                    key = name.casefold() if isinstance(name, str) else name
                    if key in seen:
                        continue
                    seen.add(key)
                    genres.append(name)
            self._populate_genre_chips(genres)
        else:
            # No genres available — hide the container too
            self._genres_container.hide()

    def set_recommendation_reason(self, reason: str | None) -> None:
        if reason:
            self.rec_reason_label.setText(f"{self.config.preferences_icon} Recommended: {reason}")
            self.rec_reason_label.show()
        else:
            self.rec_reason_label.hide()

    def clear(self) -> None:
        self.title_label.clear()
        self._prefix_chip.hide()
        self._quality_chip.hide()
        self._name_year_lbl.hide()
        self._tagline_lbl.hide()
        self._media_type_lbl.clear()
        self.runtime_label.hide()
        self._imdb_lbl.hide()
        self._tmdb_lbl.hide()
        self.rating_label.clear()
        self.rating_label.hide()
        self._content_rating_lbl.hide()
        self._genres_loading_lbl.hide()
        self._clear_genre_chips()
        self._genres_container.hide()
        self.source_label.clear()
        self.source_label.hide()
        self.adult_indicator.hide()
        self.rec_reason_label.hide()

    # ------------------------------------------------------------------ #
    # Genre chips — private helpers                                        #
    # ------------------------------------------------------------------ #

    def _clear_genre_chips(self) -> None:
        """Remove all genre chip buttons from the flow layout."""
        while self._genres_layout.count():
            item = self._genres_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

    def _populate_genre_chips(self, genres: list[str]) -> None:
        """Replace the flow layout contents with one chip button per genre."""
        self._clear_genre_chips()
        for g in genres:
            chip = QPushButton(g)
            chip.setFlat(True)
            chip.setStyleSheet(_theme.GENRE_CHIP)
            chip.setToolTip(f"Filter by genre: {g}")
            chip.clicked.connect(lambda _checked, _g=g: self.genre_clicked.emit(_g))
            self._genres_layout.addWidget(chip)
        self._genres_container.updateGeometry()
        self._genres_container.show()


# ---------------------------------------------------------------------------
# _PlotSection
# ---------------------------------------------------------------------------

class _PlotSection(QWidget):
    """Overview header + plot text + loading indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_live: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = QLabel("<b>Overview</b>")
        layout.addWidget(self._header)

        self.plot_label = QLabel()
        self.plot_label.setWordWrap(True)
        self.plot_label.setTextFormat(Qt.TextFormat.PlainText)
        self.plot_label.setStyleSheet(_theme.DETAIL_TEXT)
        _no_width_force(self.plot_label)
        layout.addWidget(self.plot_label)

        self.plot_loading = QLabel("Loading description...")
        self.plot_loading.setStyleSheet(_theme.LOADING_TEXT)
        self.plot_loading.hide()
        layout.addWidget(self.plot_loading)

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

class _TechnicalSection(QWidget):
    """Collapsible Technical Details section."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._collapsed: bool = False
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        self._header_widget = QWidget()
        hdr = QHBoxLayout(self._header_widget)
        hdr.setContentsMargins(0, 5, 0, 5)
        self._toggle_btn = QPushButton(self.config.collapse_icon)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._toggle_btn)
        hdr.addWidget(QLabel("<b>Technical Details</b>"))
        hdr.addStretch()
        layout.addWidget(self._header_widget)

        # Content
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 0, 0, 0)
        self.tech_details_label = QLabel()
        self.tech_details_label.setWordWrap(True)
        self.tech_details_label.setTextFormat(Qt.TextFormat.RichText)
        self.tech_details_label.setStyleSheet(_theme.DETAIL_TEXT)
        _no_width_force(self.tech_details_label)
        content_layout.addWidget(self.tech_details_label)
        layout.addWidget(self._content)

    def restore_collapse_state(self, collapsed_sections: list[str]) -> None:
        self._collapsed = "technical" in collapsed_sections
        self._apply()

    def set_mode(self, is_live: bool) -> None:
        if is_live:
            self.hide()
        else:
            self._apply()

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

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._apply()

    def _apply(self) -> None:
        self._content.setVisible(not self._collapsed)
        self._toggle_btn.setText(
            self.config.expand_icon if self._collapsed else self.config.collapse_icon
        )

    def is_collapsed(self) -> bool:
        return self._collapsed

    def save_state(self, config) -> None:
        sections = set(config.details_pane_collapsed_sections)
        if self._collapsed:
            sections.add("technical")
        else:
            sections.discard("technical")
        config.details_pane_collapsed_sections = list(sections)
        config.save()


# ---------------------------------------------------------------------------
# _CastSection
# ---------------------------------------------------------------------------

class _CastSection(QWidget):
    """Collapsible Cast & Crew section."""

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

        self._header_widget = QWidget()
        hdr = QHBoxLayout(self._header_widget)
        hdr.setContentsMargins(0, 5, 0, 5)
        self._toggle_btn = QPushButton(self.config.collapse_icon)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._toggle_btn)
        hdr.addWidget(QLabel("<b>Cast & Crew</b>"))
        hdr.addStretch()
        layout.addWidget(self._header_widget)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(20, 0, 0, 0)
        content_layout.setSpacing(4)

        self._director_lbl = QLabel()
        self._director_lbl.setWordWrap(True)
        self._director_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._director_lbl.setStyleSheet(_theme.DETAIL_TEXT)
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
        self.cast_label.setStyleSheet(_theme.DETAIL_TEXT)
        self.cast_label.setOpenExternalLinks(False)
        self.cast_label.linkActivated.connect(
            lambda url: self.person_clicked.emit(url)
        )
        _no_width_force(self.cast_label)
        content_layout.addWidget(self.cast_label)
        layout.addWidget(self._content)

    def restore_collapse_state(self, collapsed_sections: list[str]) -> None:
        self._collapsed = "cast" in collapsed_sections
        self._apply()

    def set_mode(self, is_live: bool) -> None:
        self._is_live = is_live
        if not is_live:
            self._apply()
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

        # A director alone OR any cast is enough to show the section.
        self._has_content = bool(director) or bool(cast)
        self._apply_visibility()

    def clear(self) -> None:
        self._director_lbl.hide()
        self.cast_label.clear()
        self._has_content = False
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """Hide the whole Cast & Crew section (header + body) when live, or when
        there is no cast and no crew — so a credit-less title shows no empty box.
        Re-shown when a reused pane lands on a title that has people."""
        self.setVisible(not self._is_live and self._has_content)

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._apply()

    def _apply(self) -> None:
        self._content.setVisible(not self._collapsed)
        self._toggle_btn.setText(
            self.config.expand_icon if self._collapsed else self.config.collapse_icon
        )

    def is_collapsed(self) -> bool:
        return self._collapsed

    def save_state(self, config) -> None:
        sections = set(config.details_pane_collapsed_sections)
        if self._collapsed:
            sections.add("cast")
        else:
            sections.discard("cast")
        config.details_pane_collapsed_sections = list(sections)
        config.save()


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
}

# Confidence threshold below which a chip is styled as low-confidence.
_LOW_CONF_THRESHOLD: float = 0.5


class _TagsSection(QWidget):
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

    # (facet_type, value) — left-click: strict exact-tag context filter
    tag_filter_clicked = pyqtSignal(str, str)
    # (facet_type, value) — right-click: seed Discover/Recipe with this one tag
    tag_discover_clicked = pyqtSignal(str, str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._collapsed: bool = False
        self._setup()

    # ------------------------------------------------------------------ #
    # Setup                                                                #
    # ------------------------------------------------------------------ #

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Collapsible header
        self._header_widget = QWidget()
        hdr = QHBoxLayout(self._header_widget)
        hdr.setContentsMargins(0, 5, 0, 5)

        self._toggle_btn = QPushButton(_icons.collapse_icon)
        self._toggle_btn.setFixedSize(20, 20)
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._toggle_btn)
        hdr.addWidget(QLabel(f"<b>{_icons.tag_section_icon} Tags</b>"))
        hdr.addStretch()
        layout.addWidget(self._header_widget)

        # Scrollable content area — chips can wrap into many rows
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 0, 0, 6)
        self._content_layout.setSpacing(6)
        layout.addWidget(self._content)

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

        self._apply()
        self.show()

    def clear(self) -> None:
        """Clear all chips and hide the section."""
        self._clear_content()
        self.hide()

    def restore_collapse_state(self, collapsed_sections: list[str]) -> None:
        self._collapsed = "tags" in collapsed_sections
        self._apply()

    def save_state(self, config) -> None:
        sections = set(config.details_pane_collapsed_sections)
        if self._collapsed:
            sections.add("tags")
        else:
            sections.discard("tags")
        config.details_pane_collapsed_sections = list(sections)
        config.save()

    def is_collapsed(self) -> bool:
        return self._collapsed

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
        lbl.setStyleSheet(_theme.TAG_FACET_LABEL)
        self._content_layout.addWidget(lbl)

        # Chip row — wrapped with QHBoxLayout + stretch to left-align
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        for tag in tags:
            chip = self._make_chip(tag)
            row_layout.addWidget(chip)

        row_layout.addStretch()
        self._content_layout.addWidget(row)

    def _make_chip(self, tag) -> QPushButton:
        """Build a single QPushButton chip for a ChannelTagDTO."""
        # Provenance prefix: ■ = source-given, □ = inferred
        prov_icon = (
            _icons.tag_source_given_icon if tag.source_given
            else _icons.tag_inferred_icon
        )
        label = f"{prov_icon} {tag.value}"

        chip = QPushButton(label)
        chip.setFlat(True)
        chip.setFixedHeight(22)

        # Provenance style: source-given = solid border; inferred = dashed border.
        # Low-confidence = extra dimming on top of provenance style.
        if tag.source_given:
            chip.setStyleSheet(_theme.TAG_CHIP_SOURCE)
        else:
            chip.setStyleSheet(_theme.TAG_CHIP_INFERRED)

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
            f"{tag.facet_type}: {tag.value}\n"
            f"Provenance: {prov_label}\n"
            f"Feeder(s): {feeder_str}\n"
            f"Confidence: {conf_pct}%{conf_note}\n"
            f"{action_hint}"
        )

        return chip

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._apply()

    def _apply(self) -> None:
        self._content.setVisible(not self._collapsed)
        self._toggle_btn.setText(
            _icons.expand_icon if self._collapsed else _icons.collapse_icon
        )
