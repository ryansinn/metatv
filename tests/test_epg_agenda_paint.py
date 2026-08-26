"""The EPG agenda's progress bar must actually paint.

A crash shipped here: migrating this widget to the shared painter left an
orphaned ``p.end()`` referring to a local that no longer existed. ``ast.parse``
accepts it, no test touched the widget, and it only raised when a viewer clicked
an upcoming Watch Alerts entry — which took the app down with SIGABRT.

The lesson these guard: a paint path needs a test that FORCES a paint. Importing
the module, or constructing the widget, proves nothing.
"""

import pytest

from metatv.gui.epg_agenda_widget import _ProgressBar


@pytest.mark.parametrize("pct", [0, 1, 42, 99, 100])
def test_the_bar_paints_at_every_fill(qapp, pct):
    """grab() forces a real paintEvent — construction alone would not."""
    bar = _ProgressBar(pct)
    bar.resize(80, 4)
    pixmap = bar.grab()
    assert not pixmap.isNull()
    assert pixmap.width() == 80


def test_the_bar_paints_at_a_degenerate_size(qapp):
    """A zero-width bar must not raise; layouts do produce these mid-resize."""
    bar = _ProgressBar(50)
    bar.resize(0, 4)
    bar.grab()


def test_out_of_range_fills_are_clamped_not_crashed(qapp):
    bar = _ProgressBar(500)
    assert bar._pct == 100
    bar = _ProgressBar(-20)
    assert bar._pct == 0
    bar.resize(80, 4)
    bar.grab()
