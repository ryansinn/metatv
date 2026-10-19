"""Icon resolution — thin wrapper around qtawesome.

Widget code references only config field names (semantic identifiers).
Config field values hold icon pack keys (e.g. "fa5s.filter").
This module is the only place in the codebase that imports qtawesome.

If the primary key fails to load (font rendering issue on some systems),
fallback keys are tried in order before giving up.
"""

from __future__ import annotations

import weakref
from typing import Callable, Union

from loguru import logger

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QSize
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import QPushButton

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

#: A colour a button icon can be painted in: a literal CSS string, or a
#: zero-arg builder re-invoked on every theme switch (see `set_button_icon`).
ColorSpec = Union[str, Callable[[], str], None]

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
        spin = _safe_spin_class(qta)(widget, interval=SPIN_INTERVAL_MS, step=SPIN_STEP_DEG)
        widget.setIcon(qta.icon(icon_key, color=color or _theme.COLOR_TEXT, animation=spin))
    except Exception:  # silent: a spinner is decoration — no icon beats no dialog
        return None
    widget._metatv_spin = spin   # reachable for tests and for an explicit stop
    return widget


_SAFE_SPIN: dict = {}


def _safe_spin_class(qta):
    """qtawesome's ``Spin`` with a timer tick that refuses a dead widget.

    ``Spin._update`` calls ``parent_widget.update()`` from a 40ms QTimer. When
    the widget's C++ object has already gone — its section torn down, the
    spinner's parent deleted — that call is a ``RuntimeError`` when sip knows
    and a SEGFAULT when the tick lands mid-destruction: the 2026-09-07 CI
    teardown crashes (Linux and macOS, a different shard each run, never under
    gdb) and the macOS "wrapped C/C++ object of type IconWidget has been
    deleted" error both came from this tick. The guard stops the timer and
    forgets the widget instead. Built lazily so the module still imports when
    qtawesome is missing.
    """
    cls = _SAFE_SPIN.get("cls")
    if cls is None:
        class _SafeSpin(qta.Spin):
            def _update(self):
                widget = self.parent_widget
                if widget is None or sip.isdeleted(widget):
                    entry = self.info.pop(widget, None)
                    if entry is not None:
                        try:
                            entry[0].stop()
                        except RuntimeError:
                            pass   # the timer died with its widget; nothing to stop
                    return
                super()._update()
        cls = _SAFE_SPIN["cls"] = _SafeSpin
    return cls


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


# ── A ROLE, three ways (one icon set, 2026-10-19) ───────────────────────────
#
# Every icon is a role in ``icons.VECTOR_KEYS`` drawn from mdi6. These are the
# three shapes a call site needs, so none of them reaches for a text glyph:
# a QIcon (actions, menus), a pixmap (painted rows), and an inline glyph for
# a QLabel's rich text ("[icon] 3 new").


def role_icon(role: str, color: str | None = None) -> QIcon:
    """The QIcon for a semantic *role*, painted in *color* (default ``COLOR_TEXT``).

    Raises:
        KeyError: *role* is not in ``icons.VECTOR_KEYS``.
    """
    return resolve_icon(_icons.vector_key(role),
                        color=color if color is not None else _theme.COLOR_TEXT)


def role_pixmap(role: str, color: str, size: int = 16) -> object:
    """A cached, DPR-correct pixmap of *role* — see :func:`vector_pixmap`."""
    return vector_pixmap(_icons.vector_key(role), color, size)


def role_html(role: str, color: str | None = None, px: int | None = None) -> str:
    """*role* as an inline rich-text glyph, for a label that mixes icon and words.

    The mdi6 font, addressed by codepoint, inside a ``<span>`` — so the icon
    sits on the text baseline and scales with it, and the label stays one
    widget. The label must use ``Qt.TextFormat.RichText`` and the caller must
    HTML-escape any text around it.

    Args:
        role: A key of ``icons.VECTOR_KEYS``.
        color: A CSS colour (a theme token's value); omitted, the glyph takes
            the label's own colour.
        px: Pixel size; omitted, the label's font size.

    Raises:
        KeyError: *role* is not in ``icons.VECTOR_KEYS``.
    """
    import qtawesome as qta

    key = _icons.vector_key(role)
    char = qta.charmap(key)
    family = qta.font(key.split(".", 1)[0], px or 12).family()
    style = f"font-family:'{family}';"
    if color:
        style += f" color:{color};"
    if px:
        style += f" font-size:{px}px;"
    return f'<span style="{style}">&#x{ord(char):x};</span>'


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
#: What each button was last painted with. The colour is stored AS PASSED —
#: a string stays a string, a builder stays a builder — because
#: :func:`refresh_icon_buttons` feeds it straight back in, and only a builder
#: can re-read a token after the palette has moved under it.
_registered_icon_buttons: (
    "weakref.WeakKeyDictionary[QPushButton, tuple[str, ColorSpec]]"
) = weakref.WeakKeyDictionary()


class _FollowTextColour(QObject):
    """Repaints a follow-text icon button when its colours change.

    Qt writes a stylesheet's ``color`` into the widget's palette and then sends
    ``PaletteChange`` — so this catches a style applied AFTER the icon was set
    (the usual order at construction) as well as every theme switch.
    """

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        if event.type() != QEvent.Type.PaletteChange:
            return False
        # Never raise from here: an exception escaping an event filter is a
        # qFatal in PyQt, and this runs for widgets mid-teardown too.
        try:
            entry = _registered_icon_buttons.get(obj)
            if entry is not None and entry[1] is None:
                _paint(obj, entry[0], obj.palette().color(QPalette.ColorRole.ButtonText).name())
            label = _registered_icon_labels.get(obj)
            if label is not None:
                _paint_label(obj, *label)
        except Exception:
            logger.debug("icon repaint skipped for a widget being torn down")
        return False


_FOLLOW = _FollowTextColour()


def _paint(btn: QPushButton, role: str, color: str) -> None:
    if role in _icons.VECTOR_KEYS:
        icon = resolve_icon(_icons.vector_key(role), color=color)
    else:
        glyph = getattr(_icons, f"{role}_icon", None)
        if glyph is None:
            raise KeyError(
                f"icon role {role!r} is not in icons.VECTOR_KEYS and "
                f"icons.{role}_icon does not exist"
            )
        icon = _icons.glyph_icon(glyph, color)
    btn.setIcon(icon)


#: Labels showing a role as a pixmap in their own text colour: label → (role, px).
_registered_icon_labels: "weakref.WeakKeyDictionary[object, tuple[str, int]]" = (
    weakref.WeakKeyDictionary())


def _paint_label(label, role: str, px: int) -> None:
    label.ensurePolished()
    label.setPixmap(role_pixmap(role, label.palette().color(QPalette.ColorRole.WindowText).name(), px))


def label_role(label) -> str | None:
    """The role :func:`set_label_icon` last put on *label*, or None."""
    entry = _registered_icon_labels.get(label)
    return entry[0] if entry else None


def set_label_icon(label, role: str, px: int = 14) -> None:
    """Show *role* as *label*'s pixmap, in the label's own text colour.

    The label equivalent of an omitted colour in :func:`set_button_icon`: the
    colour is read from the palette (Qt fills it from the stylesheet) and the
    icon repaints when the style or theme changes — so a glyph-only label
    keeps the colour its role gave it, on any surface.
    """
    _registered_icon_labels[label] = (role, px)
    label.removeEventFilter(_FOLLOW)
    label.installEventFilter(_FOLLOW)
    _paint_label(label, role, px)


def set_button_icon(btn: QPushButton, role: str, *, color: ColorSpec = None) -> None:
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
        color: Omitted (None), the icon takes the button's own TEXT colour —
            read from its palette, which Qt fills from the stylesheet — and
            follows it whenever the style or theme changes, so an icon always
            matches its words (on the fixed-dark cinema surface too). Or any
            CSS colour string, OR a zero-arg callable returning one —
            the same distinction :func:`theme.style` and
            :func:`theme.style_fn` draw, for the same reason. A STRING is
            frozen at this call: correct for a runtime colour (a provider
            hue, a fixed cinema token), stale for a palette token, because
            :func:`refresh_icon_buttons` can only replay what it was given.
            Pass ``lambda: _theme.COLOR_MUTED_2`` for a token so the glyph
            follows a theme switch.

    Raises:
        KeyError: *role* is neither a vector key nor a glyph constant name —
            naming both lookups tried, so a typo surfaces at the call site.
    """
    if callable(color):
        resolved_color = color()
    elif color is not None:
        resolved_color = color
    else:
        btn.ensurePolished()   # an unshown button's palette updates only on polish
        resolved_color = btn.palette().color(QPalette.ColorRole.ButtonText).name()
        btn.removeEventFilter(_FOLLOW)
        btn.installEventFilter(_FOLLOW)
    _paint(btn, role, resolved_color)
    _registered_icon_buttons[btn] = (role, color)


def button_role(btn: QPushButton) -> str | None:
    """The role this module last painted on *btn*, or None. For tests and for
    code that needs to know which icon a toggle currently shows."""
    entry = _registered_icon_buttons.get(btn)
    return entry[0] if entry else None


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
        try:
            gone = sip.isdeleted(btn)
        except TypeError:   # not a Qt object (a test double): nothing to repaint
            gone = True
        if gone:
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
