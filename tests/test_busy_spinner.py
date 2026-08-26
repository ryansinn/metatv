"""The busy indicator has to actually spin.

Owner, on Watch Alerts' "⟳ checking…": *"isn't there some animated icon rather
than the word? something spinning?"*

Two ways this can be shipped broken, and a test that only checks the widget
exists catches neither:

* a QIcon with an animation assigned to a **QLabel** never moves, because
  nothing repaints it — the animation drives a widget, not the icon;
* qtawesome's default ``Spin`` step is **one degree per tick**, which at 13px
  renders an identical image frame after frame. A spinner nobody can see spin
  is worse than the word it replaced, because it also says nothing.

So this compares real rendered FRAMES over time.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEventLoop, QTimer

pytest.importorskip("PyQt6")
pytest.importorskip("qtawesome")


def _frame(widget) -> tuple:
    img = widget.grab().toImage()
    return tuple(
        img.pixelColor(x, y).rgb()
        for y in range(img.height()) for x in range(img.width())
    )


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_the_spinner_renders_different_frames_over_time(qapp, qtbot):
    """The whole point, measured on pixels rather than on the widget's type."""
    from metatv.gui import icon_utils as _icon_utils
    from metatv.gui import theme as _theme

    spinner = _icon_utils.busy_spinner(color=_theme.COLOR_OK, size=13)
    assert spinner is not None, "no spinner built — qtawesome present but unusable"
    qtbot.addWidget(spinner)
    spinner.show()

    _wait(60)
    frames = {_frame(spinner)}
    for _ in range(3):
        _wait(150)
        frames.add(_frame(spinner))

    assert len(frames) > 1, (
        "the spinner rendered an identical frame every time — it is not "
        "animating. qtawesome's default step is 1 degree per tick, which is "
        "invisible at this size; see SPIN_STEP_DEG."
    )


def test_the_step_is_large_enough_to_read_as_motion():
    """Guards the specific default that makes it look static."""
    from metatv.gui import icon_utils as _icon_utils

    assert _icon_utils.SPIN_STEP_DEG >= 6, (
        f"{_icon_utils.SPIN_STEP_DEG}°/tick is too small to read as motion at "
        f"sidebar sizes — qtawesome's own default of 1° is why this constant exists"
    )
    assert _icon_utils.SPIN_INTERVAL_MS <= 100, "too slow to look like spinning"


def test_a_missing_icon_pack_costs_the_spinner_not_the_section(monkeypatch):
    """Callers fall back to their static hint; nothing raises."""
    import builtins
    from metatv.gui import icon_utils as _icon_utils

    real_import = builtins.__import__

    def _no_qta(name, *a, **k):
        if name == "qtawesome":
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_qta)
    assert _icon_utils.busy_spinner() is None


def test_watch_alerts_shows_and_hides_it_with_the_check(qapp, tmp_path):
    """It is wired to the real busy signal, not merely constructed."""
    from metatv.core.config import Config
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    spinner = section.__dict__.get("_series_spinner")
    assert spinner is not None, "Movies & Series has no spinner"

    # ``isHidden``, not ``isVisible``: the section itself is not shown here, and
    # an unshown ancestor makes ``isVisible()`` False however correct the
    # production code is. ``isHidden()`` is the widget's OWN flag, which is
    # exactly what ``set_series_checking`` toggles: delete the ``setVisible``
    # call and this goes red.
    assert spinner.isHidden(), "the spinner shows before any check starts"

    section.set_series_checking(True)
    assert not spinner.isHidden(), "a check started and the spinner stayed hidden"
    section.set_series_checking(False)
    assert spinner.isHidden(), "the check finished and the spinner kept spinning"


def test_the_spinner_lives_on_the_section_header(qapp, tmp_path):
    """It reports on a check that belongs to the whole section.

    Replaces two tests that asserted things about the "Movies & Series" header
    button's TEXT — that it did not spell out "checking", that the count was not
    appended behind a "·". That header has been dissolved: it labelled a wrapper
    that read as a peer of the two groups it contained. With no button there is
    no button text to police, and the spinner sits with the section's own
    controls instead of on a sub-group heading.
    """
    from metatv.core.config import Config
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    spinner = section.__dict__.get("_series_spinner")
    assert spinner is not None

    header = section.__dict__.get("_header")
    assert header is not None, "the section header was never built"
    assert spinner.parent() is not None
    # Same header that carries Manage and +, not a sub-group's.
    assert spinner.parent() is section._manage_btn.parent(), (
        "the busy indicator is not with the section's own controls"
    )


def test_the_new_total_combines_rules_and_series(qapp, tmp_path):
    """The count the section badge shows, after a VOD refresh.

    Replaces a geometry test that measured the "N new" label's x against the
    "Movies & Series" header it sat in. Both are gone: the label duplicated the
    count the SECTION header badge already shows, and the header it lived in
    was a wrapper reading as a peer of its own children. What survives is the
    arithmetic — firing keyword rules plus series with unseen episodes.
    """
    from metatv.core.config import Config
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    section._firing_count = 2
    section._series_new_count = 3
    section._update_vod_toggle_label(5)
    assert section._new_total == 5
