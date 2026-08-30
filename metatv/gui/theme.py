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

import re
import weakref

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

from metatv.gui import theme_palettes
# The palette-invariant scales — corner radius, and the zoom transform for
# the type scale. See tokens/scales.py, in particular why a PILL cannot be
# a radius step.
from metatv.gui.tokens.scales import (  # noqa: F401
    RADIUS_LG, RADIUS_MD, RADIUS_NONE, RADIUS_SM,
    SPACE_LG, SPACE_MD, SPACE_NONE, SPACE_SM, SPACE_XS,
    radius_px, space_px, zoomed_font,
)
# Role groups that compose themselves from the tokens and merge in below.
from metatv.gui.tokens import chip_roles as _chip_roles
from metatv.gui.tokens import detail_roles as _detail_roles


# ── 1. Design tokens ────────────────────────────────────────────────────────────
# Values for every COLOR_*/FONT_*/OVERLAY_*/BACKDROP_TINTS name below live in
# theme_palettes.py (Midnight/Graphite/Daylight), NOT as literals in this file —
# _apply_palette_tokens() seeds them as module globals from the active palette.
# Do not hardcode a hex/rgba/px literal here; add or edit a value in
# theme_palettes.py instead. The module-level names stay stable (hundreds of
# consumers do ``from metatv.gui import theme as _theme`` and read
# ``_theme.COLOR_X`` at call time) — only their bound VALUE changes per palette.

_current_theme: str = theme_palettes.DEFAULT_PALETTE


class _TokenStr(str):
    """A token value that remembers which token it came from.

    Behaves as an ordinary ``str`` everywhere — it IS a str, so every existing
    f-string, concatenation and comparison is unaffected — but reading it into a
    stylesheet records the token's NAME in :data:`_READ_LOG`. That is what makes
    live re-theming token-aware instead of colour-aware.

    Why this exists
    ---------------
    The first live-theme pass (#286) diffed old→new VALUES and substring-replaced
    them in live stylesheets, because ~310 call sites across 44 files compose
    sheets with raw ``setStyleSheet(f"…{_theme.COLOR_X}…")`` and never register a
    builder. Diffing values worked only while every value was unique — which was
    true purely by accident, because all 140 were independently hand-picked
    (Graphite: 140 tokens, 140 distinct values).

    Deriving the palette from a scale broke that assumption on purpose: roles
    legitimately share steps (``COLOR_ACCENT`` and ``COLOR_ACCENT_HOVER`` may be
    one blue), so Midnight resolves 140 tokens to 84 distinct values. A global
    value-diff then cannot tell which token produced a given colour, and the
    ambiguity guard correctly refused 56 of them.

    Recording the read makes the question answerable per widget: we know the
    exact tokens THIS widget's sheet was built from, so a colour shared by two
    tokens is only ambiguous if this widget used both AND they diverge in the new
    palette — which is rare, and detectable rather than guessed.
    """

    __slots__ = ("token_name",)

    def __new__(cls, value: str, token_name: str):
        obj = super().__new__(cls, value)
        obj.token_name = token_name
        return obj

    def _record(self) -> None:
        if _RECORDING_SUSPENDED:
            return
        _READ_LOG.append(self.token_name)
        if len(_READ_LOG) > _READ_LOG_MAX:
            del _READ_LOG[:-_READ_LOG_MAX]

    def __str__(self) -> str:            # f"{TOKEN}" and str(TOKEN)
        self._record()
        return str.__str__(self)

    def __format__(self, spec: str) -> str:
        self._record()
        return str.__format__(self, spec)

    def __add__(self, other):            # "…" + TOKEN + "…"
        self._record()
        return str.__add__(self, other)

    def __radd__(self, other):
        self._record()
        return str.__add__(str(other), str.__str__(self))


# Token names read since the last stylesheet was applied. Bounded: tokens are
# also read for non-stylesheet purposes (QColor, comparisons), and an unbounded
# list would grow for the life of the process.
_READ_LOG: list[str] = []
_READ_LOG_MAX = 96

# Recording is suspended while theme.py reads its own tokens. Without this, the
# token reads inside apply_theme (rebuilding every semantic constant, restyling
# every registered widget) pile up in the log and are attributed to whichever
# widget is styled NEXT — measured: 27 tokens credited to a label that used 2,
# which reintroduced exactly the ambiguity this mechanism removes.
_RECORDING_SUSPENDED = False


class _suspend_recording:
    """Context manager: token reads inside are not attributed to any widget."""

    def __enter__(self):
        global _RECORDING_SUSPENDED
        _RECORDING_SUSPENDED = True
        return self

    def __exit__(self, *exc):
        global _RECORDING_SUSPENDED
        _RECORDING_SUSPENDED = False
        _READ_LOG.clear()
        return False


def _drain_read_log() -> tuple[str, ...]:
    """Take the tokens read since the last drain, and clear it."""
    tokens = tuple(dict.fromkeys(_READ_LOG))   # de-duped, order preserved
    _READ_LOG.clear()
    return tokens


def _apply_palette_tokens(palette: dict[str, object]) -> None:
    """Rebind every raw design-token global from *palette*, then recompute the
    handful of tokens that are themselves DERIVED from another token (kept as
    plain token-to-token references, not independent per-palette literals, so
    they automatically track whichever palette is active).

    Colour values are wrapped in :class:`_TokenStr` so that composing a
    stylesheet records which tokens went into it (see that class). Non-colour
    entries (the ``FONT_*`` type scale, ``BACKDROP_TINTS``) are left alone —
    they are not re-themed and do not need provenance.
    """
    g = globals()
    for name, value in palette.items():
        if isinstance(value, str) and name.startswith(("COLOR_", "OVERLAY_")):
            value = _TokenStr(value, name)
        g[name] = value
    # Derived tokens — composed from another token, not an independent
    # literal, so they aren't stored in theme_palettes.py's palette dicts.
    g["COLOR_SPLITTER_GRIP"] = g["COLOR_MUTED_2"]
    g["COLOR_FACET_CATEGORY"] = g["COLOR_ACCENT_ORANGE"]
    g["COLOR_LINK"] = g["COLOR_ACCENT_BLUE"]


_apply_palette_tokens(theme_palettes.PALETTES[_current_theme])


# --- per-widget token provenance -------------------------------------------
# Which tokens each widget's stylesheet was composed from. Populated by wrapping
# QWidget.setStyleSheet ONCE, here, rather than by editing 310 call sites across
# 44 files — that migration would be a single unreviewable diff, and it would
# still not cover a site nobody has written yet.
#
# The capture is sound because of evaluation order: an f-string is fully
# evaluated (reading its tokens) BEFORE setStyleSheet is called with the
# finished string, so draining the read log inside the wrapper yields exactly
# the tokens that composed the sheet being applied.
_STYLE_TOKENS: "weakref.WeakKeyDictionary[QWidget, tuple[str, ...]]" = (
    weakref.WeakKeyDictionary()
)


def _install_style_provenance() -> None:
    """Wrap ``QWidget.setStyleSheet`` so every applied sheet records its tokens.

    Idempotent — re-importing the module (or a test reloading it) must not stack
    wrappers, which would drain the read log twice and lose the provenance.
    """
    if getattr(QWidget.setStyleSheet, "_metatv_provenance", False):
        return
    original = QWidget.setStyleSheet

    def setStyleSheet(self, sheet):  # noqa: N802 — matching Qt's name
        tokens = _drain_read_log()
        if tokens:
            try:
                _STYLE_TOKENS[self] = tokens
            except TypeError:
                pass          # not weak-referenceable; falls back to value-diff
        return original(self, sheet)

    setStyleSheet._metatv_provenance = True
    QWidget.setStyleSheet = setStyleSheet


_install_style_provenance()


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
    # COLOR_ACCENT is the accent as a FILL; as TEXT on the app surface it is a
    # midtone (2.61:1 in Graphite, 4.19 in Daylight). COLOR_ACCENT_BLUE is the
    # accent-as-text member of the family and clears 11:1 in every palette.
    PLAY_BTN = (
        "QPushButton { background: transparent; border: none; color: " + COLOR_ACCENT_BLUE +
        "; font-size: " + FONT_XL + "; padding: 0 2px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_HOVER + "; }"
    )
    PLAY_BTN_SMALL = (
        "QPushButton { background: transparent; border: none; color: " + COLOR_ACCENT_BLUE +
        "; font-size: " + FONT_LG + "; padding: 0; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_HOVER + "; }"
    )
    CLEAR_BTN = "border: none; color: " + COLOR_DISABLED + "; font-size: " + FONT_SM + ";"
    # COLOR_TEXT, not COLOR_MUTED_2 ({neutral.8}): a dismiss control has to be
    # findable. On the app surface the old pairing measured 2.81 / 2.53 / 1.68
    # across the palettes — in Daylight the × was very nearly invisible.
    CLOSE_BTN = "color: " + COLOR_TEXT + "; border: none; background: transparent; font-size: " + FONT_2XL + ";"
    EYE_BTN = "border: none; padding: 0; color: " + COLOR_TEXT + ";"

    # The log viewer's stream. COLOR_BG_DEEP rather than the card surface: it
    # is a wall of dense monospace text, and the deepest ground is what gives
    # the smallest legible type the most contrast to work with. The family is
    # set on the widget (Qt resolves "monospace" per platform through a
    # StyleHint, which a stylesheet string cannot do), so only colour and size
    # come from here.
    LOG_STREAM = (
        "QPlainTextEdit { background: " + COLOR_BG_DEEP + "; color: " + COLOR_TEXT
        + "; border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM
        + "; padding: 6px; font-size: " + FONT_SM + "; }"
    )
    # A control at rest gets the CONTAINER surface, not COLOR_LINE — that is a
    # separator hairline, and pairing it with COLOR_DIM measured 2.70:1 in every
    # palette. Same mistake, same family, as the results list reading COLOR_LINE
    # for its background.
    PANEL_BTN = (
        "QPushButton { background:" + COLOR_BG_CARD + "; color:" + COLOR_TEXT + "; border:1px solid " + COLOR_BORDER + ";"
        " border-radius: " + RADIUS_SM + "; padding:0 7px; font-size:" + FONT_MD + "; }"
        "QPushButton:hover { background:" + COLOR_SURFACE_LIGHT_2 + "; color:" + COLOR_TEXT_HI + "; }"
    )
    # Filter-bar controls — the multi-select dropdowns ("Genres ▼") in
    # filter_bar.py and sports_filter_bar.py, and filter_bar's "Clear" button.
    # One role rather than three copies of the same sheet. Both used to hardcode ``background-color: white`` with
    # ``COLOR_LINE`` as the text: a hard-white slab in the dark themes, lettered
    # in a hairline-separator colour. Same shape as the #298 view-chip bug
    # documented in filter_bar.py — a literal cannot track a palette.
    FILTER_CONTROL_BTN = (
        "QPushButton { background-color: " + COLOR_BG_CARD + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + ";"
        " padding: 6px 12px; text-align: left; }"
        "QPushButton:hover { background-color: " + COLOR_SURFACE_LIGHT_2 + ";"
        " color: " + COLOR_TEXT_HI + "; }"
    )

    # Compact inline "Only" link-button for filter group rows
    # Same COLOR_MUTED_2-on-app-surface problem as CLOSE_BTN (2.81/2.53/1.68):
    # this is a link the user is meant to notice and click, not decoration.
    FILTER_ONLY_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_TEXT + ";"
        " font-size: " + FONT_SM + "; padding: 0 2px; }"
        "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_3 + "; }"
    )
    # "Show all (N)" / "Show less" expander link inside large filter facet sections
    FILTER_SHOW_ALL_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_TEXT + ";"
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
        "QPushButton { border: none; border-radius: " + RADIUS_SM + "; padding: 2px " + SPACE_SM + ";"
        " font-size: " + FONT_XL + "; color: " + COLOR_TEXT + "; }"
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
    # Rail buttons: a real SURFACE at rest, accent fill only when active.
    #
    # Owner: "those button backgrounds are shitty" — measured, and they were:
    # a 40% white wash composited to a flat mid-grey (#767676) carrying COLOR_DIM
    # text at 1.97:1, about half the 3:1 floor for UI chrome. The palette
    # restructure did NOT fix this and briefly made it worse (1.13:1), because
    # the defect was never in the token values — it was here, in the role: an
    # overlay wash is a HOVER effect being used as a resting fill, so the button
    # had no real surface of its own and every state looked filled.
    #
    # Now: surface.container at rest with body text on it, and the accent fill
    # reserved for :checked. That is what makes "is this favourited?" legible at
    # a glance — when every state is filled, a fill says nothing.
    DETAIL_RAIL_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + ";"
        " padding: 4px " + SPACE_XS + "; font-size: " + FONT_2XL + "; background: " + COLOR_BG_CARD + ";"
        " color: " + COLOR_TEXT + "; }"
        "QPushButton:checked { background: " + OVERLAY_ACCENT_35 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_ACCENT + "; }"
        "QPushButton:hover { background: " + COLOR_SURFACE_LIGHT_2 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_BORDER + "; }"
        # Hovering an ALREADY-ACTIVE button used to raise the accent wash to 50%
        # while keeping near-white text on it — which LOWERS contrast (4.24:1 in
        # Midnight), so the one interaction that should confirm "yes, this is
        # on" degraded it. It now goes to a SOLID accent with the on-accent
        # foreground: the same "state is a fill" rule the results row follows,
        # and a clearer progression than tint -> slightly-more-tint.
        "QPushButton:checked:hover { background: " + COLOR_ACCENT + "; color: " + COLOR_ON_ACCENT + ";"
        " border-color: " + COLOR_ACCENT_HOVER + "; }"
    )

    # Alert/monitor rail button — inactive reads like a normal rail button; active
    # (:checked, "alerting") glows red so the siren clearly turns on.
    # Resting/hover fills MIRROR DETAIL_RAIL_BTN above — this variant differs
    # only in what its CHECKED state means, and it had been left behind when
    # its sibling was given real surfaces (#297). It was filling with OVERLAY_40
    # and OVERLAY_55: white-alpha washes at 43%/48%, measuring 1.13:1 and
    # 1.92:1 against their own label. Those two tokens are documented as the
    # "frosted-light" pair that sits over POSTER IMAGES — photographic, never
    # reskinned — so they were never a candidate for a button fill at all.
    DETAIL_RAIL_BTN_ALERT = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + ";"
        " padding: 4px " + SPACE_XS + "; font-size: " + FONT_2XL + "; background: " + COLOR_BG_CARD + ";"
        " color: " + COLOR_TEXT + "; }"
        "QPushButton:checked { background: " + OVERLAY_ERR + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_ERR + "; }"
        "QPushButton:hover { background: " + COLOR_SURFACE_LIGHT_2 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_BORDER + "; }"
    )

    # Gold (COLOR_GOLD) tints — the FAVORITED rail-button fill.
    OVERLAY_GOLD_18 = "rgba(255,215,0,0.18)"
    OVERLAY_GOLD_28 = "rgba(255,215,0,0.28)"

    # Favorite rail button, FAVORITED state — glows GOLD (the star fills yellow): on-brand
    # (favorite = gold star) and unmistakable.  The favorite button is NOT :checkable
    # (state is icon-swap ☆→★), so the accent :checked fix couldn't reach it — this whole
    # style is swapped in via update_favorite() rather than a :checked rule.
    # FAVOURITED is a STATE, so it gets a solid fill (the same rule the results
    # row follows) with COLOR_ON_BRIGHT on it. It used to paint gold text on an
    # 18% gold TINT — the same hue at two lightnesses. That reads acceptably on
    # a dark app and collapses to 1.32:1 on Daylight, where the tint composites
    # to pale yellow and the gold sits almost invisibly on it. Solid gold also
    # says "on" far more clearly than a wash of the same colour.
    DETAIL_RAIL_BTN_FAV = (
        "QPushButton { border: 1px solid " + COLOR_GOLD + "; border-radius: " + RADIUS_SM + ";"
        " padding: 4px " + SPACE_XS + "; font-size: " + FONT_2XL + "; background: " + COLOR_GOLD + ";"
        " color: " + COLOR_ON_BRIGHT + "; }"
        "QPushButton:hover { background: " + COLOR_GOLD_LIGHT + "; color: " + COLOR_ON_BRIGHT + ";"
        " border-color: " + COLOR_GOLD_LIGHT + "; }"
    )

    # Alert/monitor rail button in the "new matched content" state — the reserved
    # OK/new-match GREEN, filled (a SHAPE change from the outline inactive state, so the
    # cue is never colour-alone), paired with the 🚨 siren glyph + tooltip.  Wins over
    # the red :checked alerting state when the shown title has UNVIEWED matched content.
    DETAIL_RAIL_BTN_NEW_MATCH = (
        "QPushButton { border: 2px solid " + COLOR_OK + "; border-radius: " + RADIUS_SM + ";"
        " padding: 3px " + SPACE_XS + "; font-size: " + FONT_2XL + "; background: " + OVERLAY_GREEN_15 + ";"
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
        "QPushButton { color: " + COLOR_TEXT + "; font-size: " + FONT_MD
        + "; border: none; padding: 2px " + SPACE_SM + "; }"
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
        "QPushButton { color: " + COLOR_TEXT + "; font-size: " + FONT_MD + "; font-weight: bold;"
        " border: none; text-align: left; padding: 0 2px; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; }"
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
        " padding: 1px " + SPACE_SM + "; border: none; }"
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

    # Year chip sitting right after a list-row title: a subtle bordered pill (neutral,
    # QLabel-friendly like LANG_CHIP) so the year reads as a facet chip rather than body
    # text — dim text, a faint border, no fill. Composed from tokens only.
    YEAR_CHIP            = (
        "color: " + COLOR_TEXT_LOW + "; border: 1px solid " + COLOR_BORDER + ";"
        " border-radius: " + RADIUS_MD + "; padding: 1px " + SPACE_SM + "; font-size: " + FONT_LG + ";"
    )

    # Watch Queue pinned "new matches from your alerts" line — a single clickable GREEN
    # row at the top of the queue.  GREEN fill + the 🚨 glyph + the count text = the
    # colourblind-safe pairing.
    QUEUE_NEW_MATCHES_LINE = (
        "QPushButton { text-align: left; border: 1px solid " + COLOR_OK + ";"
        " border-radius: " + RADIUS_SM + "; padding: 4px 8px; font-weight: bold;"
        " background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + "; }"
        "QPushButton:hover { background: " + OVERLAY_GREEN_40 + "; color: " + COLOR_TEXT_HI + "; }"
    )

    # "NEW" tag on an Alerts Matched row (Watch Queue sidebar's topmost group) —
    # a small filled pill.  Paired with the row's tooltip (the matched keyword) —
    # never a colour-alone cue: the word "NEW" itself carries the meaning even for a
    # colourblind reader, the green fill is reinforcement only.
    QUEUE_MATCHED_NEW_TAG = (
        "background: " + COLOR_OK + "; color: " + COLOR_BG_DEEP + ";"
        " border-radius: " + RADIUS_SM + "; padding: 0px 4px; font-size: " + FONT_XS + "; font-weight: bold;"
    )

    # History sidebar row's ">>" "Play Next Episode" trailing button (Wave 5) — a small
    # blue-tinted chip button that sits outside the row's mouse-transparent pass-through
    # area (see chip_row.build_chip_row's trailing_button slot), so it stays independently
    # clickable rather than falling through to list-item selection like the rest of the row.
    # History's per-group "forget these" control. Quiet until hovered: it sits on
    # every time heading, and a destructive action drawn as loudly as the count
    # beside it would read as the group's PURPOSE rather than as an action on it.
    # Danger colour arrives on hover, when the pointer has already committed.
    HISTORY_GROUP_FORGET_BUTTON = (
        "QPushButton { background-color: transparent; border: none;"
        " border-radius: " + RADIUS_SM + "; color: " + COLOR_MUTED_2 + "; }"
        "QPushButton:hover { background-color: " + OVERLAY_ERR_15 + ";"
        " color: " + COLOR_ERR + "; }"
    )

    HISTORY_PLAY_NEXT_BUTTON = (
        "QPushButton { background-color: " + OVERLAY_BLUE_20 + ";"
        " border: 1px solid " + COLOR_ACCENT_BLUE + "; border-radius: " + RADIUS_SM + ";"
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
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + ";"
        " padding: 8px 12px; font-size: " + FONT_XL + "; font-weight: bold;"
        " background: transparent; color: " + COLOR_TEXT + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_BORDER + "; }"
    )

    # Details-pane Play button in the "currently playing" state — a GREEN outline that
    # fires only while the title shown in the pane is the one actively playing.  Green
    # = "active / now" (the reserved semantic).  Colour is reinforcement only; the live
    # elapsed timer in the button label is the non-colour cue, so the state still reads
    # without colour vision.
    DETAIL_PLAY_BTN_PLAYING = (
        "QPushButton { border: 2px solid " + COLOR_OK + "; border-radius: " + RADIUS_SM + ";"
        " padding: 7px " + SPACE_MD + "; font-size: " + FONT_XL + "; font-weight: bold;"
        " background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + "; }"
        "QPushButton:hover { background: " + OVERLAY_GREEN_40 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_OK + "; }"
    )
    DETAIL_RESUME_BTN = (
        "QPushButton { border: 1px solid " + COLOR_ACCENT_ORANGE + "; border-radius: " + RADIUS_SM + ";"
        " padding: 8px 12px; font-size: " + FONT_XL + "; font-weight: bold;"
        " background: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
        # Hover keeps the ON-FILL text colour and moves the BORDER instead.
        # It used to switch the label to COLOR_TEXT_HI while leaving the light
        # amber fill in place — near-white on near-white, 1.04:1 — so hovering
        # the app's most-used button made its label disappear. The fill is
        # light in the dark palettes and dark in Daylight, and COLOR_BG_SECTION
        # inverts with it, which is why the resting pair was always fine.
        "QPushButton:hover { background: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + ";"
        " border-color: " + COLOR_TEXT_HI + "; }"
    )

    # Details-pane SECONDARY action button — the full-width labeled "Watch Later"
    # (queue) promoted out of the rail to sit directly under the primary Play/Resume
    # row.  Outline by default; :checked (already queued) fills subtly so the state
    # reads at a glance.  Neutral palette — orange is reserved for Resume, green for a
    # future "now playing" indicator.
    DETAIL_QUEUE_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + ";"
        " padding: 6px 12px; font-size: " + FONT_LG + "; background: transparent;"
        " color: " + COLOR_TEXT + "; }"
        "QPushButton:checked { background: " + OVERLAY_18 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_BORDER + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_BORDER + "; }"
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
        "QPushButton { background: " + OVERLAY_BLACK_30 + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 13px;"
        " font-size: " + FONT_XL + "; }"
        "QPushButton:hover { background: " + OVERLAY_BLACK_55 + "; color: " + COLOR_TEXT_HI + ";"
        " border-color: " + COLOR_TEXT_HI + "; }"
    )

    # Channel-name labels (EPG rows)
    CHANNEL_NAME          = "font-size: " + FONT_MD + ";"
    CHANNEL_NAME_LIVE     = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    CHANNEL_NAME_UPCOMING = "color: " + COLOR_DIM_2 + "; font-size: " + FONT_MD + ";"
    CHANNEL_NAME_DIM      = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"

    # Channel-list row — ForegroundRole color for fully-watched (non-live) rows.
    # Dimmed so completed content recedes; in-progress and unwatched rows use the
    # default (delegate) foreground.  Build a QBrush from this at the call site:
    #   QBrush(QColor(CHANNEL_ROW_WATCHED_FG))
    CHANNEL_ROW_WATCHED_FG: str = COLOR_DISABLED

    # Channel-list row — ForegroundRole color for "degraded" reliability_state rows
    # (graduated play-failure ledger, roadmap S3 — 3+ consecutive user-initiated
    # play failures). Grayed-but-clickable: more desaturated than the watched-dim
    # state above so an unreliable stream reads as visually distinct from merely
    # "already seen".  Never encodes state by color alone — the row stays fully
    # clickable/playable, this is reinforcement only.
    CHANNEL_ROW_DEGRADED_FG: str = COLOR_DISABLED

    # Channel-list playback-state indicator — colour applied by the row delegate to the
    # fixed "·"/▶/✓ separator glyph.  Shape carries the meaning; these are reinforcement
    # only.  IN_PROGRESS reuses the details Resume-button orange so "resumable" reads the
    # same everywhere; WATCHED is the standard success green.
    COLOR_PLAYBACK_IN_PROGRESS: str = COLOR_ACCENT_ORANGE   # ▶ resumable — matches DETAIL_RESUME_BTN
    COLOR_PLAYBACK_WATCHED: str = COLOR_OK                   # ✓ finished

    # Time labels
    TIME_LABEL          = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
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
    SECTION_HINT      = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + "; padding: 2px 0 6px 0;"
    # A bordered warn-coloured notice block. Generic on purpose: this shape was
    # defined once for the EPG stale-guide banner and immediately wanted by the
    # connection-diagnosis panel, which is the point at which a second copy
    # would have been the wrong answer.
    NOTICE_WARN = (
        "color: " + COLOR_WARN + "; font-size: " + FONT_MD + ";"
        " border: 1px solid " + COLOR_WARN + "; border-radius: " + RADIUS_SM + "; padding: 6px " + SPACE_MD + ";"
    )
    # Warning banner for stale/out-of-date EPG guide data (EPG view). Kept as a
    # name because call sites read better for it; it is the same style.
    EPG_STALE_NOTICE  = NOTICE_WARN
    # Browse timeline-scrubber current-position label (Phase 2).
    EPG_SCRUBBER_POS  = (
        "color: " + COLOR_ACCENT_HOVER + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    SECTION_ITEM      = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + "; padding: 4px 0;"
    SECTION_TITLE_SM  = "font-size: " + FONT_LG + "; font-weight: bold; padding-top: 4px;"

    # Generic labels
    EMPTY_LABEL  = "color: " + COLOR_TEXT + "; font-size: " + FONT_XL + "; padding: 20px;"
    LABEL_MUTED  = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD + ";"
    LIST_TITLE   = "font-weight: bold; font-size: " + FONT_XL + ";"
    FIELD_LABEL  = "font-weight: 600;"
    DETAIL_TITLE = "font-size: " + FONT_3XL + "; font-weight: bold;"
    # Byline — "Movie · 2024" on the line under the title. Quiet and small: it
    # answers "what is this" for someone who has already read the title, so it
    # must not compete with it. COLOR_TEXT, not a legacy grey — those clear
    # 4.5:1 against no app surface in any palette.
    DETAIL_BYLINE = "font-size: " + FONT_LG + "; color: " + COLOR_TEXT + ";"
    # Episode byline — the episode title shown under the series title in episode mode.
    # Subordinate to the series title (smaller than DETAIL_TITLE) but still emphasized.
    DETAIL_EPISODE_BYLINE = "font-size: " + FONT_2XL + "; font-weight: 600; color: " + COLOR_TEXT_HI + ";"
    # Episode-mode rating chip (Wave 4 — #247) — mirrors the gold/bold star treatment
    # used for the series-level rating (_MetadataSection.rating_label in
    # details_sections.py) so per-episode and series-level ratings render identically.
    DETAIL_EPISODE_RATING = "color: " + COLOR_GOLD + "; font-weight: bold;"
    # Episode-mode air-date chip — small and muted, sits beside the rating.
    DETAIL_EPISODE_AIR_DATE = "color: " + COLOR_TEXT + "; font-size: " + FONT_SM + ";"
    DETAIL_TEXT  = "color: " + COLOR_LIGHTGRAY + ";"
    META_DIM     = "color: " + COLOR_GRAY + ";"
    LOADING_TEXT = "color: " + COLOR_GRAY + "; font-style: italic;"

    # Filter dialog / panel
    FILTER_CHECKBOX  = "QCheckBox { color: " + COLOR_TEXT + "; }"
    FILTER_ITEM_TEXT = "font-size: " + FONT_LG + ";"
    ITEM_COUNT       = "font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
    EXPAND_HINT      = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_XS + ";"
    INFO_LABEL       = "color: " + COLOR_TEXT + "; font-size: " + FONT_LG + "; padding-left: 4px; padding-top: 4px;"

    # Provider editor
    META_HINT = "color: " + COLOR_TEXT + "; font-size: " + FONT_SM + ";"
    STATUS_OK   = "color: " + COLOR_OK + "; font-size: " + FONT_LG + "; font-weight: 600;"
    STATUS_WARN = "color: " + COLOR_WARN + "; font-size: " + FONT_LG + "; font-weight: 600;"
    STATUS_ERR  = "color: " + COLOR_ERR + "; font-size: " + FONT_LG + "; font-weight: 600;"

    # Provider editor — URL-test result badge (smaller than STATUS_*)
    URL_BADGE         = "font-size: " + FONT_SM + "; font-weight: 600;"
    URL_BADGE_TESTING = "font-size: " + FONT_SM + "; color: " + COLOR_TEXT + ";"
    URL_BADGE_OK      = "font-size: " + FONT_SM + "; font-weight: 600; color: " + COLOR_OK + ";"
    URL_BADGE_ERR     = "font-size: " + FONT_SM + "; font-weight: 600; color: " + COLOR_ERR_2 + ";"
    URL_REMOVE_BTN    = (
        "QPushButton { color: " + COLOR_ERR_2 + "; border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; }"
        "QPushButton:hover { background: " + OVERLAY_ERR + "; }"
    )

    # Provider editor — icon picker
    ICON_PICK_BTN = (
        "QPushButton { font-size: " + FONT_ICON + "; border: 2px solid transparent;"
        " border-radius: " + RADIUS_SM + "; padding: 0; }"
        " QPushButton:hover { border: 2px solid " + COLOR_ACCENT_BLUE + ";"
        " background: " + OVERLAY_BLUE_15 + "; }"
    )
    ICON_PICK_BTN_SELECTED = (
        "QPushButton { font-size: " + FONT_ICON + "; border: 2px solid " + COLOR_ACCENT_BLUE + ";"
        " border-radius: " + RADIUS_SM + "; padding: 0;"
        " background: " + OVERLAY_BLUE_20 + "; }"
        " QPushButton:hover { border: 2px solid " + COLOR_ACCENT_BLUE + ";"
        " background: " + OVERLAY_BLUE_25 + "; }"
    )
    ICON_PICK_MAIN_BTN = (
        "QPushButton { font-size: " + FONT_ICON_LG + "; border: 1px solid " + OVERLAY_15 + ";"
        " border-radius: " + RADIUS_MD + "; }"
        " QPushButton:hover { border: 1px solid " + COLOR_ACCENT_BLUE + ";"
        " background: " + OVERLAY_BLUE_10 + "; }"
    )
    ICON_PICK_POPUP = (
        "QFrame { background: " + OVERLAY_POPUP + ";"
        " border: 1px solid " + OVERLAY_18 + "; border-radius: " + RADIUS_MD + "; }"
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
        "QPushButton { color: " + COLOR_ERR_2 + "; border: 1px solid " + COLOR_ERR_2 + "; border-radius: " + RADIUS_SM + "; padding: 6px " + SPACE_LG + "; }"
        "QPushButton:hover { background: " + OVERLAY_ERR_15 + "; }"
    )
    SAVE_BTN = (
        "QPushButton { background: " + COLOR_BTN_SAVE + "; color: " + COLOR_TEXT_HI + "; border-radius: " + RADIUS_SM + "; padding: 6px " + SPACE_LG + "; font-weight: 600; }"
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
        " border: none; border-radius: " + RADIUS_SM + "; padding: 5px " + SPACE_LG + "; font-weight: 600;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + COLOR_ACCENT_HOVER + "; }"
    )

    # Category / prefix chips (version chips, similar-title chips, title-area prefix badge)
    CATEGORY_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 2px 8px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_BORDER + ";"
        " background: " + OVERLAY_05 + "; }"
    )
    CATEGORY_CHIP_SM = (
        "QPushButton { font-size: " + FONT_SM + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 1px " + SPACE_SM + ";"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_BORDER + ";"
        " background: " + OVERLAY_05 + "; }"
    )
    # Quality badge in the details pane title bar (amber/gold, next to language chip)
    QUALITY_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_WARN + ";"
        " border: 1px solid " + COLOR_WARN + "; border-radius: " + RADIUS_SM + "; padding: 2px 8px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_WARN + ";"
        " background: " + OVERLAY_08 + "; }"
    )

    # Genre chips — details pane metadata genre buttons (blue / link-like, flow-layout row)
    GENRE_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_ACCENT_BLUE_2 + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 2px 8px;"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_ACCENT_BLUE_2 + ";"
        " background: " + OVERLAY_BLUE_10 + "; }"
    )

    # Variant-count badge (content-collapse Slice 2) — bottom-left overlay on poster cards.
    # Shown only when variant_count > 1; styled to be unobtrusive (muted + slight tint).
    VARIANT_BADGE = (
        "background: " + OVERLAY_BLACK_55 + "; color: " + COLOR_TEXT
        + "; border-radius: " + RADIUS_SM + "; padding: 1px 4px;"
    )

    # Separators / surfaces
    SEPARATOR_LINE = "background: " + COLOR_LINE + "; margin-top: 4px; margin-bottom: 2px;"
    SEPARATOR_H    = "border: none; border-top: 1px solid " + COLOR_LINE + "; margin: 8px 0;"
    SEP_DARK       = "color: " + COLOR_TEXT + "; margin-top: 4px; margin-bottom: 4px;"
    CARD_BG        = "QWidget { background: " + OVERLAY_03 + "; border-radius: " + RADIUS_MD + "; }"
    HEADER_TINT    = "background-color: " + OVERLAY_05 + ";"
    # Scoped variant of HEADER_TINT for sidebar section headers: an *unscoped*
    # ``background-color`` cascades onto child widgets (the title label + the flat
    # link buttons), stacking the translucent overlay into a visibly darker box.  The
    # ``#sectionHeader`` selector pins the tint to the header container only.  Applied
    # by ``_ClickableHeader`` (which sets ``objectName("sectionHeader")``).
    # OVERLAY_10, not 05: the section card sits on the DEEP ground now, and a
    # 3.5% tint over it was invisible — the header bled into the content.
    SECTION_HEADER_TINT = "#sectionHeader { background-color: " + OVERLAY_10 + "; }"
    BG_TRANSPARENT = "background: transparent;"

    # Exclusions chip (FilterChip in bottom nav bar) — three visual states.
    # Active (teal): global exclusions are enabled and applying.
    # Paused (amber): exclusions exist but are temporarily bypassed.
    # Hover and pressed fill the chip solid so feedback is visible over the text, not just in
    # the padding area. Text flips to the dark background color so contrast is maintained.
    EXCL_CHIP_ACTIVE = (
        "QPushButton { background-color: " + OVERLAY_EXCLUSIONS_10 + "; color: " + COLOR_EXCLUSIONS_ACTIVE + ";"
        " border: 1px solid " + COLOR_EXCLUSIONS_ACTIVE + "; border-radius: 12px;"
        " padding: 6px " + SPACE_LG + "; font-weight: bold; }"
        "QPushButton:hover { background-color: " + COLOR_EXCLUSIONS_ACTIVE + "; color: " + COLOR_BG_SECTION + "; }"
        "QPushButton:pressed { background-color: " + COLOR_EXCLUSIONS_ACTIVE + "; color: " + COLOR_BG_SECTION + "; }"
    )
    EXCL_CHIP_PAUSED = (
        "QPushButton { background-color: " + OVERLAY_ORANGE_10 + "; color: " + COLOR_ACCENT_ORANGE + ";"
        " border: 1px solid " + COLOR_ACCENT_ORANGE + "; border-radius: 12px;"
        " padding: 6px " + SPACE_LG + "; font-weight: bold; }"
        "QPushButton:hover { background-color: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
        "QPushButton:pressed { background-color: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
    )

    # Context filter chip — inline in the search bar when a details-pane filter is active
    # (genre click, person click). Amber/orange so it's clearly distinct from a normal search.
    CONTEXT_FILTER_CHIP = (
        "QWidget { background: " + OVERLAY_ORANGE_12 + ";"
        " border: 1px solid " + COLOR_ACCENT_ORANGE + ";"
        " border-radius: " + RADIUS_SM + "; }"
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
        " border: 1px solid " + COLOR_WARN + "; border-radius: " + RADIUS_SM + "; padding: 6px " + SPACE_MD + ";"
    )
    # Verdict headline base — color is interpolated at runtime per verdict (see dialog).
    DIAG_VERDICT_HEADLINE = "font-size: " + FONT_2XL + "; font-weight: bold;"
    # Always-visible URL line — redacted stream URL with optional episode code.
    DIAG_URL = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    # Plain-language summary paragraph under the headline.
    DIAG_SUMMARY = "color: " + COLOR_LIGHTGRAY + "; font-size: " + FONT_LG + ";"
    # Metrics block (throughput / bitrate / headroom / ttfb / codec / resolution).
    DIAG_METRICS = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    # Key column in the diagnostics technical-details grid (dim label, value beside it).
    DIAG_METRIC_KEY = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + "; font-weight: 600;"
    # Recommended-args / placeholder line.
    DIAG_RECOMMEND = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + "; font-style: italic;"
    # Saved-confirmation line after applying tuning.
    DIAG_SAVED = "color: " + COLOR_OK + "; font-size: " + FONT_MD + "; font-weight: 600;"

    # Live playback-health readout in the bottom nav bar (buffer · speed · dropped frames).
    # Dim/muted at-a-glance line; only visible while mpv is actively playing.
    NAV_HEALTH = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"

    # Discover / recommendation rows (EPG Watchlist tab)
    # DISCOVER_REC_NAME        — channel name label in a recommendation row
    # DISCOVER_REC_PILL_BTN    — "± Channel" and Play pill buttons (outlined accent pill)
    # DISCOVER_REC_SKIP_BTN    — ghost "skip" dismiss button
    # DISCOVER_REC_COUNT       — clickable "{n} matches" toggle label (pointing-hand cursor)
    # DISCOVER_REC_MATCH_ROW   — compact programme sub-row revealed on expand
    DISCOVER_REC_NAME = "font-size: " + FONT_LG + ";"
    DISCOVER_REC_PILL_BTN = (
        "QPushButton { color: " + COLOR_ACCENT_HOVER + "; font-size: " + FONT_MD + ";"
        " border: 1px solid " + COLOR_ACCENT_HOVER + "; border-radius: " + RADIUS_SM + ";"
        " padding: 1px 4px; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; background: " + OVERLAY_BLUE_15 + "; }"
    )
    # Third site of the same COLOR_MUTED_2-as-body-text pattern (2.81/2.53/1.68)
    # — see CLOSE_BTN. {neutral.8} is a BORDER step; it is not a text colour on
    # any surface, in any palette.
    DISCOVER_REC_SKIP_BTN = (
        "QPushButton { color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
        " border: none; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; }"
    )
    DISCOVER_REC_COUNT = (
        "color: " + COLOR_ACCENT + "; font-size: " + FONT_MD + "; text-decoration: underline;"
    )
    DISCOVER_REC_MATCH_ROW = "color: " + COLOR_DIM_2 + "; font-size: " + FONT_MD + "; padding-left: 4px;"

    # Shelf-row placeholder — shown in a Discover shelf's card row while a
    # lazy-expand fetch is in flight (DISCOVER_SHELF_LOADING) or after it fails
    # (DISCOVER_SHELF_ERROR). See discover_shelf.py set_loading()/show_load_error().
    # Shelf scrollbar. Thin by design: it is a position indicator here, not the
    # primary control — DISCOVER_SHELF_PAGE_BTN is, because macOS hides overlay
    # scrollbars at rest.
    DISCOVER_SHELF_SCROLLBAR = "QScrollBar:horizontal { height: 10px; }"

    # Shelf paging chevrons. macOS draws scrollbars as OVERLAYS — they appear
    # while scrolling and fade out — so ScrollBarAsNeeded leaves a shelf with no
    # visible affordance at rest and the row reads as un-scrollable. These are a
    # real control rather than a styled scrollbar, so they behave the same on
    # every platform.
    #
    # Takes the FIXED-DARK family, not a palette tint. The chevron is drawn over
    # poster artwork, so it has no known ground to borrow contrast from: a
    # translucent wash measured 3.31:1 against COLOR_TEXT_HI and the conformance
    # guard rejected it. COLOR_LIGHTBOX_BG/_TEXT_HI is the pair built for
    # exactly this — an opaque control over imagery — and it measures 16.40:1
    # identically in all six palettes because the family is theme-invariant.
    DISCOVER_SHELF_PAGE_BTN = (
        "QPushButton {"
        " background: " + COLOR_LIGHTBOX_BG + "; color: " + COLOR_LIGHTBOX_TEXT_HI + ";"
        " border: none; border-radius: 4px;"
        " font-size: " + FONT_LG + "; font-weight: 600; padding: 0px;"
        "}"
        "QPushButton:hover { background: " + COLOR_LIGHTBOX_FILL_HOVER + "; }"
    )
    DISCOVER_SHELF_LOADING = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD + "; padding: 8px 4px;"
    DISCOVER_SHELF_ERROR = "color: " + COLOR_WARN + "; font-size: " + FONT_MD + "; padding: 8px 4px;"

    # What's New dialog.  One step down the scale from where these started
    # (2XL/LG): an entry title is a card heading inside a dialog, not a view
    # title, and it was competing with the dialog's own "What's New" header —
    # which stays at 3XL and is the only thing here that should read as the
    # biggest text on screen.  The bullets follow it down to body size, which
    # is what they are.  Owner: "what's new content could be sized down
    # slightly. same with the title of the whats new entry (not the 'What's
    # New' title)".
    # The heading at the top of a dialog. Generic because a second dialog
    # (About) wanted the identical style — the moment a copy would be wrong.
    DIALOG_TITLE = (
        "font-size: " + FONT_XL + "; font-weight: bold; color: " + COLOR_TEXT_HI + ";"
    )
    # Kept as a name because the What's New call site reads better for it.
    WHATS_NEW_TITLE = DIALOG_TITLE
    WHATS_NEW_META = (
        "font-size: " + FONT_SM + "; color: " + COLOR_TEXT + ";"
    )
    WHATS_NEW_ITEM = (
        "font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
    )
    WHATS_NEW_CARD = (
        "QWidget { background: " + OVERLAY_04 + "; border: 1px solid " + COLOR_LINE + ";"
        " border-radius: " + RADIUS_MD + "; }"
    )
    # What's New carousel — navigation chevron buttons (large, monochrome, minimal border)
    WHATS_NEW_NAV_BTN = (
        "QPushButton { font-size: " + FONT_3XL + "; color: " + COLOR_TEXT + ";"
        " background: transparent; border: 1px solid " + COLOR_LINE + "; border-radius: " + RADIUS_SM + ";"
        " padding: 2px " + SPACE_MD + "; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_BORDER + "; }"
        "QPushButton:disabled { color: " + COLOR_TEXT + "; border-color: " + COLOR_LINE_DARK + "; }"
    )
    # What's New carousel — "1 / 4" position indicator label
    WHATS_NEW_POS_LABEL = (
        "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    )

    # Tag provenance + confidence chips (details pane — DR-0006 display)
    # SOURCE-GIVEN chips: solid border + slightly brighter text → "provider said so"
    TAG_CHIP_SOURCE = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 1px " + SPACE_SM + ";"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_BORDER + ";"
        " background: " + OVERLAY_05 + "; }"
    )
    # INFERRED chips: dashed border + muted text → "MetaTV guessed this"
    TAG_CHIP_INFERRED = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
        " border: 1px dashed " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 1px " + SPACE_SM + ";"
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
        "QPushButton { color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + ";"
        " padding: 3px " + SPACE_MD + "; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; border-color: " + COLOR_BORDER + "; }"
    )
    EVENTS_SEG_ACTIVE = (
        "QPushButton { color: " + COLOR_TEXT_HI + "; font-size: " + FONT_MD + "; font-weight: 600;"
        " border: 1px solid " + COLOR_ACCENT + "; border-radius: " + RADIUS_SM + ";"
        " padding: 3px " + SPACE_MD + "; background: " + OVERLAY_BLUE_15 + "; }"
    )
    # Event row group header (bold, non-selectable section label inside the list)
    EVENTS_GROUP_HEADER = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_MUTED_2 + ";"
        " letter-spacing: 1px; padding: 4px " + SPACE_XS + " 2px " + SPACE_XS + ";"
    )
    # Time/availability hint label on each event row
    EVENTS_TIME_HINT = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    EVENTS_TIME_HINT_PASSED = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    EVENTS_TIME_ON_NOW = "color: " + COLOR_OK + "; font-size: " + FONT_MD + "; font-weight: 600;"

    # WeightedTagCloud — role-named semantic constants
    # Count badge next to each tag value (small, muted, non-clickable)
    CLOUD_COUNT = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_SM + ";"
    # State-mark prefix on include-state tags (green checkmark)
    CLOUD_INCLUDE_MARK = "color: " + COLOR_OK + ";"
    # State-mark prefix on exclude-state tags (orange/red ⊘)
    CLOUD_EXCLUDE_MARK = "color: " + COLOR_WARN + ";"
    # Header label for the tag cloud ("Genre · N values · sized by catalogue weight")
    CLOUD_HEADER_LABEL = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
    # Sort-toggle and filter search controls in the cloud header
    CLOUD_CTRL_BTN = (
        "QPushButton { font-size: " + FONT_SM + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 1px " + SPACE_SM + ";"
        " background: transparent; }"
        "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_BORDER + "; }"
        "QPushButton:checked { color: " + COLOR_ACCENT + "; border-color: " + COLOR_ACCENT + "; }"
    )
    # "+N more" expand button at the tail of the cloud
    CLOUD_MORE_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_TEXT + ";"
        " font-size: " + FONT_MD + "; padding: 4px " + SPACE_XS + "; text-align: left; }"
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
        " text-align: left; padding: 5px 8px; border-radius: " + RADIUS_SM + "; }"
        "QPushButton:hover { background: " + OVERLAY_05 + "; }"
    )

    # A facet row in the pantry — selected/active state
    RECIPE_FACET_ROW_SELECTED = (
        "QPushButton { border: none; background: " + OVERLAY_RECIPE_SELECTED + ";"
        " color: " + COLOR_RECIPE_TEXT + "; font-size: " + FONT_MD + ";"
        " text-align: left; padding: 5px 8px; border-radius: " + RADIUS_SM + ";"
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
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 2px 8px;"
        " background: " + OVERLAY_05 + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; }"
    )

    # An omit (exclude) chip — strikethrough appearance via text decoration
    RECIPE_OMIT_CHIP = (
        "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_WARN + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 2px 8px;"
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
        " border-radius: " + RADIUS_SM + "; padding: 6px " + SPACE_LG + "; font-weight: 600; font-size: " + FONT_MD + "; }"
        "QPushButton:disabled { background: " + COLOR_LINE + "; color: " + COLOR_MUTED_2 + "; }"
    )

    # Clear button — ghost style
    RECIPE_CLEAR_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_TEXT + "; border-radius: " + RADIUS_SM + "; padding: 6px " + SPACE_LG + ";"
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
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_MD + "; }"
    )

    # "· N values" subtitle beside a cluster's facet header.
    RECIPE_CLUSTER_SUBTITLE = (
        "color: " + COLOR_RECIPE_MUTED_2 + "; font-size: " + FONT_SM + ";"
    )

    # Collapsible "▸ More facets" section toggle at the foot of the cluster grid.
    RECIPE_MORE_FACETS_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_RECIPE_MUTED + ";"
        " font-size: " + FONT_SM + "; font-weight: bold; letter-spacing: 1px;"
        " text-align: left; padding: 6px " + SPACE_XS + "; }"
        "QPushButton:hover { color: " + COLOR_RECIPE_TEXT + "; }"
    )

    # Column-1 collapse/expand chevron (hides the Tonight's-Recipe rail to widen the grid).
    RECIPE_COL1_CHEVRON = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_RECIPE_MUTED + ";"
        " font-size: " + FONT_MD + "; padding: 2px 4px; }"
        "QPushButton:hover { color: " + COLOR_RECIPE_TEXT + "; background: " + OVERLAY_05 + ";"
        " border-radius: " + RADIUS_SM + "; }"
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
        "QPushButton { border: none; background: transparent; color: " + COLOR_TEXT + ";"
        " font-size: " + FONT_XL + "; font-weight: 600; padding: 5px 16px; border-radius: " + RADIUS_MD + "; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; }"
    )
    RECIPE_TAB_ACTIVE = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: " + COLOR_BG_CARD + ";"
        " color: " + COLOR_TEXT_HI + "; font-size: " + FONT_XL + "; font-weight: 600;"
        " padding: 5px 16px; border-radius: " + RADIUS_MD + "; }"
    )
    # Small right-aligned hint next to the tabs.
    RECIPE_TABBAR_HINT = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"

    # "BROWSE BY FACET" uppercase section header above the masonry grid.
    RECIPE_BROWSE_HDR = (
        "font-size: " + FONT_MD + "; font-weight: 600; color: " + COLOR_TEXT + ";"
        " letter-spacing: 1.4px;"
    )

    # The slim one-line recipe "sentence" bar dividing the grid from Matching Content.
    RECIPE_BAR_BG = (
        "QWidget#recipeBar { background: " + COLOR_RECIPE_PANEL_BG + ";"
        " border-top: 1px solid " + COLOR_BORDER + "; border-bottom: 1px solid " + COLOR_BORDER + "; }"
    )
    RECIPE_BAR_LABEL = (
        "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_TEXT + ";"
        " letter-spacing: 1.6px;"
    )
    RECIPE_BAR_EMPTY = (
        "color: " + COLOR_TEXT + "; font-size: " + FONT_LG + "; font-style: italic;"
    )
    RECIPE_BAR_OP = "color: " + COLOR_TEXT + "; font-size: " + FONT_LG + "; font-weight: 600;"
    RECIPE_BAR_YIELD = (
        "font-size: " + FONT_LG + "; color: " + COLOR_TEXT + ";"
    )
    # Save (gold, primary) + Clear (ghost) actions on the recipe bar.
    RECIPE_BAR_SAVE_BTN = (
        "QPushButton { border: 1px solid " + COLOR_GOLD + "; background: transparent;"
        " color: " + COLOR_GOLD + "; font-size: " + FONT_LG + "; font-weight: 600;"
        " padding: 5px " + SPACE_MD + "; border-radius: " + RADIUS_MD + "; }"
        "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_GOLD_LIGHT + "; }"
        "QPushButton:disabled { border-color: " + COLOR_LINE + "; color: " + COLOR_MUTED_2 + "; }"
    )
    RECIPE_BAR_CLEAR_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_TEXT + ";"
        " font-size: " + FONT_LG + "; font-weight: 600; padding: 5px " + SPACE_MD + "; border-radius: " + RADIUS_MD + "; }"
        "QPushButton:hover { color: " + COLOR_TEXT + "; background: " + OVERLAY_05 + "; }"
        "QPushButton:disabled { color: " + COLOR_MUTED_2 + "; }"
    )

    # "MATCHING CONTENT" shelf header + "preview · N total" subtitle.
    RECIPE_MATCH_HDR = (
        "font-size: " + FONT_LG + "; font-weight: bold; color: " + COLOR_TEXT + ";"
        " letter-spacing: 1.3px;"
    )
    RECIPE_MATCH_SUB = "font-size: " + FONT_LG + "; color: " + COLOR_TEXT + ";"
    # "Show all →" link (flat blue accent, shared by shelf header).
    RECIPE_SHOW_ALL_BTN = (
        "QPushButton { color: " + COLOR_ACCENT_BLUE + "; border: none;"
        " font-size: " + FONT_LG + "; font-weight: 600; padding: 2px " + SPACE_SM + "; }"
        "QPushButton:hover { color: " + COLOR_GOLD + "; }"
    )

    # Saved tab — subtitle + recipe card frame + editable name + count line.
    RECIPE_SAVED_SUB = "color: " + COLOR_TEXT + "; font-size: " + FONT_XL + ";"
    RECIPE_SAVED_CARD = (
        "QFrame#savedRecipeCard { background: " + COLOR_RECIPE_PANEL_BG + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: 12px; }"
        "QFrame#savedRecipeCard:hover { border-color: " + COLOR_BORDER + "; }"
    )
    RECIPE_SAVED_NAME_EDIT = (
        "QLineEdit { border: none; background: transparent; color: " + COLOR_TEXT_HI + ";"
        " font-size: " + FONT_2XL + "; font-weight: 600; padding: 0; }"
        "QLineEdit:focus { border-bottom: 1px solid " + COLOR_BORDER + "; }"
    )
    RECIPE_SAVED_COUNT = "font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
    # Generic muted empty/loading placeholder text (saved-empty, grid-loading, no-matches).
    RECIPE_EMPTY_HINT = (
        "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_XL + "; padding: 8px " + SPACE_XS + ";"
    )
    # Small icon button on a saved card (delete / load) — faint, hover-lit.
    RECIPE_SAVED_ICON_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_TEXT + ";"
        " font-size: " + FONT_XL + "; padding: 2px " + SPACE_XS + "; border-radius: " + RADIUS_SM + "; }"
        "QPushButton:hover { color: " + COLOR_TEXT_HI + "; background: " + OVERLAY_10 + "; }"
    )


    # ── Dev-only QA Testing Checklist — tri-state pass/fail ───────────────────────
    # Pass/fail toggle buttons.  Each has an inactive (ghost) and active state; the
    # active state tints to the OK (green) / ERR (red) palette so the chosen state
    # reads at a glance.  Composed from existing tokens — no new colour literals.
    QA_PASS_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_TEXT + "; border-radius: " + RADIUS_SM + "; padding: 0 8px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + "; }"
    )
    QA_PASS_BTN_ACTIVE = (
        "QPushButton { border: 1px solid " + COLOR_OK + "; background: " + OVERLAY_GREEN_15 + ";"
        " color: " + COLOR_OK + "; border-radius: " + RADIUS_SM + "; padding: 0 8px;"
        " font-size: " + FONT_MD + "; font-weight: bold; }"
    )
    QA_FAIL_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_TEXT + "; border-radius: " + RADIUS_SM + "; padding: 0 8px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_ERR_2 + "; }"
    )
    QA_FAIL_BTN_ACTIVE = (
        "QPushButton { border: 1px solid " + COLOR_ERR_2 + "; background: " + OVERLAY_ERR2_15 + ";"
        " color: " + COLOR_ERR_2 + "; border-radius: " + RADIUS_SM + "; padding: 0 8px;"
        " font-size: " + FONT_MD + "; font-weight: bold; }"
    )

    # Fail comment box — revealed beneath a failed step.
    QA_FAIL_NOTE_BOX = (
        "QPlainTextEdit { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_ERR_2 + "; border-radius: " + RADIUS_SM + "; padding: 4px;"
        " font-size: " + FONT_MD + "; }"
    )

    # Attachment chip — small removable label for a saved screenshot / log path.
    QA_ATTACHMENT_CHIP = (
        "QPushButton { background: " + OVERLAY_05 + "; color: " + COLOR_TEXT + ";"
        " border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 0 6px;"
        " font-size: " + FONT_SM + "; }"
        "QPushButton:hover { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_ERR_2 + "; }"
    )
    QA_ATTACH_BTN = (
        "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
        " color: " + COLOR_TEXT + "; border-radius: " + RADIUS_SM + "; padding: 0 8px;"
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
        " color: " + COLOR_ACCENT_BLUE + "; border-radius: " + RADIUS_SM + "; padding: 0 8px;"
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
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; }"
    )
    LIGHTBOX_HEADER_BAR = (
        "background: " + COLOR_LIGHTBOX_HEADER + "; border-radius: 12px 12px 0 0;"
    )
    LIGHTBOX_FOOTER_BAR = (
        "background: " + COLOR_LIGHTBOX_HEADER + "; border-radius: 0 0 12px 12px;"
    )
    LIGHTBOX_BACK_BTN = (
        "QPushButton { color: " + COLOR_LIGHTBOX_LINK + "; font-size: " + FONT_XL + ";"
        " font-weight: bold; border: none; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    LIGHTBOX_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_2XL + "; font-weight: bold;"
    )
    LIGHTBOX_COUNTER = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_LG + ";"
    LIGHTBOX_CLOSE_BTN = (
        "QPushButton { color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_3XL + ";"
        " border: none; background: transparent; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    # Round prev/next chevron flanking the card (used 2×).
    LIGHTBOX_CHEVRON = (
        "QPushButton { color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_4XL + ";"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; border-radius: 22px;"
        " background: " + COLOR_LIGHTBOX_BG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_LIGHTBOX_ACCENT + "; }"
        "QPushButton:disabled { color: " + COLOR_LIGHTBOX_LINE + "; border-color: " + COLOR_LIGHTBOX_LINE + "; }"
    )

    # Hero — poster slot + future-player affordance
    LIGHTBOX_POSTER_SLOT = (
        "#lightbox_poster { background: " + COLOR_LIGHTBOX_SUNKEN + "; border-radius: 9px;"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; }"
    )
    LIGHTBOX_POSTER_PLACEHOLDER = (
        "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_LG + ";"
    )

    # Primary Play button under the poster (filled accent, dark text).
    LIGHTBOX_PLAY_PRIMARY = (
        "QPushButton { background: " + COLOR_LIGHTBOX_FILL + "; color: " + COLOR_LIGHTBOX_ON_FILL + ";"
        " border: none; border-radius: 9px; padding: 9px 12px; font-size: " + FONT_XL + ";"
        " font-weight: bold; }"
        "QPushButton:hover { background: " + COLOR_LIGHTBOX_FILL_HOVER + "; }"
    )
    # Secondary action button (Queue / Favorite / Hide) — outline, checkable-friendly.
    LIGHTBOX_ACTION_BTN = (
        "QPushButton { border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; background: " + COLOR_LIGHTBOX_HEADER + ";"
        " color: " + COLOR_LIGHTBOX_TEXT + "; border-radius: 9px; padding: 8px 12px;"
        " font-size: " + FONT_LG + "; font-weight: bold; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_LIGHTBOX_ACCENT + "; }"
    )

    # Right column typography
    LIGHTBOX_HEADING = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_3XL + "; font-weight: bold;"
    )
    LIGHTBOX_META = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_XL + ";"
    LIGHTBOX_STAR = "color: " + COLOR_LIGHTBOX_GOLD + "; font-size: " + FONT_XL + "; font-weight: bold;"
    LIGHTBOX_SOURCE = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_LG + ";"
    # ×N versions badge on the meta line (used when >1 content_key sibling).
    LIGHTBOX_VERSION_BADGE = (
        "background: " + OVERLAY_BLUE_15 + "; color: " + COLOR_LIGHTBOX_LINK + ";"
        " border: 1px solid " + COLOR_LIGHTBOX_ACCENT + "; border-radius: " + RADIUS_MD + ";"
        " padding: 1px " + SPACE_SM + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )

    # Genre chips — DISPLAY ONLY here (not clickable-to-Recipe yet); no hover affordance.
    LIGHTBOX_GENRE_CHIP = (
        "background: " + OVERLAY_BLUE_10 + "; color: " + COLOR_LIGHTBOX_LINK + ";"
        " border-radius: 10px; padding: 3px " + SPACE_MD + "; font-size: " + FONT_LG + ";"
    )

    # Section sub-heading (OVERVIEW / CAST & CREW / OTHER VERSIONS / SIMILAR TITLES).
    LIGHTBOX_SECTION_HDR = (
        "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " letter-spacing: 1px;"
    )
    LIGHTBOX_PLOT = "color: " + COLOR_LIGHTBOX_TEXT + "; font-size: " + FONT_XL + ";"
    LIGHTBOX_CAST = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_LG + ";"

    # ── Facet lens: the header's exit link + the empty-result notice ─────────
    # A cast/genre click re-seeds the overlay with that facet's titles. The
    # HEADER already names the lens ("With Nicolas Cage") and the breadcrumb
    # already shows the anchor it was opened from, so there is no separate
    # label: an earlier cut repeated the name in a full-width bordered strip
    # that read as a disabled text input. What is left is the one thing neither
    # of those says — the explicit way out to the channel list, which sits in
    # the header beside the name it applies to.
    LIGHTBOX_LENS_LINK = (
        "QPushButton { background: transparent; color: " + COLOR_LIGHTBOX_LINK + ";"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; border-radius: 9px;"
        " padding: 4px " + SPACE_MD + "; font-size: " + FONT_MD + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + ";"
        " border-color: " + COLOR_LIGHTBOX_ACCENT + "; }"
    )
    # Transient notice under the header, used when a click produced NOTHING —
    # the one case with no navigation to act as its own feedback.
    LIGHTBOX_NOTICE_BAR = (
        "background: " + COLOR_LIGHTBOX_SUNKEN + ";"
        " border-bottom: 1px solid " + COLOR_LIGHTBOX_LINE + ";"
    )
    LIGHTBOX_NOTICE_TEXT = (
        "background: transparent; color: " + COLOR_LIGHTBOX_MUTED + ";"
        " font-size: " + FONT_MD + ";"
    )

    # Other Versions row (used N×) — a full-width entry in the hero's vertical, scrollable
    # list showing the friendly "<source> · <quality/region>" label plus an optional
    # source-icon glyph; the full "<name> · <source>" lives in the tooltip. Click dives to
    # that variant. A runtime provider colour (``ProviderDB.color``) may be injected as a
    # left-border source badge in code (via :func:`lightbox_version_row`); the label text
    # is always present, so the row never distinguishes by colour alone.
    LIGHTBOX_VERSION_ROW = (
        "QPushButton { text-align: left; background: transparent; color: " + COLOR_LIGHTBOX_TEXT + ";"
        " border: none; border-bottom: 1px solid " + COLOR_LIGHTBOX_LINE + "; padding: 6px 8px;"
        " font-size: " + FONT_MD + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; background: " + COLOR_LIGHTBOX_SUNKEN + "; }"
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
        "#lightbox_sim_poster { background: " + COLOR_LIGHTBOX_SUNKEN + "; border-radius: " + RADIUS_MD + ";"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; color: " + COLOR_LIGHTBOX_TEXT + ";"
        " font-size: " + FONT_MD + "; }"
    )
    LIGHTBOX_SIM_NAME = "color: " + COLOR_LIGHTBOX_TEXT + "; font-size: " + FONT_LG + ";"
    LIGHTBOX_SIM_YEAR = "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_MD + ";"

    # Language/region chip — the ONE canonical bordered chip shared by the sim-badge
    # renderer (lightbox strip + trail-map rows, via ``sim_badges.make_sim_badges``) and
    # the trail-map detail strip, so the lang/region badge reads identically everywhere
    # (single source of truth — no per-surface lang style).
    # COLOR_ACCENT_BLUE, not COLOR_LIGHTBOX_LINK. The LIGHTBOX_* family is the
    # FIXED-DARK cinema surface's own palette — chosen to be legible on a panel
    # that is dark in every theme. This chip is not on that panel; it is on the
    # app surface, which is CREAM in the light themes. The result measured
    # 1.36:1 in Daylight and 1.23:1 in Gruvbox Light — the sidebar's language
    # chips have been effectively invisible in the light theme since it shipped.
    # It reads fine in the results list because that is painted by the row
    # delegate from its own COLOR_ROW_* tokens and never touches this role.
    LANG_CHIP = (
        "background: " + OVERLAY_BLUE_10 + "; color: " + COLOR_ACCENT_BLUE + ";"
        " border-radius: " + RADIUS_MD + "; padding: 1px " + SPACE_SM + "; font-size: " + FONT_MD + ";"
    )

    # Similar-strip mini-card badge cluster — a compact meta line (language/region +
    # rating) above a state-glyph line (liked / in Watch Later / favorited / watched),
    # mirroring the badges the details-pane Similar rows show.  Colours match those
    # surfaces (blue like/queue, gold favorite/rating, green watched); each glyph also
    # carries a tooltip, so state is never conveyed by colour alone.  (Language uses the
    # shared ``LANG_CHIP`` above.)
    LIGHTBOX_SIM_RATING        = "color: " + COLOR_LIGHTBOX_GOLD + "; font-size: " + FONT_MD + "; font-weight: bold;"
    LIGHTBOX_SIM_GLYPH_LIKE    = "color: " + COLOR_LIGHTBOX_ACCENT + "; font-size: " + FONT_MD + ";"
    LIGHTBOX_SIM_GLYPH_QUEUE   = "color: " + COLOR_LIGHTBOX_ACCENT + "; font-size: " + FONT_MD + ";"
    LIGHTBOX_SIM_GLYPH_FAV     = "color: " + COLOR_LIGHTBOX_GOLD + "; font-size: " + FONT_MD + ";"
    LIGHTBOX_SIM_GLYPH_WATCHED = "color: " + COLOR_LIGHTBOX_OK + "; font-size: " + FONT_MD + ";"

    # Footer keyboard-hint kbd chip (used N×).
    LIGHTBOX_KBD = (
        "background: " + COLOR_LIGHTBOX_SUNKEN + "; color: " + COLOR_LIGHTBOX_TEXT + ";"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; border-radius: " + RADIUS_SM + "; padding: 1px " + SPACE_SM + ";"
        " font-size: " + FONT_MD + ";"
    )
    # Explicit transparent background: these labels carry their own stylesheet,
    # and a stylesheet-bearing QLabel paints the palette background unless told
    # otherwise — on Daylight that is a light box on the dark cinema bar.
    LIGHTBOX_FOOTER_HINT = (
        "background: transparent; color: " + COLOR_LIGHTBOX_MUTED + ";"
        " font-size: " + FONT_MD + ";"
    )

    # ── Explore trail-map (cascading columns + detail strip) ─────────────────────
    # Role constants for ``trail_map_view.py`` / ``trail_map_detail.py``.  Same
    # FIXED-DARK cinema surface as the preview overlay (owner: propagate the
    # lightbox styling app-wide), so — like that family — every colour here comes
    # from the fixed COLOR_LIGHTBOX_* set, never a palette-tuned token. Measured
    # against the shell they actually paint on, the palette-tuned ones collapsed
    # in Daylight: the "here" tag was white-on-white (1.03:1), the watched badges
    # 1.33/1.44:1, the header link 1.24:1, and the thumb/poster wells rendered as
    # white boxes. tests/test_cinema_surface_contrast.py measures them.

    # Shell + header
    TRAILMAP_SHELL = (
        "#trailmap_shell { background: " + COLOR_LIGHTBOX_BG + "; border-radius: 12px;"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; }"
    )
    TRAILMAP_HEADER_BAR = (
        "background: " + COLOR_LIGHTBOX_HEADER + "; border-radius: 12px 12px 0 0;"
    )
    TRAILMAP_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_2XL + "; font-weight: bold;"
    )
    TRAILMAP_SUBTITLE = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_LG + ";"
    TRAILMAP_CLOSE_BTN = LIGHTBOX_CLOSE_BTN
    # Flat "collapse branches" link button in the header.
    TRAILMAP_LINK_BTN = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_LIGHTBOX_LINK + ";"
        " font-size: " + FONT_LG + "; padding: 3px " + SPACE_SM + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )

    # Columns
    TRAILMAP_COLUMN = (
        "#trailmap_col { background: transparent;"
        " border-right: 1px solid " + COLOR_LIGHTBOX_LINE + "; }"
    )
    TRAILMAP_TRAIL_COLUMN = (
        "#trailmap_col { background: " + OVERLAY_03 + ";"
        " border-right: 2px solid " + COLOR_LIGHTBOX_BORDER + "; }"
    )
    TRAILMAP_COLHEAD = (
        "background: transparent; border-bottom: 1px solid " + COLOR_LIGHTBOX_LINE + ";"
    )
    TRAILMAP_COLHEAD_KICKER = (
        "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " letter-spacing: 1px;"
    )
    TRAILMAP_COLHEAD_NAME = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    TRAILMAP_COLHINT = (
        "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_SM + ";"
        " border-top: 1px solid " + COLOR_LIGHTBOX_LINE + ";"
    )

    # Rows (custom QWidget; needs WA_StyledBackground). Two states applied in code —
    # each carries its own :hover so hover works in both.
    TRAILMAP_ROW = (
        "#trailmap_row { background: transparent; border-radius: " + RADIUS_MD + "; }"
        "#trailmap_row:hover { background: " + OVERLAY_05 + "; }"
    )
    TRAILMAP_ROW_SELECTED = (
        "#trailmap_row { background: " + OVERLAY_BLUE_15 + "; border-radius: " + RADIUS_MD + ";"
        " border-left: 2px solid " + COLOR_LIGHTBOX_ACCENT + "; }"
    )
    TRAILMAP_THUMB = (
        "#trailmap_thumb { background: " + COLOR_LIGHTBOX_SUNKEN + "; border-radius: " + RADIUS_SM + ";"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; color: " + COLOR_LIGHTBOX_FAINT + ";"
        " font-size: " + FONT_LG + "; }"
    )
    TRAILMAP_ROW_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    TRAILMAP_ROW_YEAR = "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_SM + ";"
    TRAILMAP_ROW_CHEVRON = "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_XL + ";"
    TRAILMAP_TRAIL_NUM = "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_SM + ";"
    # "here" tag on the current (last) trail stop.
    TRAILMAP_HERE_TAG = (
        "background: " + COLOR_LIGHTBOX_TEXT_HI + "; color: " + COLOR_LIGHTBOX_BG + ";"
        " border-radius: " + RADIUS_SM + "; padding: 0 4px; font-size: " + FONT_XS + "; font-weight: bold;"
    )

    # Detail strip
    TRAILMAP_DETAIL = (
        "#trailmap_detail { background: " + COLOR_LIGHTBOX_SUNKEN + ";"
        " border-top: 1px solid " + COLOR_LIGHTBOX_LINE + "; }"
    )
    TRAILMAP_DETAIL_POSTER = (
        "#trailmap_detail_poster { background: " + COLOR_LIGHTBOX_SUNKEN + "; border-radius: " + RADIUS_MD + ";"
        " border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; color: " + COLOR_LIGHTBOX_FAINT + ";"
        " font-size: " + FONT_LG + "; }"
    )
    # Corner "mark watched" badge on the detail poster — 3 states (base / partial / done);
    # shape+glyph carry meaning, colour reinforces (colour-not-alone).
    TRAILMAP_WBADGE = (
        "QPushButton { border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; border-radius: 11px;"
        " background: " + COLOR_LIGHTBOX_BG + "; color: " + COLOR_LIGHTBOX_FAINT + ";"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_LIGHTBOX_OK + "; }"
    )
    TRAILMAP_WBADGE_DONE = (
        "QPushButton { border: 1px solid " + COLOR_LIGHTBOX_OK + "; border-radius: 11px;"
        " background: " + COLOR_LIGHTBOX_BG + "; color: " + COLOR_LIGHTBOX_OK + ";"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    TRAILMAP_WBADGE_PARTIAL = (
        "QPushButton { border: 1px solid " + COLOR_LIGHTBOX_WARN + "; border-radius: 11px;"
        " background: " + COLOR_LIGHTBOX_BG + "; color: " + COLOR_LIGHTBOX_WARN + ";"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    TRAILMAP_DETAIL_TITLE = (
        "color: " + COLOR_LIGHTBOX_TEXT_HI + "; font-size: " + FONT_3XL + "; font-weight: bold;"
    )
    TRAILMAP_DETAIL_YEAR = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_2XL + ";"
    # Favourite title-star (☆→★) — persistent, gold when on (NOT a rail button).
    TRAILMAP_FAV_STAR = (
        "QPushButton { border: none; background: transparent; color: " + COLOR_LIGHTBOX_FAINT + ";"
        " font-size: " + FONT_4XL + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_GOLD + "; }"
        "QPushButton:checked { color: " + COLOR_LIGHTBOX_GOLD + "; }"
    )
    TRAILMAP_DETAIL_META = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_LG + ";"
    TRAILMAP_DETAIL_STAR = (
        "color: " + COLOR_LIGHTBOX_GOLD + "; font-size: " + FONT_LG + "; font-weight: bold;"
    )
    TRAILMAP_SECTION_HDR = (
        "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_SM + "; font-weight: bold;"
        " letter-spacing: 1px;"
    )
    TRAILMAP_OVERVIEW = "color: " + COLOR_LIGHTBOX_TEXT + "; font-size: " + FONT_LG + ";"
    TRAILMAP_CREW = "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_LG + ";"
    TRAILMAP_PLAY_BTN = LIGHTBOX_PLAY_PRIMARY
    # Secondary outline link buttons (↗ Open in details, ✦ Make recipe).
    TRAILMAP_DETAIL_LINK_BTN = (
        "QPushButton { border: 1px solid " + COLOR_LIGHTBOX_BORDER + "; background: transparent;"
        " color: " + COLOR_LIGHTBOX_TEXT + "; border-radius: " + RADIUS_MD + "; padding: 6px " + SPACE_MD + ";"
        " font-size: " + FONT_LG + "; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; border-color: " + COLOR_LIGHTBOX_LINK + "; }"
    )
    TRAILMAP_EMPTY_HINT = "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_LG + ";"

    # Explore views (embedded trail-map: History / Favorites / Watch Queue / Recommended):
    # opaque backing so the transient loading / empty state is not a see-through gap over
    # the content area.  One role constant shared by every Explore entry point.
    EXPLORE_VIEW_BG = "#exploreView { background: " + COLOR_LIGHTBOX_BG + "; }"
    EXPLORE_STATUS = (
        "color: " + COLOR_LIGHTBOX_MUTED + "; font-size: " + FONT_XL + ";"
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
    # These render INSIDE the lightbox header, so they belong to the fixed
    # cinema family like the rest of it — they were still on the app-surface
    # ramp (COLOR_MUTED/COLOR_TEXT/COLOR_MUTED_2), which put the separator at
    # 2.2:1 in every theme and the current crumb at 2.4:1 in Daylight.
    LIGHTBOX_BREADCRUMB_CRUMB = (
        "QPushButton { color: " + COLOR_LIGHTBOX_LINK + "; font-size: " + FONT_SM + ";"
        " border: none; background: transparent; padding: 0 2px; text-align: left; }"
        "QPushButton:hover { color: " + COLOR_LIGHTBOX_TEXT_HI + "; }"
    )
    LIGHTBOX_BREADCRUMB_CURRENT = (
        "color: " + COLOR_LIGHTBOX_TEXT + "; font-size: " + FONT_SM + ";"
    )
    LIGHTBOX_BREADCRUMB_SEP = (
        "color: " + COLOR_LIGHTBOX_FAINT + "; font-size: " + FONT_SM + ";"
    )

    # Shared QProgressBar role (background enrichment queue view; migration_progress_widget.py
    # still builds its own inline — left alone, out of scope for this addition).
    PROGRESS_BAR = (
        "QProgressBar { border: 1px solid " + COLOR_BORDER + "; border-radius: " + RADIUS_SM + ";"
        " background: " + COLOR_LINE + "; text-align: center; color: " + COLOR_TEXT_HI + ";"
        " font-size: " + FONT_SM + "; }"
        "QProgressBar::chunk { background: " + COLOR_ACCENT_BLUE + "; border-radius: " + RADIUS_SM + "; }"
    )

    return {k: v for k, v in dict(locals()).items() if not k.startswith("_")}


globals().update(_build_semantic_constants())
# Role groups that live in their own module. `theme.py` is on a shrink-only
# ratchet, and a semantic constant is a pure function of the tokens — so a new
# family composes itself from the token globals and merges in here, the same
# way tokens/scales.py keeps the radius and spacing scales out of this file.
# Both this call and apply_theme's rebuild must run, or a theme switch would
# leave these roles on the old palette.
globals().update(_chip_roles.build(globals()))
globals().update(_detail_roles.build(globals()))


def _relative_luminance(value: str) -> float:
    """WCAG 2.1 relative luminance of a ``#rgb``/``#rrggbb`` colour."""
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def on_fill(fill: str) -> str:
    """The legible text colour for something painted ON a solid *fill*.

    The one definition of "what colour goes on top of this". Hardcoding
    ``white`` was the bug this replaces: the accent/status fills invert between
    the light and dark palettes, so a fixed foreground is wrong in one of them
    — white on Midnight's mint ``COLOR_OK`` measured 1.88:1, and white on the
    orange PPV accent 2.51:1, in the theme most people run.

    Picks whichever of the two fixed on-fill tokens contrasts more, so the
    answer follows the FILL rather than the palette. Callers pass a resolved
    colour, so this composes with runtime fills (a provider's colour, a quality
    hue) as readily as with a token.

    Args:
        fill: The background this text sits on, as ``#rgb``/``#rrggbb``.

    Returns:
        ``COLOR_ON_FILL_DARK`` or ``COLOR_ON_FILL_LIGHT``.
    """
    fill_lum = _relative_luminance(fill)
    def _contrast(fg: str) -> float:
        fg_lum = _relative_luminance(fg)
        hi, lo = max(fg_lum, fill_lum), min(fg_lum, fill_lum)
        return (hi + 0.05) / (lo + 0.05)
    return max(
        (COLOR_ON_FILL_DARK, COLOR_ON_FILL_LIGHT), key=_contrast
    )


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
    # Base is the background of every item view and text field — the results
    # list above all. It read COLOR_LINE, which is a HAIRLINE token
    # (outline.subtle): in Midnight that is #363a3f, so the channel list sat on
    # a mid-grey slab noticeably LIGHTER than the app around it, and the
    # separator colour was doing a job no separator colour can do. A resting
    # surface must be a surface token. surface.dim (COLOR_BG_DEEP) puts the list
    # a step BELOW the surrounding chrome — content recessed into the shell
    # rather than floating on top of it — and stays distinct from
    # COLOR_BG_SECTION so the panel edge is still readable without a border.
    palette.setColor(QPalette.ColorRole.Base, QColor(COLOR_BG_DEEP))
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


def _repolish_all_widgets() -> int:
    """Force every existing widget to re-read the palette. Returns the count.

    The palette push in :func:`_sync_qt_application_palette` updates what
    widgets *resolve*, but Qt does not automatically re-render item-view
    backgrounds and other style-computed surfaces for widgets that already
    exist. Cold launch looked correct only because ``apply_theme`` runs before
    any widget is constructed (``__main__.py``) — a LIVE switch left the channel
    list and sidebar lists painted in the previous palette, which in Daylight
    read as dark panels under light chrome (owner report, confirmed by "when I
    restart the app in daylight theme, the backgrounds are correct").

    ``unpolish``/``polish`` is Qt's supported way to make a widget recompute
    style-derived values. Uses ``QApplication.allWidgets()`` rather than a
    maintained list — the enumeration problem the style registry exists to
    avoid applies here too, and a theme switch is a rare, user-initiated action
    where walking every widget once is cheap.
    """
    app = QApplication.instance()
    if app is None:
        return 0
    count = 0
    for widget in app.allWidgets():
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        except RuntimeError:
            # The C++ object is gone while the Python wrapper lingers.
            continue
        count += 1
    return count


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


# --------------------------------------------------------------------------- #
#  Palette-difference rewrite — the floor under COMPOSED stylesheets           #
# --------------------------------------------------------------------------- #
#
# style()/style_fn() cover widgets that opted in. ~370 call sites still build a
# stylesheet by f-string and hand it straight to setStyleSheet(), and Qt caches
# the RENDERED string, so those keep painting the previous palette after a
# switch. Converting them one by one is ~300 edits across every screen, each an
# opportunity for a late-binding closure bug — and it would fix only the sites
# that existed the day it was done.
#
# Instead: after the tokens rebind, compute what each *colour value* became, and
# rewrite those substrings wherever they still appear. A stylesheet built from
# COLOR_BG literally contains COLOR_BG's old value, whatever expression produced
# it — so this reaches every composed sheet, including ones not yet written.
#
# Two guards keep it from rewriting something it shouldn't:
#
#   * **Ambiguity** — if one old value maps to two different new values, there is
#     no single right answer, so it is skipped rather than guessed at.
#   * **Invariance** — some tokens are deliberately theme-INVARIANT (the mood
#     chips, COLOR_QUALITY_*, the lightbox family, which sit over photographic
#     posters). If an invariant token holds the same value some variable token
#     used to hold, rewriting that value would silently re-theme the thing that
#     was pinned on purpose. Those values are excluded outright.

_COLOR_TOKEN_PREFIXES: tuple[str, ...] = ("COLOR_", "OVERLAY_")

# A hex colour must not be rewritten when it is the prefix of a longer one
# (#fff inside #ffffff), and rgba(...) values are matched whole.
_HEX_TAIL_RE = re.compile(r"[0-9A-Fa-f]")


def _color_token_snapshot() -> dict[str, str]:
    """Current value of every string-valued colour token, by token name."""
    return {
        name: value
        for name, value in globals().items()
        if name.startswith(_COLOR_TOKEN_PREFIXES) and isinstance(value, str) and value
    }


def _build_palette_rewrite_map(
    before: dict[str, str], after: dict[str, str]
) -> dict[str, str]:
    """Return ``{old_value: new_value}`` for colour values that can be rewritten safely.

    Args:
        before: Token name → value snapshot taken BEFORE the palette switch.
        after:  The same snapshot taken after.

    Returns:
        A substitution map with ambiguous and theme-invariant values removed.
    """
    # Values held by a token that did NOT change are pinned on purpose.
    invariant: set[str] = {
        old for name, old in before.items() if after.get(name) == old
    }

    candidates: dict[str, set[str]] = {}
    for name, old in before.items():
        new = after.get(name)
        if new is None or new == old:
            continue
        candidates.setdefault(old, set()).add(new)

    return {
        old: next(iter(news))
        for old, news in candidates.items()
        if len(news) == 1 and old not in invariant
    }


def _widget_rewrite_map(widget) -> dict[str, str] | None:
    """Old→new substitutions for *widget*, from the tokens its sheet used.

    Returns ``None`` when this widget has no recorded provenance (its sheet was
    set before the wrapper was installed, or built without reading a token), so
    the caller falls back to the global value-diff. That fallback is why this is
    never a regression: token-aware where we know, value-diff where we do not.

    Skips a token whose OLD value is shared with another token this widget used
    that maps somewhere ELSE — the one genuinely undecidable case, and now
    scoped to a handful of tokens instead of all 140.
    """
    tokens = _STYLE_TOKENS.get(widget)
    if not tokens:
        return None
    before = _PREVIOUS_TOKEN_VALUES
    if not before:
        return None
    g = globals()
    proposals: dict[str, set[str]] = {}
    for name in tokens:
        old, new = before.get(name), g.get(name)
        if not isinstance(old, str) or not isinstance(new, str) or old == new:
            continue
        proposals.setdefault(old, set()).add(str(new))
    return {
        old: next(iter(news)) for old, news in proposals.items() if len(news) == 1
    }


# Snapshot of token values from BEFORE the palette switch, so a per-widget map
# can be built from token identity rather than by matching colours globally.
_PREVIOUS_TOKEN_VALUES: dict[str, str] = {}

# {old rendered constant: new rendered constant} for the active switch.
_CONSTANT_REWRITE: dict[str, str] = {}
_SEMANTIC_CONSTANT_NAMES: tuple[str, ...] = tuple(_build_semantic_constants())


def _rewrite_stale_palette_values(mapping: dict[str, str]) -> int:
    """Swap old palette colours for new ones in every live widget's stylesheet.

    Registered widgets have already been re-rendered exactly by
    :func:`_reapply_registered_styles`; this is the fallback for everything else.

    Args:
        mapping: ``{old_value: new_value}`` from :func:`_build_palette_rewrite_map`.

    Returns:
        Number of widgets whose stylesheet actually changed.
    """
    app = QApplication.instance()
    if app is None:
        return 0

    # Longest first: a token whose value contains another's must win.
    ordered = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
    changed = 0
    for widget in app.allWidgets():
        try:
            sheet = widget.styleSheet()
        except RuntimeError:
            continue                      # C++ object already deleted
        if not sheet:
            continue
        # Exact case first: the whole sheet IS a semantic role constant, so it
        # can be replaced wholesale with that role's new rendering.
        exact = _CONSTANT_REWRITE.get(sheet)
        if exact is not None:
            widget.setStyleSheet(exact)
            changed += 1
            continue
        # Token-aware when we know what this widget's sheet was composed from:
        # build the substitution from ONLY those tokens. A colour shared by two
        # tokens is then ambiguous only if this widget used both AND they
        # diverge in the new palette — checkable, rather than guessed globally.
        per_widget = _widget_rewrite_map(widget)
        ordered_here = (
            sorted(per_widget.items(), key=lambda kv: len(kv[0]), reverse=True)
            if per_widget is not None else ordered
        )
        if not ordered_here:
            continue
        updated = sheet
        for old, new in ordered_here:
            if old not in updated:
                continue
            # Don't rewrite #fff when the sheet actually says #ffffff.
            pattern = re.escape(old) + (
                r"(?![0-9A-Fa-f])" if old.startswith("#") else ""
            )
            updated = re.sub(pattern, new.replace("\\", "\\\\"), updated)
        if updated == sheet:
            continue
        try:
            widget.setStyleSheet(updated)
        except RuntimeError:
            continue
        changed += 1
    return changed


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

    Widgets already on screen ARE brought along, by three mechanisms in order
    of precision:

    1. :func:`_reapply_registered_styles` re-renders every widget styled via
       :func:`style` / :func:`style_fn` from the updated constant — exact.
    2. :func:`_rewrite_stale_palette_values` swaps old palette colour values
       for new ones in any other live stylesheet, so the ~370 sites that build
       a sheet with an f-string and call ``setStyleSheet`` directly switch too,
       without each having to be converted.
    3. :func:`_repolish_all_widgets` tells everything to re-read the QPalette,
       which is what themes widgets carrying no stylesheet at all.

    (This used to say the opposite — that a cached stylesheet keeps the old
    style until something re-invokes ``setStyleSheet`` — and that was accurate
    when only the hand-maintained ``refresh_theme()`` sweep existed. It is the
    behaviour the owner reported repeatedly as "themes are still fucked up".)

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
    # Everything below reads tokens heavily (rebuilding semantic constants,
    # restyling the registry). Those reads are theme.py's own, not a widget
    # composing its sheet, so they must not be attributed to whatever widget is
    # styled next — see _suspend_recording.
    with _suspend_recording():
        return _apply_theme_locked(name)


def _apply_theme_locked(name: str) -> bool:
    """The body of :func:`apply_theme`, with token-read recording suspended."""
    global _current_theme
    changed = name != _current_theme
    rewrite_map: dict[str, str] = {}
    global _CONSTANT_REWRITE
    _CONSTANT_REWRITE = {}
    if changed:
        # Semantic role constants are whole, pre-rendered strings, so an
        # unregistered widget styled with one can be switched EXACTLY by
        # swapping the whole sheet — no colour matching, no ambiguity. This is
        # what keeps the "any hand-set sheet follows the palette" guarantee
        # intact for role constants now that per-value diffing cannot.
        _before_constants = {
            n: globals().get(n) for n in _SEMANTIC_CONSTANT_NAMES
        }
        before = _color_token_snapshot()
        # Kept for the per-widget, token-aware map (_widget_rewrite_map). The
        # global value-diff below stays as the fallback for widgets with no
        # recorded provenance.
        global _PREVIOUS_TOKEN_VALUES
        _PREVIOUS_TOKEN_VALUES = dict(before)
        _current_theme = name
        _apply_palette_tokens(theme_palettes.PALETTES[name])
        globals().update(_build_semantic_constants())
        globals().update(_chip_roles.build(globals()))
        globals().update(_detail_roles.build(globals()))
        rewrite_map = _build_palette_rewrite_map(before, _color_token_snapshot())
        _CONSTANT_REWRITE = {
            was: globals()[n]
            for n, was in _before_constants.items()
            if isinstance(was, str) and isinstance(globals().get(n), str)
            and was != globals()[n]
        }
    _sync_qt_application_palette()
    # Restyle every widget registered through style()/style_fn(). Unconditional,
    # like the palette push above: a cold launch whose saved theme already
    # matches the resting default still needs one pass so nothing is left on a
    # stale string. Cheap when the registry is empty (startup, tests).
    _reapply_registered_styles()
    # Everything that built its stylesheet by hand still holds the OLD palette's
    # colour values verbatim. Swap them for the new ones (guarded — see
    # _build_palette_rewrite_map) so a composed f-string sheet switches too,
    # without needing ~370 call sites converted one at a time.
    _rewrite_stale_palette_values(rewrite_map)
    # Registered widgets got a fresh stylesheet above; everything else needs to
    # be told to re-read the palette, or it keeps painting the old one.
    _repolish_all_widgets()
    return changed


def current_theme() -> str:
    """Return the name of the currently active palette."""
    return _current_theme


def available_themes() -> list[str]:
    """Return every palette name, in a stable display order (dict-insertion
    order of :data:`theme_palettes.PALETTES` — Midnight, Graphite, Daylight)."""
    return list(theme_palettes.PALETTES.keys())
