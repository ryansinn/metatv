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

from PyQt6.QtCore import QEvent, Qt, QTimer
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

        **Only when the viewer has asked for "Show N more" rows.** By default
        every row is present and the list scrolls, like every other list in the
        app and in every other program.

        Budgeting exists to avoid a scrollbar inside a scrollbar (R13: Watch
        Alerts split 173px four ways, each sub-group scrolling in ~35px, a
        window too small to read through). But hiding rows is only worth doing
        when something can REVEAL them, and the only thing that does is the tail
        row. A section hiding two hundred rows while looking exactly like one
        showing all three is simply misleading. Owner: "should really load the
        whole list with scroll bars at the start, no?" and "the scrollbars
        should only be hidden when it's the initial option to have the 'show
        more' option."

        So one setting switches BOTH halves — scrollbar, or budget-plus-tail.
        Never a truncated list with neither.

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
        if not self._wants_more_row():
            self._show_all_rows(list_widget)
            return 0
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

        # "Show N more", not "+ N more →". The arrow said "this leaves for
        # somewhere else", which is what the header's Explore → does; this one
        # grows the section in place. Two affordances that looked and behaved
        # the same were a duplicate, not a choice.
        #
        # Its audience is specifically people WITHOUT a scroll wheel — wheeling
        # the list is the primary way to reveal more (see eventFilter). That is
        # why it keeps the link colour instead of being muted as secondary
        # chrome: de-emphasising it would hide the accessible path from exactly
        # the people who depend on it.
        if self._wants_more_row():
            label, tip = self._tail_text(hidden)
            tail = QListWidgetItem(label)
            tail.setData(_MORE_ROLE, _MORE_ROW)
            # Clickable but NOT selectable: it is a link, not a row you can be
            # "on", and leaving it selectable also means every selection handler
            # has to cope with the current item having no payload.
            tail.setFlags(tail.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            tail.setToolTip(tip)
            list_widget.addItem(tail)

            # The tail costs whatever the tail ACTUALLY costs. This used to
            # reserve ``ROW_H`` up front, which is the SIMPLE-row constant
            # (24px) while a rendered tail draws ~17 — so the section quietly
            # gave away up to a row of content to space it never used.
            # Measuring after the fact is exact, and it is the only way to be
            # exact: a plain QListWidgetItem has no size hint until a list has
            # laid it out.
            while fits > 1:
                rect = list_widget.visualItemRect(tail)
                if rect.height() <= 0 or rect.bottom() <= viewport:
                    break
                fits -= 1
                list_widget.item(fits).setHidden(True)
                hidden += 1
                # Re-label through _tail_text, never with a literal. This loop
                # used to hardcode the old "+ N more  →" string, so a tail that
                # was rendered correctly reverted to the old label — and the old
                # ACTION's promise — the moment the budget shrank it by a row.
                # That is the "second Show more launched the explorer" report.
                label, tip = self._tail_text(hidden)
                tail.setText(label)
                tail.setToolTip(tip)

        # Wiring happens whether or not the tail was drawn: the WHEEL is the
        # primary way to reveal more, and gating it on a row that exists to
        # serve people who cannot use the wheel would be exactly backwards.
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
        # Collect the groups and strip any previous tails FIRST: both branches
        # below need them, and the early return read `groups` before this ran.
        groups = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        for group in groups:
            for index in reversed(range(group.childCount())):
                if group.child(index).data(0, _MORE_ROLE) == _MORE_ROW:
                    group.takeChild(index)
        if not groups:
            return 0

        if not self._wants_more_row():
            for group in groups:
                for index in range(group.childCount()):
                    group.child(index).setHidden(False)
            # The SECTION scrolls, never the tree — one scrolling surface.
            tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.fit_to_rows(tree)
            return 0
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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
            if not self._wants_more_row():
                continue
            label, tip = self._tail_text(hidden)
            tail = QTreeWidgetItem([label])
            tail.setData(0, _MORE_ROLE, _MORE_ROW)
            tail.setFlags(tail.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            tail.setToolTip(0, tip)
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
        self._after_budget()
        if lst is not None or tree is not None:
            self.refresh_header_status()

    def _after_budget(self) -> None:
        """Re-run the pressure pass after the rows have been re-fitted.

        The budget is what changes the content height, and the content height
        is what the section's maximum is derived from — so a refresh has to
        recompute the cap, not just a resize. Routed through the DEBOUNCED
        scheduler rather than called directly, so a burst of refreshes costs
        one pass.
        """
        schedule = getattr(self, "_schedule_pressure", None)
        if callable(schedule):
            schedule()

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        """Re-fit on every resize — the splitter drag is the whole point.

        Deferred by a zero-timer because the viewport has not taken its new
        height yet while this fires; measuring here would budget against the
        size the section is leaving, not the one it is arriving at.
        """
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reapply_row_budget)

    def _show_all_rows(self, view) -> None:
        """Show every row at full height and let the SECTION scroll.

        The view itself must not scroll: the section owns one scroll area
        (``CollapsibleSection.content_scroll``), and a view scrolling inside it
        is the nested scrollbar R13 forbids — a ~35px window nobody can read
        through. So the view takes the height its rows need, and the surplus
        becomes the section's scroll range.

        Sizing it here rather than leaving it to Qt matters: a view asks for a
        DEFAULT viewport, not for its contents, so an unsized one both clips its
        own rows and draws over whatever follows it — which is how Stream
        Monitoring ended up printed across the Series rows.
        """
        for index in range(view.count()):
            view.item(index).setHidden(False)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fit_to_rows(view)

    @staticmethod
    def fit_to_rows(view) -> None:
        """Set a view's height to exactly what its contents need.

        Qt's own ``viewportSizeHint()`` — the ideal viewport for the current
        contents. Two hand-rolled versions got this wrong differently:
        ``visualItemRect`` is (0,0,0,0) before layout, and
        ``sizeHint().height()`` returns **-1** when unset, which poisons a sum.
        Qt already knows the number.
        """
        view.updateGeometries()
        hint = view.viewportSizeHint().height()
        view.setFixedHeight(max(0, hint) + 2 * view.frameWidth())

    def _wants_more_row(self) -> bool:
        """Whether to draw the "Show N more" tail at all.

        Off by default. Wheeling the list reveals more (see :meth:`eventFilter`),
        so for anyone with a scroll wheel the row is a standing distraction
        advertising something they would do anyway. It stays available as a
        setting for pointing devices that cannot scroll — the rows are still
        hidden either way, and the budget still reports them.
        """
        # No longer forced on for a subdividing section. That was true while
        # each of its views had to fit inside the panel: a scrollbar there would
        # have been a ~35px band, so a tail row was the only way out. The
        # section owns ONE scroll area now, so overflow has somewhere to go and
        # every view can simply be its full height.
        #
        # Forcing it also broke collapsing: with budgeting on, collapsing the
        # Series group let the budget swallow the group's heading and replace
        # everything with "See all 11 more →".
        return bool(getattr(self.config, "sidebar_show_more_row", False))

    def _can_grow(self) -> bool:
        """Whether asking for room would actually get any."""
        grow = self.__dict__.get("grow_request")
        if grow is None:
            return False
        try:
            return bool(grow(self, None, probe=True))
        except TypeError:
            # A host wired before probe existed. Assume it can, and let the
            # click find out — the fallback still catches it.
            return True

    def _tail_text(self, hidden: int) -> tuple[str, str]:
        """The tail's label and tooltip, matching what clicking it will DO.

        Two different actions need two different labels. "Show N more" grows the
        section in place; when there is no room left to take, the only way to
        see the rest is the full view, and the row says so with an arrow rather
        than promising one thing and doing another.
        """
        if self._can_grow():
            return (f"Show {hidden} more",
                    f"{hidden} more — make this section taller to show them")
        return (f"See all {hidden} more  →",
                f"{hidden} more — this section is as tall as it can get, so "
                f"this opens the full view")

    def rows_hidden(self, list_widget) -> int:
        """How many rows the budget is currently withholding from ``list_widget``."""
        return sum(
            1 for index in range(list_widget.count())
            if list_widget.item(index).isHidden()
        )

    def rows_hidden_total(self) -> int:
        """Rows withheld across every list this section budgets.

        A section can budget more than one list — Watch Alerts budgets its VOD
        rules and its stream-retry list as well as the EPG tree — so "how much
        taller do I need to be" is the sum, not whichever list was clicked.
        """
        total = 0
        primary = self.budgeted_list()
        if primary is not None:
            total += self.rows_hidden(primary)
        for extra, _on_more in self.extra_budgeted_lists():
            if extra is not None:
                total += self.rows_hidden(extra)
        return total

    def _on_more_row_clicked(self, item) -> None:
        """Grow the section so the hidden rows fit — that is what "more" means.

        This used to fire ``exploreClicked``, which is exactly what the header's
        ``Explore →`` button already does: two controls, same action, one of them
        hidden at the bottom of a list. Owner spotted it.

        The rows are not capped, only unallocated — ``apply_row_budget``'s
        docstring has always said "drag the section taller and it renders more
        rows". That was true and completely undiscoverable, so this makes the
        drag clickable rather than inventing a new mechanism. The sub-lists
        cannot scroll (nested scrollbars are the jam this whole budget exists to
        remove), which is why growing the section is the only way to reveal
        them in place.

        Falls back to the section's own handler when there is no room left to
        take — every sibling already at its floor — so the click is never dead.
        """
        if item is None or item.data(_MORE_ROLE) != _MORE_ROW:
            return
        grow = self.__dict__.get("grow_request")
        if grow is not None and grow(self, None):   # None = every hidden row
            return
        handler = self.__dict__.get("_more_handler")
        if handler is not None:
            handler()
