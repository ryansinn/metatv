"""The Browse tab's timeline scrubber (Phase 2).

The scrubber is a single slider that maps onto the scoped guide's time range
(``_scrubber_left``/``_scrubber_right``, sized from the fetched page's bounds)
in fixed-minute increments: moving the handle re-anchors the forward-looking
Browse fetch at that time, and scrolling the list moves the handle back to
track the topmost visible programme — each direction guarded against
re-triggering the other (``_scrubber_syncing``, ``_last_seek_value``). This
mixin held ``_EpgBrowseMixin``'s "map the scrubber to the guide's time range
and keep it in step with the scroll" concern; it was extracted verbatim so
that ``epg_browse_mixin.py`` stays at the 1000-line floor (REC-A, 2026-09-05).
"""

from __future__ import annotations

from metatv.gui.epg_widgets import _PROG_START_ROLE as _START_ROLE

from metatv.core.epg_utils import (
    now_utc as _now_utc,
    scrubber_bounds as _scrubber_bounds,
    scrubber_time_for as _scrubber_time_for,
    scrubber_value_for as _scrubber_value_for,
    scrubber_label as _scrubber_label,
)


class _EpgBrowseScrubberMixin:
    """Plain Python mixin — not a QWidget; accesses shared state via ``self``.

    Mixed into ``_EpgBrowseMixin`` (see ``epg_browse_mixin.py``), which builds
    the scrubber's widgets (``_browse_scrubber``, the position/end labels) and
    initializes its instance state in ``_build_browse_tab``.
    """

    # ── Timeline scrubber (Phase 2) ────────────────────────────────────────

    def _scrubber_anchor(self):
        """The anchor (UTC-naive) for the next fetch — the scrubber handle's time.

        Falls back to the anchor combo's data before the scrubber has been sized
        (first load) or in lightweight unit hosts without a scrubber, so the Phase-1
        reload path stays valid.
        """
        scrubber = getattr(self, "_browse_scrubber", None)
        if scrubber is None or not getattr(self, "_scrubber_ready", False):
            return self.anchor_combo.currentData()
        return _scrubber_time_for(
            self._scrubber_left, scrubber.value(), self._scrubber_increment
        )

    def _configure_scrubber(self, guide_bounds, oldest_airing_start=None) -> None:
        """Size the scrubber track from the scoped guide bounds (main thread).

        Called from the browse data-loaded dispatch on a fresh (non-append) page.
        Re-reads the snap increment from config each time so a Settings change takes
        effect on the next load. The current handle TIME is preserved across a
        re-size (the track rarely changes), defaulting to "now" on first configure.

        ``oldest_airing_start`` (start of the oldest currently-airing show, from the
        same fresh page) is the track's DEFAULT left edge — so the timeline reaches
        back to the beginning of everything on right now, but no further by default.
        """
        if getattr(self, "_browse_scrubber", None) is None:
            return
        min_start, max_start = guide_bounds or (None, None)
        now = _now_utc()

        # Resolve the handle's current TIME using the OLD bounds/increment BEFORE they
        # are overwritten — so a re-size (or a Settings snap change) never yanks the
        # handle. Defaults to NOW on first open / on view re-activation (reset flag).
        reset = getattr(self, "_scrubber_reset_to_now", False)
        keep = (
            getattr(self, "_scrubber_ready", False)
            and self._scrubber_left is not None
            and not reset
        )
        prev_time = (
            _scrubber_time_for(self._scrubber_left, self._browse_scrubber.value(),
                               self._scrubber_increment)
            if keep else now
        )
        self._scrubber_reset_to_now = False

        self._scrubber_increment = (
            getattr(self.config, "epg_scrubber_increment_minutes", 30) or 30
        )
        inc = self._scrubber_increment
        left, right = _scrubber_bounds(
            min_start, max_start,
            getattr(self.config, "epg_browse_hide_older_than_hours", 0) or 0,
            oldest_airing_start=oldest_airing_start,
            _now=now,
        )

        self._scrubber_left = left
        self._scrubber_right = right
        steps = max(1, _scrubber_value_for(left, right, inc))
        value = min(max(_scrubber_value_for(left, prev_time, inc), 0), steps)

        self._scrubber_syncing = True
        self._browse_scrubber.setRange(0, steps)
        self._browse_scrubber.setTickInterval(max(1, round(24 * 60 / inc)))  # day marks
        self._browse_scrubber.setValue(value)
        self._browse_scrubber.setEnabled(min_start is not None)
        self._scrubber_syncing = False

        self._scrubber_ready = True
        self._last_seek_value = value
        self._update_scrubber_labels()

    def _set_scrubber_time(self, dt) -> None:
        """Move the handle to a datetime PROGRAMMATICALLY (no seek), e.g. combo jump."""
        if getattr(self, "_browse_scrubber", None) is None or not self._scrubber_ready:
            return
        value = _scrubber_value_for(self._scrubber_left, dt, self._scrubber_increment)
        value = min(max(value, self._browse_scrubber.minimum()),
                    self._browse_scrubber.maximum())
        self._scrubber_syncing = True
        self._browse_scrubber.setValue(value)
        self._scrubber_syncing = False
        self._last_seek_value = value
        self._update_scrubber_labels()

    def _on_anchor_selected(self) -> None:
        """Anchor combo changed → jump the handle to that time, then seek there."""
        anchor = self.anchor_combo.currentData()
        if anchor is not None and getattr(self, "_scrubber_ready", False):
            self._set_scrubber_time(anchor)
        self._reload_browse()

    def _on_scrubber_value_changed(self, _value: int = 0) -> None:
        """Slider value changed — refresh the live label; seek unless it's a sync.

        Mid-drag (``isSliderDown``) we only update the label and defer the seek to
        ``sliderReleased``; a PROGRAMMATIC change (``_scrubber_syncing``) never seeks
        — that is the feedback-loop guard for scroll-driven / combo / re-size moves.
        Keyboard and page-click changes (not down, not syncing) seek immediately.
        """
        self._update_scrubber_labels()
        if getattr(self, "_scrubber_syncing", False):
            return
        if self._browse_scrubber.isSliderDown():
            return
        self._scrubber_seek()

    def _scrubber_seek(self) -> None:
        """Reload the list anchored at the handle's (snapped) time. De-duped."""
        if not getattr(self, "_scrubber_ready", False):
            return
        value = self._browse_scrubber.value()
        if value == getattr(self, "_last_seek_value", None):
            return
        self._last_seek_value = value
        self._reload_browse()

    def _sync_scrubber_to_scroll(self) -> None:
        """Move the handle to the topmost visible programme's time (no seek)."""
        if not getattr(self, "_scrubber_ready", False):
            return
        scrubber = getattr(self, "_browse_scrubber", None)
        if scrubber is None or self._scrubber_left is None:
            return
        item = self.browse_list.itemAt(2, 2)  # top-left of the viewport
        if item is None:
            return
        start = item.data(0, _START_ROLE)
        if start is None:
            # A Q3 day-separator row (no _START_ROLE) is topmost — skip forward to
            # the next real programme row so the handle still tracks the content.
            idx = self.browse_list.indexOfTopLevelItem(item)
            count = self.browse_list.topLevelItemCount()
            while start is None and 0 <= idx < count - 1:
                idx += 1
                item = self.browse_list.topLevelItem(idx)
                start = item.data(0, _START_ROLE)
            if start is None:
                return
        value = _scrubber_value_for(self._scrubber_left, start, self._scrubber_increment)
        value = min(max(value, scrubber.minimum()), scrubber.maximum())
        if value == scrubber.value():
            return
        self._scrubber_syncing = True
        scrubber.setValue(value)
        self._scrubber_syncing = False
        # The list now reflects this position; record it so a release here is a no-op.
        self._last_seek_value = value
        self._update_scrubber_labels()

    def _update_scrubber_labels(self) -> None:
        """Refresh the live position label + the two end labels (local day-context)."""
        if getattr(self, "_scrubber_pos_label", None) is None:
            return
        if not getattr(self, "_scrubber_ready", False) or self._scrubber_left is None:
            return
        now = _now_utc()
        current = _scrubber_time_for(
            self._scrubber_left, self._browse_scrubber.value(), self._scrubber_increment
        )
        self._scrubber_pos_label.setText(_scrubber_label(current, _now=now))
        self._scrubber_left_label.setText(_scrubber_label(self._scrubber_left, _now=now))
        self._scrubber_right_label.setText(_scrubber_label(self._scrubber_right, _now=now))
