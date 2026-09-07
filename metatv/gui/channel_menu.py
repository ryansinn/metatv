"""Unified channel context-menu registry and composer for MetaTV.

All channel context menus in the MainWindow family are built through
``build_channel_menu``.  A registry of ``ChannelAction`` objects plus
per-surface ``SURFACE_LAYOUTS`` define what actions appear and in what order.
The composer handles separator hygiene (no leading / trailing / doubled seps).

Usage::

    from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu

    ctx = ChannelMenuContext(channel_ids=[channel_id], surface="channel", ...)
    handlers = {"play": lambda: play_channel_by_id(cid), ...}
    menu = build_channel_menu(ctx, handlers, parent=self)
    menu.exec(QPoint(gx, gy))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

if TYPE_CHECKING:                                    # pragma: no cover
    from datetime import datetime

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.channel_menu_layouts import SURFACE_LAYOUTS

__all__ = [
    "ChannelMenuContext",
    "ChannelAction",
    "ACTIONS",
    "SURFACE_LAYOUTS",
    "build_channel_menu",
]


# ---------------------------------------------------------------------------
# Context dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChannelMenuContext:
    """All state needed to build a channel context menu.

    Populated in two passes:
    * DB pass (off-thread): channel fields, queue/rating DB lookups.
    * Main-thread pass: config-derived fields (is_watched, has_unavailable).
    """

    channel_ids: list[str]
    surface: str  # "channel"|"history"|"favorites"|"queue"|"recommended"|"alerts"|"retry"
    media_type: str = ""
    is_favorite: bool = False
    in_queue: bool = False
    rating: int = 0
    is_hidden: bool = False
    is_watched: bool = False          # channel_id in config.epg_watchlist_channels
    epg_link_blocked: bool = False    # channel_id in config.epg_link_blocklist (EPG "Clear link")
    is_vod_watched: bool = False      # channel.watch_completed (VOD manual-watched state)
    is_series_monitored: bool = False  # channel_id in config.monitored_series
    # UNVIEWED match — a VOD watch-for keyword match on most surfaces; on
    # "alerts_series" the same flag carries a monitored series' own unseen-episode
    # state (the two never render in the same menu, so one field serves both).
    has_unviewed_match: bool = False
    has_unavailable: bool = False     # favorites/queue Clear-Unavailable enablement
    channel_name: str = ""
    user_category: str | None = None
    entry_id: str = ""                # retry surface: identifies the StreamRetryEntry
    channel_found: bool = True        # retry surface: False when lookup returned None
    watch_progress: int = 0           # saved resume position in seconds (0 = unwatched/completed)
    watch_completed: bool = False     # True when VOD has been watched to completion
    playback_resume_mode: str = "resume"  # mirrors config.playback_resume_mode at menu-build time
    # Stored detected_title, read straight off ChannelDB — NEVER re-derived via
    # parse_channel_name() here (CLAUDE.md). Empty when unset; use `title`.
    detected_title: str = ""
    # Cross-source identity key (ChannelDB.content_key). "" when unset.
    content_key: str = ""
    # Sibling count for this content_key group (>=1; 1 = no other versions),
    # so "Show N versions" only appears when there is something to show.
    variant_count: int = 1
    # (quality, language, source) options for the "Show N versions" picker —
    # each dict a row from get_content_key_siblings, fetched alongside the
    # rest of the DB-pass context so the picker needs no second round trip.
    variant_options: list = field(default_factory=list)
    # REC-3: the EPG programme this row represents (alerts/On Now/Browse),
    # else None/"" — what "record_programme"'s applies= predicate gates on.
    programme_start: "datetime | None" = None
    programme_end: "datetime | None" = None
    programme_title: str = ""
    # "versions" surface (details-pane per-version chip menu): the variant's own
    # region/prefix code, read by the play/show_details label hooks, and whether
    # ITS source is inactive (gates reactivate_play / disables play).
    version_prefix: str = ""
    source_inactive: bool = False
    # Disabled first action, rendered by build_channel_menu when non-empty — the
    # ONE header mechanism (never a second): "versions" uses it for the picked
    # variant's region/source name.
    header: str = ""

    @property
    def is_single(self) -> bool:
        return len(self.channel_ids) == 1

    @property
    def title(self) -> str:
        """The clean title for title-based actions (search / copy).

        One definition shared by every title action, so they never disagree:
        the stored ``detected_title``, falling back to the raw channel name.
        """
        return (self.detected_title or self.channel_name or "").strip()

    @property
    def is_multi(self) -> bool:
        return len(self.channel_ids) > 1

    @property
    def channel_id(self) -> str | None:
        return self.channel_ids[0] if self.channel_ids else None


# ---------------------------------------------------------------------------
# Action dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChannelAction:
    """Definition of one context-menu action."""

    id: str
    label: Callable[[ChannelMenuContext], str]
    icon: str = ""                                         # icons.py value or ""
    tooltip: "str | Callable[[ChannelMenuContext], str]" = ""
    checkable: bool = False
    checked: Callable[[ChannelMenuContext], bool] = field(
        default_factory=lambda: (lambda c: False)
    )
    applies: Callable[[ChannelMenuContext], bool] = field(
        default_factory=lambda: (lambda c: True)
    )
    enabled: Callable[[ChannelMenuContext], bool] = field(
        default_factory=lambda: (lambda c: True)
    )
    disabled_tooltip: str = ""
    # Dynamic glyph overriding ``icon`` (e.g. favorite flips on ``is_favorite``).
    icon_fn: "Callable[[ChannelMenuContext], str] | None" = None
    # Dynamic icon colour (theme token, or None for muted/gray) — only the
    # resume affordance returns the orange accent.
    icon_color: "Callable[[ChannelMenuContext], str | None] | None" = None


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------

def _fav_label(c: ChannelMenuContext) -> str:
    return "Remove from Favorites" if c.is_favorite else "Add to Favorites"


def _fav_icon(c: ChannelMenuContext) -> str:
    return _icons.unfavorite_icon if c.is_favorite else _icons.favorite_icon


def _queue_label(c: ChannelMenuContext) -> str:
    # "Watch Later" is the standardized user-facing verb for the watch-queue action
    # (the sidebar COLLECTION stays "Watch Queue"); the DB/vars keep the queue names.
    return "Remove from Watch Later" if c.in_queue else "Add to Watch Later"


def _watch_label(c: ChannelMenuContext) -> str:
    return "Stop watching this channel" if c.is_watched else "Watch this channel (EPG alerts)"


def _clear_epg_link_label(c: ChannelMenuContext) -> str:
    """Toggles between clearing a good link and re-allowing a blocked one."""
    return "Re-link EPG data" if c.epg_link_blocked else "Clear EPG link"


def _clear_epg_link_tooltip(c: ChannelMenuContext) -> str:
    return (
        "Remove this channel from the EPG block list — the next relink pass will re-match it"
        if c.epg_link_blocked
        else "Unlink this channel's guide data and stop future auto-matching (fixes wrong EPG data)"
    )


def _browse_series_label(c: ChannelMenuContext) -> str:
    # "alerts_series" (the monitored-series row itself) names the verb the row's
    # OWN menu used pre-registry ("Open series"); every other surface keeps
    # "Browse the series" (test_sidebar_followups.py calls this directly).
    return "Open series" if c.surface == "alerts_series" else "Browse the series"


def _monitor_label(c: ChannelMenuContext) -> str:
    if not c.is_series_monitored:
        return "Alert me to new episodes"
    # "alerts_series" (the monitored-series row itself) names the verb the row's
    # OWN menu used pre-registry ("Stop alerts"); every other surface keeps the
    # fuller "Stop new-episode alerts" (test_series_monitor.py pins that text).
    return "Stop alerts" if c.surface == "alerts_series" else "Stop new-episode alerts"


def _mark_watched_label(c: ChannelMenuContext) -> str:
    return "Mark as Unwatched" if c.is_vod_watched else "Mark as Watched"


def _category_label(c: ChannelMenuContext) -> str:
    if c.user_category:
        return f"Category: {c.user_category}  (change…)"
    return "Add to Category…"


def _fmt_seconds(seconds: int) -> str:
    """Format seconds as M:SS for use in resume labels."""
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _resume_from_label(c: ChannelMenuContext) -> str:
    return f"Resume from {_fmt_seconds(c.watch_progress)}"


def _is_resumable_vod(c: ChannelMenuContext) -> bool:
    """True when the item is a non-live VOD with saved, incomplete progress."""
    return (
        c.is_single
        and c.channel_found
        and not c.is_hidden
        and c.media_type in ("movie",)
        and c.watch_progress > 0
        and not c.watch_completed
    )


def _play_resumes_by_default(c: ChannelMenuContext) -> bool:
    """True when triggering the default Play would resume from the saved position.

    This is the resume affordance the menu paints orange: a resumable VOD while
    the resume-by-default mode is active.  In 'beginning' mode the default Play
    starts from zero instead, so a separate orange ``resume_from`` action carries
    the resume cue and Play stays neutral/gray.
    """
    return _is_resumable_vod(c) and c.playback_resume_mode != "beginning"


def _play_label(c: ChannelMenuContext) -> str:
    """Default Play label — 'Play from M:SS' when it would resume, else 'Play'.

    "versions" (details-pane per-version chip menu) names the specific variant
    instead — extended here rather than a sibling action, since resume semantics
    are meaningless for a variant picker (watch_progress is never set there).
    """
    if c.surface == "versions":
        return f"Play {c.version_prefix} version"
    if _play_resumes_by_default(c):
        return f"Play from {_fmt_seconds(c.watch_progress)}"
    return "Play"


def _play_color(c: ChannelMenuContext) -> str | None:
    """Orange resume accent when Play would resume; otherwise the default gray."""
    return _theme.COLOR_PLAYBACK_IN_PROGRESS if _play_resumes_by_default(c) else None


def _resume_color(c: ChannelMenuContext) -> str:
    """The explicit resume affordance is always the orange in-progress accent."""
    return _theme.COLOR_PLAYBACK_IN_PROGRESS


def _bulk_category_label(c: ChannelMenuContext) -> str:
    n = len(c.channel_ids)
    s = "s" if n != 1 else ""
    return f"Add {n:,} selected channel{s} to Category…"


ACTIONS: dict[str, ChannelAction] = {
    # ── Core ────────────────────────────────────────────────────────────────
    "play": ChannelAction(
        id="play",
        label=_play_label,
        icon=_icons.play_icon,
        icon_color=_play_color,
        tooltip="Play this channel",
        # source_inactive defaults False everywhere except "versions", so this
        # is a no-op on every other surface.
        applies=lambda c: c.is_single and c.channel_found and not c.source_inactive,
    ),
    "play_new_window": ChannelAction(
        id="play_new_window",
        label=lambda c: "Play in New Window",
        icon=_icons.new_window_icon,
        tooltip="Open in a separate player window (per-source)",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "play_open_ended_buffer": ChannelAction(
        id="play_open_ended_buffer",
        label=lambda c: "Play with open-ended buffer",
        icon=_icons.open_ended_buffer_icon,
        tooltip=(
            "Buffer ahead open-endedly — caches as far as the stream allows "
            "(disk-backed, up to 2 GiB). Useful for riding out an unstable stream."
        ),
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "play_deep_cache": ChannelAction(
        id="play_deep_cache",
        label=lambda c: "Buffer without limit (pre-load fully)",
        icon=_icons.deep_cache_icon,
        tooltip=(
            "Pre-load this title fully to a scratch cache before/while playing — goes "
            "further than the open-ended buffer by recording to disk. VOD only; the "
            "recording is temporary and discarded when playback stops."
        ),
        # VOD-only (movie/series) — live channels have no fixed end to pre-load to,
        # so this action is never shown for them (same predicate as like/dislike).
        applies=lambda c: c.is_single and c.channel_found and c.media_type in ("movie", "series"),
    ),
    "download": ChannelAction(
        id="download",
        label=lambda c: "Download to library",
        icon=_icons.download_icon,
        tooltip=(
            "Save this title to your library folder so it plays without the source. "
            "Resumes if interrupted, and pauses while you watch anything on this source."
        ),
        # VOD-only — a live channel has no end to download TO; it records
        # instead (below), a different feature with a different priority rule.
        applies=lambda c: c.is_single and c.channel_found and c.media_type in ("movie", "series"),
    ),
    "record": ChannelAction(
        id="record",
        label=lambda c: "Record what's on",
        icon=_icons.record_icon,
        tooltip=(
            "Record this channel to your library. Keeps recording if you start "
            "watching something else, and waits rather than giving up if busy."
        ),
        # Inverse of "download" (a VOD has an end, a live channel a clock). A row
        # that carries its programme window offers record_programme instead.
        applies=lambda c: (
            c.is_single and c.channel_found and c.media_type == "live"
            and c.programme_start is None
        ),
    ),
    # Option B: a picked window, no guide data — "record" minus its gate clause.
    "record_window": ChannelAction(
        id="record_window",
        label=lambda c: "Record for a time window…",
        icon=_icons.record_window_icon,
        tooltip="Record a start/end window you set — no guide needed. MetaTV must stay open.",
        applies=lambda c: c.is_single and c.channel_found and c.media_type == "live",
    ),
    # REC-3: THIS row's start/stop, not "now" — so a future Browse row works too.
    "record_programme": ChannelAction(
        id="record_programme",
        label=lambda c: "Record this programme",
        icon=_icons.record_icon,
        tooltip=(
            "Schedule a recording for this programme's guide window, padded by your "
            "Settings → Recording defaults; a clash on this source is caught now."
        ),
        applies=lambda c: (
            c.is_single and c.channel_found and c.media_type == "live"
            and c.programme_start is not None and c.programme_end is not None
        ),
    ),
    # ── Resume-position overrides ────────────────────────────────────────────
    "play_from_beginning": ChannelAction(
        id="play_from_beginning",
        label=lambda c: "Play from Beginning",
        icon=_icons.play_from_beginning_icon,
        tooltip=(
            "Start playback from the beginning, ignoring the saved resume position.\n"
            "Your resume position is preserved — this is a one-time override."
        ),
        # Only meaningful when the default Play WOULD resume — the exact mirror
        # of resume_from (beginning-mode only, else a redundant second ▶).
        applies=_play_resumes_by_default,
    ),
    "resume_from": ChannelAction(
        id="resume_from",
        label=_resume_from_label,
        icon=_icons.resume_from_icon,
        icon_color=_resume_color,
        tooltip=(
            "Resume from your saved position — overrides the 'Start from beginning' default\n"
            "for this one play."
        ),
        applies=lambda c: (
            _is_resumable_vod(c)
            and c.playback_resume_mode == "beginning"
        ),
    ),
    # ── "versions" surface (details-pane per-version chip menu) ────────────
    # reactivate_play mirrors play (mutually exclusive via source_inactive), so
    # they never render together — order matters here for the inactive branch.
    "reactivate_play": ChannelAction(
        id="reactivate_play",
        label=lambda c: "Reactivate source & play",
        icon=_icons.play_icon,
        tooltip=lambda c: f"Re-enable {c.version_prefix or 'this source'} and play this variant",
        applies=lambda c: c.source_inactive,
    ),
    "show_details": ChannelAction(
        id="show_details",
        label=lambda c: f"Show details for {c.version_prefix} version",
        icon=_icons.info_icon,
        tooltip=lambda c: c.channel_name or "",
        applies=lambda c: True,
    ),
    "favorite": ChannelAction(
        id="favorite",
        label=_fav_label,
        icon_fn=_fav_icon,   # ★ / ☆ flips on is_favorite (resolved in _resolve_menu_icon)
        tooltip="Toggle this channel in your Favorites sidebar",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "queue": ChannelAction(
        id="queue",
        label=_queue_label,
        icon=_icons.queue_icon,
        tooltip="Toggle this channel in your Watch Queue",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "like": ChannelAction(
        id="like",
        label=lambda c: "Like",
        icon=_icons.like_icon,
        tooltip="Rate this title positively",
        checkable=True,
        checked=lambda c: c.rating == 1,
        applies=lambda c: c.is_single and c.channel_found and c.media_type in ("movie", "series"),
    ),
    "dislike": ChannelAction(
        id="dislike",
        label=lambda c: "Dislike",
        icon=_icons.dislike_icon,
        tooltip="Rate this title negatively",
        checkable=True,
        checked=lambda c: c.rating == -1,
        applies=lambda c: c.is_single and c.channel_found and c.media_type in ("movie", "series"),
    ),
    # ── Title actions ────────────────────────────────────────────────────────
    # Both read ctx.title (detected_title, falling back to the raw name); hidden
    # when unresolvable — an action that would search/copy "" is noise.
    "search_title": ChannelAction(
        id="search_title",
        label=lambda c: "Search this title",
        icon=_icons.search_icon,
        tooltip="Find every version of this title in the channel list",
        applies=lambda c: c.is_single and c.channel_found and bool(c.title),
    ),
    "copy_title": ChannelAction(
        id="copy_title",
        label=lambda c: "Copy title",
        icon=_icons.copy_icon,
        tooltip="Copy this title to the clipboard",
        applies=lambda c: c.is_single and c.channel_found and bool(c.title),
    ),
    # ── Collapsed-row variant picker ────────────────────────────────────────
    # Only appears on a row that IS a collapsed content_key representative with
    # other variants (Settings → Interface → "Collapse quality/language
    # versions"); variant_count is 1 (default) everywhere else, so this action
    # is invisible when the setting is off. Opens a menu of the sibling
    # (quality, language, source) options fetched alongside the rest of the
    # menu context — see ChannelMenuContext.variant_options.
    "show_versions": ChannelAction(
        id="show_versions",
        label=lambda c: f"Show {c.variant_count} versions",
        icon=_icons.versions_icon,
        tooltip="Pick a specific quality/language/source version of this title",
        applies=lambda c: c.is_single and c.channel_found and c.variant_count > 1,
    ),
    # A DIFFERENT grouping than show_versions above: this one governs whether the
    # recommendation engine's own cross-source dedup (rec_dedupe_overrides,
    # preference_engine.build_dedup_key — a temporary title-heuristic, distinct
    # from the content_key siblings show_versions reads) folds this title into a
    # sibling's row. Reuses ctx.variant_count (the content_key count) as the
    # gate/label rather than threading a second count through the context —
    # see docs/REFACTOR_PLAN.md's duplication ledger for the two counts' delta.
    "show_separately": ChannelAction(
        id="show_separately",
        label=lambda c: f"Show {c.variant_count} versions separately",
        icon=_icons.show_separately_icon,
        tooltip="Show this title as its own row instead of grouped with its other versions",
        applies=lambda c: c.is_single and c.channel_found and c.variant_count > 1,
    ),
    # ── The series itself ───────────────────────────────────────────────────
    # Beside monitor_series rather than up with the play actions: both are
    # about the SERIES, while everything above concerns this one episode. The
    # owner spotted the grouping already half-present — "like and dislike
    # options ... apply to the series, not the episode, so maybe the browse
    # series menu option should be bundled near them" — and judgment is indeed
    # title-level (see CLAUDE.md, "Judgment applies to the title").
    "browse_series": ChannelAction(
        id="browse_series",
        # Was a bare string, not a callable — build_channel_menu's unconditional
        # ``action_def.label(ctx)`` raised TypeError the moment a real handler
        # was provided (every production surface via _build_handlers), so this
        # action has never actually rendered where it applies. Found migrating
        # "alerts_series" onto it (MENU-1); see docs/REFACTOR_PLAN.md.
        label=_browse_series_label,
        icon=_icons.series_icon,
        tooltip="Open every season and episode of this series",
        applies=lambda c: (
            c.is_single and c.channel_found
            and not c.is_hidden
            and c.media_type == "series"
        ),
    ),
    "monitor_series": ChannelAction(
        id="monitor_series",
        label=_monitor_label,
        icon=_icons.alert_icon,
        tooltip="Alert me when this series has new episodes",
        applies=lambda c: (
            c.is_single and c.channel_found
            and not c.is_hidden
            and c.media_type == "series"
        ),
    ),
    # ── Alert visibility ────────────────────────────────────────────────────
    # Shown ONLY for an unviewed watch-for match. Acknowledges it (viewed →
    # green-off everywhere) — never removes from the queue or marks watched.
    "clear_alert": ChannelAction(
        id="clear_alert",
        label=lambda c: "Clear alert — I've seen this",
        icon=_icons.new_match_icon,
        tooltip="Acknowledge this new match — clears the alert highlight everywhere",
        applies=lambda c: c.is_single and c.has_unviewed_match,
    ),
    # "alerts" surface only — a keyword-rule row (config aggregate, no channel_id)
    # reuses this same surface for its own two verbs; sites without a handler
    # simply never render it (registry skip-if-absent).
    "view_matches": ChannelAction(
        id="view_matches",
        label=lambda c: "View matches",
        icon=_icons.search_icon,
        tooltip="Show this alert's matched content in the main list",
        applies=lambda c: True,
    ),
    # "alerts_series" surface: a monitored series' own new-episode count — see
    # has_unviewed_match's dual-meaning comment above.
    "mark_seen": ChannelAction(
        id="mark_seen",
        label=lambda c: "Mark seen",
        icon=_icons.watched_icon,
        tooltip="Clear the new-episode count for this series",
        applies=lambda c: c.has_unviewed_match,
    ),
    # "alerts_series" surface-level admin action ("Manage watch alerts…").
    "manage_alerts": ChannelAction(
        id="manage_alerts",
        label=lambda c: "Manage…",
        icon=_icons.manage_icon,
        tooltip="Manage watch alerts — keyword rules and monitored series",
        applies=lambda c: True,
    ),
    # ── VOD mark watched ────────────────────────────────────────────────────
    "mark_watched": ChannelAction(
        id="mark_watched",
        label=_mark_watched_label,
        icon=_icons.watched_icon,
        tooltip="Mark this movie or series as watched / unwatched",
        applies=lambda c: (
            c.is_single and c.channel_found
            and not c.is_hidden
            and c.media_type in ("movie", "series")
        ),
    ),
    # ── Channel extras ──────────────────────────────────────────────────────
    "watch": ChannelAction(
        id="watch",
        label=_watch_label,
        icon="",
        tooltip="Toggle EPG watchlist alerts for this channel",
        applies=lambda c: c.is_single and c.channel_found and not c.is_hidden,
    ),
    "track": ChannelAction(
        id="track",
        label=lambda c: "Track keyword…",
        icon="",
        tooltip="Add a keyword pattern to your EPG watchlist",
        applies=lambda c: c.is_single and c.channel_found and not c.is_hidden,
    ),
    "unhide": ChannelAction(
        id="unhide",
        label=lambda c: "Unhide",
        icon=_icons.hide_icon,
        tooltip="Un-hide this channel so it appears in the channel list",
        applies=lambda c: c.is_single and c.channel_found and c.is_hidden,
    ),
    "hide": ChannelAction(
        id="hide",
        label=lambda c: "Hide",
        icon=_icons.hide_icon,
        tooltip="Hide this channel from the channel list",
        applies=lambda c: c.is_single and c.channel_found and not c.is_hidden,
    ),
    "category": ChannelAction(
        id="category",
        label=_category_label,
        icon=_icons.category_icon,
        tooltip=(
            "Assign this channel to a user-defined category.\n"
            "Categories appear as shelves in the Discover view."
        ),
        applies=lambda c: c.is_single and c.channel_found,
    ),
    # ── History extras ──────────────────────────────────────────────────────
    "remove_history": ChannelAction(
        id="remove_history",
        label=lambda c: "Remove from History",
        icon=_icons.delete_icon,
        tooltip="Remove this entry from your playback history",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    # ── Favorites extras ────────────────────────────────────────────────────
    "clear_unavailable": ChannelAction(
        id="clear_unavailable",
        label=lambda c: "Clear Unavailable",
        icon="",
        tooltip="Remove all unavailable items",
        applies=lambda c: True,  # always shown; disabled when none
        enabled=lambda c: c.has_unavailable,
        disabled_tooltip="No unavailable content",
    ),
    # ── Recommended extras ──────────────────────────────────────────────────
    "not_interested": ChannelAction(
        id="not_interested",
        label=lambda c: "Not Interested",
        icon=_icons.not_interested_icon,
        tooltip="Suppress this title from recommendations",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    # ── Retry extras ────────────────────────────────────────────────────────
    "remove_retry": ChannelAction(
        id="remove_retry",
        label=lambda c: "Remove from Stream Monitoring",
        icon=_icons.close_icon,
        tooltip="Stop monitoring this stream for reconnection",
        applies=lambda c: True,
    ),
    "clear_retry": ChannelAction(
        id="clear_retry",
        label=lambda c: "Clear all from Stream Monitoring",
        icon="",
        tooltip="Remove all entries from the Stream Monitoring list",
        applies=lambda c: True,
    ),
    # ── EPG extras ──────────────────────────────────────────────────────────
    "epg_watch": ChannelAction(
        id="epg_watch",
        label=lambda c: (
            "Watch this channel (EPG alerts)" if c.is_single
            else "Watch channels…"
        ),
        icon=_icons.watchlist_on_icon,
        tooltip="Add this channel to your EPG watchlist for alerts",
        applies=lambda c: True,
    ),
    "epg_unwatch": ChannelAction(
        id="epg_unwatch",
        label=lambda c: (
            "Stop watching this channel" if c.is_single
            else "Unwatch channels…"
        ),
        icon=_icons.watchlist_off_icon,
        tooltip="Remove this channel from your EPG watchlist",
        applies=lambda c: True,
    ),
    "epg_track_show": ChannelAction(
        id="epg_track_show",
        label=lambda c: "Track show…" if c.is_single else "Track shows…",
        icon=_icons.watchlist_icon,
        tooltip="Add the current show title as a watchlist pattern",
        applies=lambda c: True,
    ),
    "epg_assign_category": ChannelAction(
        id="epg_assign_category",
        label=lambda c: "Assign category…",
        icon=_icons.category_icon,
        tooltip=(
            "Assign this channel to a user-defined EPG category.\n"
            "Categories appear as shelves in the On Now view."
        ),
        applies=lambda c: True,
    ),
    "epg_remove_override": ChannelAction(
        id="epg_remove_override",
        label=lambda c: "Remove category override",
        icon="",
        tooltip="Remove the manually-assigned category override for this channel",
        applies=lambda c: True,
    ),
    "epg_hide_channel": ChannelAction(
        id="epg_hide_channel",
        label=lambda c: (
            "Hide channel" if c.is_single else "Hide channels…"
        ),
        icon=_icons.hide_icon,
        tooltip="Hide this channel from the EPG On Now view",
        applies=lambda c: True,
    ),
    "epg_hide_show": ChannelAction(
        id="epg_hide_show",
        label=lambda c: (
            "Hide show" if c.is_single else "Hide shows…"
        ),
        icon=_icons.hide_icon,
        tooltip="Hide this show title from the EPG On Now view",
        applies=lambda c: True,
    ),
    "clear_epg_link": ChannelAction(
        id="clear_epg_link",
        label=_clear_epg_link_label,
        icon=_icons.clear_epg_link_icon,
        tooltip=_clear_epg_link_tooltip,
        # Live channels only — VOD has no XMLTV guide to (mis)link. Single-select
        # only (the toggle label/behavior depends on ONE channel's blocked state).
        applies=lambda c: c.is_single and c.media_type == "live",
    ),
    # ── Multi-select play ───────────────────────────────────────────────────
    "play_all": ChannelAction(
        id="play_all",
        label=lambda c: f"Play All ({len(c.channel_ids)})",
        icon=_icons.play_all_icon,
        tooltip="Play first selected item, queue the rest in selection order",
        applies=lambda c: c.is_multi,
    ),
    # ── Multi-select (channel surface only) ─────────────────────────────────
    "quickpick_trash": ChannelAction(
        id="quickpick_trash",
        label=lambda c: "Trash",
        icon=_icons.delete_icon,
        tooltip="Assign to Trash — Dislike mood, added to Global Exclusions",
        applies=lambda c: c.is_multi,
    ),
    "quickpick_watch_later": ChannelAction(
        id="quickpick_watch_later",
        label=lambda c: "Watch Later",
        icon=_icons.watch_later_icon,
        tooltip="Assign to Watch Later — Neutral mood",
        applies=lambda c: c.is_multi,
    ),
    "quickpick_explore": ChannelAction(
        id="quickpick_explore",
        label=lambda c: "Explore",
        icon=_icons.curious_icon,
        tooltip="Assign to Explore — Curious mood, surfaces more like this",
        applies=lambda c: c.is_multi,
    ),
    "bulk_category": ChannelAction(
        id="bulk_category",
        label=_bulk_category_label,
        icon=_icons.category_icon,
        tooltip="Assign a user-defined category to the selected channels",
        applies=lambda c: c.is_multi,
    ),
    # ── Multi-select bulk actions ────────────────────────────────────────────
    "bulk_favorite": ChannelAction(
        id="bulk_favorite",
        label=lambda c: "Add to Favorites",
        icon=_icons.favorite_icon,
        tooltip="Add all selected channels to Favorites",
        applies=lambda c: c.is_multi,
    ),
    "bulk_queue": ChannelAction(
        id="bulk_queue",
        label=lambda c: "Add to Watch Later",
        icon=_icons.queue_icon,
        tooltip="Add all selected channels to the Watch Queue",
        applies=lambda c: c.is_multi,
    ),
    "bulk_mark_watched": ChannelAction(
        id="bulk_mark_watched",
        label=_mark_watched_label,
        icon=_icons.watched_icon,
        tooltip=lambda c: (
            "Mark all selected as unwatched"
            if c.is_vod_watched
            else "Mark all selected movies/series as watched"
        ),
        applies=lambda c: c.is_multi,
    ),
    "bulk_hide": ChannelAction(
        id="bulk_hide",
        label=lambda c: "Hide Selected",
        icon=_icons.hide_icon,
        tooltip="Hide all selected channels from the channel list",
        applies=lambda c: c.is_multi,
    ),
}


# ---------------------------------------------------------------------------
# Icon resolution
# ---------------------------------------------------------------------------

def _resolve_menu_icon(
    action: ChannelAction, ctx: ChannelMenuContext
) -> tuple[str, str | None]:
    """Resolve the (glyph, colour-token) a menu action renders in *ctx*.

    Single source of truth shared by :func:`build_channel_menu` and the icon
    tests — so the menu and its assertions can never drift:

    * glyph — ``action.icon_fn(ctx)`` when set (dynamic, e.g. favorite flips on
      ``is_favorite``), else the static ``action.icon``.  ``""`` means no icon.
    * colour — ``action.icon_color(ctx)`` when set, else ``None`` (the default
      muted/gray).  Only the resume affordance returns the orange accent, keeping
      the menu monotone with a single colour cue.

    Args:
        action: The registry action definition.
        ctx: The menu context.

    Returns:
        ``(glyph, colour_token_or_None)``.
    """
    glyph = action.icon_fn(ctx) if action.icon_fn else action.icon
    color = action.icon_color(ctx) if (glyph and action.icon_color) else None
    return glyph, color


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

def build_channel_menu(
    ctx: ChannelMenuContext,
    handlers: dict[str, Callable[[], None]],
    parent=None,
) -> QMenu:
    """Build and return a QMenu for *ctx* using *handlers*.

    Args:
        ctx: Populated ``ChannelMenuContext`` describing the target channel(s)
            and surface.
        handlers: Mapping from action id → zero-argument callable.  Actions
            whose id is NOT in this dict are silently skipped.
        parent: Qt parent widget for the ``QMenu``.

    Returns:
        A ``QMenu`` ready to ``.exec()``.  The caller is responsible for
        positioning and executing it.

    Separator hygiene:
        * A separator is emitted only when at least one real action has already
          been added AND at least one more real action will follow.
        * This eliminates leading, trailing, and doubled separators regardless
          of which actions are skipped due to ``applies`` / handler absence.

    Header:
        ``ctx.header``, when non-empty, renders as a disabled first action
        (identifies WHICH variant/rule this menu is for) followed by a
        separator — the one header mechanism every surface shares.
    """
    layout = SURFACE_LAYOUTS.get(ctx.surface, [])
    menu = QMenu(parent)

    if ctx.header:
        header_act = QAction(ctx.header, menu)
        header_act.setEnabled(False)
        menu.addAction(header_act)
        menu.addSeparator()

    pending_sep = False   # a "sep" token was seen but not yet emitted
    added_any = False     # at least one real QAction has been added

    for token in layout:
        if token == "sep":
            if added_any:
                pending_sep = True
            continue

        action_def = ACTIONS.get(token)
        if action_def is None:
            continue
        if not action_def.applies(ctx):
            continue
        if token not in handlers:
            continue

        # Emit the pending separator now that we know a real action follows.
        if pending_sep:
            menu.addSeparator()
            pending_sep = False

        # Parent the QAction to the menu (not to parent widget) so Qt owns
        # the object and it is not garbage-collected while the menu is open.
        label_text = action_def.label(ctx)
        act = QAction(label_text, menu)
        tooltip_text = (
            action_def.tooltip(ctx)
            if callable(action_def.tooltip)
            else action_def.tooltip
        )
        act.setToolTip(tooltip_text)

        # QAction.setIcon() reserves a uniform icon column: frequent actions
        # get a rendered glyph (monochrome, gray except orange resume), rare/
        # admin rows get none — the blank column signals a different tier.
        glyph, glyph_color = _resolve_menu_icon(action_def, ctx)
        if glyph:
            act.setIcon(_icons.glyph_icon(glyph, glyph_color))

        if action_def.checkable:
            act.setCheckable(True)
            act.setChecked(action_def.checked(ctx))

        is_enabled = action_def.enabled(ctx)
        act.setEnabled(is_enabled)
        if not is_enabled and action_def.disabled_tooltip:
            act.setToolTip(action_def.disabled_tooltip)

        handler = handlers[token]
        # Absorb optional checkable bool so handlers are uniformly no-arg.
        act.triggered.connect(lambda *_a, h=handler: h())

        menu.addAction(act)
        added_any = True

    return menu
