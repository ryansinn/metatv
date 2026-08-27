"""Icon resolution — thin wrapper around qtawesome.

Widget code references only config field names (semantic identifiers).
Config field values hold icon pack keys (e.g. "fa5s.filter").
This module is the only place in the codebase that imports qtawesome.

If the primary key fails to load (font rendering issue on some systems),
fallback keys are tried in order before giving up.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon

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
            except Exception:
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
    except Exception:
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
