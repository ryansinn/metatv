"""Shared Qt stylesheet tokens and constants.

Two layers — keep them separate:

1. **Design tokens** (``COLOR_*``, ``FONT_*``, ``OVERLAY_*``) — the *only* place raw
   palette values (hex, rgba, px) are allowed to live. They describe the design scale,
   so token names may be appearance-based (``FONT_MD``, ``COLOR_MUTED``).

2. **Semantic constants** — full stylesheet strings composed *from tokens*, named by the
   **role** they play in the UI (``STATUS_OK``, ``SECTION_HINT``, ``LOADING_TEXT``), never
   by their appearance (no ``TEXT_SM`` / ``GREY_11``). A role name localizes intent and
   prevents two unrelated widgets from accidentally coupling to the same literal.

Rules (also in CLAUDE.md; rationale in docs/UI_UX_GUIDELINES.md → "Theming & style tokens"):
- Never hardcode a hex/rgba/px literal in widget code *or* in a new semantic constant.
  Reuse a token, or add one here, then compose.
- Any stylesheet string used by more than one widget must be a named, role-based constant
  here. A genuinely single-use style may stay inline, but should still build from tokens.
- Dynamic styles (color chosen at runtime) compose a token into an f-string at the call
  site — that is fine; the literal still comes from a token.

Named palettes (wave7/theme-system): design-token VALUES live in
``theme_palettes.py`` (``MIDNIGHT``/``GRAPHITE``/``DAYLIGHT``), not as literals in
this file — every token NAME below stays a stable module-level global (hundreds of
consumers do ``from metatv.gui import theme as _theme`` and read ``_theme.COLOR_X``
at call time), only its bound VALUE changes per palette. :func:`apply_theme` swaps
the active palette by rebinding every token global AND recomposing every semantic
constant below it (:func:`_build_semantic_constants`) — see both docstrings for why
the semantic-constant rebuild step exists. Switching the palette does not, by
itself, repaint anything already on screen; see ``MainWindow.refresh_theme()``.

QPalette floor (#253): ``MainWindow.refresh_theme()``'s sweep only reaches
widgets it (or a widget-owned ``refresh_theme()``) explicitly re-styles — a
widget built with NO stylesheet at all (e.g. a bare ``QLabel``/``QStatusBar``)
instead falls back to Qt's built-in default palette, which is light regardless
of the active app theme. :func:`qt_palette` builds a ``QPalette`` from the
CURRENTLY ACTIVE tokens; :func:`apply_theme` pushes it onto the whole
``QApplication`` so every unstyled widget inherits correct theme colors
automatically, live, with no enumeration required. This is a FLOOR beneath the
semantic-constant sweep, not a replacement for it — an explicitly styled
widget still needs its cached stylesheet re-applied to pick up new token
values (``setStyleSheet()`` bakes a string, it doesn't track the token live).
"""

from __future__ import annotations

import weakref

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

from metatv.gui import theme_palettes


def zoomed_font(token: str, zoom: float, *, bold: bool = False) -> QFont:
    """Return a QFont whose pixel size is the token's px value scaled by *zoom*.

    The token must be one of the ``FONT_*`` constants defined below (e.g.
    ``FONT_MD = "11px"``).  This is the sanctioned way to scale fonts by the
    Discover zoom level without violating the "no inline px literals" rule —
    the token remains the base/source-of-truth; zoom is a user transform
    applied via QFont (not a stray stylesheet literal).

    Args:
        token: A ``FONT_*`` constant string, e.g. ``FONT_MD``.
        zoom:  Zoom multiplier (will be clamped to the card-zoom range 0.6–1.8
               by the caller; no clamping here).
        bold:  When True, the returned font is bold.

    Returns:
        A ``QFont`` with ``pixelSize`` set to ``max(6, round(px * zoom))``.
    """
    px = int(token.replace("px", ""))
    f = QFont()
    f.setPixelSize(max(6, round(px * zoom)))
    if bold:
        f.setBold(True)
    return f


# ── 1. Design tokens ────────────────────────────────────────────────────────────
# Values for every COLOR_*/FONT_*/OVERLAY_*/BACKDROP_TINTS name below live in
# theme_palettes.py (Midnight/Graphite/Daylight), NOT as literals in this file —
# _apply_palette_tokens() seeds them as module globals from the active palette.
# Do not hardcode a hex/rgba/px literal here; add or edit a value in
# theme_palettes.py instead. The module-level names stay stable (hundreds of
# consumers do ``from metatv.gui import theme as _theme`` and read
# ``_theme.COLOR_X`` at call time) — only their bound VALUE changes per palette.

_current_theme: str = theme_palettes.DEFAULT_PALETTE


def _apply_palette_tokens(palette: dict[str, object]) -> None:
    """Rebind every raw design-token global from *palette*, then recompute the
    handful of tokens that are themselves DERIVED from another token (kept as
    plain token-to-token references, not independent per-palette literals, so
    they automatically track whichever palette is active).
    """
    g = globals()
    for name, value in palette.items():
        g[name] = value
    # Derived tokens — composed from another token, not an independent
    # literal, so they aren't stored in theme_palettes.py's palette dicts.
    g["COLOR_SPLITTER_GRIP"] = g["COLOR_MUTED_2"]
    g["COLOR_FACET_CATEGORY"] = g["COLOR_ACCENT_ORANGE"]
    g["COLOR_LINK"] = g["COLOR_ACCENT_BLUE"]


_apply_palette_tokens(theme_palettes.PALETTES[_current_theme])


def _build_semantic_constants() -> dict[str, object]:
    """Compose every role-named semantic constant from the CURRENT token
    globals (section 2 of the module docstring's two-layer design).

    This is a plain function, re-run by :func:`apply_theme` after tokens
    rebind, rather than the flat module-level code it used to be — the
    constants below are ordinary Python string/list values computed ONCE by
    string concatenation, not lazily-evaluated properties, so switching the
    active palette wouldn't change anything a consumer already read unless
    this whole section is rebuilt and reassigned into the module globals
    again. See :func:`apply_theme`.
    """
    # ── 2. Semantic constants (composed from tokens, named by role) ──────────────────

    # Play / action buttons
    PLAY_BTN = (
        "QPushButton { background: transparent; border: none; color: " + COLOR_ACCENT +
        "; font-size: " + FONT_XL + "; padding: 0 2px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_HOVER + "; }"
    )
    PLAY_BTN_SMALL = (
        "QPushButton { background: transparent; border: none; color: " + COLOR_ACCENT +
        "; font-size: " + FONT_LG + "; padding: 0; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_HOVER + "; }"
    )
    CLEAR_BTN = "border: none; color: " + COLOR_DISABLED + "; font-size: " + FONT_SM + ";"
    CLOSE_BTN = "color: " + COLOR_MUTED_2 + "; border: none; background: transparent; font-size: " + FONT_2XL + ";"
    EYE_BTN = "border: none; padding: 0; color: " + COLOR_DIM + ";"
    PANEL_BTN = (
        "QPushButton { background:" + COLOR_LINE + "; color:" + COLOR_DIM + "; border:1px solid " + COLOR_BORDER + ";"
        " border-radius:3px; padding:0 7px; font-size:" + FONT_MD + "; }"
        "QPushButton:hover { background:" + COLOR_BORDER + "; color:" + COLOR_TEXT_2 + "; }"
    )
    # Compact inline "Only" link-button for filter group rows
    FILTER_ONLY_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_MUTED_2 + ";"
        " font-size: " + FONT_SM + "; padding: 0 2px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_3 + "; }"
    )
    # "Show all (N)" / "Show less" expander link inside large filter facet sections
    FILTER_SHOW_ALL_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_MUTED + ";"
        " font-size: " + FONT_MD + "; padding: 4px 8px; text-align: left; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_3 + "; }"
    )
    # Flat full-bleed nav button on a bar/footer panel (sidebar Settings, bottom-nav Diagnose)
    FLAT_NAV_BTN = (
        "QPushButton { font-size: " + FONT_XL + "; color: " + COLOR_TEXT_LOW +
        "; padding: 7px 12px; border-top: 1px solid " + COLOR_LINE +
        "; background: " + COLOR_BG_BAR + "; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; background: " + COLOR_LINE_DARK + "; }"
    )
    # Checkable flat nav-bar toggle button (e.g. Split Streams).  Off state mirrors
    # FLAT_NAV_BTN; checked state highlights with the accent color so ON is obvious.
    NAV_TOGGLE_BTN = (
        "QPushButton { font-size: " + FONT_XL + "; color: " + COLOR_TEXT_LOW +
        "; padding: 7px 12px; border-top: 1px solid " + COLOR_LINE +
        "; background: " + COLOR_BG_BAR + "; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; background: " + COLOR_LINE_DARK + "; }"
        "QPushButton:checked { color: " + COLOR_ACCENT + "; border-top: 1px solid " + COLOR_ACCENT + "; }"
        "QPushButton:checked:hover { color: " + COLOR_ACCENT_HOVER + "; background: " + COLOR_LINE_DARK + "; }"
    )
    RATING_BTN = (
        "QPushButton { border: none; border-radius: 3px; padding: 2px 6px;"
        " font-size: " + FONT_XL + "; color: " + COLOR_MUTED + "; }"
        "QPushButton:checked { background: " + OVERLAY_18 + "; color: " + COLOR_TEXT_HI + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT + "; }"
    )

    # Details-pane action rail — one shared role for every icon-only button in the
    # vertical rail left of the poster (favorite/play/queue/sentiment/alert/watchlist/
    # hide).  State is conveyed via :checked + icon-swap + tooltip (no text labels), so
    # all rail buttons read uniformly as distinct interactive targets.
    # :checked reads as the ACCENT (accent-tint fill + accent border + bright text) — a
    # fill AND border change, unmistakably ON — modelled on NAV_TOGGLE_BTN. It used to
    # reuse OVERLAY_55, which EQUALS :hover, so a selected rating/like/queue looked all
    # but identical to an unselected one.  The explicit :checked:hover keeps the accent
    # when a selected button is hovered (a bare :hover would otherwise win and revert it).
    DETAIL_RAIL_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
        " padding: 4px 2px; font-size: " + FONT_2XL + "; background: " + OVERLAY_40 + ";"
        " color: " + COLOR_DIM + "; }"
        "QPushButton:checked { background: " + OVERLAY_ACCENT_35 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_ACCENT + "; }"
        "QPushButton:hover { background: " + OVERLAY_55 + "; color: " + COLOR_TEXT + ";"
        " border-color: " + COLOR_DIM + "; }"
        "QPushButton:checked:hover { background: " + OVERLAY_ACCENT_50 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_ACCENT_HOVER + "; }"
    )

    # Alert/monitor rail button — inactive reads like a normal rail button; active
    # (:checked, "alerting") glows red so the siren clearly turns on.
    DETAIL_RAIL_BTN_ALERT = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
        " padding: 4px 2px; font-size: " + FONT_2XL + "; background: " + OVERLAY_40 + ";"
        " color: " + COLOR_DIM + "; }"
        "QPushButton:checked { background: " + OVERLAY_ERR + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_ERR + "; }"
        "QPushButton:hover { background: " + OVERLAY_55 + "; color: " + COLOR_TEXT + ";"
        " border-color: " + COLOR_DIM + "; }"
    )

    # Gold (COLOR_GOLD) tints — the FAVORITED rail-button fill.
    OVERLAY_GOLD_18 = "rgba(255,215,0,0.18)"
    OVERLAY_GOLD_28 = "rgba(255,215,0,0.28)"

    # Favorite rail button, FAVORITED state — glows GOLD (the star fills yellow): on-brand
    # (favorite = gold star) and unmistakable.  The favorite button is NOT :checkable
    # (state is icon-swap ☆→★), so the accent :checked fix couldn't reach it — this whole
    # style is swapped in via update_favorite() rather than a :checked rule.
    DETAIL_RAIL_BTN_FAV = (
        "QPushButton { border: 1px solid " + COLOR_GOLD + "; border-radius: 4px;"
        " padding: 4px 2px; font-size: " + FONT_2XL + "; background: " + OVERLAY_GOLD_18 + ";"
        " color: " + COLOR_GOLD + "; }"
        "QPushButton:hover { background: " + OVERLAY_GOLD_28 + "; color: " + COLOR_GOLD + ";"
        " border-color: " + COLOR_GOLD + "; }"
    )

    # Alert/monitor rail button in the "new matched content" state — the reserved
    # OK/new-match GREEN, filled (a SHAPE change from the outline inactive state, so the
    # cue is never colour-alone), paired with the 🚨 siren glyph + tooltip.  Wins over
    # the red :checked alerting state when the shown title has UNVIEWED matched content.
    DETAIL_RAIL_BTN_NEW_MATCH = (
        "QPushButton { border: 2px solid " + COLOR_OK + "; border-radius: 4px;"
        " padding: 3px 1px; font-size: " + FONT_2XL + "; background: " + OVERLAY_GREEN_15 + ";"
        " color: " + COLOR_OK + "; }"
        "QPushButton:checked { background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + ";"
        " border-color: " + COLOR_OK + "; }"
        "QPushButton:hover { background: " + OVERLAY_GREEN_40 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_OK + "; }"
    )

    # "New matched content" GREEN count badge — used in the Alerts sidebar header (global
    # glance) and on the Watch Queue's pinned new-matches line.  Always rendered next to
    # the 🚨 glyph + a number, so colour is reinforcement only (colourblind-safe).
    ALERT_NEW_MATCH_BADGE = "color: " + COLOR_OK + "; font-weight: bold;"

    # Shared subtle selection style for coloured-text item views — a soft translucent
    # tint + a left accent bar, and deliberately NO foreground override (so green stays
    # green and readable).  Applied per-widget via apply_list_selection() (one chokepoint)
    # to the lists/trees that show coloured rows; leaves widgets with their own selection
    # style (filter_panel, pantry OVERLAY_RECIPE_SELECTED) untouched.
    LIST_SELECTION_QSS = (
        "QAbstractItemView::item:selected { background: " + OVERLAY_SELECTION + ";"
        " border-left: 2px solid " + COLOR_ACCENT_BLUE + "; }"
    )


    def apply_list_selection(view) -> None:
        """Apply :data:`LIST_SELECTION_QSS` to an item view without clobbering its
        existing stylesheet (appends the rule).  Duck-typed on ``styleSheet`` /
        ``setStyleSheet`` so this module needs no Qt import.

        Args:
            view: A ``QAbstractItemView`` (QListWidget / QListView / QTreeWidget).
        """
        existing = view.styleSheet()
        view.setStyleSheet((existing + LIST_SELECTION_QSS) if existing else LIST_SELECTION_QSS)

    # Flat inline text action that also has an inert state (Recommendations dashboard:
    # the "Automatic" mix reset, greyed out while the mix already IS automatic).
    # Neutral rather than blue — it sits inside a control row, not beside a heading.
    INLINE_ACTION_BTN = (
        "QPushButton { color: " + COLOR_DIM + "; font-size: " + FONT_MD
        + "; border: none; padding: 2px 6px; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; }"
        "QPushButton:disabled { color: " + COLOR_MUTED_2 + "; }"
    )

    # Small flat text link (Alerts "Clear all"/"Manage") — blue, hover lighter.
    LINK_BTN_SM = (
        "QPushButton { border: none; color: " + COLOR_ACCENT_BLUE + "; font-size: " + FONT_SM + "; padding: 0 2px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_2 + "; }"
    )

    # Collapsible SUB-section header toggle inside a sidebar section (Watch Alerts:
    # EPG / Movies & Series / Stream Monitoring).  Muted bold left-aligned text with an
    # expand/collapse arrow; brightens on hover.  Shared so the three sub-headers stay
    # visually identical (one role constant, never copy-pasted per sub-section).
    SIDEBAR_SUBSECTION_TOGGLE = (
        "QPushButton { color: " + COLOR_MUTED + "; font-size: " + FONT_MD + "; font-weight: bold;"
        " border: none; text-align: left; padding: 0 2px; }"
        "QPushButton:hover { color: " + COLOR_DIM + "; }"
    )

    # Sub-section header inside a management dialog (Manage Watch Alerts: "keyword
    # rules" / "monitored series").  Bold, muted, sits above each grouped list.
    DIALOG_SUBHEADER = (
        "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD
        + "; font-weight: bold; padding-top: 6px;"
    )

    # Flat red "danger" text button inside a management dialog (Manage Watch Alerts:
    # rule "Remove" / series "Stop alerts").  Shared so both destructive links match.
    DIALOG_DANGER_LINK = (
        "QPushButton { font-size: " + FONT_SM + "; color: " + COLOR_ERR_2 + ";"
        " padding: 1px 6px; border: none; }"
        "QPushButton:hover { color: " + COLOR_RED_BRIGHT + "; }"
    )

    # A rule/series row flipped to pending-remove inside a management dialog (Manage
    # Watch Alerts: "Remove"/"Stop" no longer deletes immediately — the row goes
    # muted + strikethrough in place while the button swaps to "Undo").  Recoverable
    # remove, not immediate — the actual config mutation only lands when the dialog
    # closes with the row still pending (see ManageVodAlertsDialog._finalize_pending_removals).
    DIALOG_PENDING_REMOVE_NAME = (
        "color: " + COLOR_MUTED_2 + "; text-decoration: line-through;"
    )

    # VOD watch-for rule row (Alerts sidebar) — legible name + right-aligned count.
    # The name stays COLOR_TEXT (never tinted); the count goes green only when there
    # are unviewed matches, muted otherwise.  Colour-only (font-size inherits the list).
    VOD_ALERT_NAME       = "color: " + COLOR_TEXT + ";"
    # Year chip sitting right after a list-row title: a subtle bordered pill (neutral,
    # QLabel-friendly like LANG_CHIP) so the year reads as a facet chip rather than body
    # text — dim text, a faint border, no fill. Composed from tokens only.
    YEAR_CHIP            = (
        "color: " + COLOR_TEXT_LOW + "; border: 1px solid " + COLOR_BORDER + ";"
        " border-radius: 8px; padding: 1px 7px; font-size: " + FONT_LG + ";"
    )
    VOD_ALERT_COUNT_NEW  = "color: " + COLOR_OK + ";"
    VOD_ALERT_COUNT_IDLE = "color: " + COLOR_MUTED + ";"

    # Watch Queue pinned "new matches from your alerts" line — a single clickable GREEN
    # row at the top of the queue.  GREEN fill + the 🚨 glyph + the count text = the
    # colourblind-safe pairing.
    QUEUE_NEW_MATCHES_LINE = (
        "QPushButton { text-align: left; border: 1px solid " + COLOR_OK + ";"
        " border-radius: 4px; padding: 4px 8px; font-weight: bold;"
        " background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + "; }"
        "QPushButton:hover { background: " + OVERLAY_GREEN_40 + "; color: " + COLOR_TEXT_HI + "; }"
    )

    # "NEW" tag on an Alerts Matched row (Watch Queue sidebar's topmost group) —
    # a small filled pill.  Paired with the row's tooltip (the matched keyword) —
    # never a colour-alone cue: the word "NEW" itself carries the meaning even for a
    # colourblind reader, the green fill is reinforcement only.
    QUEUE_MATCHED_NEW_TAG = (
        "background: " + COLOR_OK + "; color: " + COLOR_BG_DEEP + ";"
        " border-radius: 3px; padding: 0px 4px; font-size: " + FONT_XS + "; font-weight: bold;"
    )

    # History sidebar row's ">>" "Play Next Episode" trailing button (Wave 5) — a small
    # blue-tinted chip button that sits outside the row's mouse-transparent pass-through
    # area (see chip_row.build_chip_row's trailing_button slot), so it stays independently
    # clickable rather than falling through to list-item selection like the rest of the row.
    HISTORY_PLAY_NEXT_BUTTON = (
        "QPushButton { background-color: " + OVERLAY_BLUE_20 + ";"
        " border: 1px solid " + COLOR_ACCENT_BLUE + "; border-radius: 3px;"
        " font-size: " + FONT_MD + "; font-weight: bold; color: " + COLOR_ACCENT_BLUE + "; }"
        "QPushButton:hover { background-color: " + OVERLAY_BLUE_40 + "; }"
        "QPushButton:pressed { background-color: " + OVERLAY_BLUE_60 + "; }"
    )

    # Details-pane PRIMARY action buttons — full-size, labeled (icon + text), shown in
    # a row directly below the poster (the most-used actions get the prominent slot).
    # Play is the SECONDARY/outline action (always starts from the beginning); Resume
    # is the DOMINANT filled-orange action (continue from the saved position).  Orange,
    # never green — green is reserved for the "currently playing" indicator
    # (DETAIL_PLAY_BTN_PLAYING below).
    DETAIL_PLAY_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
        " padding: 8px 12px; font-size: " + FONT_XL + "; font-weight: bold;"
        " background: transparent; color: " + COLOR_TEXT + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_DIM + "; }"
    )

    # Details-pane Play button in the "currently playing" state — a GREEN outline that
    # fires only while the title shown in the pane is the one actively playing.  Green
    # = "active / now" (the reserved semantic).  Colour is reinforcement only; the live
    # elapsed timer in the button label is the non-colour cue, so the state still reads
    # without colour vision.
    DETAIL_PLAY_BTN_PLAYING = (
        "QPushButton { border: 2px solid " + COLOR_OK + "; border-radius: 4px;"
        " padding: 7px 11px; font-size: " + FONT_XL + "; font-weight: bold;"
        " background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + "; }"
        "QPushButton:hover { background: " + OVERLAY_GREEN_40 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_OK + "; }"
    )
    DETAIL_RESUME_BTN = (
        "QPushButton { border: 1px solid " + COLOR_ACCENT_ORANGE + "; border-radius: 4px;"
        " padding: 8px 12px; font-size: " + FONT_XL + "; font-weight: bold;"
        " background: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
        "QPushButton:hover { background: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_TEXT_HI + "; }"
    )

    # Details-pane SECONDARY action button — the full-width labeled "Watch Later"
    # (queue) promoted out of the rail to sit directly under the primary Play/Resume
    # row.  Outline by default; :checked (already queued) fills subtly so the state
    # reads at a glance.  Neutral palette — orange is reserved for Resume, green for a
    # future "now playing" indicator.
    DETAIL_QUEUE_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
        " padding: 6px 12px; font-size: " + FONT_LG + "; background: transparent;"
        " color: " + COLOR_TEXT + "; }"
        "QPushButton:checked { background: " + OVERLAY_18 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_DIM + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_DIM + "; }"
    )

    # Poster watched badge — a corner check overlay (Plex/Jellyfin convention).
    # WATCHED: a persistent SOLID badge (hover tints red = "click to unmark").
    # UNWATCHED: a FAINT badge revealed only on poster hover (hover brightens =
    # "click to mark watched").  Neutral palette — NOT green (reserved as above).
    POSTER_WATCHED_BADGE = (
        "QPushButton { background: " + OVERLAY_BLACK_65 + "; color: " + COLOR_TEXT_HI + ";"
        " border: 1px solid " + COLOR_TEXT_HI + "; border-radius: 13px;"
        " font-size: " + FONT_XL + "; font-weight: bold; }"
        "QPushButton:hover { background: " + OVERLAY_ERR + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_ERR + "; }"
    )
    POSTER_UNWATCHED_BADGE = (
        "QPushButton { background: " + OVERLAY_BLACK_30 + "; color: " + COLOR_DIM + ";"
        " border: 1px solid " + COLOR_DIM + "; border-radius: 13px;"
        " font-size: " + FONT_XL + "; }"
        "QPushButton:hover { background: " + OVERLAY_BLACK_55 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_TEXT_HI + "; }"
    )

    # Channel-name labels (EPG rows)
    CHANNEL_NAME          = "font-size: " + FONT_MD + ";"
    CHANNEL_NAME_LIVE     = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    CHANNEL_NAME_UPCOMING = "color: " + COLOR_DIM_2 + "; font-size: " + FONT_MD + ";"
    CHANNEL_NAME_DIM      = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"

    # Channel-list row — ForegroundRole color for fully-watched (non-live) rows.
    # Dimmed so completed content recedes; in-progress and unwatched rows use the
    # default (delegate) foreground.  Build a QBrush from this at the call site:
    #   QBrush(QColor(CHANNEL_ROW_WATCHED_FG))
    CHANNEL_ROW_WATCHED_FG: str = COLOR_MUTED

    # Channel-list row — ForegroundRole color for "degraded" reliability_state rows
    # (graduated play-failure ledger, roadmap S3 — 3+ consecutive user-initiated
    # play failures). Grayed-but-clickable: more desaturated than the watched-dim
    # state above so an unreliable stream reads as visually distinct from merely
    # "already seen".  Never encodes state by color alone — the row stays fully
    # clickable/playable, this is reinforcement only.
    CHANNEL_ROW_DEGRADED_FG: str = COLOR_FAINT

    # Channel-list playback-state indicator — colour applied by the row delegate to the
    # fixed "·"/▶/✓ separator glyph.  Shape carries the meaning; these are reinforcement
    # only.  IN_PROGRESS reuses the details Resume-button orange so "resumable" reads the
    # same everywhere; WATCHED is the standard success green.
    COLOR_PLAYBACK_IN_PROGRESS: str = COLOR_ACCENT_ORANGE   # ▶ resumable — matches DETAIL_RESUME_BTN
    COLOR_PLAYBACK_WATCHED: str = COLOR_OK                   # ✓ finished

    # Time labels
    TIME_LABEL          = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"
    TIME_LABEL_UPCOMING = "color: " + COLOR_DISABLED + "; font-size: " + FONT_MD + ";"

    # Section headers / hints / items
    SECTION_HDR = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_MUTED_2 +
        "; letter-spacing: 1px; padding: 6px 4px 4px 4px;"
    )
    SECTION_HDR_LG = (
        "font-size: " + FONT_MD + "; font-weight: bold; color: " + COLOR_MUTED_2 +
        "; letter-spacing: 1px; padding: 4px 0;"
    )
    SECTION_HINT      = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + "; padding: 2px 0 6px 0;"
    # Warning banner for stale/out-of-date EPG guide data (EPG view).
    EPG_STALE_NOTICE  = (
        "color: " + COLOR_WARN + "; font-size: " + FONT_MD + ";"
        " border: 1px solid " + COLOR_WARN + "; border-radius: 4px; padding: 6px 10px;"
    )
    # Browse timeline-scrubber current-position label (Phase 2).
    EPG_SCRUBBER_POS  = (
        "color: " + COLOR_ACCENT_HOVER + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    SECTION_ITEM      = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + "; padding: 4px 0;"
    SECTION_TITLE_SM  = "font-size: " + FONT_LG + "; font-weight: bold; padding-top: 4px;"

    # Generic labels
    EMPTY_LABEL  = "color: " + COLOR_FAINT + "; font-size: " + FONT_XL + "; padding: 20px;"
    LABEL_MUTED  = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD + ";"
    LIST_TITLE   = "font-weight: bold; font-size: " + FONT_XL + ";"
    FIELD_LABEL  = "font-weight: 600;"
    DETAIL_TITLE = "font-size: " + FONT_3XL + "; font-weight: bold;"
    # Episode byline — the episode title shown under the series title in episode mode.
    # Subordinate to the series title (smaller than DETAIL_TITLE) but still emphasized.
    DETAIL_EPISODE_BYLINE = "font-size: " + FONT_2XL + "; font-weight: 600; color: " + COLOR_TEXT_HI + ";"
    # Episode-mode rating chip (Wave 4 — #247) — mirrors the gold/bold star treatment
    # used for the series-level rating (_MetadataSection.rating_label in
    # details_sections.py) so per-episode and series-level ratings render identically.
    DETAIL_EPISODE_RATING = "color: " + COLOR_GOLD + "; font-weight: bold;"
    # Episode-mode air-date chip — small and muted, sits beside the rating.
    DETAIL_EPISODE_AIR_DATE = "color: " + COLOR_MUTED + "; font-size: " + FONT_SM + ";"
    DETAIL_TEXT  = "color: " + COLOR_LIGHTGRAY + ";"
    META_DIM     = "color: " + COLOR_GRAY + ";"
    LOADING_TEXT = "color: " + COLOR_GRAY + "; font-style: italic;"

    # Filter dialog / panel
    FILTER_CHECKBOX  = "QCheckBox { color: " + COLOR_TEXT + "; }"
    FILTER_ITEM_TEXT = "font-size: " + FONT_LG + ";"
    ITEM_COUNT       = "font-size: " + FONT_MD + "; color: " + COLOR_FAINT + ";"
    EXPAND_HINT      = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_XS + ";"
    INFO_LABEL       = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + "; padding-left: 4px; padding-top: 4px;"

    # Provider editor
    META_HINT = "color: " + COLOR_MUTED + "; font-size: " + FONT_SM + ";"
    STATUS_OK   = "color: " + COLOR_OK + "; font-size: " + FONT_LG + "; font-weight: 600;"
    STATUS_WARN = "color: " + COLOR_WARN + "; font-size: " + FONT_LG + "; font-weight: 600;"
    STATUS_ERR  = "color: " + COLOR_ERR + "; font-size: " + FONT_LG + "; font-weight: 600;"

    # Provider editor — URL-test result badge (smaller than STATUS_*)
    URL_BADGE         = "font-size: " + FONT_SM + "; font-weight: 600;"
    URL_BADGE_TESTING = "font-size: " + FONT_SM + "; color: " + COLOR_MUTED + ";"
    URL_BADGE_OK      = "font-size: " + FONT_SM + "; font-weight: 600; color: " + COLOR_OK + ";"
    URL_BADGE_ERR     = "font-size: " + FONT_SM + "; font-weight: 600; color: " + COLOR_ERR_2 + ";"
    URL_REMOVE_BTN    = (
        "QPushButton { color: " + COLOR_ERR_2 + "; border: 1px solid " + COLOR_FAINT + "; border-radius: 3px; }"
        "QPushButton:hover { background: " + OVERLAY_ERR + "; }"
    )

    # Provider editor — icon picker
    ICON_PICK_BTN = (
        "QPushButton { font-size: " + FONT_ICON + "; border: 2px solid transparent;"
        " border-radius: 5px; padding: 0; }"
        " QPushButton:hover { border: 2px solid " + COLOR_ACCENT_BLUE + ";"
        " background: " + OVERLAY_BLUE_15 + "; }"
    )
    ICON_PICK_BTN_SELECTED = (
        "QPushButton { font-size: " + FONT_ICON + "; border: 2px solid " + COLOR_ACCENT_BLUE + ";"
        " border-radius: 5px; padding: 0;"
        " background: " + OVERLAY_BLUE_20 + "; }"
        " QPushButton:hover { border: 2px solid " + COLOR_ACCENT_BLUE + ";"
        " background: " + OVERLAY_BLUE_25 + "; }"
    )
    ICON_PICK_MAIN_BTN = (
        "QPushButton { font-size: " + FONT_ICON_LG + "; border: 1px solid " + OVERLAY_15 + ";"
        " border-radius: 6px; }"
        " QPushButton:hover { border: 1px solid " + COLOR_ACCENT_BLUE + ";"
        " background: " + OVERLAY_BLUE_10 + "; }"
    )
    ICON_PICK_POPUP = (
        "QFrame { background: " + OVERLAY_POPUP + ";"
        " border: 1px solid " + OVERLAY_18 + "; border-radius: 8px; }"
    )

    # Provider editor — persistent footer (Delete / Test Connection / Discard /
    # Save Changes) below the Summary/Connection/Settings tabs, always visible
    # regardless of the selected tab.
    PROVIDER_FOOTER = "background: " + OVERLAY_04 + "; border-top: 1px solid " + OVERLAY_08 + ";"
    LINK_BTN = (
        "QPushButton { border: none; color: " + COLOR_ACCENT_BLUE + "; font-size: " + FONT_XL + "; padding: 4px 8px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_2 + "; }"
    )
    DELETE_BTN = (
        "QPushButton { color: " + COLOR_ERR_2 + "; border: 1px solid " + COLOR_ERR_2 + "; border-radius: 4px; padding: 6px 14px; }"
        "QPushButton:hover { background: " + OVERLAY_ERR_15 + "; }"
    )
    SAVE_BTN = (
        "QPushButton { background: " + COLOR_BTN_SAVE + "; color: " + COLOR_TEXT_HI + "; border-radius: 4px; padding: 6px 18px; font-weight: 600; }"
        "QPushButton:hover { background: " + COLOR_BTN_SAVE_HOVER + "; }"
        "QPushButton:disabled { background: " + COLOR_LINE + "; color: " + COLOR_MUTED_2 + "; }"
    )
    # Vertical divider — provider-editor footer, visually separating the
    # destructive Delete action (far left) from the Test Connection / Discard /
    # Save Changes group (right) so Delete never reads as adjacent to Save.
    FOOTER_DIVIDER = "background: " + COLOR_LINE + ";"

    # Sources-manager header "+ Add Source" — the PRIMARY call to action of that
    # view, and the one control a user with zero sources must find. It previously
    # borrowed RECIPE_SAVED_ICON_BTN, whose role is a de-emphasised icon button
    # (transparent background, COLOR_FAINT text): correct there, but it rendered
    # this CTA as dim grey text with no affordance, indistinguishable from a
    # disabled label (#266). A solid accent fill instead — and therefore
    # COLOR_ON_ACCENT for the foreground, since the rule for text on a solid
    # COLOR_ACCENT fill is the on-accent token, never the on-background ramp.
    SOURCES_ADD_BTN = (
        "QPushButton { background: " + COLOR_ACCENT + "; color: " + COLOR_ON_ACCENT + ";"
        " border: none; border-radius: 4px; padding: 5px 14px; font-weight: 600;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + COLOR_ACCENT_HOVER + "; }"
    )

    # Category / prefix chips (version chips, similar-title chips, title-area prefix badge)
    CATEGORY_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 2px 8px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_DIM + ";"
        " background: " + OVERLAY_05 + "; }"
    )
    CATEGORY_CHIP_SM = (
        "QPushButton { font-size: " + FONT_SM + "; color: " + COLOR_DIM + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 1px 6px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_DIM + ";"
        " background: " + OVERLAY_05 + "; }"
    )
    # Quality badge in the details pane title bar (amber/gold, next to language chip)
    QUALITY_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_WARN + ";"
        " border: 1px solid " + COLOR_WARN + "; border-radius: 4px; padding: 2px 8px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_WARN + ";"
        " background: " + OVERLAY_08 + "; }"
    )

    # Genre chips — details pane metadata genre buttons (blue / link-like, flow-layout row)
    GENRE_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_ACCENT_BLUE_2 + ";"
        " border: 1px solid " + COLOR_FAINT + "; border-radius: 4px; padding: 2px 8px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_ACCENT_BLUE_2 + ";"
        " background: " + OVERLAY_BLUE_10 + "; }"
    )

    # Variant-count badge (content-collapse Slice 2) — bottom-left overlay on poster cards.
    # Shown only when variant_count > 1; styled to be unobtrusive (muted + slight tint).
    VARIANT_BADGE = (
        "background: " + OVERLAY_BLACK_55 + "; color: " + COLOR_DIM
        + "; border-radius: 3px; padding: 1px 4px;"
    )

    # Separators / surfaces
    SEPARATOR_LINE = "background: " + COLOR_LINE + "; margin-top: 4px; margin-bottom: 2px;"
    SEPARATOR_H    = "border: none; border-top: 1px solid " + COLOR_LINE + "; margin: 8px 0;"
    SEP_DARK       = "color: " + COLOR_BORDER + "; margin-top: 4px; margin-bottom: 4px;"
    CARD_BG        = "QWidget { background: " + OVERLAY_03 + "; border-radius: 6px; }"
    HEADER_TINT    = "background-color: " + OVERLAY_05 + ";"
    # Scoped variant of HEADER_TINT for sidebar section headers: an *unscoped*
    # ``background-color`` cascades onto child widgets (the title label + the flat
    # link buttons), stacking the translucent overlay into a visibly darker box.  The
    # ``#sectionHeader`` selector pins the tint to the header container only.  Applied
    # by ``_ClickableHeader`` (which sets ``objectName("sectionHeader")``).
    SECTION_HEADER_TINT = "#sectionHeader { background-color: " + OVERLAY_05 + "; }"
    BG_TRANSPARENT = "background: transparent;"

    # Exclusions chip (FilterChip in bottom nav bar) — three visual states.
    # Active (teal): global exclusions are enabled and applying.
    # Paused (amber): exclusions exist but are temporarily bypassed.
    # Hover and pressed fill the chip solid so feedback is visible over the text, not just in
    # the padding area. Text flips to the dark background color so contrast is maintained.
    EXCL_CHIP_ACTIVE = (
        "QPushButton { background-color: " + OVERLAY_EXCLUSIONS_10 + "; color: " + COLOR_EXCLUSIONS_ACTIVE + ";"
        " border: 1px solid " + COLOR_EXCLUSIONS_ACTIVE + "; border-radius: 12px;"
        " padding: 6px 14px; font-weight: bold; }"
        "QPushButton:hover { background-color: " + COLOR_EXCLUSIONS_ACTIVE + "; color: " + COLOR_BG_SECTION + "; }"
        "QPushButton:pressed { background-color: " + COLOR_EXCLUSIONS_ACTIVE + "; color: " + COLOR_BG_SECTION + "; }"
    )
    EXCL_CHIP_PAUSED = (
        "QPushButton { background-color: " + OVERLAY_ORANGE_10 + "; color: " + COLOR_ACCENT_ORANGE + ";"
        " border: 1px solid " + COLOR_ACCENT_ORANGE + "; border-radius: 12px;"
        " padding: 6px 14px; font-weight: bold; }"
        "QPushButton:hover { background-color: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
        "QPushButton:pressed { background-color: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
    )

    # Context filter chip — inline in the search bar when a details-pane filter is active
    # (genre click, person click). Amber/orange so it's clearly distinct from a normal search.
    CONTEXT_FILTER_CHIP = (
        "QWidget { background: " + OVERLAY_ORANGE_12 + ";"
        " border: 1px solid " + COLOR_ACCENT_ORANGE + ";"
        " border-radius: 4px; }"
    )
    CONTEXT_FILTER_CHIP_LABEL = (
        "color: " + COLOR_ACCENT_ORANGE + "; font-size: " + FONT_MD + "; font-weight: bold;"
        " background: transparent; border: none;"
    )
    CONTEXT_FILTER_CHIP_BTN = (
        "QPushButton { color: " + COLOR_ACCENT_ORANGE + "; font-size: " + FONT_MD + ";"
        " background: transparent; border: none; padding: 0 2px; font-weight: bold; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; }"
    )

    # Stream-diagnostics dialog
    # Warning banner shown when a stream is already playing (single-connection providers
    # can't be probed concurrently). Amber, bordered — distinct from the verdict headline.
    DIAG_PLAYING_WARNING = (
        "color: " + COLOR_WARN + "; font-size: " + FONT_LG + ";"
        " border: 1px solid " + COLOR_WARN + "; border-radius: 4px; padding: 6px 10px;"
    )
    # Verdict headline base — color is interpolated at runtime per verdict (see dialog).
    DIAG_VERDICT_HEADLINE = "font-size: " + FONT_2XL + "; font-weight: bold;"
    # Plain-language summary paragraph under the headline.
    DIAG_SUMMARY = "color: " + COLOR_LIGHTGRAY + "; font-size: " + FONT_LG + ";"
    # Metrics block (throughput / bitrate / headroom / ttfb / codec / resolution).
    DIAG_METRICS = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"
    # Recommended-args / placeholder line.
    DIAG_RECOMMEND = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + "; font-style: italic;"
    # Saved-confirmation line after applying tuning.
    DIAG_SAVED = "color: " + COLOR_OK + "; font-size: " + FONT_MD + "; font-weight: 600;"

    # Live playback-health readout in the bottom nav bar (buffer · speed · dropped frames).
    # Dim/muted at-a-glance line; only visible while mpv is actively playing.
    NAV_HEALTH = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"

    # Discover / recommendation rows (EPG Watchlist tab)
    # DISCOVER_REC_NAME        — channel name label in a recommendation row
    # DISCOVER_REC_PILL_BTN    — "± Channel" and Play pill buttons (outlined accent pill)
    # DISCOVER_REC_SKIP_BTN    — ghost "skip" dismiss button
    # DISCOVER_REC_COUNT       — clickable "{n} matches" toggle label (pointing-hand cursor)
    # DISCOVER_REC_MATCH_ROW   — compact programme sub-row revealed on expand
    DISCOVER_REC_NAME = "font-size: " + FONT_LG + ";"
    DISCOVER_REC_PILL_BTN = (
        "QPushButton { color: " + COLOR_ACCENT_HOVER + "; font-size: " + FONT_MD + ";"
        " border: 1px solid " + COLOR_ACCENT_HOVER + "; border-radius: 3px;"
        " padding: 1px 4px; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; background: " + OVERLAY_BLUE_15 + "; }"
    )
    DISCOVER_REC_SKIP_BTN = (
        "QPushButton { color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD + ";"
        " border: none; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_DIM + "; }"
    )
    DISCOVER_REC_COUNT = (
        "color: " + COLOR_ACCENT + "; font-size: " + FONT_MD + "; text-decoration: underline;"
    )
    DISCOVER_REC_MATCH_ROW = "color: " + COLOR_DIM_2 + "; font-size: " + FONT_MD + "; padding-left: 4px;"

    # Shelf-row placeholder — shown in a Discover shelf's card row while a
    # lazy-expand fetch is in flight (DISCOVER_SHELF_LOADING) or after it fails
    # (DISCOVER_SHELF_ERROR). See discover_shelf.py set_loading()/show_load_error().
    DISCOVER_SHELF_LOADING = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD + "; padding: 8px 4px;"
    DISCOVER_SHELF_ERROR = "color: " + COLOR_WARN + "; font-size: " + FONT_MD + "; padding: 8px 4px;"

    # What's New dialog
    WHATS_NEW_TITLE = (
        "font-size: " + FONT_2XL + "; font-weight: bold; color: " + COLOR_TEXT_HI + ";"
    )
    WHATS_NEW_META = (
        "font-size: " + FONT_SM + "; color: " + COLOR_MUTED + ";"
    )
    WHATS_NEW_ITEM = (
        "font-size: " + FONT_LG + "; color: " + COLOR_TEXT + ";"
    )
    WHATS_NEW_CARD = (
        "QWidget { background: " + OVERLAY_04 + "; border: 1px solid " + COLOR_LINE + ";"
        " border-radius: 6px; }"
    )
    # What's New carousel — navigation chevron buttons (large, monochrome, minimal border)
    WHATS_NEW_NAV_BTN = (
        "QPushButton { font-size: " + FONT_3XL + "; color: " + COLOR_DIM + ";"
        " background: transparent; border: 1px solid " + COLOR_LINE + "; border-radius: 4px;"
        " padding: 2px 10px; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_BORDER + "; }"
        "QPushButton:disabled { color: " + COLOR_FAINT + "; border-color: " + COLOR_LINE_DARK + "; }"
    )
    # What's New carousel — "1 / 4" position indicator label
    WHATS_NEW_POS_LABEL = (
        "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"
    )

    # Tag provenance + confidence chips (details pane — DR-0006 display)
    # SOURCE-GIVEN chips: solid border + slightly brighter text → "provider said so"
    TAG_CHIP_SOURCE = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 1px 6px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_DIM + ";"
        " background: " + OVERLAY_05 + "; }"
    )
    # INFERRED chips: dashed border + muted text → "MetaTV guessed this"
    TAG_CHIP_INFERRED = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_MUTED + ";"
        " border: 1px dashed " + COLOR_FAINT + "; border-radius: 4px; padding: 1px 6px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; border-color: " + COLOR_BORDER + ";"
        " background: " + OVERLAY_05 + "; }"
    )
    # LOW-CONFIDENCE modifier: further dims any chip whose confidence < 0.5
    TAG_CHIP_LOW_CONF_EXTRA = (
        "QPushButton { opacity: 0.6; color: " + COLOR_DISABLED + ";"
        " border-color: " + COLOR_LINE + "; }"
    )
    # Facet group label inside the Tags section
    TAG_FACET_LABEL = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_MUTED_2 + ";"
        " letter-spacing: 1px;"
    )

    # Events tab — segmented view-mode toggle (Timeline / By Network)
    EVENTS_SEG_INACTIVE = (
        "QPushButton { color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 3px;"
        " padding: 3px 10px; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; border-color: " + COLOR_DIM + "; }"
    )
    EVENTS_SEG_ACTIVE = (
        "QPushButton { color: " + COLOR_TEXT_HI + "; font-size: " + FONT_MD + "; font-weight: 600;"
        " border: 1px solid " + COLOR_ACCENT + "; border-radius: 3px;"
        " padding: 3px 10px; background: " + OVERLAY_BLUE_15 + "; }"
    )
    # Event row group header (bold, non-selectable section label inside the list)
    EVENTS_GROUP_HEADER = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_MUTED_2 + ";"
        " letter-spacing: 1px; padding: 4px 2px 2px 2px;"
    )
    # Time/availability hint label on each event row
    EVENTS_TIME_HINT = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"
    EVENTS_TIME_HINT_PASSED = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + ";"
    EVENTS_TIME_ON_NOW = "color: " + COLOR_OK + "; font-size: " + FONT_MD + "; font-weight: 600;"

    # WeightedTagCloud — role-named semantic constants
    # Count badge next to each tag value (small, muted, non-clickable)
    CLOUD_COUNT = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_SM + ";"
    # State-mark prefix on include-state tags (green checkmark)
    CLOUD_INCLUDE_MARK = "color: " + COLOR_OK + ";"
    # State-mark prefix on exclude-state tags (orange/red ⊘)
    CLOUD_EXCLUDE_MARK = "color: " + COLOR_WARN + ";"
    # Header label for the tag cloud ("Genre · N values · sized by catalogue weight")
    CLOUD_HEADER_LABEL = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"
    # Sort-toggle and filter search controls in the cloud header
    CLOUD_CTRL_BTN = (
        "QPushButton { font-size: " + FONT_SM + "; color: " + COLOR_MUTED + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 3px; padding: 1px 6px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_DIM + "; }"
        "QPushButton:checked { color: " + COLOR_ACCENT + "; border-color: " + COLOR_ACCENT + "; }"
    )
    # "+N more" expand button at the tail of the cloud
    CLOUD_MORE_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_MUTED + ";"
        " font-size: " + FONT_MD + "; padding: 4px 2px; text-align: left; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_3 + "; }"
    )

    # ── Recipe builder (Broadcast Noir, task #56 slice 3) ──────────────────────────

    # Left Pantry sidebar background
    RECIPE_PANTRY_BG = "QWidget { background: " + COLOR_RECIPE_PANEL_BG + "; }"

    # Pantry "THE PANTRY" and "SAVED RECIPES" section headers
    RECIPE_PANTRY_HDR = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
        " letter-spacing: 2px; padding: 6px 4px 4px 4px;"
    )

    # A facet row in the pantry — idle state
    RECIPE_FACET_ROW = (
        "QPushButton { border: none; background: transparent;"
        " color: " + COLOR_RECIPE_TEXT + "; font-size: " + FONT_MD + ";"
        " text-align: left; padding: 5px 8px; border-radius: 4px; }"
        "QPushButton:hover { background: " + OVERLAY_05 + "; }"
    )

    # A facet row in the pantry — selected/active state
    RECIPE_FACET_ROW_SELECTED = (
        "QPushButton { border: none; background: " + OVERLAY_RECIPE_SELECTED + ";"
        " color: " + COLOR_RECIPE_TEXT + "; font-size: " + FONT_MD + ";"
        " text-align: left; padding: 5px 8px; border-radius: 4px;"
        " border-left: 2px solid " + COLOR_FACET_REGION + "; }"
    )

    # Center stage header (facet name + count subtitle)
    RECIPE_STAGE_HDR = (
        "font-size: " + FONT_2XL + "; font-weight: bold; color: " + COLOR_RECIPE_TEXT + ";"
    )
    RECIPE_STAGE_SUBTITLE = (
        "font-size: " + FONT_MD + "; color: " + COLOR_RECIPE_MUTED + ";"
    )

    # Right recipe rail background
    RECIPE_RAIL_BG = "QWidget { background: " + COLOR_RECIPE_PANEL_BG + "; }"

    # "TONIGHT'S RECIPE" header
    RECIPE_RAIL_HDR = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
        " letter-spacing: 2px; padding: 4px 0;"
    )

    # Auto-generated recipe name (editorial title)
    RECIPE_EDITORIAL_NAME = (
        "font-size: " + FONT_LG + "; font-weight: bold; color: " + COLOR_RECIPE_TEXT + ";"
        " padding: 4px 0 8px 0;"
    )

    # Role label in the recipe ingredient list (BASE / IN / FROM / ON / ERA / FINISH / SET / OMIT)
    RECIPE_ROLE_LABEL = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
        " letter-spacing: 1px;"
    )

    # An ingredient chip in the recipe rail (include)
    RECIPE_INGREDIENT_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_RECIPE_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 2px 8px;"
        " background: " + OVERLAY_05 + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; }"
    )

    # An omit (exclude) chip — strikethrough appearance via text decoration
    RECIPE_OMIT_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_WARN + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 2px 8px;"
        " background: transparent; text-decoration: line-through; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; }"
    )

    # YIELDS count label
    RECIPE_YIELDS = (
        "font-size: " + FONT_LG + "; color: " + COLOR_RECIPE_TEXT + "; font-weight: 600;"
        " padding: 4px 0;"
    )

    # "Now plating" strip header
    RECIPE_NOW_PLATING_HDR = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
        " letter-spacing: 2px; padding: 4px 0 2px 0;"
    )

    # Save recipe button — present but disabled for slice 4
    RECIPE_SAVE_BTN = (
        "QPushButton { background: " + COLOR_BTN_SAVE + "; color: " + COLOR_TEXT_HI + ";"
        " border-radius: 4px; padding: 6px 14px; font-weight: 600; font-size: " + FONT_MD + "; }"
        "QPushButton:disabled { background: " + COLOR_LINE + "; color: " + COLOR_MUTED_2 + "; }"
    )

    # Clear button — ghost style
    RECIPE_CLEAR_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_MUTED + "; border-radius: 4px; padding: 6px 14px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + OVERLAY_05 + "; color: " + COLOR_TEXT_2 + "; }"
    )


    # ── Recipe builder — default "cluster grid" of per-facet mini tag-clouds ───────
    # The default overview replaces the one-facet-at-a-time pantry list with a grid
    # of per-facet mini clouds ("clusters").  Per-facet header colors stay dynamic
    # (composed inline from the COLOR_FACET_* tokens, like the pantry rows); only the
    # facet-agnostic chrome below is a shared role constant.

    # One cluster tile frame (a single facet's mini cloud in the overview grid).
    RECIPE_CLUSTER_TILE = (
        "QFrame#clusterTile { background: " + COLOR_RECIPE_PANEL_BG + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 6px; }"
    )

    # "· N values" subtitle beside a cluster's facet header.
    RECIPE_CLUSTER_SUBTITLE = (
        "color: " + COLOR_RECIPE_MUTED_2 + "; font-size: " + FONT_SM + ";"
    )

    # Collapsible "▸ More facets" section toggle at the foot of the cluster grid.
    RECIPE_MORE_FACETS_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_RECIPE_MUTED + ";"
        " font-size: " + FONT_SM + "; font-weight: bold; letter-spacing: 1px;"
        " text-align: left; padding: 6px 2px; }"
        "QPushButton:hover { color: " + COLOR_RECIPE_TEXT + "; }"
    )

    # Column-1 collapse/expand chevron (hides the Tonight's-Recipe rail to widen the grid).
    RECIPE_COL1_CHEVRON = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_RECIPE_MUTED + ";"
        " font-size: " + FONT_MD + "; padding: 2px 4px; }"
        "QPushButton:hover { color: " + COLOR_RECIPE_TEXT + "; background: " + OVERLAY_05 + ";"
        " border-radius: 4px; }"
    )

    # "‹ All facets" link — returns the drill-in / search view to the cluster grid.
    RECIPE_BACK_TO_GRID_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_ACCENT_BLUE + ";"
        " font-size: " + FONT_MD + "; padding: 2px 4px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_HOVER + "; }"
    )


    # ── Recipe builder — redesign (masonry grid · Recipe|Saved tabs · one-line bar) ─
    # The locked-mockup port: two sub-tabs, a masonry facet grid, a slim one-line
    # "recipe sentence" bar, and a Discover-style "Matching Content" shelf.  Only the
    # facet-agnostic chrome is a shared role constant here; per-facet colored chips
    # stay composed inline from the COLOR_FACET_* tokens (see recipe_widgets helpers).

    # Sub-tab bar ("Recipe" | "Saved") — pill toggle group.
    RECIPE_TABBAR_BG = "QWidget { background: transparent; }"
    RECIPE_TAB = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_MUTED + ";"
        " font-size: " + FONT_XL + "; font-weight: 600; padding: 5px 16px; border-radius: 7px; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; }"
    )
    RECIPE_TAB_ACTIVE = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: " + COLOR_BG_CARD + ";"
        " color: " + COLOR_TEXT_HI + "; font-size: " + FONT_XL + "; font-weight: 600;"
        " padding: 5px 16px; border-radius: 7px; }"
    )
    # Small right-aligned hint next to the tabs.
    RECIPE_TABBAR_HINT = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + ";"

    # "BROWSE BY FACET" uppercase section header above the masonry grid.
    RECIPE_BROWSE_HDR = (
        "font-size: " + FONT_MD + "; font-weight: 600; color: " + COLOR_MUTED + ";"
        " letter-spacing: 1.4px;"
    )

    # The slim one-line recipe "sentence" bar dividing the grid from Matching Content.
    RECIPE_BAR_BG = (
        "QWidget#recipeBar { background: " + COLOR_RECIPE_PANEL_BG + ";"
        " border-top: 1px solid " + COLOR_BORDER + "; border-bottom: 1px solid " + COLOR_BORDER + "; }"
    )
    RECIPE_BAR_LABEL = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_FAINT + ";"
        " letter-spacing: 1.6px;"
    )
    RECIPE_BAR_EMPTY = (
        "color: " + COLOR_FAINT + "; font-size: " + FONT_LG + "; font-style: italic;"
    )
    RECIPE_BAR_OP = "color: " + COLOR_FAINT + "; font-size: " + FONT_LG + "; font-weight: 600;"
    RECIPE_BAR_YIELD = (
        "font-size: " + FONT_LG + "; color: " + COLOR_MUTED + ";"
    )
    # Save (gold, primary) + Clear (ghost) actions on the recipe bar.
    RECIPE_BAR_SAVE_BTN = (
        "QPushButton { border: 1px solid " + COLOR_GOLD + "; background: transparent;"
        " color: " + COLOR_GOLD + "; font-size: " + FONT_LG + "; font-weight: 600;"
        " padding: 5px 13px; border-radius: 8px; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_GOLD_LIGHT + "; }"
        "QPushButton:disabled { border-color: " + COLOR_LINE + "; color: " + COLOR_MUTED_2 + "; }"
    )
    RECIPE_BAR_CLEAR_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_FAINT + ";"
        " font-size: " + FONT_LG + "; font-weight: 600; padding: 5px 11px; border-radius: 8px; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; background: " + OVERLAY_05 + "; }"
        "QPushButton:disabled { color: " + COLOR_MUTED_2 + "; }"
    )

    # "MATCHING CONTENT" shelf header + "preview · N total" subtitle.
    RECIPE_MATCH_HDR = (
        "font-size: " + FONT_LG + "; font-weight: bold; color: " + COLOR_MUTED + ";"
        " letter-spacing: 1.3px;"
    )
    RECIPE_MATCH_SUB = "font-size: " + FONT_LG + "; color: " + COLOR_FAINT + ";"
    # "Show all →" link (flat blue accent, shared by shelf header).
    RECIPE_SHOW_ALL_BTN = (
        "QPushButton { color: " + COLOR_ACCENT_BLUE + "; border: none;"
        " font-size: " + FONT_LG + "; font-weight: 600; padding: 2px 6px; }"
        "QPushButton:hover { color: " + COLOR_GOLD + "; }"
    )

    # Saved tab — subtitle + recipe card frame + editable name + count line.
    RECIPE_SAVED_SUB = "color: " + COLOR_FAINT + "; font-size: " + FONT_XL + ";"
    RECIPE_SAVED_CARD = (
        "QFrame#savedRecipeCard { background: " + COLOR_RECIPE_PANEL_BG + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 12px; }"
        "QFrame#savedRecipeCard:hover { border-color: " + COLOR_DIM + "; }"
    )
    RECIPE_SAVED_NAME_EDIT = (
        "QLineEdit { border: none; background: transparent; color: " + COLOR_TEXT_HI + ";"
        " font-size: " + FONT_2XL + "; font-weight: 600; padding: 0; }"
        "QLineEdit:focus { border-bottom: 1px solid " + COLOR_BORDER + "; }"
    )
    RECIPE_SAVED_COUNT = "font-size: " + FONT_MD + "; color: " + COLOR_FAINT + ";"
    # Generic muted empty/loading placeholder text (saved-empty, grid-loading, no-matches).
    RECIPE_EMPTY_HINT = (
        "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_XL + "; padding: 8px 2px;"
    )
    # Small icon button on a saved card (delete / load) — faint, hover-lit.
    RECIPE_SAVED_ICON_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_FAINT + ";"
        " font-size: " + FONT_XL + "; padding: 2px 5px; border-radius: 4px; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; background: " + OVERLAY_10 + "; }"
    )


    # ── Dev-only QA Testing Checklist — tri-state pass/fail ───────────────────────
    # Pass/fail toggle buttons.  Each has an inactive (ghost) and active state; the
    # active state tints to the OK (green) / ERR (red) palette so the chosen state
    # reads at a glance.  Composed from existing tokens — no new colour literals.
    QA_PASS_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_MUTED + "; border-radius: 4px; padding: 0 8px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + "; }"
    )
    QA_PASS_BTN_ACTIVE = (
        "QPushButton { border: 1px solid " + COLOR_OK + "; background: " + OVERLAY_GREEN_15 + ";"
        " color: " + COLOR_OK + "; border-radius: 4px; padding: 0 8px;"
        " font-size: " + FONT_MD + "; font-weight: bold; }"
    )
    QA_FAIL_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_MUTED + "; border-radius: 4px; padding: 0 8px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_ERR_2 + "; }"
    )
    QA_FAIL_BTN_ACTIVE = (
        "QPushButton { border: 1px solid " + COLOR_ERR_2 + "; background: " + OVERLAY_ERR2_15 + ";"
        " color: " + COLOR_ERR_2 + "; border-radius: 4px; padding: 0 8px;"
        " font-size: " + FONT_MD + "; font-weight: bold; }"
    )

    # Fail comment box — revealed beneath a failed step.
    QA_FAIL_NOTE_BOX = (
        "QPlainTextEdit { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_ERR_2 + "; border-radius: 4px; padding: 4px;"
        " font-size: " + FONT_MD + "; }"
    )

    # Attachment chip — small removable label for a saved screenshot / log path.
    QA_ATTACHMENT_CHIP = (
        "QPushButton { background: " + OVERLAY_05 + "; color: " + COLOR_DIM + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 3px; padding: 0 6px;"
        " font-size: " + FONT_SM + "; }"
        "QPushButton:hover { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_ERR_2 + "; }"
    )
    QA_ATTACH_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_DIM + "; border-radius: 4px; padding: 0 8px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT + "; }"
    )

    # "Newer build — re-test" amber hint (a step's stored sha differs from current HEAD).
    QA_STALE_HINT = "color: " + COLOR_WARN + "; font-size: " + FONT_SM + "; font-weight: 600;"

    # Failed-entry header badge — red flag on the entry title row.
    QA_ENTRY_FAILED_TITLE = (
        "font-size: " + FONT_LG + "; font-weight: bold; color: " + COLOR_ERR_2 + ";"
    )
    QA_FAIL_BADGE = (
        "color: " + COLOR_ERR_2 + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " padding-left: 4px;"
    )
    # "Addressed in PR #NNN — re-test" green badge on a failed step that a newer PR fixes.
    QA_ADDRESSED_BADGE = (
        "color: " + COLOR_OK + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " padding-left: 4px;"
    )
    # Clickable variant of the addressed badge — jumps to the addressing entry.
    QA_ADDRESSED_BADGE_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_OK + ";"
        " font-size: " + FONT_SM + "; font-weight: bold; padding-left: 4px; text-align: left; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; text-decoration: underline; }"
    )
    # "Go ▸" deep-link button — jumps the app to the view/content a test step targets.
    QA_GOTO_BTN = (
        "QPushButton { border: 1px solid " + COLOR_ACCENT_BLUE + "; background: transparent;"
        " color: " + COLOR_ACCENT_BLUE + "; border-radius: 4px; padding: 0 8px;"
        " font-size: " + FONT_SM + "; font-weight: bold; }"
        "QPushButton:hover { background: " + OVERLAY_BLUE_15 + "; color: " + COLOR_ACCENT_BLUE_2 + "; }"
    )

    # ── Similar-titles lightbox (redesign) ───────────────────────────────────────
    # Role constants for the poster-hero preview overlay (similar_lightbox.py +
    # similar_lightbox_card.py).  Colours come only from tokens above; these name the
    # roles so the two widget files carry no palette/font-size literals.

    # Card frame + chrome
    LIGHTBOX_CARD = (
        "#lightbox_card { background: " + COLOR_LIGHTBOX_BG + "; border-radius: 12px;"
        " border: 1px solid " + COLOR_BORDER + "; }"
    )
    LIGHTBOX_HEADER_BAR = (
        "background: " + COLOR_LIGHTBOX_HEADER + "; border-radius: 12px 12px 0 0;"
    )
    LIGHTBOX_FOOTER_BAR = (
        "background: " + COLOR_LIGHTBOX_HEADER + "; border-radius: 0 0 12px 12px;"
    )
    LIGHTBOX_BACK_BTN = (
        "QPushButton { color: " + COLOR_ACCENT_BLUE_2 + "; font-size: " + FONT_XL + ";"
        " font-weight: bold; border: none; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    LIGHTBOX_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_2XL + "; font-weight: bold;"
    )
    LIGHTBOX_COUNTER = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + ";"
    LIGHTBOX_CLOSE_BTN = (
        "QPushButton { color: " + COLOR_MUTED + "; font-size: " + FONT_3XL + ";"
        " border: none; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    # Round prev/next chevron flanking the card (used 2×).
    LIGHTBOX_CHEVRON = (
        "QPushButton { color: " + COLOR_MUTED + "; font-size: " + FONT_4XL + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 22px;"
        " background: " + COLOR_LIGHTBOX_BG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_ACCENT_BLUE + "; }"
        "QPushButton:disabled { color: " + COLOR_LINE + "; border-color: " + COLOR_LINE + "; }"
    )

    # Hero — poster slot + future-player affordance
    LIGHTBOX_POSTER_SLOT = (
        "#lightbox_poster { background: " + COLOR_BG_DEEP + "; border-radius: 9px;"
        " border: 1px solid " + COLOR_BORDER + "; }"
    )
    LIGHTBOX_POSTER_PLACEHOLDER = (
        "color: " + COLOR_FAINT + "; font-size: " + FONT_LG + ";"
    )

    # Primary Play button under the poster (filled accent, dark text).
    LIGHTBOX_PLAY_PRIMARY = (
        "QPushButton { background: " + COLOR_ACCENT + "; color: " + COLOR_LIGHTBOX_TEXT_HI + ";"
        " border: none; border-radius: 9px; padding: 9px 12px; font-size: " + FONT_XL + ";"
        " font-weight: bold; }"
        "QPushButton:hover { background: " + COLOR_ACCENT_HOVER + "; }"
    )
    # Secondary action button (Queue / Favorite / Hide) — outline, checkable-friendly.
    LIGHTBOX_ACTION_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: " + COLOR_LIGHTBOX_HEADER + ";"
        " color: " + COLOR_LIGHTBOX_TEXT + "; border-radius: 9px; padding: 8px 12px;"
        " font-size: " + FONT_LG + "; font-weight: bold; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_ACCENT_BLUE + "; }"
    )

    # Right column typography
    LIGHTBOX_HEADING = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_3XL + "; font-weight: bold;"
    )
    LIGHTBOX_META = "color: " + COLOR_MUTED + "; font-size: " + FONT_XL + ";"
    LIGHTBOX_STAR = "color: " + COLOR_GOLD + "; font-size: " + FONT_XL + "; font-weight: bold;"
    LIGHTBOX_SOURCE = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + ";"
    # ×N versions badge on the meta line (used when >1 content_key sibling).
    LIGHTBOX_VERSION_BADGE = (
        "background: " + OVERLAY_BLUE_15 + "; color: " + COLOR_ACCENT_BLUE_LIGHT + ";"
        " border: 1px solid " + COLOR_ACCENT_BLUE + "; border-radius: 6px;"
        " padding: 1px 7px; font-size: " + FONT_LG + "; font-weight: bold;"
    )

    # Genre chips — DISPLAY ONLY here (not clickable-to-Recipe yet); no hover affordance.
    LIGHTBOX_GENRE_CHIP = (
        "background: " + OVERLAY_BLUE_10 + "; color: " + COLOR_ACCENT_BLUE_LIGHT + ";"
        " border-radius: 10px; padding: 3px 10px; font-size: " + FONT_LG + ";"
    )

    # Section sub-heading (OVERVIEW / CAST & CREW / OTHER VERSIONS / SIMILAR TITLES).
    LIGHTBOX_SECTION_HDR = (
        "color: " + COLOR_FAINT + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " letter-spacing: 1px;"
    )
    LIGHTBOX_PLOT = "color: " + COLOR_LIGHTBOX_TEXT + "; font-size: " + FONT_XL + ";"
    LIGHTBOX_CAST = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + ";"

    # Other Versions row (used N×) — a full-width entry in the hero's vertical, scrollable
    # list showing the friendly "<source> · <quality/region>" label plus an optional
    # source-icon glyph; the full "<name> · <source>" lives in the tooltip. Click dives to
    # that variant. A runtime provider colour (``ProviderDB.color``) may be injected as a
    # left-border source badge in code (via :func:`lightbox_version_row`); the label text
    # is always present, so the row never distinguishes by colour alone.
    LIGHTBOX_VERSION_ROW = (
        "QPushButton { text-align: left; background: transparent; color: " + COLOR_LIGHTBOX_TEXT + ";"
        " border: none; border-bottom: 1px solid " + COLOR_LINE + "; padding: 6px 8px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; background: " + COLOR_BG_DEEP + "; }"
    )


    def lightbox_version_row(accent_color: str = "") -> str:
        """Compose the Other-Versions list-row style, tinting the left border by
        *accent_color*.

        ``accent_color`` is a runtime provider colour (``ProviderDB.color``) — NOT a
        palette literal — so injecting it here mirrors the accepted sidebar source-label
        pattern. Blank/absent → the plain :data:`LIGHTBOX_VERSION_ROW`.
        """
        if not accent_color:
            return LIGHTBOX_VERSION_ROW
        return LIGHTBOX_VERSION_ROW + (
            "QPushButton { border-left: 3px solid " + accent_color + "; }"
        )

    # Similar-strip mini card (used N×) — poster (whole card dives in), name, year.
    LIGHTBOX_SIM_POSTER = (
        "#lightbox_sim_poster { background: " + COLOR_BG_DEEP + "; border-radius: 8px;"
        " border: 1px solid " + COLOR_BORDER + "; color: " + COLOR_LIGHTBOX_TEXT + ";"
        " font-size: " + FONT_MD + "; }"
    )
    LIGHTBOX_SIM_NAME = "color: " + COLOR_LIGHTBOX_TEXT + "; font-size: " + FONT_LG + ";"
    LIGHTBOX_SIM_YEAR = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + ";"

    # Language/region chip — the ONE canonical bordered chip shared by the sim-badge
    # renderer (lightbox strip + trail-map rows, via ``sim_badges.make_sim_badges``) and
    # the trail-map detail strip, so the lang/region badge reads identically everywhere
    # (single source of truth — no per-surface lang style).
    LANG_CHIP = (
        "background: " + OVERLAY_BLUE_10 + "; color: " + COLOR_ACCENT_BLUE_LIGHT + ";"
        " border-radius: 8px; padding: 1px 7px; font-size: " + FONT_MD + ";"
    )

    # Similar-strip mini-card badge cluster — a compact meta line (language/region +
    # rating) above a state-glyph line (liked / in Watch Later / favorited / watched),
    # mirroring the badges the details-pane Similar rows show.  Colours match those
    # surfaces (blue like/queue, gold favorite/rating, green watched); each glyph also
    # carries a tooltip, so state is never conveyed by colour alone.  (Language uses the
    # shared ``LANG_CHIP`` above.)
    LIGHTBOX_SIM_RATING        = "color: " + COLOR_GOLD + "; font-size: " + FONT_MD + "; font-weight: bold;"
    LIGHTBOX_SIM_GLYPH_LIKE    = "color: " + COLOR_ACCENT_BLUE + "; font-size: " + FONT_MD + ";"
    LIGHTBOX_SIM_GLYPH_QUEUE   = "color: " + COLOR_ACCENT_BLUE + "; font-size: " + FONT_MD + ";"
    LIGHTBOX_SIM_GLYPH_FAV     = "color: " + COLOR_GOLD + "; font-size: " + FONT_MD + ";"
    LIGHTBOX_SIM_GLYPH_WATCHED = "color: " + COLOR_OK + "; font-size: " + FONT_MD + ";"

    # Footer keyboard-hint kbd chip (used N×).
    LIGHTBOX_KBD = (
        "background: " + COLOR_BG_DEEP + "; color: " + COLOR_LIGHTBOX_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 5px; padding: 1px 6px;"
        " font-size: " + FONT_MD + ";"
    )
    LIGHTBOX_FOOTER_HINT = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"

    # ── Explore trail-map (cascading columns + detail strip) ─────────────────────
    # Role constants for ``trail_map_view.py`` / ``trail_map_detail.py``.  Same dark
    # lightbox design family (owner: propagate the lightbox styling app-wide); colours
    # come only from the tokens above so the widget files carry no literals.

    # Shell + header
    TRAILMAP_SHELL = (
        "#trailmap_shell { background: " + COLOR_LIGHTBOX_BG + "; border-radius: 12px;"
        " border: 1px solid " + COLOR_BORDER + "; }"
    )
    TRAILMAP_HEADER_BAR = (
        "background: " + COLOR_LIGHTBOX_HEADER + "; border-radius: 12px 12px 0 0;"
    )
    TRAILMAP_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_2XL + "; font-weight: bold;"
    )
    TRAILMAP_SUBTITLE = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + ";"
    TRAILMAP_CLOSE_BTN = LIGHTBOX_CLOSE_BTN
    # Flat "collapse branches" link button in the header.
    TRAILMAP_LINK_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_ACCENT_BLUE + ";"
        " font-size: " + FONT_LG + "; padding: 3px 6px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_2 + "; }"
    )

    # Columns
    TRAILMAP_COLUMN = (
        "#trailmap_col { background: transparent;"
        " border-right: 1px solid " + COLOR_LINE + "; }"
    )
    TRAILMAP_TRAIL_COLUMN = (
        "#trailmap_col { background: " + OVERLAY_03 + ";"
        " border-right: 2px solid " + COLOR_BORDER + "; }"
    )
    TRAILMAP_COLHEAD = (
        "background: transparent; border-bottom: 1px solid " + COLOR_LINE + ";"
    )
    TRAILMAP_COLHEAD_KICKER = (
        "color: " + COLOR_FAINT + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " letter-spacing: 1px;"
    )
    TRAILMAP_COLHEAD_NAME = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    TRAILMAP_COLHINT = (
        "color: " + COLOR_FAINT + "; font-size: " + FONT_SM + ";"
        " border-top: 1px solid " + COLOR_LINE + ";"
    )

    # Rows (custom QWidget; needs WA_StyledBackground). Two states applied in code —
    # each carries its own :hover so hover works in both.
    TRAILMAP_ROW = (
        "#trailmap_row { background: transparent; border-radius: 8px; }"
        "#trailmap_row:hover { background: " + OVERLAY_05 + "; }"
    )
    TRAILMAP_ROW_SELECTED = (
        "#trailmap_row { background: " + OVERLAY_BLUE_15 + "; border-radius: 8px;"
        " border-left: 2px solid " + COLOR_ACCENT + "; }"
    )
    TRAILMAP_THUMB = (
        "#trailmap_thumb { background: " + COLOR_BG_DEEP + "; border-radius: 4px;"
        " border: 1px solid " + COLOR_BORDER + "; color: " + COLOR_FAINT + ";"
        " font-size: " + FONT_LG + "; }"
    )
    TRAILMAP_ROW_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    TRAILMAP_ROW_YEAR = "color: " + COLOR_FAINT + "; font-size: " + FONT_SM + ";"
    TRAILMAP_ROW_CHEVRON = "color: " + COLOR_FAINT + "; font-size: " + FONT_XL + ";"
    TRAILMAP_TRAIL_NUM = "color: " + COLOR_FAINT + "; font-size: " + FONT_SM + ";"
    # "here" tag on the current (last) trail stop.
    TRAILMAP_HERE_TAG = (
        "background: " + COLOR_LIGHTBOX_TEXT_HI + "; color: " + COLOR_BG_DEEP + ";"
        " border-radius: 3px; padding: 0 4px; font-size: " + FONT_XS + "; font-weight: bold;"
    )

    # Detail strip
    TRAILMAP_DETAIL = (
        "#trailmap_detail { background: " + COLOR_BG_DEEP + ";"
        " border-top: 1px solid " + COLOR_LINE + "; }"
    )
    TRAILMAP_DETAIL_POSTER = (
        "#trailmap_detail_poster { background: " + COLOR_BG_DEEP + "; border-radius: 8px;"
        " border: 1px solid " + COLOR_BORDER + "; color: " + COLOR_FAINT + ";"
        " font-size: " + FONT_LG + "; }"
    )
    # Corner "mark watched" badge on the detail poster — 3 states (base / partial / done);
    # shape+glyph carry meaning, colour reinforces (colour-not-alone).
    TRAILMAP_WBADGE = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 11px;"
        " background: " + COLOR_LIGHTBOX_BG + "; color: " + COLOR_FAINT + ";"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_OK + "; }"
    )
    TRAILMAP_WBADGE_DONE = (
        "QPushButton { border: 1px solid " + COLOR_OK + "; border-radius: 11px;"
        " background: " + COLOR_LIGHTBOX_BG + "; color: " + COLOR_OK + ";"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    TRAILMAP_WBADGE_PARTIAL = (
        "QPushButton { border: 1px solid " + COLOR_ACCENT_ORANGE + "; border-radius: 11px;"
        " background: " + COLOR_LIGHTBOX_BG + "; color: " + COLOR_ACCENT_ORANGE + ";"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    TRAILMAP_DETAIL_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_3XL + "; font-weight: bold;"
    )
    TRAILMAP_DETAIL_YEAR = "color: " + COLOR_MUTED + "; font-size: " + FONT_2XL + ";"
    # Favourite title-star (☆→★) — persistent, gold when on (NOT a rail button).
    TRAILMAP_FAV_STAR = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_FAINT + ";"
        " font-size: " + FONT_4XL + "; }"
        "QPushButton:hover { color: " + COLOR_GOLD + "; }"
        "QPushButton:checked { color: " + COLOR_GOLD + "; }"
    )
    TRAILMAP_DETAIL_META = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + ";"
    TRAILMAP_DETAIL_STAR = (
        "color: " + COLOR_GOLD + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    TRAILMAP_SECTION_HDR = (
        "color: " + COLOR_FAINT + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " letter-spacing: 1px;"
    )
    TRAILMAP_OVERVIEW = "color: " + COLOR_LIGHTBOX_TEXT + "; font-size: " + FONT_LG + ";"
    TRAILMAP_CREW = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + ";"
    TRAILMAP_PLAY_BTN = LIGHTBOX_PLAY_PRIMARY
    # Secondary outline link buttons (↗ Open in details, ✦ Make recipe).
    TRAILMAP_DETAIL_LINK_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_LIGHTBOX_TEXT + "; border-radius: 8px; padding: 6px 10px;"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_ACCENT_BLUE + "; }"
    )
    TRAILMAP_EMPTY_HINT = "color: " + COLOR_FAINT + "; font-size: " + FONT_LG + ";"

    # Explore views (embedded trail-map: History / Favorites / Watch Queue / Recommended):
    # opaque backing so the transient loading / empty state is not a see-through gap over
    # the content area.  One role constant shared by every Explore entry point.
    EXPLORE_VIEW_BG = "#exploreView { background: " + COLOR_LIGHTBOX_BG + "; }"
    EXPLORE_STATUS = (
        "color: " + COLOR_MUTED + "; font-size: " + FONT_XL + ";"
    )

    # Sidebar "Explore →" header link (History / Favorites / Queue / Recommended → the
    # matching Explore cascading-columns view).
    SIDEBAR_SEE_ALL_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_ACCENT_BLUE + ";"
        " font-size: " + FONT_MD + "; padding: 0 4px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_2 + "; }"
    )

    # Sources status strip (Wave 6) — compact, always-clickable footer row pinned above
    # the sidebar Settings button, replacing the old collapsible Sources section. Mirrors
    # FLAT_NAV_BTN's footer-bar treatment (top hairline + bar background) so the two read
    # as one continuous footer; the whole strip is clickable (opens the Sources manager
    # view), so it brightens on hover like a nav button even though it isn't one.
    SOURCES_STRIP = (
        "QWidget#sourcesStatusStrip { background: " + COLOR_BG_BAR + ";"
        " border-top: 1px solid " + COLOR_LINE + "; }"
        "QWidget#sourcesStatusStrip:hover { background: " + COLOR_LINE_DARK + "; }"
    )
    SOURCES_STRIP_TITLE = (
        "color: " + COLOR_TEXT_LOW + "; font-size: " + FONT_XL + "; font-weight: bold;"
    )

    # Lightbox dive-trail breadcrumb (#388) — inside the builder so a theme
    # switch recomposes them like every other semantic constant.
    LIGHTBOX_BREADCRUMB_CRUMB = (
        "QPushButton { color: " + COLOR_MUTED + "; font-size: " + FONT_SM + ";"
        " border: none; background: transparent; padding: 0 2px; text-align: left; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; }"
    )
    LIGHTBOX_BREADCRUMB_CURRENT = (
        "color: " + COLOR_TEXT + "; font-size: " + FONT_SM + ";"
    )
    LIGHTBOX_BREADCRUMB_SEP = (
        "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_SM + ";"
    )

    # Shared QProgressBar role (background enrichment queue view; migration_progress_widget.py
    # still builds its own inline — left alone, out of scope for this addition).
    PROGRESS_BAR = (
        "QProgressBar { border: 1px solid " + COLOR_BORDER + "; border-radius: 3px;"
        " background: " + COLOR_LINE + "; text-align: center; color: " + COLOR_TEXT_HI + ";"
        " font-size: " + FONT_SM + "; }"
        "QProgressBar::chunk { background: " + COLOR_ACCENT_BLUE + "; border-radius: 2px; }"
    )

    return {k: v for k, v in dict(locals()).items() if not k.startswith("_")}


globals().update(_build_semantic_constants())


def qt_palette() -> QPalette:
    """Build a ``QPalette`` from the CURRENTLY ACTIVE design tokens (#253).

    This is the QPalette chokepoint: applied to the whole ``QApplication`` by
    :func:`apply_theme`, it gives every widget a correctly themed floor color
    EVEN IF that widget never calls ``setStyleSheet()`` at all — which is
    exactly why the details-pane "Overview"/"Technical Details" ``QLabel``s
    and the bottom ``QStatusBar`` used to render near-black-on-near-black /
    pure white regardless of the active app theme: with no stylesheet, Qt
    fell back to its own built-in (light) default palette instead of this
    one. ``MainWindow.refresh_theme()``'s hand-maintained sweep still handles
    every EXPLICITLY styled widget (a cached ``setStyleSheet()`` string
    doesn't track a token live) — this is the floor beneath that sweep, not a
    replacement for it.

    Every role below is sourced from an existing ``COLOR_*`` token (the
    current module globals, already rebound to the active palette by
    :func:`_apply_palette_tokens`) — no new hex literal lives here.

    Returns:
        A ``QPalette`` reflecting :func:`current_theme`'s active tokens.
    """
    palette = QPalette()

    # Core surfaces + text — the two pairs verified at >= 4.5:1 contrast by
    # tests/test_palette_completeness.py's primary-text check (COLOR_TEXT on
    # COLOR_BG_SECTION) and this slice's own qt_palette floor tests.
    palette.setColor(QPalette.ColorRole.Window, QColor(COLOR_BG_SECTION))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLOR_TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLOR_LINE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLOR_BG_BAR))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLOR_TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLOR_LINE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLOR_TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLOR_BG_CARD))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLOR_TEXT_HI))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLOR_DISABLED))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLOR_ACCENT))
    # COLOR_ON_ACCENT, not the COLOR_TEXT_HI ramp: Highlight is a solid accent
    # FILL, so its foreground is the on-accent token. The two coincide in the
    # dark palettes, which is why the original COLOR_TEXT_HI reading looked
    # right — in Daylight it put near-black text on a navy fill (~1.2:1).
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLOR_ON_ACCENT))

    # Disabled-state variants — a visibly dimmer read than the active-state
    # roles above, reusing the token already named for exactly this purpose
    # ("disabled / clear buttons").
    disabled_color = QColor(COLOR_DISABLED)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, disabled_color)

    return palette


def _sync_qt_application_palette() -> None:
    """Push :func:`qt_palette` onto the running ``QApplication``, if one
    exists yet.

    Guarded because ``theme.py`` (and :func:`apply_theme`) is imported/called
    in plenty of contexts with no ``QApplication`` around — every test file
    that imports ``theme`` without also standing up a ``qapp`` fixture, plus
    ``theme.py``'s own module-import-time palette seed, which runs before
    ``metatv.__main__.main()`` has constructed the app.
    """
    app = QApplication.instance()
    if app is not None:
        app.setPalette(qt_palette())


# ---------------------------------------------------------------------------
# Live-restyle registry (#277)
# ---------------------------------------------------------------------------
#
# Qt caches the RENDERED stylesheet string, not a reference to the Python
# constant — so ``apply_theme`` rebinding ``LIST_ROW`` does nothing to a widget
# that already called ``setStyleSheet(LIST_ROW)``. The previous answer was a
# hand-maintained sweep in ``MainWindow.refresh_theme()``, which cannot work:
# there were ~838 setStyleSheet call sites against 22 refresh_theme methods, and
# an enumeration can never see the ones nobody remembered to add.
#
# This inverts it. A widget styled through :func:`style` registers itself, and
# ``apply_theme`` re-applies every live registration. Nothing has to be
# remembered, and a new widget is covered the moment it is written.
#
# Held by WEAK reference so the registry never keeps a closed dialog alive; dead
# entries are reaped on the next pass. A deleted C++ object raises RuntimeError
# on access even while the Python wrapper lives, so that is caught too.
_style_registry: "list[tuple[weakref.ref, object]]" = []


def style(widget, role: str) -> None:
    """Apply the named semantic constant to *widget* and register it.

    Use this instead of ``theme.style(widget, "SOME_ROLE")`` — the plain
    call renders correctly once and then goes stale on every theme switch.

    Args:
        widget: Any QWidget.
        role: Name of a semantic constant in this module, e.g. ``"LIST_ROW"``.

    Raises:
        AttributeError: If *role* is not a constant here — a typo would
            otherwise register a widget that silently never restyles.
    """
    widget.setStyleSheet(_role_qss(role))
    _style_registry.append((weakref.ref(widget), role))


def style_fn(widget, builder) -> None:
    """Register a widget whose stylesheet is COMPOSED rather than a bare role.

    For the f-string/concatenation sites (``f"color: {COLOR_WARN}"``): pass a
    zero-arg callable and it is re-invoked on every theme switch, so the
    interpolated tokens are re-read.

    Args:
        widget: Any QWidget.
        builder: Zero-arg callable returning a stylesheet string.
    """
    widget.setStyleSheet(builder())
    _style_registry.append((weakref.ref(widget), builder))


def _role_qss(role) -> str:
    """Resolve a registration to its current stylesheet string."""
    if callable(role):
        return role()
    value = globals().get(role)
    if value is None:
        raise AttributeError(f"theme has no semantic constant {role!r}")
    return value


def _reapply_registered_styles() -> int:
    """Re-apply every live registration; reap dead ones. Returns the count."""
    survivors: list = []
    applied = 0
    for ref, role in _style_registry:
        widget = ref()
        if widget is None:
            continue
        try:
            widget.setStyleSheet(_role_qss(role))
        except (RuntimeError, AttributeError):
            # RuntimeError: the C++ object is gone while the wrapper lingers.
            # AttributeError: a role that no longer exists — drop it rather
            # than wedging the whole sweep on one stale entry.
            continue
        survivors.append((ref, role))
        applied += 1
    _style_registry[:] = survivors
    return applied


def registered_style_count() -> int:
    """Live registrations — for tests and diagnostics."""
    return sum(1 for ref, _ in _style_registry if ref() is not None)


def apply_theme(name: str) -> bool:
    """Switch the active palette, rebinding every token AND semantic-constant
    module-level global in place so already-imported consumers
    (``from metatv.gui import theme as _theme`` / ``import theme``) see the
    new values on their next attribute read. Also pushes the rebuilt
    :func:`qt_palette` onto the running ``QApplication`` (if one exists) —
    every call, including a same-name/no-op one, so a cold launch that never
    actually "switches" (the saved theme already matches the module's resting
    default) still gets the QPalette floor applied at least once. See
    ``metatv.__main__.main()`` for the startup call.

    This does NOT repaint anything already on screen that caches a
    stylesheet string — a widget that called ``setStyleSheet()`` keeps
    showing the OLD rendered style until something re-invokes
    ``setStyleSheet()`` with the (now updated) constant. See
    ``MainWindow.refresh_theme()`` for the sweep that does that for the app's
    persistent, explicitly-styled chrome; :func:`qt_palette` above is the
    floor for everything that sweep doesn't (or can't yet) reach.

    Args:
        name: One of :data:`theme_palettes.PALETTES`'s keys (e.g. "Midnight").

    Returns:
        True if *name* names a known palette different from the current one
        and the switch was applied; False for an unknown name or a no-op
        (already the active palette) — callers use this to skip an
        unnecessary repaint sweep.
    """
    global _current_theme
    if name not in theme_palettes.PALETTES:
        return False
    changed = name != _current_theme
    if changed:
        _current_theme = name
        _apply_palette_tokens(theme_palettes.PALETTES[name])
        globals().update(_build_semantic_constants())
    _sync_qt_application_palette()
    # Restyle every widget registered through style()/style_fn(). Unconditional,
    # like the palette push above: a cold launch whose saved theme already
    # matches the resting default still needs one pass so nothing is left on a
    # stale string. Cheap when the registry is empty (startup, tests).
    _reapply_registered_styles()
    return changed


def current_theme() -> str:
    """Return the name of the currently active palette."""
    return _current_theme


def available_themes() -> list[str]:
    """Return every palette name, in a stable display order (dict-insertion
    order of :data:`theme_palettes.PALETTES` — Midnight, Graphite, Daylight)."""
    return list(theme_palettes.PALETTES.keys())
