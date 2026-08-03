"""Test that ChannelListView never shows a horizontal scrollbar.

When rows are painted with fm.elidedText() to fit available width, there is
nothing to scroll to horizontally. The view should suppress the horizontal
scrollbar entirely via setHorizontalScrollBarPolicy(ScrollBarAlwaysOff).

This test proves that the policy is set and remains enforced through layout
passes (including after a resize).
"""

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_channel_list_view_suppresses_horizontal_scrollbar(qapp):
    """ChannelListView should never show a horizontal scrollbar.

    After initial layout and after a resize, the horizontal scrollbar policy
    must be ScrollBarAlwaysOff, and the scrollbar must remain invisible.
    """
    from PyQt6.QtWidgets import QListView
    from PyQt6.QtCore import Qt, QStringListModel, QSize
    from metatv.gui.channel_list_view import ChannelListView

    # Create a view with enough rows to ensure we've gone through layout passes.
    view = ChannelListView()
    model = QStringListModel(
        [f"Channel {i}: Very Long Name With Extra Details {i}" for i in range(50)]
    )
    view.setModel(model)

    # First layout: after showing the view, it should not have a horizontal scrollbar.
    view.show()
    view.resize(800, 400)
    view.repaint()

    # Force layout by processing events.
    qapp.processEvents()

    # Assert policy and visibility after first layout.
    assert (
        view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    ), "Policy must be ScrollBarAlwaysOff after initial layout"
    assert (
        not view.horizontalScrollBar().isVisible()
    ), "Horizontal scrollbar must be invisible after initial layout"

    # Resize to a smaller width — even if rows might try to overflow,
    # the scrollbar policy should suppress it.
    view.resize(400, 400)
    view.repaint()
    qapp.processEvents()

    # Assert policy and visibility after resize.
    assert (
        view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    ), "Policy must remain ScrollBarAlwaysOff after resize"
    assert (
        not view.horizontalScrollBar().isVisible()
    ), "Horizontal scrollbar must remain invisible after resize"
