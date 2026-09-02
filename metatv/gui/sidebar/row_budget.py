"""Fitting a section's views to the rows they actually hold.

R13, mechanism 1 — **no nested scrollbars.** The sidebar had a scrollbar inside
a scrollbar: Watch Alerts subdivided 173px four ways, each sub-group scrolling
in about 35px, which is a window too small to read through. *"This alone
recovers most of the jam."*

So a view is sized to its rows and the SECTION scrolls. One scrolling surface,
one behaviour, no setting.

Two shapes, because sections have two:

``apply_row_budget``      a flat ``QListWidget``.
``apply_tree_row_budget`` a ``QTreeWidget`` of sub-groups. Top-level rows the
                          USER folded stay folded; nothing here re-opens a group
                          somebody closed.

**What was removed, 2026-09-02, and why it is not coming back.** There used to
be a second mode behind ``sidebar_show_more_row``: hide the rows that did not
fit, end the list with a "Show N more" row, and let clicking it grow the section
by taking pixels from its neighbours. It was off by default — the owner had
already said *"should really load the whole list with scroll bars at the start,
no?"* — and it was kept on the argument, written twice in this file, that
*"wheeling the list reveals more (see eventFilter)"*.

**There was no eventFilter, here or anywhere in the sidebar.** Budgeted rows
were ``setHidden(True)``, so no amount of scrolling could reach them, and the
only way to see one was the tail row itself. The mode's stated audience —
people who cannot use a scroll wheel — was precisely the group it failed. It
cost ~333 of this file's 552 lines plus 84 lines of splitter arithmetic in
``main_window``, carried a measured empty-list defect of its own, and made every
sidebar change something to reason about twice. Owner: *"why not always show
everything"*.

Its own module because ``base.py`` carries a 1000-line cap and this is a
separable concern: it takes a view and gives it the height its rows need.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer

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


def _has_visible_rows(view) -> bool:
    """Whether *view* is currently showing the user anything at all.

    Visibility, not ``rowCount()``: :mod:`alerts_epg` folds a sub-group by
    HIDING its rows rather than removing them, so a tree can hold rows and
    still show none. Top-level items only, matching
    :meth:`RowBudgetMixin.apply_tree_row_budget`, which already skips hidden
    groups for the same reason.

    An empty-state placeholder ("No favorites yet") counts as a visible row —
    it is a line the user reads, so the view keeps the height to draw it. What
    this excludes is a view with literally nothing in it.

    Args:
        view: A ``QListWidget`` or ``QTreeWidget``.

    Returns:
        True when at least one row is present and not hidden.
    """
    top_level_count = getattr(view, "topLevelItemCount", None)
    if callable(top_level_count):
        return any(not view.topLevelItem(i).isHidden()
                   for i in range(top_level_count()))
    count = getattr(view, "count", None)
    if callable(count):
        return any(not view.item(i).isHidden() for i in range(count()))
    model = view.model()
    return model is not None and model.rowCount() > 0


class RowBudgetMixin:
    """Fits a section's rows to its current height.

    Mixed into ``CollapsibleSection``; expects ``ROW_H`` and ``exploreClicked``
    from it.
    """

    # ── Row budget: no nested scrollbars ────────────────────────────────────

    def apply_row_budget(self, list_widget) -> None:
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

        **This used to have a second mode** — hide the rows that did not fit and
        end the list with a "Show N more" row that grew the section by taking
        pixels from its neighbours. It was off by default, and the argument for
        keeping it was that anyone with a scroll wheel could reveal the rows
        anyway: *"Wheeling the list reveals more (see eventFilter)"*. **There was
        no eventFilter.** Budgeted rows were ``setHidden(True)``, so scrolling
        could never reach them, and the only way to see one was the tail row
        itself. The mode's stated audience — people who cannot use a wheel — was
        the one group it did not help.

        It cost about 333 of this file's 552 lines plus 84 of splitter
        arithmetic in ``main_window``, and every sidebar change had to be
        reasoned about twice. Owner, 2026-09-02: *"why not always show
        everything"*. So: one behaviour, and the scrollbar does what a scrollbar
        does.

        Args:
            list_widget: The section's ``QListWidget``, already populated.
        """
        for index in range(list_widget.count()):
            list_widget.item(index).setHidden(False)
        list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fit_to_rows(list_widget)

    def apply_tree_row_budget(self, tree) -> None:
        """Fit a ``QTreeWidget`` of sub-groups to its contents.

        Same single behaviour as :meth:`apply_row_budget`: every child visible,
        the tree sized to its rows, and the SECTION does the scrolling — never
        the tree, which would be the nested scrollbar R13 forbids.

        Hidden top-level rows are skipped rather than un-hidden: a folded
        sub-group (Watch Alerts' "Upcoming") is folded because the USER folded
        it, and re-opening it here would be the app undoing a person's choice —
        the defect ``section_cap``'s docstring records four times over.
        """
        groups = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                  if not tree.topLevelItem(i).isHidden()]
        for group in groups:
            for index in range(group.childCount()):
                group.child(index).setHidden(False)
        # The SECTION scrolls, never the tree — one scrolling surface.
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Unconditional, including when there are no groups at all: an unsized
        # empty tree reports a DEFAULT viewport rather than zero, which is the
        # same fabricated measurement that made an empty Recordings section
        # 108px tall.
        self.fit_to_rows(tree)

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
        """Further lists this section fits, beyond :meth:`budgeted_list`.

        For a section built from SEVERAL lists — Watch Alerts has Movies &
        Series and Stream Monitoring alongside its EPG tree. They have to be
        re-fitted from the same seam as everything else, because a size applied
        once at populate is computed against a viewport that has not been laid
        out yet.

        Returns:
            An iterable of ``QListWidget``. Empty by default — most sections
            have one list and use :meth:`budgeted_list`.
        """
        return ()

    def reapply_row_budget(self) -> None:
        """Re-fit every view to the section's CURRENT height.

        Called on resize and after every populate. Without it a view sized once
        at load would keep that size when the section is dragged taller, and the
        rows would sit in a box the wrong shape.
        """
        lst = self.budgeted_list()
        if lst is not None:
            self.apply_row_budget(lst)
        for extra in self.extra_budgeted_lists():
            if extra is not None and extra.isVisible():
                self.apply_row_budget(extra)
        tree = self.budgeted_tree()
        if tree is not None:
            self.apply_tree_row_budget(tree)
        self._after_budget()
        if lst is not None or tree is not None:
            self.refresh_header_status()

    def _after_budget(self) -> None:
        """Re-derive the section's MAXIMUM after the rows have been re-fitted.

        Rows arriving is exactly when the cap goes stale: a section sized for
        an empty list must be allowed to grow, and one whose list emptied must
        stop claiming the height. Content that outgrows the section is what the
        scroll area is for.
        """
        cap = getattr(self, "_apply_content_cap", None)
        if callable(cap):
            cap()

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        """Re-fit on every resize — the splitter drag is the whole point.

        Deferred by a zero-timer because the viewport has not taken its new
        height yet while this fires; measuring here would budget against the
        size the section is leaving, not the one it is arriving at.
        """
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reapply_row_budget)


    @staticmethod
    def fit_to_rows(view) -> None:
        """Set a view's height to exactly what its contents need.

        Qt's own ``viewportSizeHint()`` — the ideal viewport for the current
        contents. Two hand-rolled versions got this wrong differently:
        ``visualItemRect`` is (0,0,0,0) before layout, and
        ``sizeHint().height()`` returns **-1** when unset, which poisons a sum.
        Qt already knows the number.

        **Except when there is nothing to show.** ``viewportSizeHint()`` on an
        empty view does not return 0 — it falls back to a default viewport
        (72px measured on an empty ``QListWidget`` here), which is a guess at
        how big a list WOULD be, not a measurement of this one. The section cap
        then honours that guess faithfully: an empty Recordings section
        measured 108px against a 28px header, ~80px of blank panel, and the
        same for Downloads. Owner: *"headers are oversized by default, they
        shouldn't grow beyond the standard size"*. Zero rows is a real
        measurement, so it is taken rather than asked for.

        A view whose rows are all HIDDEN is the same case — ``alerts_epg``
        hides rows rather than removing them — so visibility is what is
        counted, not ``rowCount()``.
        """
        view.updateGeometries()
        if not _has_visible_rows(view):
            view.setFixedHeight(0)
            return
        hint = view.viewportSizeHint().height()
        view.setFixedHeight(max(0, hint) + 2 * view.frameWidth())

