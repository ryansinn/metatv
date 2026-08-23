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

``MetaTVIcons.ttf``
    Material Symbols Outlined, instantiated at the pinned axes
    (``FILL 0 / GRAD 0 / opsz 24 / wght 400``) and subset to the 48 icons the
    interface names — **7 KB**. Bundled and verified loading, but the icon
    system still runs on ``mdi6`` through ``qtawesome`` (see ``icons.py``);
    switching over is its own slice and this file is what unblocks it.
    ``material_symbols_codepoints.json`` maps each name to its codepoint,
    because these are addressed by CODEPOINT rather than by ligature: the
    ligature route needs the ``liga`` feature and every latin letter, and the
    layout closure that comes with it kept 3,621 glyphs and 765 KB.

Regenerate with ``scripts/build_font_assets.py`` — never by hand, and never
into a scratchpad.
"""

from __future__ import annotations

import json
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
    ("MetaTVIcons.ttf", "icons"),
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
    font = QFont(family)
    # Keep the platform's own size — the type scale sets pixel sizes per role,
    # and overriding the base here would silently rescale anything that has
    # not been given an explicit token yet.
    font.setPointSizeF(app.font().pointSizeF())
    app.setFont(font)
    return True


@lru_cache(maxsize=1)
def icon_codepoints() -> dict[str, str]:
    """``{icon_name: "e8b6"}`` for the bundled Material Symbols subset.

    Read from the JSON the build script emits, so the map cannot drift from
    the font it describes — both are produced by the same run.
    """
    path = ASSET_DIR / "material_symbols_codepoints.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def icon_char(name: str) -> str:
    """The character that renders *name* in the bundled icon face.

    Raises:
        KeyError: if *name* is not in the subset — deliberately loud, the same
            contract ``icons.vector_key`` keeps, so a typo surfaces at the call
            site instead of rendering a blank box.
    """
    return chr(int(icon_codepoints()[name], 16))
