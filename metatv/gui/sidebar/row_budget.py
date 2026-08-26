"""Fitting a section's rows to the height it was allocated.

R13, mechanism 1 — **no nested scrollbars.** The sidebar had a scrollbar inside
a scrollbar: Watch Alerts subdivided 173px four ways, each sub-group scrolling
in about 35px, which is a window too small to read through. *"This alone
recovers most of the jam."*

A section shows the rows that fit and ends with ``+N more``. That is **a
consequence of the allocated height, never a cap** — drag a section taller and
it renders more rows; the minimum is a floor, never a ceiling.

Two shapes, because sections have two:

``apply_row_budget``      a flat ``QListWidget`` — one tail at the end.
``apply_tree_row_budget`` a ``QTreeWidget`` of sub-groups — every group header
                          stays on screen and each truncates its OWN children,
                          because the fix R13 asks for is "three readable
                          groups". Budgeting the top-level rows instead hides
                          whole groups, which is the problem rather than the
                          fix.

Its own module because ``base.py`` carries a 1000-line cap and this is a
separable concern: it takes a widget and a height and returns a count.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QListWidgetItem, QTreeWidgetItem

#: The role the "+N more" marker lives in — **not** ``UserRole``.
#:
#: It was UserRole, and that crashed the app. Every section stores its own
#: payload there — a channel id, or in Watch Queue a dict — and twelve
#: handlers read it back and use it. Selecting the tail row handed
#: ``_on_selection_changed`` a string where it expected a dict:
#:
#:     AttributeError: 'str' object has no attribute 'get'
#:
#: Its own role keeps UserRole untouched on the tail, so every one of those
#: readers sees ``None`` and takes its existing "no payload" branch. Guarding
#: twelve call sites would have been twelve chances to miss one.
_MORE_ROLE = Qt.ItemDataRole.UserRole + 1

#: Value stored in :data:`_MORE_ROLE`. Kept as a name so a reader of the click
#: handler can see what is being compared.
_MORE_ROW = "__more_row__"


class RowBudgetMixin:
    """Fits a section's rows to its current height.

    Mixed into ``CollapsibleSection``; expects ``ROW_H`` and ``exploreClicked``
    from it.
    """

    # ── Row budget: no nested scrollbars ────────────────────────────────────

    def apply_row_budget(self, list_widget, on_more=None) -> int:
        """Show the rows that FIT and end with ``+N more →``; never scroll.

        The sidebar had a scrollbar inside a scrollbar — Watch Alerts
        subdivided 173px four ways, each sub-group scrolling in ~35px, which is
        a window too small to read through. *This alone recovers most of the
        jam* (R13, mechanism 1).

        ``+N more`` is **a consequence of the allocated height, never a cap**:
        drag the section taller and it renders more rows. The minimum is a
        floor, never a ceiling.

        Args:
            list_widget: The section's ``QListWidget``, already populated.
            on_more: Called when the tail row is activated. Defaults to the
                section's Explore link, which is where "show me the rest"
                already goes.

        Returns:
            How many rows were hidden behind the tail (0 when everything fit).
        """
        list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Drop any tail from a previous pass FIRST. This runs again on every
        # resize, and without this each drag would stack another "+N more" row
        # on the end of the list.
        for index in reversed(range(list_widget.count())):
            if list_widget.item(index).data(_MORE_ROLE) == _MORE_ROW:
                list_widget.takeItem(index)

        total = list_widget.count()
        if total == 0:
            return 0

        viewport = list_widget.viewport().height()
        if viewport <= 0:
            # Not laid out yet — leave every row visible rather than guessing a
            # budget from a zero height and hiding the whole list.
            for index in range(total):
                list_widget.item(index).setHidden(False)
            return 0

        used, fits = 0, 0
        for index in range(total):
            item = list_widget.item(index)
            item.setHidden(False)
            height = item.sizeHint().height() or self.ROW_H
            if used + height > viewport:
                break
            used += height
            fits += 1

        if fits >= total:
            return 0

        # ...but never all of it. A section rendering "+ 6 more →" over an empty
        # list tells you there is content and shows you none of it, which reads
        # as a broken section rather than a full one. One real row always wins
        # over the marker that counts them, and the header's → is still the way
        # to the rest.
        #
        # And the row it keeps must be CONTENT. Group headings and dividers
        # carry NoItemFlags, and a floor of 1 that lands on one of those renders
        # a label, a separator, and a count of things it is not showing —
        # exactly what Movies & Series did with "──── Watching for ────" over
        # "+ 12 more →".
        first_content = next(
            (i for i in range(total)
             if list_widget.item(i).flags() != Qt.ItemFlag.NoItemFlags),
            None,
        )
        floor = 1 if first_content is None else first_content + 1
        fits = min(max(fits, floor), total)

        hidden = total - fits
        for index in range(fits, total):
            list_widget.item(index).setHidden(True)

        tail = QListWidgetItem(f"+ {hidden} more  →")
        tail.setData(_MORE_ROLE, _MORE_ROW)
        # Clickable but NOT selectable: it is a link, not a row you can be "on",
        # and leaving it selectable also means every selection handler has to
        # cope with the current item having no payload.
        tail.setFlags(tail.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        tail.setToolTip(f"{hidden} more — open the full view")
        list_widget.addItem(tail)

        # The tail costs whatever the tail ACTUALLY costs. This used to reserve
        # ``ROW_H`` up front, which is the SIMPLE-row constant (24px) while a
        # rendered tail draws ~17 — so the section quietly gave away up to a row
        # of content to space it never used. Measuring after the fact is exact,
        # and it is the only way to be exact: a plain QListWidgetItem has no
        # size hint until a list has laid it out.
        while fits > 1:
            rect = list_widget.visualItemRect(tail)
            if rect.height() <= 0 or rect.bottom() <= viewport:
                break
            fits -= 1
            list_widget.item(fits).setHidden(True)
            hidden += 1
            tail.setText(f"+ {hidden} more  →")
            tail.setToolTip(f"{hidden} more — open the full view")

        self._more_handler = on_more or self.exploreClicked.emit
        try:
            list_widget.itemClicked.disconnect(self._on_more_row_clicked)
        except TypeError:
            pass
        list_widget.itemClicked.connect(self._on_more_row_clicked)
        return hidden

    def apply_tree_row_budget(self, tree) -> int:
        """Fit a ``QTreeWidget`` of sub-groups — budgeting WITHIN each group.

        Watch Alerts is the section R13 names directly: 173px subdivided four
        ways, each sub-group scrolling in about 35px. The fix it asks for is
        *"three readable groups"*, which means every group stays on screen and
        each one truncates its own children — not one tail at the bottom that
        hides whole groups. The approved render shows exactly that: ``EPG · 5``
        with ``+ 4 more`` under it, then ``MOVIES & SERIES · 13`` with
        ``+ 12 more``, then ``STREAM MONITORING · 1`` in full.

        So the group headers are never hidden; only their children are, and
        each group carries its own tail.

        Returns:
            Total children hidden across all groups.
        """
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        groups = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        for group in groups:
            for index in reversed(range(group.childCount())):
                if group.child(index).data(0, _MORE_ROLE) == _MORE_ROW:
                    group.takeChild(index)
        if not groups:
            return 0

        viewport = tree.viewport().height()
        if viewport <= 0:
            for group in groups:
                for index in range(group.childCount()):
                    group.child(index).setHidden(False)
            return 0

        # Every group header is guaranteed its row; what is left is split among
        # the groups that are actually open. A group closed by the user costs
        # its header and nothing else.
        open_groups = [g for g in groups if g.isExpanded() and g.childCount()]
        headroom = viewport - len(groups) * self.ROW_H
        if not open_groups or headroom < self.ROW_H:
            return 0

        share = max(1, (headroom // len(open_groups)) // self.ROW_H)
        hidden_total = 0
        for group in open_groups:
            total = group.childCount()
            for index in range(total):
                group.child(index).setHidden(False)
            if total <= share:
                continue
            keep = max(1, share - 1)          # the tail costs one child row
            for index in range(keep, total):
                group.child(index).setHidden(True)
            hidden = total - keep
            hidden_total += hidden
            tail = QTreeWidgetItem([f"+ {hidden} more"])
            tail.setData(0, _MORE_ROLE, _MORE_ROW)
            tail.setFlags(tail.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            tail.setToolTip(0, f"{hidden} more in this group")
            group.addChild(tail)
        return hidden_total

    def budgeted_tree(self):
        """The ``QTreeWidget`` this section fits rows into, or ``None``."""
        return None

    def budgeted_list(self):
        """The list this section fits rows into, or ``None`` to opt out.

        Sections override with their ``QListWidget``. Opting out is the right
        answer for a section whose content is not a flat list — Watch Alerts
        renders a ``QTreeWidget`` of sub-groups, which needs its own budget.
        """
        return None

    def extra_budgeted_lists(self):
        """Further lists this section budgets, as ``[(list, on_more), …]``.

        For a section built from SEVERAL lists — Watch Alerts has Movies &
        Series and Stream Monitoring alongside its EPG tree. They have to be
        re-budgeted from the same seam as everything else, because a budget
        applied once at populate is computed against a viewport that has not
        been laid out yet: Movies & Series rendered a divider and
        "+ 12 more →" inside a box with room for five rows, and nothing ever
        recomputed it when the section reached its real height.

        Returns:
            An iterable of ``(QListWidget, on_more callable)``. Empty by
            default — most sections have one list and use
            :meth:`budgeted_list`.
        """
        return ()

    def reapply_row_budget(self) -> None:
        """Re-fit the rows to the section's CURRENT height.

        This is what makes ``+N more`` an allocation consequence rather than a
        cap: without it the budget would be computed once, at load, and dragging
        a section taller would leave it showing the same rows it showed at its
        old size. Called on resize and after every populate.
        """
        lst = self.budgeted_list()
        if lst is not None:
            self.apply_row_budget(lst)
        for extra, on_more in self.extra_budgeted_lists():
            if extra is not None and extra.isVisible():
                self.apply_row_budget(extra, on_more=on_more)
        tree = self.budgeted_tree()
        if tree is not None:
            self.apply_tree_row_budget(tree)
        if lst is not None or tree is not None:
            self.refresh_header_status()

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        """Re-fit on every resize — the splitter drag is the whole point.

        Deferred by a zero-timer because the viewport has not taken its new
        height yet while this fires; measuring here would budget against the
        size the section is leaving, not the one it is arriving at.
        """
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reapply_row_budget)

    def _on_more_row_clicked(self, item) -> None:
        """Route a click on the ``+N more`` tail to the section's full view."""
        if item is not None and item.data(_MORE_ROLE) == _MORE_ROW:
            handler = self.__dict__.get("_more_handler")
            if handler is not None:
                handler()
