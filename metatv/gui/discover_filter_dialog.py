"""Discover shelf management dialog.

Four sections mirroring the zone model:
  1. Pinned shelves  — Move to Top / Up / Down; Unpin
  2. Active shelves  — same reorder; Pin / Collapse
  3. Collapsed shelves — Expand / Pin / Hide
  4. Hidden shelves  — Restore (the only recovery path)

Global actions: Collapse all / Expand all (pinned shelves immune to Collapse all).

All changes are applied to config immediately on each action; a single "Close"
button dismisses the dialog. DiscoverView.refresh() fires once on close if anything
changed (dlg._changed == True).

Inside every section the rows are grouped by FAMILY (Platforms, Collections,
Genres, ...) from the one table in ``discover_workers.SHELF_FAMILIES``, each
heading foldable so a run of eighteen collections can be passed in one click.
The fold is dialog state only (``discover_manage_folded_families``): it never
touches a zone list, and the Discover strip itself is not grouped at all -- a
platform shelf browses exactly like every other shelf.

Cross-section transfers (Hide, Restore, Pin, etc.) are O(1): one row removed from
the source container, one row added to the destination -- landing under its
family heading, which is created or pruned as that family gains or loses its
last row there. No full-section rebuilds.
Reorder operations (Up/Down/Top, Collapse All / Expand All) rebuild only the affected
section(s), which are small (pinned/expanded ≤ ~5 items in practice).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from metatv.gui.dialog_chrome import dialog_buttons
from metatv.core.config import Config
from metatv.core.database import Database
from metatv.gui import deferred_config_save as _cfgsave
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.discover_workers import SHELF_FAMILY_ORDER, family_of

if TYPE_CHECKING:
    pass

_ZONE_PINNED    = "pinned"
_ZONE_EXPANDED  = "expanded"
_ZONE_COLLAPSED = "collapsed"


def _heading_sheet(sub: bool) -> str:
    """The dialog's ONE heading style -- a zone label, or a family one step down.

    Args:
        sub: True for a family heading nested inside a zone section.

    Returns:
        A stylesheet body composed from the live theme tokens.
    """
    if sub:
        return (f"font-size: {_theme.FONT_MD}; font-weight: bold; "
                f"color: {_theme.COLOR_MUTED}; padding: 4px 0 1px 0;")
    return (f"font-size: {_theme.FONT_LG}; font-weight: bold; "
            f"color: {_theme.COLOR_TEXT}; padding: 6px 0 2px 0;")


def _section_label(text: str, sub: bool = False) -> QLabel:
    """A zone heading, or (``sub=True``) a family heading one step down."""
    lbl = QLabel(text)
    _theme.style_fn(lbl, lambda: _heading_sheet(sub))
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    _theme.style_fn(line, lambda: f"color: {_theme.COLOR_BORDER};")
    return line


class _ShelfRow(QWidget):
    """A single row in the manage list — title + action buttons."""

    def __init__(self, shelf_key: str, display_title: str, parent=None) -> None:
        super().__init__(parent)
        self.shelf_key = shelf_key

        hl = QHBoxLayout(self)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(4)

        self._title_lbl = QLabel(display_title)
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hl.addWidget(self._title_lbl)

        self._buttons: list[QPushButton] = []

    def add_button(self, label: str, slot, tooltip: str = "") -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(22)
        btn.setFlat(True)
        _theme.style_fn(btn, lambda: f"QPushButton {{ background: {_theme.COLOR_LINE}; border: 1px solid {_theme.COLOR_BORDER}; "
            f"border-radius: 3px; color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_SM}; padding: 1px 6px; }}"
            f"QPushButton:hover {{ background: {_theme.COLOR_BORDER}; color: {_theme.COLOR_TEXT_HI}; }}")
        if tooltip:
            btn.setToolTip(tooltip)
        btn.clicked.connect(lambda _checked=False, _s=slot: _s())
        self.layout().addWidget(btn)
        self._buttons.append(btn)
        return btn


class _FamilyGroup(QWidget):
    """One family's heading plus the rows that belong to it, foldable in place.

    The heading states its count because a disclosure states its count, and the
    fold is what the whole grouping exists for: eighteen collections are passed
    in one click instead of eighteen scroll-lines.  Folding is DIALOG state — it
    writes ``discover_manage_folded_families`` and nothing else, so it never
    moves a shelf between zones and never changes what Discover renders.
    """

    def __init__(self, family: str, folded: bool, on_toggle, parent=None) -> None:
        """Build the heading and its (possibly folded) row well.

        Args:
            family: The family label, from ``SHELF_FAMILY_ORDER``.
            folded: Start with the rows hidden.
            on_toggle: Called ``(family, folded)`` when the heading is clicked.
            parent: Qt parent.
        """
        super().__init__(parent)
        self.family = family
        self._folded = folded
        self._on_toggle = on_toggle

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        self.heading = QPushButton()
        self.heading.setFlat(True)
        _theme.style_fn(self.heading, lambda: (
            "QPushButton { border: none; background: transparent; text-align: left; "
            + _heading_sheet(True) + " }"
            f"QPushButton:hover {{ color: {_theme.COLOR_TEXT_HI}; }}"))
        self.heading.clicked.connect(self._toggle)
        vl.addWidget(self.heading)

        self._rows = QWidget()
        rows_vl = QVBoxLayout(self._rows)
        rows_vl.setContentsMargins(12, 0, 0, 0)
        rows_vl.setSpacing(2)
        vl.addWidget(self._rows)
        # Explicit either way: a layout skips a widget only once
        # WA_WState_Hidden is actually set, so the unfolded well is shown just
        # as deliberately as the folded one is hidden.
        self._rows.setVisible(not folded)
        self.sync_heading()

    # ---- rows ---------------------------------------------------------------

    def row_count(self) -> int:
        """How many shelf rows sit under this heading."""
        return self._rows.layout().count()

    def add_row(self, row: QWidget) -> None:
        """Append *row* under the heading and restate the count."""
        self._rows.layout().addWidget(row)
        self.sync_heading()

    # ---- fold ---------------------------------------------------------------

    def is_folded(self) -> bool:
        """True when the rows are folded away."""
        return self._folded

    def set_folded(self, folded: bool) -> None:
        """Fold or unfold WITHOUT reporting it — for syncing sibling sections."""
        self._folded = folded
        self._rows.setVisible(not folded)
        self.sync_heading()

    def _toggle(self) -> None:
        self.set_folded(not self._folded)
        self._on_toggle(self.family, self._folded)

    def sync_heading(self) -> None:
        """Restate the caret, the label and the count after any row change."""
        arrow = _icons.expand_icon if self._folded else _icons.collapse_icon
        count = self.row_count()
        self.heading.setText(f"{arrow}  {self.family} ({count})")
        verb = "Show" if self._folded else "Fold away"
        noun = "shelf" if count == 1 else "shelves"
        self.heading.setToolTip(f"{verb} {self.family} ({count} {noun})")


class DiscoverManageDialog(QDialog):
    """Shelf management: reorder, pin/collapse/hide, restore hidden.

    All changes write to config immediately. DiscoverView should check
    dlg._changed after exec() and call refresh() if True.
    """

    def __init__(self, db: Database, config: Config,
                 shelf_widgets: dict, shelf_zones: dict,
                 parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._changed = False

        # Convenience aliases — these ARE the config lists (modified in place)
        self._pinned    = config.discover_pinned_shelves
        self._expanded  = config.discover_expanded_shelves
        self._collapsed = config.discover_collapsed_shelves
        self._hidden    = config.discover_hidden_shelves

        # Display names from live shelf_widgets (already loaded)
        self._titles: dict[str, str] = {}
        for key, shelf in shelf_widgets.items():
            self._titles[key] = shelf._title_lbl.text().replace("<b>", "").replace("</b>", "")

        # Shelves present in zone map but not yet assigned to a list (first launch)
        for key, zone in shelf_zones.items():
            if (key not in self._pinned and key not in self._expanded
                    and key not in self._collapsed and key not in self._hidden):
                if zone == _ZONE_PINNED:
                    self._pinned.append(key)
                elif zone == _ZONE_EXPANDED:
                    self._expanded.append(key)
                else:
                    self._collapsed.append(key)

        # shelf_key → current row widget — enables O(1) cross-section transfers
        self._row_widgets: dict[str, _ShelfRow] = {}

        # Family headings the user folded away last time. Filtered against the
        # live table so a renamed family drops its stale fold instead of
        # resurrecting under a label nothing renders any more.
        self._folded_families: set[str] = {
            f for f in config.discover_manage_folded_families
            if f in SHELF_FAMILY_ORDER
        }

        self.setWindowTitle("Manage Discovery Shelves")
        self.setMinimumSize(500, 600)
        self._setup_ui()

    # ---- Helpers ------------------------------------------------------------

    def _commit(self) -> None:
        """Persist current config state and mark dialog as having changes."""
        _cfgsave.save_soon(self)
        self._changed = True

    # ---- UI construction ----------------------------------------------------

    def _setup_ui(self) -> None:
        vl = QVBoxLayout(self)
        vl.setSpacing(8)

        # Global actions
        global_row = QHBoxLayout()
        collapse_all_btn = QPushButton("Collapse all")
        collapse_all_btn.clicked.connect(self._collapse_all)
        expand_all_btn = QPushButton("Expand all")
        expand_all_btn.clicked.connect(self._expand_all)
        for btn in (collapse_all_btn, expand_all_btn):
            _theme.style_fn(btn, lambda: f"QPushButton {{ background: {_theme.COLOR_LINE_DARK}; border: 1px solid {_theme.COLOR_BORDER}; "
                f"border-radius: 3px; color: {_theme.COLOR_TEXT}; padding: 3px 10px; }}"
                f"QPushButton:hover {{ background: {_theme.COLOR_BORDER}; }}")
        global_row.addWidget(collapse_all_btn)
        global_row.addWidget(expand_all_btn)
        global_row.addStretch()
        vl.addLayout(global_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner_vl = QVBoxLayout(inner)
        inner_vl.setSpacing(4)

        inner_vl.addWidget(_section_label("📌 Pinned shelves"))
        self._pinned_list = self._make_list(inner_vl, self._pinned, self._build_pinned_row)
        inner_vl.addWidget(_divider())

        inner_vl.addWidget(_section_label("Active shelves"))
        self._expanded_list = self._make_list(inner_vl, self._expanded, self._build_expanded_row)
        inner_vl.addWidget(_divider())

        inner_vl.addWidget(_section_label("── Collapsed shelves ──"))
        self._collapsed_list = self._make_list(inner_vl, self._collapsed, self._build_collapsed_row)
        inner_vl.addWidget(_divider())

        inner_vl.addWidget(_section_label("🚫 Hidden shelves"))
        self._hidden_list = self._make_list(inner_vl, self._hidden, self._build_hidden_row)
        inner_vl.addStretch()

        scroll.setWidget(inner)
        vl.addWidget(scroll)

        # Close ACCEPTS here, as it always has: the caller reads the exit code
        # to decide whether to re-render the shelves.
        vl.addWidget(dialog_buttons(self, ok="Close", cancel=False))

    def _make_list(self, parent_layout: QVBoxLayout,
                   keys: list[str], row_factory) -> QWidget:
        container = QWidget()
        vl = QVBoxLayout(container)
        vl.setContentsMargins(8, 0, 0, 0)
        vl.setSpacing(2)
        self._fill_section(container, keys, row_factory)
        parent_layout.addWidget(container)
        return container

    def _sections(self) -> tuple[QWidget, ...]:
        """The four zone containers, in the order the dialog stacks them."""
        return (self._pinned_list, self._expanded_list,
                self._collapsed_list, self._hidden_list)

    def _fill_section(self, container: QWidget,
                      keys: list[str], row_factory) -> None:
        """Build a row for every key in *container*, grouped by family.

        Families render in ``SHELF_FAMILY_ORDER``; WITHIN a family the keys keep
        the order the config list gave them, which is the user's manual order —
        grouping regroups, it never re-sorts.

        Args:
            container: The zone section widget to fill.
            keys: Shelf keys, in the user's stored order.
            row_factory: Builds the row for one key (the zone's own builder).
        """
        by_family: dict[str, list[str]] = {}
        for key in keys:
            by_family.setdefault(family_of(key), []).append(key)
        for family in SHELF_FAMILY_ORDER:
            for key in by_family.get(family, ()):
                row = row_factory(key)
                self._family_group(container, family).add_row(row)
                self._row_widgets[key] = row
        self._sync_empty_label(container)

    def _family_group(self, container: QWidget, family: str) -> _FamilyGroup:
        """The container's group for *family*, created in table order if absent.

        Creating on demand is what keeps ``_transfer`` O(1): a row arriving in a
        section that has no heading for its family gets one, inserted at the
        rank the table gives it, without rebuilding a single sibling row.

        Args:
            container: The zone section widget.
            family: A label from ``SHELF_FAMILY_ORDER``.

        Returns:
            The existing or newly inserted group.
        """
        vl = container.layout()
        rank = SHELF_FAMILY_ORDER.index(family)
        insert_at = 0
        for i in range(vl.count()):
            widget = vl.itemAt(i).widget()
            if not isinstance(widget, _FamilyGroup):
                continue
            if widget.family == family:
                return widget
            if SHELF_FAMILY_ORDER.index(widget.family) < rank:
                insert_at = i + 1
        group = _FamilyGroup(family, family in self._folded_families,
                             self._on_family_folded)
        vl.insertWidget(insert_at, group)
        return group

    def _on_family_folded(self, family: str, folded: bool) -> None:
        """Record a fold and mirror it across the other zone sections.

        Deliberately NOT ``_commit()``: a fold changes nothing Discover renders,
        so it must not set ``_changed`` and trigger a shelf refresh on close.
        """
        if folded:
            self._folded_families.add(family)
        else:
            self._folded_families.discard(family)
        for container in self._sections():
            for group in container.findChildren(_FamilyGroup):
                if group.family == family and group.is_folded() != folded:
                    group.set_folded(folded)
        self._config.discover_manage_folded_families = [
            f for f in SHELF_FAMILY_ORDER if f in self._folded_families
        ]
        _cfgsave.save_soon(self)

    # ---- Row builders -------------------------------------------------------

    def _build_pinned_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, f"📌 {title}")
        row.add_button("↑↑ Top", lambda k=key: self._move_top(self._pinned, k, self._pinned_list, self._build_pinned_row), "Move to top")
        row.add_button("↑ Up",   lambda k=key: self._move_up(self._pinned, k, self._pinned_list, self._build_pinned_row))
        row.add_button("↓ Down", lambda k=key: self._move_down(self._pinned, k, self._pinned_list, self._build_pinned_row))
        row.add_button("Unpin",  lambda k=key: self._transfer(k, self._pinned, self._pinned_list,
                                                               self._expanded, self._expanded_list,
                                                               self._build_expanded_row))
        return row

    def _build_expanded_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("↑↑ Top",   lambda k=key: self._move_top(self._expanded, k, self._expanded_list, self._build_expanded_row))
        row.add_button("↑ Up",     lambda k=key: self._move_up(self._expanded, k, self._expanded_list, self._build_expanded_row))
        row.add_button("↓ Down",   lambda k=key: self._move_down(self._expanded, k, self._expanded_list, self._build_expanded_row))
        row.add_button("Pin",      lambda k=key: self._transfer(k, self._expanded, self._expanded_list,
                                                                 self._pinned, self._pinned_list,
                                                                 self._build_pinned_row))
        row.add_button("Collapse", lambda k=key: self._transfer(k, self._expanded, self._expanded_list,
                                                                 self._collapsed, self._collapsed_list,
                                                                 self._build_collapsed_row))
        return row

    def _build_collapsed_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("Expand", lambda k=key: self._transfer(k, self._collapsed, self._collapsed_list,
                                                               self._expanded, self._expanded_list,
                                                               self._build_expanded_row))
        row.add_button("Pin",    lambda k=key: self._transfer(k, self._collapsed, self._collapsed_list,
                                                               self._pinned, self._pinned_list,
                                                               self._build_pinned_row))
        row.add_button("Hide",   lambda k=key: self._transfer(k, self._collapsed, self._collapsed_list,
                                                               self._hidden, self._hidden_list,
                                                               self._build_hidden_row))
        return row

    def _build_hidden_row(self, key: str) -> _ShelfRow:
        title = self._titles.get(key, key)
        row = _ShelfRow(key, title)
        row.add_button("Restore", lambda k=key: self._transfer(k, self._hidden, self._hidden_list,
                                                                self._collapsed, self._collapsed_list,
                                                                self._build_collapsed_row))
        return row

    # ---- List operations ----------------------------------------------------

    def _move_top(self, lst: list[str], key: str, container: QWidget, row_factory) -> None:
        """Move *key* to the top of its family — the top of the group it is drawn in."""
        if key not in lst:
            return
        lst.remove(key)
        family = family_of(key)
        at = next((i for i, k in enumerate(lst) if family_of(k) == family), 0)
        lst.insert(at, key)
        self._reload_section(container, lst, row_factory)
        self._commit()

    def _move_up(self, lst: list[str], key: str, container: QWidget, row_factory) -> None:
        self._swap_within_family(lst, key, -1, container, row_factory)

    def _move_down(self, lst: list[str], key: str, container: QWidget, row_factory) -> None:
        self._swap_within_family(lst, key, +1, container, row_factory)

    def _swap_within_family(self, lst: list[str], key: str, step: int,
                            container: QWidget, row_factory) -> None:
        """Swap *key* with its nearest same-family neighbour in *step*'s direction.

        Rows are DRAWN grouped by family, so swapping with the raw list
        neighbour moves the key past a row in another family and nothing
        visibly happens — Up/Down would silently no-op at every family
        boundary. Walking to the next member of the same family is what makes
        the button do what it looks like it does.

        Args:
            lst: The zone's config list, reordered in place.
            key: The shelf being moved.
            step: -1 for up, +1 for down.
            container: The zone section to re-render.
            row_factory: The zone's row builder.
        """
        if key not in lst:
            return
        family = family_of(key)
        idx = lst.index(key)
        probe = idx + step
        while 0 <= probe < len(lst):
            if family_of(lst[probe]) == family:
                lst[idx], lst[probe] = lst[probe], lst[idx]
                self._reload_section(container, lst, row_factory)
                self._commit()
                return
            probe += step

    def _transfer(self, key: str,
                  src_list: list[str], src_container: QWidget,
                  dst_list: list[str], dst_container: QWidget,
                  dst_factory) -> None:
        """Move a shelf between sections — O(1): one row removed, one row added.

        The row lands under its family heading in the destination, which is
        created if it is that family's first row there and pruned when its last
        row leaves.  Still O(1): only the moving row's own two groups are
        touched, never a sibling row and never a section rebuild.

        Enforces ``pin ⟹ expand``: when the destination is the pinned list, the
        key is also removed from the expanded and collapsed lists so the config
        lists remain mutually exclusive.  The row widget in those containers is
        detached the same way if the key somehow appeared in more than one
        visual section (config-inconsistency repair path).
        """
        if key in src_list:
            src_list.remove(key)
        if key not in dst_list:
            dst_list.append(key)

        # If the destination is pinned, ensure the key is not duplicated in
        # expanded or collapsed (mutual-exclusion invariant).
        if dst_list is self._pinned:
            for extra_list, extra_container in (
                (self._expanded,  self._expanded_list),
                (self._collapsed, self._collapsed_list),
            ):
                if key in extra_list:
                    extra_list.remove(key)
                    # Remove the stale row widget from that container too.
                    extra_row = self._row_widgets.pop(key, None)
                    if extra_row:
                        self._detach_row(extra_row)
                    self._sync_empty_label(extra_container)

        # Remove old row from source container
        old_row = self._row_widgets.pop(key, None)
        if old_row:
            self._detach_row(old_row)
        self._sync_empty_label(src_container)

        # Add new row under its family heading in the destination, then remove
        # the placeholder if one existed
        new_row = dst_factory(key)
        self._family_group(dst_container, family_of(key)).add_row(new_row)
        self._row_widgets[key] = new_row
        self._sync_empty_label(dst_container)

        self._commit()

    def _detach_row(self, row: _ShelfRow) -> None:
        """Take *row* out of whatever holds it, pruning an emptied family heading.

        A heading with no rows left is noise the user has to read past, so it
        goes with its last row; a heading that still has rows restates its
        count. Both are O(1) — the row's own group and nothing else.

        Args:
            row: The row widget to remove from the layout tree.
        """
        holder = row.parentWidget()
        if holder is not None and holder.layout() is not None:
            holder.layout().removeWidget(row)
        row.setParent(None)
        group = holder.parentWidget() if holder is not None else None
        if not isinstance(group, _FamilyGroup):
            return
        if group.row_count() == 0:
            section = group.parentWidget()
            if section is not None and section.layout() is not None:
                section.layout().removeWidget(group)
            group.setParent(None)
        else:
            group.sync_heading()

    # ---- Section helpers ----------------------------------------------------

    def _add_empty_label(self, container: QWidget) -> None:
        empty = QLabel("(none)")
        empty.setObjectName("_empty_placeholder")
        _theme.style_fn(empty, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; padding: 2px 0;")
        container.layout().addWidget(empty)

    def _sync_empty_label(self, container: QWidget) -> None:
        """Show (none) label when no _ShelfRow remains; remove it when rows exist.

        Searches the whole subtree: a row now lives inside its family group
        rather than directly under the section, and a folded group's rows are
        hidden but still present — a folded section is not an empty one.
        """
        has_rows = bool(container.findChildren(_ShelfRow))
        placeholder = container.findChild(QLabel, "_empty_placeholder")
        if has_rows and placeholder:
            placeholder.setParent(None)
        elif not has_rows and not placeholder:
            self._add_empty_label(container)

    def _reload_section(self, container: QWidget,
                        keys: list[str], row_factory) -> None:
        """Full rebuild — used only for reorder (Up/Down/Top) and Collapse/Expand All."""
        vl = container.layout()
        while vl.count():
            item = vl.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        self._fill_section(container, keys, row_factory)

    # ---- Global actions -----------------------------------------------------

    def _collapse_all(self) -> None:
        """Move all expanded shelves to collapsed (pinned are immune)."""
        for key in list(self._expanded):
            self._expanded.remove(key)
            if key not in self._collapsed:
                self._collapsed.append(key)
        self._reload_section(self._expanded_list, self._expanded, self._build_expanded_row)
        self._reload_section(self._collapsed_list, self._collapsed, self._build_collapsed_row)
        self._commit()

    def _expand_all(self) -> None:
        """Move all collapsed shelves to expanded."""
        for key in list(self._collapsed):
            self._collapsed.remove(key)
            if key not in self._expanded:
                self._expanded.append(key)
        self._reload_section(self._collapsed_list, self._collapsed, self._build_collapsed_row)
        self._reload_section(self._expanded_list, self._expanded, self._build_expanded_row)
        self._commit()
