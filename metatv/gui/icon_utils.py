"""Icon resolution — thin wrapper around qtawesome.

Widget code references only config field names (semantic identifiers).
Config field values hold icon pack keys (e.g. "fa5s.filter").
This module is the only place in the codebase that imports qtawesome.

If the primary key fails to load (font rendering issue on some systems),
fallback keys are tried in order before giving up.
"""

from __future__ import annotations

import weakref

from loguru import logger

from PyQt6 import sip
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QPushButton

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

# Fallback chains for keys known to have font-loading issues on some systems.
# Only this module knows about icon pack identifiers.
_FALLBACKS: dict[str, list[str]] = {
    "fa5s.filter": ["ph.funnel", "mdi6.filter-outline", "ri.filter-line", "mdi.filter"],
}


def resolve_icon(icon_key: str, color: str = _theme.COLOR_TEXT) -> QIcon:
    """Resolve an icon pack key to a QIcon, trying fallbacks on null result.

    Returns an empty QIcon only if every key in the chain fails.
    Callers should check isNull() and fall back to text if needed.
    """
    keys = [icon_key] + _FALLBACKS.get(icon_key, [])
    try:
        import qtawesome as qta
        for key in keys:
            try:
                icon = qta.icon(key, color=color)
                if not icon.isNull():
                    return icon
            except Exception:  # silent: qtawesome raises per unknown key; try the next one
                continue
    except ImportError:
        pass
    return QIcon()


# ── Vector glyphs on a raw QPainter surface (the channel row) ───────────────
#
# The channel-list delegate paints with QPainter, not stylesheets, so it can use
# neither a QIcon in a QLabel nor the rich-text <img> above. It needs a pixmap,
# and it needs one per PAINTED ROW — so the resolve+render cost has to be paid
# once per (key, colour, size, DPR) and never again.
#
# Keyed on the colour STRING rather than a theme constant, which is what makes a
# theme switch correct for free: the delegate re-reads ``theme.COLOR_*`` on every
# paint (that is how the whole file already works), so a new palette produces a
# new key and a fresh render, while the old entries simply go unused.
_VECTOR_PIXMAP_CACHE: dict[tuple[str, str, int, float], object] = {}


#: Spinner rotation. qtawesome's default step is 1°/tick, which does not read
#: as motion at sidebar sizes.
SPIN_INTERVAL_MS = 40
SPIN_STEP_DEG = 12


def busy_spinner(parent=None, icon_key: str = "mdi6.loading",
                 color: str | None = None, size: int = 13):
    """A genuinely SPINNING busy indicator, or ``None`` if the pack is missing.

    The codebase's busy hint has been a static ``⟳`` glyph beside the word
    "checking…" (``icons.loading_icon``) — a still picture of motion plus a
    label doing the work the motion should. Owner: *"isn't there some animated
    icon rather than the word? something spinning?"*

    qtawesome animates by repainting a widget, so this returns a widget rather
    than a QIcon or a QPixmap: an animated QIcon assigned to a QLabel never
    moves, because nothing repaints it. The animation is owned by the returned
    widget and stops when it is destroyed.

    This module is the only place that imports qtawesome, which is why the
    helper lives here rather than beside its first caller.

    Args:
        parent: Parent widget, if any.
        icon_key: The glyph to spin. ``mdi6.loading`` is a partial ring, which
            reads as motion at 13px where a full circle does not.
        color: Any CSS colour; defaults to the current ``COLOR_TEXT``.
        size: Logical edge length in px.

    Returns:
        A ``qtawesome.IconWidget`` sized to *size*, or ``None`` when qtawesome
        is unavailable — callers fall back to their existing static hint rather
        than losing the indicator entirely.
    """
    try:
        import qtawesome as qta
    except ImportError:
        return None

    widget = qta.IconWidget(parent=parent)
    widget.setIconSize(QSize(size, size))
    widget.setFixedSize(size, size)
    try:
        # An explicit step, because qtawesome's default advances ONE DEGREE per
        # tick — at 13px that is invisible, and a "spinner" nobody can see spin
        # is worse than the word it replaced. 12° every 40ms is ~0.8 turns a
        # second: unmistakably moving, not distractingly fast.
        widget.setIcon(qta.icon(
            icon_key,
            color=color or _theme.COLOR_TEXT,
            animation=qta.Spin(widget, interval=SPIN_INTERVAL_MS, step=SPIN_STEP_DEG),
        ))
    except Exception:  # silent: a spinner is decoration — no icon beats no dialog
        return None
    return widget


def vector_pixmap(icon_key: str, color: str, size: int = 16) -> object:
    """A device-pixel-ratio-correct ``QPixmap`` of *icon_key* painted in *color*.

    Builds a ``QPixmap``, so main thread only (see docs/THREADING_PATTERNS.md) —
    which a delegate's ``paint()`` always is.

    Args:
        icon_key: An icon-pack key, normally from ``icons.vector_key(role)``.
        color: Any CSS colour the glyph should be painted in.
        size: Logical edge length in px.

    Returns:
        A cached ``QPixmap``. A key that resolves to nothing yields a null
        pixmap, which callers must skip rather than draw — a row with a missing
        glyph should lose the glyph, not the row.
    """
    from PyQt6.QtGui import QPixmap
    from PyQt6.QtWidgets import QApplication

    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    cache_key = (icon_key, color, size, dpr)
    cached = _VECTOR_PIXMAP_CACHE.get(cache_key)
    if cached is not None:
        return cached

    icon = resolve_icon(icon_key, color=color)
    if icon.isNull():
        pixmap = QPixmap()
    else:
        # ``size`` LOGICAL, never size * dpr. Qt 6's QIcon.pixmap() is already
        # device-pixel-ratio aware: on a 2x screen it returns a 2x-denser pixmap
        # with devicePixelRatio set for whatever logical size you ask for. Asking
        # for `size * dpr` therefore applied the ratio TWICE — a request for 11px
        # came back 44px physical at dpr 2, i.e. 22 LOGICAL, and every sidebar
        # icon rendered at double size on a HiDPI display.
        #
        # It hid for so long because the two consumers fail differently. A
        # delegate paints into an explicit QRect, which scales the oversized
        # pixmap back down and looks correct; a QLabel draws a pixmap at its own
        # logical size, so only the label path inflated. Offscreen renders run
        # at dpr 1, where the double-apply is x1 and invisible.
        pixmap = icon.pixmap(size, size)
    _VECTOR_PIXMAP_CACHE[cache_key] = pixmap
    return pixmap


def _clear_vector_pixmap_cache() -> None:
    """Discard every cached pixmap — QPixmaps outlive their ``QApplication``
    as dangling C++ objects, so the cache must be dropped between app
    instances (the same reason ``icons._clear_glyph_icon_cache`` exists)."""
    _VECTOR_PIXMAP_CACHE.clear()


# ---------------------------------------------------------------------------
# Icon-only QPushButton factory (ICON-1)
# ---------------------------------------------------------------------------
# Icon-only buttons had been built ~37 different ways across gui/ — most
# commonly ``QPushButton(icons.x_icon)``, which sets a colour EMOJI as the
# button's TEXT: drawn at the host font size inside a fixed-size button, it
# crops (ledger F13). This is the one chokepoint: every icon-only button goes
# through :func:`icon_button` (fresh construction) or :func:`set_button_icon`
# (an existing button whose glyph is set/swapped later — toggle badges like
# watched/unwatched, favourite/unfavourite, pin/unpin, collapse/expand call
# this on state change, never ``setText``).

#: Every button whose icon this module has painted, so a theme switch can
#: repaint it. Weak: a closed dialog's button must not be kept alive by this
#: registry. Value is the (role, color) last used, so a re-paint reproduces
#: exactly what is on screen now — including a role a caller swapped to after
#: construction.
_registered_icon_buttons: "weakref.WeakKeyDictionary[QPushButton, tuple[str, str | None]]" = (
    weakref.WeakKeyDictionary()
)


def set_button_icon(btn: QPushButton, role: str, *, color: str | None = None) -> None:
    """Paint *btn*'s icon from the semantic *role* and register it for re-paint.

    Vector-first: a role present in :data:`icons.VECTOR_KEYS` resolves through
    :func:`resolve_icon` (crisp, themeable ``mdi6`` glyph). Otherwise falls
    back to the glyph constant ``icons.<role>_icon`` rendered monochrome via
    :func:`icons.glyph_icon` — every existing emoji constant is reachable this
    way with no registry changes.

    Registers *btn* in the module's weak icon-button registry regardless of
    call path (:func:`icon_button` calls this internally rather than
    duplicating the resolution+registration logic), so :func:`refresh_icon_buttons`
    repaints it too — including a button whose glyph this function is used to
    SWAP after construction (a toggle badge), which re-registers with its new
    role on every call.

    Args:
        btn: Any ``QPushButton`` (or subclass).
        role: A semantic role — either a :data:`icons.VECTOR_KEYS` key or the
            ``<role>`` in an ``icons.<role>_icon`` glyph constant.
        color: Any CSS colour string. Defaults to ``theme.COLOR_TEXT``, read
            at CALL time (never cached at import — a stale default would not
            track a theme switch).

    Raises:
        KeyError: *role* is neither a vector key nor a glyph constant name —
            naming both lookups tried, so a typo surfaces at the call site.
    """
    resolved_color = color if color is not None else _theme.COLOR_TEXT
    if role in _icons.VECTOR_KEYS:
        icon = resolve_icon(_icons.vector_key(role), color=resolved_color)
    else:
        glyph_name = f"{role}_icon"
        glyph = getattr(_icons, glyph_name, None)
        if glyph is None:
            raise KeyError(
                f"icon role {role!r} is not in icons.VECTOR_KEYS and "
                f"icons.{glyph_name} does not exist"
            )
        icon = _icons.glyph_icon(glyph, resolved_color)
    btn.setIcon(icon)
    _registered_icon_buttons[btn] = (role, color)


def icon_button(
    role: str,
    tooltip: str,
    *,
    style: str = "INLINE_ACTION_BTN",
    px: int = 16,
    parent=None,
    checkable: bool = False,
) -> QPushButton:
    """Build a fresh icon-only ``QPushButton`` through the one shared path.

    Every icon-only button needs the same handful of things done together —
    a crisp non-cropped icon, a tooltip (a11y name to match), the right theme
    role, live re-theming — and this is the one place that does all of them,
    so a call site cannot ship three of the four.

    Args:
        role: Passed to :func:`set_button_icon`.
        tooltip: Required and must be non-empty — an icon-only control with
            no tooltip is exactly the U14 defect this factory closes.
        style: A ``theme.py`` semantic-constant name, applied via
            :func:`theme.style` (which also registers *btn* so it re-renders
            on a theme switch). Defaults to the neutral flat role shared by
            most inline icon actions.
        px: Icon edge length in logical px.
        parent: Optional parent widget.
        checkable: Whether the button toggles (e.g. a filter/checkbox-style
            icon button).

    Returns:
        The constructed, fully-wired ``QPushButton``.

    Raises:
        ValueError: *tooltip* is empty — the tooltip rule is firm.
        KeyError: See :func:`set_button_icon`.
    """
    if not tooltip:
        raise ValueError("icon_button() requires a non-empty tooltip")
    btn = QPushButton(parent)
    btn.setIconSize(QSize(px, px))
    set_button_icon(btn, role)
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCheckable(checkable)
    _theme.style(btn, style)
    return btn


def refresh_icon_buttons() -> None:
    """Re-paint every live registered icon button — called after a theme switch.

    Icons are QPixmap-backed ``QIcon``s baked at paint time in a colour
    string; unlike a stylesheet role they cannot re-resolve a token on their
    own, so ``theme.style()``'s registry (built for stylesheets) cannot carry
    them. This is that same idea for icons: repaint from the (role, color)
    this module last used for that button, so the glyph follows the palette
    like everything else.
    """
    for btn, (role, color) in list(_registered_icon_buttons.items()):
        if sip.isdeleted(btn):
            # The C++ object is gone while the wrapper lingers: drop it rather
            # than touch it. (A destroyed-signal hook was tried first and
            # aborted the test teardown sweep — never weakref an object that
            # is mid-finalisation.)
            _registered_icon_buttons.pop(btn, None)
            continue
        try:
            set_button_icon(btn, role, color=color)
        except Exception:
            # Deliberately broad, and it is not defensiveness: this runs from
            # theme.apply_theme(), which runs from a Qt slot, and PyQt calls
            # qFatal() on an exception that escapes a slot (docs/REFACTOR_PLAN
            # F18). Losing one button's repaint is a cosmetic bug; taking the
            # process down over it is not. The usual cause is RuntimeError —
            # the C++ object is gone while the Python wrapper lingers.
            logger.debug("icon button {!r} not refreshed (wrapper outlived its widget?)", role)


# theme.py must not import this module (would cycle: icon_utils already imports
# theme) — so this module registers itself with theme's hook list instead.
_theme.register_post_apply(refresh_icon_buttons)
