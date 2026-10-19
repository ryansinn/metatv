"""Bundled typefaces — registered once at startup, from the repository.

The assets live in ``metatv/assets/fonts/`` and are version-controlled, which
is the whole point of this module existing. They were once produced in a
session scratchpad, reported as prepared, and then silently lost when the
temp directory was swept — so a settled decision (Inter as the UI face) had
nothing behind it. **Anything the build loads belongs in the tree.**

What is here, and why:

``Inter-Regular.ttf`` / ``Inter-SemiBold.ttf``
    The UI face (O5). Chosen for the largest x-height of the candidates and
    the clearest rendering at 11–12px, which is where most of this interface
    lives. Latin subset, ~47 KB each.

Icons are not a font here: every icon is an mdi6 glyph drawn through
qtawesome (``icons.py`` / ``icon_utils.py``) — one icon set (owner, 2026-10-19).
A Material Symbols subset once sat in this directory, loaded and unused; it
was removed rather than kept as a second system.

Regenerate with ``scripts/build_font_assets.py`` — never by hand, and never
into a scratchpad.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from loguru import logger

#: Where the assets live. Resolved from this module so a frozen build finds
#: them next to the package rather than relative to the working directory.
ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

#: Filename → the role it plays. Order matters only for logging.
_BUNDLED = (
    ("Inter-Regular.ttf", "ui"),
    ("Inter-SemiBold.ttf", "ui-semibold"),
)

#: The family the UI face registers as. Asserted at load rather than assumed —
#: a subset that loses its name table would otherwise fail silently and leave
#: every widget on the platform default.
UI_FAMILY = "Inter"


@lru_cache(maxsize=1)
def load_bundled_fonts() -> dict[str, str]:
    """Register every bundled face with Qt; return ``{role: family}``.

    Cached, because ``QFontDatabase.addApplicationFont`` returns a NEW id for
    the same file on a second call — registering twice leaves a duplicate
    family in the database.

    Safe to call before the theme is applied and before any widget exists, but
    **not** before ``QApplication`` — Qt has no font database until then.

    Returns:
        Roles that loaded, mapped to their resolved family name. A face that
        fails to load is logged and omitted rather than raising: a missing
        typeface should cost the app its typeface, not its launch.
    """
    from PyQt6.QtGui import QFontDatabase

    loaded: dict[str, str] = {}
    for filename, role in _BUNDLED:
        path = ASSET_DIR / filename
        if not path.is_file():
            logger.warning(f"Bundled font missing: {path}")
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            logger.warning(f"Qt refused to load bundled font: {path}")
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            logger.warning(f"Bundled font registered no family: {path}")
            continue
        loaded[role] = families[0]
    if loaded:
        logger.debug(f"Bundled fonts loaded: {loaded}")
    return loaded


def apply_ui_font(app) -> bool:
    """Set the bundled UI face as the application font.

    Every ``FONT_*`` token is a SIZE, not a family, so the family is set once
    here and the whole type scale rides on it. Widgets that copy the style
    option's font (the channel-row delegate, for one) inherit it for free.

    Args:
        app: The ``QApplication``.

    Returns:
        True if the bundled face was applied; False if it was unavailable and
        the platform default stands.
    """
    from PyQt6.QtGui import QFont

    families = load_bundled_fonts()
    family = families.get("ui")
    if not family:
        return False
    from metatv.gui import theme

    font = QFont(family)
    # The type scale's base, in PIXELS — never the platform's point size. The
    # OS default (13pt on macOS, 10-11pt on Linux desktops at 96 DPI) put every
    # unstyled widget at a different size from styled text, differently per
    # platform. theme's font floor re-applies this on every theme/scale change.
    font.setPixelSize(int(str(theme.FONT_MD)[:-2]))
    app.setFont(font)
    return True


def monospace_family() -> str:
    """A monospace family Qt will actually resolve on this platform.

    ``"monospace"`` is a real family only on Linux (fontconfig); on macOS and
    Windows a widget asking for it gets the proportional default. Qt's
    ``StyleHint`` is the portable way to ask, so every monospace surface —
    widget fonts and stylesheet ``font-family`` alike — takes it from here.
    """
    from PyQt6.QtGui import QFont

    font = QFont()
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font.defaultFamily()
