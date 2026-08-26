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
    assert not spinner.isVisible(), "the spinner shows before any check starts"

    section.set_series_checking(True)
    assert spinner.isVisible(), "a check started and the spinner stayed hidden"
    section.set_series_checking(False)
    assert not spinner.isVisible(), "the check finished and the spinner kept spinning"


def test_the_label_no_longer_says_checking(qapp, tmp_path):
    """The word was doing the work the motion should."""
    from metatv.core.config import Config
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection(Config(config_dir=tmp_path), db=None)
    section.set_series_checking(True)
    assert "checking" not in section._vod_toggle.text().lower(), (
        f"the header still spells it out: {section._vod_toggle.text()!r}"
    )
