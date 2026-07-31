"""EPG source status + Refresh on the programmes-count stats line (0183).

The EPG view used to carry the source-freshness status text and a Refresh button
inside its own header (a single tab row, then a stacked second row — 0181, then a
separate global bottom bar — the first cut of 0183).  All of those still left the
status/Refresh on a *different* line from the main-window "###,### EPG programmes"
count (``MainWindow.stats_label``), which reads badly.

Final design:

  * The EPG view header is a SINGLE tab row — ``[tab_bar] [stretch]`` — and the
    view no longer owns a ``status_label`` or ``refresh_btn`` at all.  It emits its
    computed status text via the ``epg_status_changed`` signal instead.
  * ``MainWindow`` owns ``epg_status_label`` + ``epg_refresh_btn``, added to the
    stats line right after ``stats_label`` and its stretch, so they sit
    right-aligned on the SAME line as the programmes count.  Both are visible only
    while the EPG view is active and hidden otherwise.  Refresh is wired to the
    EPG view's force-refresh seam.
  * The Browse "###,### programmes" count (``browse_stats``) lives back on the
    Browse tab page — it is Browse-only and never touched the global stats line.

The ``EpgView`` tests build the real widget offscreen and assert the structure +
the status signal.  The ``MainWindow`` placement/visibility/wiring is asserted in
a subprocess (booting the real window in-process alongside the EpgView tests both
crashes at teardown and destabilises later tests — same reason the launch smoke
test is a subprocess).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock

import pytest

from PyQt6.QtWidgets import QApplication, QHBoxLayout

from metatv.core.config import Config
from metatv.gui.epg_view import EpgView

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def epg_view(qapp, tmp_path):
    """A real EpgView built offscreen with a real Config + mocked db/epg_manager.

    ``_setup_ui`` (and every ``_build_*_tab`` it calls) reads config attributes
    and connects signals to real methods, but never touches the DB — so a
    MagicMock db/epg_manager is sufficient to exercise the header + Browse-tab
    build path.  ``config_dir=tmp_path`` keeps any config write off the real
    user config.
    """
    config = Config(config_dir=tmp_path)
    view = EpgView(config, db=MagicMock(), epg_manager=MagicMock())
    try:
        yield view
    finally:
        view._executor.shutdown(wait=False)
        view.close()
        view.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header_of(view: EpgView):
    """The header QWidget — parent of the tab bar."""
    return view.tab_bar.parentWidget()


def _widgets_in(layout):
    return [layout.itemAt(i).widget() for i in range(layout.count())
            if layout.itemAt(i).widget() is not None]


# ---------------------------------------------------------------------------
# EpgView structure: header is a single tab row; no status/refresh widgets
# ---------------------------------------------------------------------------

def test_epg_header_is_a_single_tab_row(epg_view):
    """The header is one horizontal row carrying only the tab bar."""
    header = _header_of(epg_view)
    assert isinstance(header.layout(), QHBoxLayout)
    assert epg_view.tab_bar in _widgets_in(header.layout())


def test_epg_view_no_longer_owns_status_or_refresh(epg_view):
    """status/Refresh moved to MainWindow's stats line — the view must not keep them.

    A lingering ``status_label``/``refresh_btn`` would mean two status widgets and
    a split source of truth; the view now emits ``epg_status_changed`` instead.
    """
    assert not hasattr(epg_view, "status_label")
    assert not hasattr(epg_view, "refresh_btn")
    assert hasattr(epg_view, "epg_status_changed")  # the replacement signal


def test_all_tabs_preserved(epg_view):
    assert epg_view.tab_bar.count() == 7


# ---------------------------------------------------------------------------
# browse_stats belongs to the Browse tab page (Browse-only), not the stats line
# ---------------------------------------------------------------------------

def test_browse_count_lives_on_the_browse_tab_page(epg_view):
    """browse_stats is a Browse-tab widget, parented inside the Browse stack page.

    It must NOT be a header widget and must NOT be hoisted onto the global stats
    line — it is the per-tab Browse count, distinct from the whole-guide EPG count.
    """
    browse_page = epg_view.stack.widget(4)  # build order: …, On Now(3), Browse(4)
    assert epg_view.browse_stats.parentWidget() is browse_page
    assert epg_view.stack.indexOf(browse_page) == 4
    assert epg_view.browse_stats.parentWidget() is not _header_of(epg_view)


# ---------------------------------------------------------------------------
# EpgView emits its status via epg_status_changed (the signal MainWindow mirrors)
# ---------------------------------------------------------------------------

def test_update_status_label_emits_no_sources_when_empty(epg_view):
    """With no EPG providers, the view emits a plain "No EPG sources" status."""
    captured: list[tuple[str, str]] = []
    epg_view.epg_status_changed.connect(lambda text, tip: captured.append((text, tip)))

    epg_view._provider_ids = []
    epg_view._update_status_label()

    assert captured[-1] == ("No EPG sources", "")


def test_update_status_label_emits_single_source_text(epg_view):
    """One provider → the emitted text is "<name> · <freshness>" (no view widget).

    _epg_source_info is monkeypatched so the status path never touches the DB; the
    point is that the computed status flows out through the signal, which is the
    only channel MainWindow's stats-line label reads from.
    """
    captured: list[tuple[str, str]] = []
    epg_view.epg_status_changed.connect(lambda text, tip: captured.append((text, tip)))

    epg_view._provider_ids = ["p1"]
    epg_view._epg_source_info = lambda: {"p1": ("TREX Shared", None)}
    epg_view.epg_manager.get_status_text.return_value = "Updated 2h ago"

    epg_view._update_status_label()

    assert captured, "status must be emitted via epg_status_changed"
    assert captured[-1][0] == "TREX Shared · Updated 2h ago"


# ---------------------------------------------------------------------------
# MainWindow: status + Refresh on the stats line, EPG-only visibility, wiring.
# Booted in a subprocess (see module docstring).
# ---------------------------------------------------------------------------

_CHILD = r"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from unittest.mock import MagicMock, call

for sub in (".config/metatv", ".local/share/metatv", ".cache/metatv/images"):
    (Path.home() / sub).mkdir(parents=True, exist_ok=True)

from PyQt6.QtWidgets import QApplication
import metatv.gui.main_window as mw

mw.PlayerManager = lambda *a, **k: MagicMock()          # no real mpv process
mw.MainWindow._run_query = lambda self, *a, **k: None    # no background pool / count query

from metatv.core.config import Config

app = QApplication([])
config, _ = Config.load()
win = mw.MainWindow(config)

# 1) The two controls sit on the SAME line as the programmes count (stats_label):
#    all three share the stats-container parent, count first then status then Refresh.
line_parent = win.stats_label.parentWidget()
assert win.epg_status_label.parentWidget() is line_parent, "status not on stats line"
assert win.epg_refresh_btn.parentWidget() is line_parent, "Refresh not on stats line"
lay = line_parent.layout()
order = [lay.itemAt(i).widget() for i in range(lay.count())
         if lay.itemAt(i).widget() is not None]
assert order.index(win.stats_label) < order.index(win.epg_status_label) < order.index(win.epg_refresh_btn), \
    "expected [stats_label] … [epg_status_label] [epg_refresh_btn] left-to-right"

# 2) Hidden until the EPG view is active.  isVisibleTo(win) reflects the explicit
#    setVisible() intent without needing the top-level window shown.
assert not win.epg_status_label.isVisibleTo(win)
assert not win.epg_refresh_btn.isVisibleTo(win)

# Keep the EPG activation network-free and deterministic.
win.epg_view.epg_manager.refresh_all_if_needed = lambda *a, **k: None
win.epg_view.epg_manager.relink_all = lambda *a, **k: None
win.epg_view._reload_all = lambda *a, **k: None

# 3) Entering the EPG view shows both, and the source status flows onto the line
#    via epg_status_changed (empty DB → "No EPG sources").
win.switch_to_epg_view()
assert win.epg_status_label.isVisibleTo(win), "status hidden while EPG active"
assert win.epg_refresh_btn.isVisibleTo(win), "Refresh hidden while EPG active"
assert win.epg_status_label.text() == "No EPG sources", win.epg_status_label.text()

# 4) The stats-line Refresh drives the EPG view's per-provider force-refresh seam.
win.epg_view.epg_manager.force_refresh_provider = MagicMock()
win.epg_view._provider_ids = ["pA", "pB"]
win.epg_refresh_btn.click()
assert win.epg_view.epg_manager.force_refresh_provider.call_args_list == [call("pA"), call("pB")], \
    win.epg_view.epg_manager.force_refresh_provider.call_args_list

# 5) Leaving the EPG view hides both again.
win._hide_all_content_views()
assert not win.epg_status_label.isVisibleTo(win), "status still shown after leaving EPG"
assert not win.epg_refresh_btn.isVisibleTo(win), "Refresh still shown after leaving EPG"

print("EPG_STATS_LINE_OK")
"""


def test_mainwindow_epg_status_and_refresh_on_stats_line(tmp_path):
    """Real MainWindow: status + Refresh live on the count line, EPG-only, wired."""
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(_REPO_ROOT),
        "QT_QPA_PLATFORM": "offscreen",
    }
    result = subprocess.run(
        [sys.executable, "-c", _CHILD],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0 and "EPG_STATS_LINE_OK" in result.stdout, (
        f"EPG stats-line wiring failed (rc={result.returncode}).\n"
        f"--- stdout ---\n{result.stdout[-2000:]}\n"
        f"--- stderr ---\n{result.stderr[-3000:]}"
    )
