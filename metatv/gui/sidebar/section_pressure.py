"""When a section runs out of room, it folds rather than clips.

Split out of :mod:`base` for the reason ``row_budget`` was — the section class
is the shared template every sidebar module inherits, and each cross-cutting
behaviour it grows makes that file harder to read for everyone. This is one
behaviour with one entry point (:meth:`SectionPressureMixin.resizeEvent`) and
no state beyond two attributes, so it lifts cleanly.

The rules and the two measurement traps are recorded in
docs/UI_UX_GUIDELINES.md, "Sidebar vertical space".
"""

from __future__ import annotations

from typing import Callable, NamedTuple

from PyQt6.QtCore import QTimer


class PressureGroup(NamedTuple):
    """One foldable group inside a section, as the pressure pass sees it.

    A plain record rather than a widget handle: sections keep their group state
    in their own way (Watch Alerts holds four ``_*_collapsed`` booleans and four
    toggles), and the pass only needs to ask "is it closed?" and say "close it".

    Attributes:
        key: Stable identity, used to remember what was folded automatically.
        collapsed: Whether it is closed right now, for any reason.
        set_collapsed: Closes or opens it — the section's own toggle, so the
            heading caret and the count follow along for free.
    """

    key: str
    collapsed: bool
    set_collapsed: "Callable[[bool], None]"


class SectionPressureMixin:
    """Fold a section's groups to their headings when height runs short.

    Mixed into ``CollapsibleSection`` beside ``RowBudgetMixin``, which has the
    same shape: a cross-cutting behaviour that reaches the section's widgets
    through ``self`` and owns none of them.

    A section with no groups returns ``[]`` from :meth:`pressure_groups` and
    this does nothing — the right answer, since it simply scrolls.
    """

    #: Headroom a folded group must see before it re-opens, on top of the space
    #: it needs. Without it a group sits exactly at the threshold and folds and
    #: unfolds on every pixel of drag, because folding CHANGES the height being
    #: measured — the classic feedback flicker.
    PRESSURE_HYSTERESIS: int = 28
    def pressure_groups(self) -> list["PressureGroup"]:
        """The groups this section may fold when it runs out of room.

        Ordered LEAST important first: the first entry is the first to go. A
        flat section has none and returns the default empty list, which is the
        right answer — with nothing to fold it simply scrolls, which it already
        did.

        Returns:
            Ordered ``PressureGroup`` records. Rebuilt on each pass rather than
            cached, because a group's importance changes with its contents.
        """
        return []
    def _apply_pressure(self) -> None:
        """Fold or unfold groups so the content fits the height available.

        Folding is a LOAN, never a decision: every group folded here is recorded
        in ``_auto_folded`` and is the only kind this method will re-open. A
        group the user collapsed is skipped entirely — it is already closed, and
        nothing here may open it.

        Runs on resize, so it must not recurse: folding a group changes the
        content height, which resizes the scroll area, which would re-enter.
        """
        if self._in_pressure or self.is_collapsed:
            return
        groups = self.pressure_groups()
        if not groups:
            return

        self._in_pressure = True
        try:
            available = max(0, self.height() - self.HEADER_H)

            # Fold, least important first, until it fits — but never the LAST
            # one. Folding every group leaves a stack of headings and a lot of
            # dead space under them; leaving the most important one open lets it
            # take the leftover room and scroll, which shows every heading AND
            # some rows. Strictly more, and nothing is hidden that was not
            # already going to be.
            for group in groups[:-1]:
                if self._content_height() <= available:
                    break
                if group.collapsed:
                    continue          # already closed, by us or by the user
                group.set_collapsed(True)
                self._auto_folded.add(group.key)

            # Unfold, most important first, while the space is comfortably there.
            for group in reversed(groups):
                if group.key not in self._auto_folded:
                    continue          # the user closed this one; not ours to open
                group.set_collapsed(False)
                if self._content_height() + self.PRESSURE_HYSTERESIS > available:
                    group.set_collapsed(True)   # it did not fit after all
                    break
                self._auto_folded.discard(group.key)
        finally:
            self._in_pressure = False
    def _content_height(self) -> int:
        """What the content wants right now — after ALL pending sizing.

        The row budget is what gives each inner view its height, and a group
        toggle defers it to a ``singleShot``. Measuring before it runs reads
        the height the content had BEFORE the group opened, so the fit check
        cannot see the thing it is checking: two groups re-opened at once on a
        zero-pixel fit, which is precisely the flicker the hysteresis exists to
        prevent. Running it here makes the measurement honest.

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
    #: Quiet period before a resize is acted on. Folding a group can mean a
    #: full re-render of its list, and a splitter drag emits a resize per frame
    #: — running the pass synchronously would rebuild the Movies and Series
    #: list sixty times a second. Coalescing also means a drag THROUGH a
    #: threshold costs one fold rather than one per pixel.
    PRESSURE_DEBOUNCE_MS: int = 60

    def resizeEvent(self, event):  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._schedule_pressure()

    def _schedule_pressure(self) -> None:
        """Queue a pressure pass, coalescing the ones already queued."""
        if self._in_pressure:
            return
        timer = self.__dict__.get("_pressure_timer")
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_pressure)
            self._pressure_timer = timer
        timer.start(self.PRESSURE_DEBOUNCE_MS)
