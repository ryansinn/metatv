"""Collapsible sections of the Global Exclusions dialog.

``TagExclusionSection`` is one tag axis — Channel Categories, Genres, Content
Provenance — as a checkbox grid with counts, a "N more" fold for the long tail,
and a header that collapses the body and summarises it ("2 of 7 excluded").
``SectionCollapser`` gives the same header behaviour to the Languages and
Platforms blocks, whose rows the dialog builds itself. Both remember their
state in ``Config.global_exclusions_collapsed`` by section title, saved the
moment it changes.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from metatv.gui import icon_utils as _icon_utils
from metatv.gui import theme as _theme

#: The narrowest a grid cell may get before the grid drops a column.
_MIN_CELL_PX = 210


def _caret_button(on_click: Callable[[], None]) -> QPushButton:
    btn = QPushButton()
    btn.setFlat(True)
    btn.setFixedSize(18, 18)
    btn.clicked.connect(on_click)
    return btn


class SectionCollapser:
    """Collapse state for one titled section, persisted by title.

    Args:
        config: The application config (``global_exclusions_collapsed``).
        title: The section title — the persistence key.
        apply: Called with ``collapsed`` whenever the state changes.
        summary: Returns the text shown beside the title (always visible, so a
            collapsed section still says what it holds).
    """

    def __init__(self, config, title: str, apply: Callable[[bool], None],
                 summary: Callable[[], str]) -> None:
        self._config = config
        self.title = title
        self._apply = apply
        self._summary = summary
        self.collapsed = title in (getattr(config, "global_exclusions_collapsed", None) or [])
        self.caret = _caret_button(self.toggle)
        self.summary_label = QLabel()
        _theme.style(self.summary_label, "LABEL_MUTED")

    def install(self, header_row: QHBoxLayout) -> None:
        """Put the caret first and the summary after the title (and info mark)."""
        header_row.insertWidget(0, self.caret)
        header_row.insertWidget(min(3, header_row.count()), self.summary_label)
        self.sync()

    def toggle(self) -> None:
        self.collapsed = not self.collapsed
        stored = [t for t in (getattr(self._config, "global_exclusions_collapsed", None) or [])
                  if t != self.title]
        self._config.global_exclusions_collapsed = stored + ([self.title] if self.collapsed else [])
        self._config.save()
        self.sync()

    def sync(self) -> None:
        """Re-apply the state and refresh caret, tooltip and summary."""
        _icon_utils.set_button_icon(self.caret, "expand" if self.collapsed else "collapse")
        self.caret.setToolTip(("Expand " if self.collapsed else "Collapse ") + self.title)
        self.summary_label.setText(self._summary())
        self._apply(self.collapsed)


class TagExclusionSection(QWidget):
    """One tag axis of the Exclusions dialog as a collapsible checkbox grid.

    Args:
        config: The application config (collapse persistence).
        title: Section title, also the collapse key.
        info: Tooltip for the info mark — what the axis matches.
        items: ``(value, label, count)`` — *value* is what gets saved.
        checked: Values excluded now.
        unit: Count suffix (``" channels"``; titles read as bare numbers).
        columns: Columns at full width; fewer when the dialog is narrow.
        fold_below: Items under this count go behind a "N more" fold
            (checked ones always stay out front).
        extra: A widget shown above the grid (the genre mode choice).
        select_links: The dialog's ``all · none`` factory.
    """

    def __init__(self, config, title: str, info: str, items: list[tuple[str, str, int]],
                 checked: set[str], *, unit: str = "", columns: int = 3,
                 fold_below: int | None = None, extra: QWidget | None = None,
                 select_links: Callable[[str, Callable[[bool], None]], QWidget] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self._columns = columns
        self._cols_now = 0
        self._checkboxes: dict[str, QCheckBox] = {}
        self._labels: dict[str, str] = {}
        self._fold_open = False
        self._searching = False
        self._matches: set[str] = set()   # values matching the active search
        self._cell_value: dict[int, str] = {}

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        _theme.style(sep, "SEP_DARK")
        vl.addWidget(sep)

        header = QHBoxLayout()
        hdr = QLabel(title)
        _theme.style(hdr, "SECTION_TITLE_SM")
        header.addWidget(hdr)
        from metatv.gui.global_filter_dialog import _info_label
        header.addWidget(_info_label(info))
        header.addStretch()
        if select_links is not None:
            header.addWidget(select_links(title, self.set_all))
        vl.addLayout(header)

        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(22, 0, 0, 6)
        body.setSpacing(2)
        if extra is not None:
            body.addWidget(extra)
        self._front, self._tail = [], []
        for value, label, count in items:
            cell = self._make_cell(value, label, count, unit, value in checked)
            folded = fold_below is not None and count < fold_below and value not in checked
            (self._tail if folded else self._front).append(cell)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(18)
        self._grid.setVerticalSpacing(0)
        body.addLayout(self._grid)
        self._fold_link = QLabel()
        self._fold_link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._fold_link.linkActivated.connect(self._toggle_fold)
        self._fold_link.setVisible(bool(self._tail))
        body.addWidget(self._fold_link)
        vl.addWidget(self._body)

        self.collapser = SectionCollapser(config, title, self._apply_collapsed, self._summary)
        self.collapser.install(header)
        for cb in self._checkboxes.values():
            cb.toggled.connect(lambda _c: self.collapser.summary_label.setText(self._summary()))
        self._sync_fold()

    def _make_cell(self, value: str, label: str, count: int, unit: str, checked: bool) -> QWidget:
        cell = QWidget(self._body)  # parented now: a folded cell never enters the grid
        hl = QHBoxLayout(cell)
        hl.setContentsMargins(2, 1, 2, 1)
        hl.setSpacing(6)
        cb = QCheckBox(label.replace("&", "&&"))  # a lone & is a Qt shortcut marker
        cb.setChecked(checked)
        _theme.style(cb, "FILTER_ITEM_TEXT")
        hl.addWidget(cb)
        count_lbl = QLabel(f"({count:,}{unit})")
        _theme.style(count_lbl, "LABEL_MUTED")
        hl.addWidget(count_lbl)
        hl.addStretch()
        self._checkboxes[value] = cb
        self._labels[value] = label.lower()
        self._cell_value[id(cell)] = value
        return cell

    # ── State API (what the dialog saves) ────────────────────────────────────

    def checked_values(self) -> list[str]:
        return [v for v, cb in self._checkboxes.items() if cb.isChecked()]

    def set_all(self, checked: bool) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(checked)

    def _summary(self) -> str:
        return f"{len(self.checked_values())} of {len(self._checkboxes)} excluded"

    # ── Layout: collapse, fold, columns ──────────────────────────────────────

    def _apply_collapsed(self, collapsed: bool) -> None:
        self._body.setVisible(self._searching or not collapsed)

    def _toggle_fold(self, _href: str = "") -> None:
        self._fold_open = not self._fold_open
        self._sync_fold()

    def _sync_fold(self) -> None:
        n = len(self._tail)
        self._fold_link.setText(
            f'<a href="#" style="color:{_theme.COLOR_ACCENT_BLUE};">'
            + ("Show fewer" if self._fold_open else f"Show {n} more") + "</a>")
        self._relayout(force=True)

    def _relayout(self, force: bool = False) -> None:
        cols = max(1, min(self._columns, (self.width() - 22) // _MIN_CELL_PX)) if self.width() > 0 else self._columns
        if cols == self._cols_now and not force:
            return
        self._cols_now = cols
        for cell in self._front + self._tail:
            self._grid.removeWidget(cell)
        # Only shown cells take a slot, so a search or a closed fold leaves no gaps.
        # Decided here, not read back from isHidden(): a cell not yet shown
        # reports hidden, which emptied the grid on first build.
        placed = []
        for cell in self._front + self._tail:
            show = (self._cell_value[id(cell)] in self._matches if self._searching
                    else cell in self._front or self._fold_open)
            cell.setVisible(show)
            if show:
                placed.append(cell)
        for i, cell in enumerate(placed):
            self._grid.addWidget(cell, i // cols, i % cols)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(event)
        self._relayout()

    # ── Realtime search (the dialog's _FilterBlock calls this) ───────────────

    def apply_filter(self, query: str) -> bool:
        """Show only cells whose label contains *query*; an empty query restores
        the fold and collapse state. Returns True when anything is visible."""
        self._searching = bool(query)
        self._matches = {v for v, label in self._labels.items() if query and query in label}
        any_match = not query or bool(self._matches)
        self._fold_link.setVisible(bool(self._tail) and not query)
        self._apply_collapsed(self.collapser.collapsed)
        self._relayout(force=True)
        self.setVisible(any_match)
        return any_match


def load_tag_counts(db, tag_type: str, *, by_title: bool = False,
                    values: list[str] | None = None) -> list[tuple[str, int]]:
    """``[(value, count)]`` for one tag type, largest first.

    Counts channels, or with *by_title* distinct titles (``content_key``,
    falling back to the channel id), so a film on four sources counts once.
    An indexed join over the tag population — about a third of a second for
    the genre tags of a 300k-channel library — so it loads with the dialog.
    """
    from sqlalchemy import func

    from metatv.core.database import ChannelDB, ContentTagDB, TagDB

    with db.session_scope() as session:
        if by_title:
            from metatv.core.content_identity import title_key_expr
            unit = func.count(func.distinct(title_key_expr(ChannelDB.content_key, ChannelDB.id)))
        else:
            unit = func.count(func.distinct(ContentTagDB.channel_key))
        q = (session.query(TagDB.value, unit)
             .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
             .filter(TagDB.type == tag_type))
        if by_title:
            q = q.join(ChannelDB, ChannelDB.channel_key == ContentTagDB.channel_key)
        if values is not None:
            q = q.filter(TagDB.value.in_(values))
        rows = q.group_by(TagDB.value).order_by(unit.desc()).all()
        return [(v, int(n)) for v, n in rows if v]


def genre_mode_choice(current: str, only_example: str, any_example: str) -> tuple[QWidget, QButtonGroup]:
    """The two-way genre rule shown above the genre grid.

    Returns:
        The widget and its button group; button id 0 = "only", 1 = "any".
    """
    w = QWidget()
    vl = QVBoxLayout(w)
    vl.setContentsMargins(0, 2, 0, 6)
    vl.setSpacing(1)
    group = QButtonGroup(w)
    for i, (text, example) in enumerate((
        ("Hide titles that are only excluded genres", only_example),
        ("Hide titles with any excluded genre", any_example),
    )):
        rb = QRadioButton(text)
        _theme.style(rb, "FILTER_ITEM_TEXT")
        rb.setChecked((current == "any") == (i == 1))
        group.addButton(rb, i)
        vl.addWidget(rb)
        hint = QLabel(example)
        _theme.style(hint, "LABEL_MUTED")
        hint.setContentsMargins(24, 0, 0, 2)
        vl.addWidget(hint)
    return w, group


def restore_dialog_size(dialog: QWidget, config) -> None:
    """Open the Exclusions dialog at the size the user last left it, else one
    that fits the category and genre grids — never larger than the screen."""
    w, h = (list(getattr(config, "global_exclusions_dialog_size", None) or []) + [0, 0])[:2]
    w, h = (w, h) if w and h else (860, 900)
    screen = dialog.screen().availableGeometry() if dialog.screen() else None
    if screen is not None:
        w, h = min(w, screen.width() - 40), min(h, screen.height() - 40)
    dialog.resize(max(w, dialog.minimumWidth()), max(h, dialog.minimumHeight()))


def remember_dialog_size(dialog: QWidget, config) -> None:
    """Save the dialog size (UI state, saved on OK and Cancel alike)."""
    config.global_exclusions_dialog_size = [dialog.width(), dialog.height()]
    config.save()
