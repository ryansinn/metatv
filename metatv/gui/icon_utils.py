"""Icon resolution — thin wrapper around qtawesome.

Widget code references only config field names (semantic identifiers).
Config field values hold icon pack keys (e.g. "fa5s.filter").
This module is the only place in the codebase that imports qtawesome.

If the primary key fails to load (font rendering issue on some systems),
fallback keys are tried in order before giving up.
"""

from __future__ import annotations

from PyQt6.QtGui import QIcon

from metatv.gui import theme as _theme

# Fallback chains for keys known to have font-loading issues on some systems.
# Only this module knows about icon pack identifiers.
_FALLBACKS: dict[str, list[str]] = {
    "fa5s.filter": ["ph.funnel", "mdi6.filter-outline", "ri.filter-line", "mdi.filter"],
}


def resolve_icon(icon_key: str, color: str = _theme.COLOR_MUTED) -> QIcon:
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
