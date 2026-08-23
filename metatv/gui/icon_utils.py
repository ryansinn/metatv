"""Icon resolution — thin wrapper around qtawesome.

Widget code references only config field names (semantic identifiers).
Config field values hold icon pack keys (e.g. "fa5s.filter").
This module is the only place in the codebase that imports qtawesome.

If the primary key fails to load (font rendering issue on some systems),
fallback keys are tried in order before giving up.
"""

from __future__ import annotations

from PyQt6.QtCore import QBuffer, QIODevice
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


def inline_icon_html(icon_key: str, color: str = _theme.COLOR_TEXT,
                     size: int = 13) -> str:
    """A rich-text ``<img>`` tag carrying the icon as an inline data URI.

    Sidebar section headers keep their icon and title inside ONE ``QLabel``,
    because at least one of them (Watch Alerts) colours the icon and the title
    together as a single state cue. Rich text cannot reference a ``QIcon``, so
    the glyph is rendered to a PNG and embedded — which keeps the single-label
    structure while letting the icon take a colour, the one thing the emoji it
    replaces could never do.

    Builds a ``QPixmap``, so main thread only (see docs/THREADING_PATTERNS.md).

    Args:
        icon_key: An icon-pack key, normally from ``icons.vector_key(role)``.
        color: Any CSS colour the glyph should be painted in.
        size: Edge length in px; the tag pins width and height to match so the
            label reserves the right space before the image decodes.

    Returns:
        The ``<img>`` tag, or ``""`` if the key resolves to nothing — callers
        concatenate it into a title string, and an empty string degrades to a
        title with no icon rather than a broken-image box.
    """
    icon = resolve_icon(icon_key, color=color)
    if icon.isNull():
        return ""

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not icon.pixmap(size, size).save(buffer, "PNG"):
        return ""
    encoded = bytes(buffer.data().toBase64()).decode("ascii")
    return (f'<img src="data:image/png;base64,{encoded}" '
            f'width="{size}" height="{size}">')


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
        pixmap = icon.pixmap(int(size * dpr), int(size * dpr))
        pixmap.setDevicePixelRatio(dpr)
    _VECTOR_PIXMAP_CACHE[cache_key] = pixmap
    return pixmap


def _clear_vector_pixmap_cache() -> None:
    """Discard every cached pixmap — QPixmaps outlive their ``QApplication``
    as dangling C++ objects, so the cache must be dropped between app
    instances (the same reason ``icons._clear_glyph_icon_cache`` exists)."""
    _VECTOR_PIXMAP_CACHE.clear()
