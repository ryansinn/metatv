"""The status line never describes the view you just left.

Sixty of the sixty-five ``status_bar.showMessage`` calls pass no timeout, so a
message stands until something else overwrites it. A view that has nothing to
say never overwrites it — so leaving EPG for Discover left "EPG: 2,109 on now"
sitting under a page it had nothing to do with. Owner: "it doesn't seem to do
anything on Recommended or Discover and keeps the previous status so EPG ->
Discover still shows EPG: 2,109 on now."

A stale status line is worse than an empty one: an empty one says nothing, and
a stale one says something false with the app's own authority.

Cleared at ``_hide_all_content_views`` — the one seam every switch already
passes through — rather than per view, which is the enumeration that leaves the
next view out.
"""
from __future__ import annotations

import inspect

from metatv.gui.main_window_nav import _NavMixin


def test_the_switch_seam_clears_the_line():
    """Structural, and deliberately so.

    Driving a real switch needs the whole window and every manager behind it;
    what must hold is that the CLEAR happens at the shared seam rather than in
    one view's handler, and that is a property of where the call sits.
    """
    source = inspect.getsource(_NavMixin._hide_all_content_views)
    assert "clearMessage()" in source, (
        "the view-switch seam no longer clears the status line, so a message "
        "from the previous view outlives it"
    )


def test_no_view_clears_it_on_its_own():
    """One clear, at the seam. A second one in a view handler means the seam
    was not trusted, and the next view added will be the one that forgets."""
    import metatv.gui.main_window_nav as nav

    hits = [
        line.strip()
        for line in inspect.getsource(nav).splitlines()
        if "clearMessage()" in line
    ]
    assert len(hits) == 1, f"status line cleared in {len(hits)} places: {hits}"


def test_it_clears_before_the_new_view_can_speak():
    """Order matters: clearing AFTER the view sets its own status would wipe
    the message the view just wrote, which is the opposite defect."""
    source = inspect.getsource(_NavMixin._hide_all_content_views)
    body = source.split('"""')[-1]
    first = body.strip().splitlines()[0].strip()
    assert "clearMessage()" in first, (
        f"the clear is not the first thing the seam does (first line: {first!r})"
    )
