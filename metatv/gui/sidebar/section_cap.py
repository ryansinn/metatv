"""A section states the tallest it can usefully be, and the splitter obeys.

Split out of :mod:`base` for the reason ``row_budget`` was — the section class
is the shared template every sidebar module inherits, and each cross-cutting
behaviour it grows makes that file harder to read for everyone. This is one
behaviour with one entry point (:meth:`SectionContentCapMixin.resizeEvent`) and
one attribute, so it lifts cleanly.

**This used to fold groups too, and no longer does.** Under vertical pressure a
section closed its own groups to their headings, least important first. It
produced four separate defects in a day, every one of them the same shape — the
app closing something the user had opened:

* groups folded during startup and could never re-open, because the content cap
  stood down while anything was folded, so the section held its full height for
  a stack of headings and its neighbour could not grow into the space;
* opening one group re-folded another to make room, so clicking Stream
  Monitoring silently closed EPG;
* shrinking the section closed EPG when EPG was the thing being looked at.

And it bought nothing, which is the part that settles it: everything below the
fold already SCROLLS, so folding hid content without revealing any. The user
can collapse a group themselves, and it then stays how they left it. Owner:
"Maybe I wanted to see just the epg, now I have to reopen it."

What remains is the half that was doing real work — the cap, which keeps a
section from claiming more height than it can fill.

The rules and the two measurement traps are recorded in
docs/UI_UX_GUIDELINES.md, "Sidebar vertical space".
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer


class SectionContentCapMixin:
    """Keep a section from growing past the content it actually has.

    Mixed into ``CollapsibleSection`` beside ``RowBudgetMixin``, which has the
    same shape: a cross-cutting behaviour that reaches the section's widgets
    through ``self`` and owns none of them.
    """

    def max_useful_height(self) -> int:
        """The tallest this section can be before it is showing dead space.

        The THIRD limit, completing the pair in :mod:`base`:

        * ``min_expanded_height`` — the header. The floor a user drag may reach.
        * ``preferred_expanded_height`` — what the section asks for when space
          is being shared out.
        * this — what it can actually FILL.

        Without it a section keeps whatever the splitter gave it and pads the
        surplus around its content, because ``fit_to_rows`` pins each view to
        exactly its rows and nothing left in the layout can absorb the rest.
        Measured on Recommended: a 420px section around a 160px list. Owner:
        "recommended should never really be able to go beyond the length of the
        list ... otherwise it's just dead space."

        Never below the floor, so a section that is empty or still loading does
        not collapse to nothing and then jump when its rows arrive.

        **And never below a height the user chose.** The cap is applied as a
        real ``setMaximumHeight``, so it does not merely influence how space is
        shared out — it stops the widget growing at all. On a sparse library
        that is total: with little content the cap sits just above the header,
        every section refuses to grow, and dragging a splitter handle changes
        ``QSplitter.sizes()`` while the widgets stay put. Measured headless:
        a splitter reporting ``[298, 298]`` around two sections both pinned at
        108px, ~190px each of allocation nothing honours. Owner: "the vertical
        resize doesn't work ... the icon changes, but the resize doesn't happen".

        "No dead space" is a rule for AUTOMATIC allocation — the splitter should
        not hand a section room it cannot fill. It was never meant to overrule a
        person who deliberately dragged a section taller, and a control that
        silently refuses is worse than one that is absent.

        A previous version of this file remembered the user's height and was
        removed because "none of that machinery could be shown to do anything"
        — every test stayed green when it was mutated away. That was a gap in
        the tests, not proof it was inert; ``tests/test_user_drag_beats_cap.py``
        is the reproduction it lacked.
        """
        return max(self.min_expanded_height(),
                   self.HEADER_H + self._content_height(),
                   self.__dict__.get("_user_height") or 0)

    def note_user_height(self, height: int) -> None:
        """Record a height the user chose by dragging, so the cap honours it.

        Called from the host's ``splitterMoved`` — the one signal that means a
        PERSON moved this, as opposed to the automatic redistribution that runs
        on every content change and must stay subject to the cap.

        Ignored below the floor: a drag that collapses a section to its header
        is a collapse, not a request for a taller section, and remembering it
        would pin the section small forever.

        Args:
            height: The section's height after the drag.
        """
        if height > self.min_expanded_height():
            self._user_height = int(height)
            self.setMaximumHeight(self.max_useful_height())

    def _apply_content_cap(self) -> None:
        """Stop the splitter handing this section more than it can fill.

        One line, deliberately. The first version also remembered the user's
        height, guarded against overwriting it while the cap was what held the
        section down, and called ``_grow_in_splitter`` to restore it when the
        content came back — and **none of that machinery could be shown to do
        anything**. Mutating all three away left every test green, because
        ``QSplitter`` already returns a widget's share when its maximum lifts.
        Code that cannot be proven to matter is the same problem as a test that
        cannot fail; both look like they are working.

        So the section states its maximum and Qt does the rest. The user's size
        survives a content dip and comes back after it because the splitter
        remembers it, not because this does.

        The re-entrancy guard is not optional: measuring the content runs the
        row budget, which lands back here, and the recursion is unbounded
        without it.
        """
        if self._in_cap:
            return
        self._in_cap = True
        try:
            self.setMaximumHeight(self.max_useful_height())
        finally:
            self._in_cap = False

    def _content_height(self) -> int:
        """What the content wants right now — after ALL pending sizing.

        The row budget is what gives each inner view its height, and a group
        toggle defers it to a ``singleShot``. Measuring before it runs reads
        the height the content had BEFORE the group opened, so the cap is
        derived from a stale content size and the section is pinned to the
        height it had one interaction ago. Running it here makes the
        measurement honest.

        Safe to force: the pass is debounced and re-entrancy-guarded, so this
        runs a handful of times per drag, not per frame.
        """
        budget = getattr(self, "reapply_row_budget", None)
        if callable(budget):
            budget()
        layout = self.content_widget.layout()
        if layout is not None:
            layout.activate()
        return self.content_widget.sizeHint().height()

    #: Quiet period before a resize is acted on. A splitter drag emits a resize
    #: per frame, and re-deriving the cap re-runs every inner view's row budget
    #: — coalescing turns a drag into a handful of passes rather than one per
    #: pixel.
    CAP_DEBOUNCE_MS: int = 60

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._schedule_cap()

    def _schedule_cap(self) -> None:
        """Queue a cap pass, coalescing the ones already queued."""
        if self._in_cap:
            return
        timer = self.__dict__.get("_cap_timer")
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_content_cap)
            self._cap_timer = timer
        timer.start(self.CAP_DEBOUNCE_MS)
