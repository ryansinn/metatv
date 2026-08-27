"""No blank band above the search controls, measured in pixels.

The series navigation bar was added to the content column unconditionally and
only its CONTENTS were hidden outside series view — an invisible Back button
and an empty label. An empty ``QWidget`` in a ``QVBoxLayout`` is still a row,
and it plus the layout spacing under it put a band of nothing above "Search:"
in every view that is not the series tree. Owner: "in the search view, there
just seems to be dead space above Search: All Hidden."

Measured rather than asserted structurally: "the bar is hidden" is a property
of a widget, and what the owner reported is a distance. The two come apart —
hiding the button while leaving the bar was exactly the state that shipped.

Run in a SUBPROCESS for the reason the nav-track test is: real geometry needs
the real MainWindow laid out and shown, which spins up ~20 managers and
destabilises the shared pytest QApplication. HOME is redirected so the child
never touches the real user config.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

_REPO_ROOT = Path(__file__).resolve().parents[1]

_CHILD = r"""
import json, os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from unittest.mock import MagicMock

for sub in (".config/metatv", ".local/share/metatv", ".cache/metatv/images"):
    (Path.home() / sub).mkdir(parents=True, exist_ok=True)

from PyQt6.QtWidgets import QApplication
import metatv.gui.main_window as mw

mw.PlayerManager = lambda *a, **k: MagicMock()
mw.MainWindow._run_query = lambda self, *a, **k: None

from metatv.core.config import Config
from metatv.gui import theme as _theme

app = QApplication([])
config, _ = Config.load()
_theme.apply_theme(config.theme_name)
win = mw.MainWindow(config)
win.resize(1400, 900)
win.show()
app.processEvents()
win.layout().activate()
app.processEvents()

content = win.content_layout.parentWidget()
nav = win._series_nav_bar
controls = win.search_controls

def measure():
    win.layout().activate()
    app.processEvents()
    top_left = controls.mapTo(content, controls.rect().topLeft())
    return {
        "controls_y": top_left.y(),
        "nav_visible": nav.isVisible(),
        "nav_h": nav.height() if nav.isVisible() else 0,
        "margin_top": win.content_layout.contentsMargins().top(),
        "spacing": win.content_layout.spacing(),
    }

out = {"list_view": measure()}

# ...and in series view, where the bar is the point.
win.show_series_nav("Silicon Valley")
out["series_view"] = measure()
out["breadcrumb"] = win.breadcrumb_label.text()
out["back_visible"] = win.back_button.isVisible()

win.show_series_nav(None)
out["back_after_leaving"] = win.back_button.isVisible()

print("GEOM " + json.dumps(out))
"""


@pytest.fixture(scope="module")
def geometry(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        env={
            "HOME": str(home),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(_REPO_ROOT),
            "QT_QPA_PLATFORM": "offscreen",
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    line = next((ln for ln in result.stdout.splitlines()
                 if ln.startswith("GEOM ")), None)
    assert line, (
        f"the window did not report geometry (rc={result.returncode}).\n"
        f"--- stdout ---\n{result.stdout[-2000:]}\n"
        f"--- stderr ---\n{result.stderr[-3000:]}"
    )
    return json.loads(line[len("GEOM "):])


def test_the_search_controls_sit_at_the_top_of_the_content_column(geometry):
    """Nothing above them but the column's own top margin.

    The number that would break is the y: with the empty bar in place it was
    the margin PLUS a whole row PLUS the spacing under it.
    """
    view = geometry["list_view"]
    assert view["controls_y"] <= view["margin_top"], (
        f"the search controls start {view['controls_y']}px down a column whose "
        f"top margin is {view['margin_top']}px — "
        f"{view['controls_y'] - view['margin_top']}px of that is a blank band"
    )


def test_the_top_padding_is_a_quarter_of_the_platform_default(geometry):
    """Shared by every view — the splitter holding all of them is a child of
    this layout, so this margin is the first thing you see in all of them.

    Asserted as a ceiling AND a floor: zero would be a different decision
    (flush against the header) and is not what was asked for.
    """
    from metatv.gui.main_window import CONTENT_TOP_PAD

    top = geometry["list_view"]["margin_top"]
    assert top == CONTENT_TOP_PAD
    assert 0 < top <= 3, (
        f"the content column's top margin is {top}px; Qt's platform default "
        "was ~9 and the ask was about a quarter of it"
    )


def test_the_nav_bar_is_not_merely_empty_outside_series_view(geometry):
    """The distinction that caused this: hidden contents, visible container."""
    assert geometry["list_view"]["nav_visible"] is False
    assert geometry["list_view"]["nav_h"] == 0


def test_series_view_still_gets_its_bar(geometry):
    """The bar exists for a reason — this must not have removed it."""
    series = geometry["series_view"]
    assert series["nav_visible"] is True
    assert series["nav_h"] > 0
    assert series["controls_y"] > geometry["list_view"]["controls_y"], (
        "the search controls did not move down for the nav bar, so the bar is "
        "overlapping them rather than taking a row"
    )


def test_the_breadcrumb_and_back_button_follow_the_bar(geometry):
    """One call sets all three — that is the whole point of the helper."""
    assert geometry["breadcrumb"].endswith("Silicon Valley")
    assert geometry["back_visible"] is True
    assert geometry["back_after_leaving"] is False
