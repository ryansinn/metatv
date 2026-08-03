"""Regression test for horizontal scrollbar on ChannelListView.

The bug (horizontal scrollbar appearing on first launch) is a first-layout
timing artifact that cannot be reproduced in a synthetic unit test.

Root cause: ChannelListView did not set a horizontal scrollbar policy.
On first layout, before the view is fully resized, option.rect.width() can
be from a pre-resize state, causing the delegate's sizeHint to cache an
incorrect width. Without the policy set, Qt's default ScrollBarAsNeeded
can trigger layout thrashing.

The fix applies the established convention from sibling list views
(Favorites, History, Queue, Recommended) and calls
setHorizontalScrollBarPolicy(ScrollBarAlwaysOff), since rows are painted
with fm.elidedText() to fit available width — there is nothing to scroll
to horizontally.

Why this test is minimal:
- The delegate's sizeHint returns QSize(option.rect.width(), height),
  so content width always equals viewport width in any properly-sized view.
- The scrollbar maximum is always 0 in a synthetic harness, regardless of
  the policy (content never exceeds viewport).
- The bug manifests only in first-launch timing (before layout is complete)
  and is observable only as visual clipping in the real app.

This file serves as a regression anchor; the fix is proven by matching the
convention at:
  - metatv/gui/sidebar/favorites.py:63
  - metatv/gui/sidebar/history.py:48
  - metatv/gui/sidebar/queue.py:85
  - metatv/gui/sidebar/recommended.py:69
"""

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_channel_list_view_scrollbar_policy_is_set(qapp):
    """ChannelListView sets horizontal scrollbar policy to ScrollBarAlwaysOff.

    This verifies that the policy is explicitly set, matching the convention
    in sibling list views. The policy itself (not visibility) is the
    testable behavior, since sizeHint returns option.rect.width() — content
    width always equals viewport width in a synthetic test.
    """
    from PyQt6.QtCore import Qt, QStringListModel
    from metatv.gui.channel_list_view import ChannelListView

    view = ChannelListView()
    model = QStringListModel(["Channel 1", "Channel 2"])
    view.setModel(model)

    assert (
        view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    ), "Policy must be ScrollBarAlwaysOff to match sibling list views"
