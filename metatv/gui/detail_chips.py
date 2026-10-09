"""The one chip/grid toolkit for the redesigned details pane.

Every DETAILS-3 slice (3b title block, 3c "Available in" copies, 3d Cast/
Details/Facts sections) renders through these builders rather than hand-
rolling a stylesheet or a grid per section — the same reason
``gui/chip_row.py`` is the sidebar's one row builder and
``gui/channel_menu.py`` is the one menu builder. A chip's LOOK (outlined,
clickable, optionally dashed/selected/bold) and a section's two-column grid
(a fixed key column + a flowing value column) are the same shape everywhere
in the pane, so they are built once here.

:func:`chip_sheet` resolves its colour by TOKEN NAME at call time
(``getattr(theme, colour_token)``) rather than taking an already-resolved
colour string — the same reason ``theme.style_fn`` takes a zero-arg callable
rather than a baked sheet: a widget built before a theme switch must still
read the post-switch palette the next time Qt asks for its stylesheet, and a
colour value captured at construction cannot do that. Callers pass the NAME
(``"COLOR_TEXT"``, ``"COLOR_TEXT_HI"``, a facet colour role...), never the
resolved string.

The chip's shared geometry (radius, padding, font size) lives in
``metatv.gui.tokens.detail_roles.chip_geometry`` — the same fragment
``DETAIL_REGION_CHIP`` composes from — so this module and that role never
carry two copies of one chip's metrics.

The quality badge is a different case: it is not a new chip look but the
app's ONE quality-tier chip (``chip_row.chip_widget(chip_row.CHIP_QUALITY,
...)``, tier-coloured text on a neutral hairline), nested inside a details
chip's own layout — see :func:`add_quality_badge`.
"""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from metatv.core.channel_name_utils import QUALITY_TOKENS, REGION_FULL_NAMES
from metatv.gui import chip_row, cursor_affordance
from metatv.gui import theme
from metatv.gui.flow_layout import FlowLayout
from metatv.gui.qt_text_utils import escape_mnemonic
from metatv.gui.tokens.detail_roles import chip_geometry

#: The one label-column width for the whole pane: "Available in" + every
#: Facts/Cast/Details row lines up under it.
KEY_COL = 92

#: How far a section's body sits under its own header text (Cast, Details,
#: Facts), matching the indent Cast already used before the redesign.
SECTION_INDENT = 20


def chip_sheet(colour_token: str, *, dashed: bool = False, selected: bool = False,
              bold: bool = False) -> str:
    """Build the one outlined, clickable chip's stylesheet.

    Every token is resolved by NAME, at call time (``getattr(theme,
    colour_token)``, plus the live ``theme.FONT_MD``/``COLOR_*`` reads below)
    — never pass an already-resolved colour string in, and never bake this
    return value into a widget with a plain ``setStyleSheet``. Register the
    widget with ``theme.style_fn`` (see :func:`make_chip`) so a palette
    switch re-invokes this function and the chip repaints correctly.

    Args:
        colour_token: Name of a ``theme`` colour constant (e.g.
            ``"COLOR_TEXT"``, ``"COLOR_TEXT_HI"``, a facet colour role) — the
            chip's TEXT colour.
        dashed: Border style. Dashed marks a navigational/guessed chip
            ("+N filtered", a guessed fact); solid marks a stated one.
        selected: Fills the chip with ``COLOR_BG_CARD`` and outlines it in
            ``COLOR_ACCENT`` — the "this is the copy you're looking at" state.
        bold: Bold chip text, for the selected/current-copy chip.

    Returns:
        A ``QPushButton``-scoped stylesheet string.
    """
    colour = getattr(theme, colour_token)
    geometry = chip_geometry(theme.FONT_MD, theme.RADIUS_SM)
    border_style = "dashed" if dashed else "solid"
    border_colour = theme.COLOR_ACCENT if selected else theme.COLOR_BORDER
    background = theme.COLOR_BG_CARD if selected else "transparent"
    weight = "bold" if bold else "normal"
    return (
        f"QPushButton {{ color: {colour}; font-weight: {weight};"
        f" background: {background};"
        f" border: 1px {border_style} {border_colour}; {geometry} }}"
        f"QPushButton:hover {{ border-color: {theme.COLOR_ACCENT}; }}"
    )


def make_chip(text: str, colour_token: str = "COLOR_TEXT", *, dashed: bool = False,
              selected: bool = False, bold: bool = False) -> QPushButton:
    """Build one outlined, clickable chip — the pane's one chip widget.

    Args:
        text: The chip's display text. Escaped for ``&`` via
            ``escape_mnemonic`` before it reaches the button, so a value like
            "Action & Adventure" renders literally instead of losing the
            ampersand to Qt's mnemonic handling.
        colour_token: Name of a ``theme`` colour constant for the chip's text
            — see :func:`chip_sheet`.
        dashed: See :func:`chip_sheet`.
        selected: See :func:`chip_sheet`.
        bold: See :func:`chip_sheet`.

    Returns:
        A clickable ``QPushButton`` whose stylesheet re-applies on every
        theme switch (``theme.style_fn``) and whose cursor is the pointing
        hand (``cursor_affordance.set_clickable``).
    """
    btn = QPushButton(escape_mnemonic(text))
    theme.style_fn(btn, lambda: chip_sheet(colour_token, dashed=dashed, selected=selected, bold=bold))
    cursor_affordance.set_clickable(btn)
    return btn


def make_key(text: str) -> QLabel:
    """Build one key-column label ("Available", "Director", "Language"…).

    Its height matches a chip's so a key and the chip row beside it line up
    on the same baseline instead of a label-sized row being shorter.

    Args:
        text: The key label text.

    Returns:
        A ``QLabel`` styled ``DETAIL_SECTION_SUMMARY`` (the same quiet label a
        section header's count uses — no twin role), fixed to a chip's height.
    """
    key = QLabel(text)
    key.setFixedHeight(make_chip("x").sizeHint().height())
    theme.style(key, "DETAIL_SECTION_SUMMARY")
    return key


def make_flow(widgets: Iterable[QWidget]) -> QWidget:
    """Wrap *widgets* in a tight, wrapping flow row (4px spacing both axes).

    Args:
        widgets: The chips/labels to lay out left-to-right, wrapping as
            needed.

    Returns:
        A plain ``QWidget`` whose layout is a ``FlowLayout``.
    """
    w = QWidget()
    flow = FlowLayout(w, h_spacing=4, v_spacing=4)
    flow.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        flow.addWidget(widget)
    return w


def make_label_grid(key_col: int = KEY_COL) -> tuple[QWidget, QGridLayout]:
    """Build the pane's one two-column grid: a fixed key column, a flowing value column.

    Args:
        key_col: The key column's minimum width in pixels. Defaults to
            :data:`KEY_COL`, the one column every "Available in"/Facts/Cast
            row in the pane lines up under; pass a narrower value for a grid
            nested under a section indent (see :data:`SECTION_INDENT`).

    Returns:
        ``(widget, grid)`` — the container widget and its ``QGridLayout``,
        ready for ``grid.addWidget(key, row, 0)`` / ``grid.addWidget(value,
        row, 1)`` calls.
    """
    w = QWidget()
    grid = QGridLayout(w)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(4)
    grid.setColumnMinimumWidth(0, key_col)
    grid.setColumnStretch(1, 1)
    return w, grid


def add_quality_badge(btn: QPushButton, colour_token: str, *, bold: bool = False) -> QPushButton:
    """Split a trailing quality token off a chip's text into the app's ONE quality badge.

    ``btn``'s text is expected to be a chip label that may end in a quality
    token ("4K", "HEVC", "RAW"…), optionally followed by a "×N" count
    ("English (EN) 4K", "Spain (ES) HD ×3"). When it does, the quality token
    is moved into its own badge — built by ``chip_row.chip_widget`` with
    ``chip_row.CHIP_QUALITY``, the SAME tier-coloured-text-on-neutral-hairline
    chip the sidebar rows use (``chip_row.quality_chip_style``) — nested
    inside ``btn``'s own layout alongside the remaining label text and count.
    A chip with no recognised trailing quality token is returned unchanged.

    Args:
        btn: A chip built by :func:`make_chip` (or any ``QPushButton``) whose
            current text may end in a quality token.
        colour_token: Name of a ``theme`` colour constant for the label/count
            text either side of the badge (the badge itself always uses the
            app's one quality→colour mapping, regardless of this value).
        bold: Bold the label text (not the badge, which has its own fixed
            weight).

    Returns:
        *btn*, mutated in place — its text cleared and replaced with a
        ``QHBoxLayout`` of (label, badge, optional count) — or *btn*
        unchanged when no trailing word is a known quality token.
    """
    words = btn.text().replace("&&", "&").split(" ")
    # The quality token may be followed by a "×N" count.
    tail = words[-2:] if len(words) > 2 and words[-1].startswith("×") else words[-1:]
    token = tail[0]
    if token.upper() not in QUALITY_TOKENS:
        return btn
    name = " ".join(words[: len(words) - len(tail)])
    count = tail[1] if len(tail) == 2 else ""

    btn.setText("")
    layout = QHBoxLayout(btn)
    layout.setContentsMargins(8, 2, 8, 2)
    layout.setSpacing(5)

    label = QLabel(name)
    theme.style_fn(label, lambda: (
        f"color: {getattr(theme, colour_token)}; font-size: {theme.FONT_MD};"
        f" background: transparent; font-weight: {'bold' if bold else 'normal'};"
    ))
    layout.addWidget(label)

    badge = chip_row.chip_widget(chip_row.CHIP_QUALITY, token)
    layout.addWidget(badge)

    if count:
        count_label = QLabel(count)
        theme.style_fn(count_label, lambda: (
            f"color: {getattr(theme, colour_token)}; font-size: {theme.FONT_MD};"
            f" background: transparent;"
        ))
        layout.addWidget(count_label)

    btn.setMinimumWidth(layout.sizeHint().width())
    btn.setMinimumHeight(make_chip("x").sizeHint().height())
    return btn


def display_code(code: str, config=None) -> str:
    """Return a code's full display form: ``"Sweden (SE)"``, falling back to the bare code.

    Args:
        code: A region/language code ("SE", "EXYU"…).
        config: Optional ``Config``, forwarded to
            ``details_versions.resolve_category_name`` so user category-name
            overrides are honoured.

    Returns:
        ``"{name} ({code})"`` when a human-readable name is known and differs
        from the code itself; the bare *code* when no name is known or the
        resolved name equals the code.
    """
    # Local import: details_versions.py is the one that defines
    # resolve_category_name and imports THIS module's chip builders (DETAILS-3c)
    # — a module-level import here would be circular.
    from metatv.gui.details_versions import resolve_category_name

    name = resolve_category_name(code, config) or REGION_FULL_NAMES.get(code, "")
    if name and name != code:
        return f"{name} ({code})"
    return code
