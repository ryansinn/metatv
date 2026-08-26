"""A vector icon renders at the size it was ASKED for, at every screen ratio.

The bug this guards is worth stating in full, because it defeated four rounds of
"make the icon smaller" and every one of them looked correct in a render.

``vector_pixmap`` built its pixmap with ``icon.pixmap(size * dpr, size * dpr)``.
Qt 6's ``QIcon.pixmap()`` is ALREADY device-pixel-ratio aware: ask it for a
logical size and on a 2x screen it hands back a 2x-denser pixmap with
``devicePixelRatio`` set. Multiplying by dpr first applied the ratio twice, so a
request for 11px came back 44px physical at dpr 2 — 22 LOGICAL, double the
intent.

It survived because its two consumers fail differently:

* a **delegate** paints into an explicit ``QRect``, which scales the oversized
  pixmap back down, so the channel list looked right;
* a **QLabel** draws a pixmap at its own logical size, so only the sidebar
  inflated — and the owner saw sidebar icons LARGER than the channel list's,
  which is the opposite of what the constants said (11 vs 16).

And every offscreen render runs at dpr 1, where the double-apply is x1 and
therefore invisible. Only a real HiDPI display showed it.

``QT_SCALE_FACTOR`` is set in a SUBPROCESS because Qt reads it once, when the
QApplication is created — a fixture cannot change the ratio of the shared
QApplication the rest of the suite is using.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

_REPO_ROOT = Path(__file__).resolve().parents[1]

_CHILD = r"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
for sub in (".config/metatv", ".local/share/metatv", ".cache/metatv/images"):
    (Path.home() / sub).mkdir(parents=True, exist_ok=True)

from PyQt6.QtWidgets import QApplication
app = QApplication([])

from metatv.gui import theme as _theme
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons

_theme.apply_theme("Midnight")
dpr = QApplication.primaryScreen().devicePixelRatio()
failures = []
for asked in (9, 11, 13, 16, 24):
    pixmap = _icon_utils.vector_pixmap(
        _icons.vector_key("movie"), _theme.COLOR_TEXT, asked
    )
    assert not pixmap.isNull(), f"{asked}px resolved to nothing"
    logical = pixmap.width() / pixmap.devicePixelRatio()
    if abs(logical - asked) > 1:
        failures.append(f"asked {asked} -> drew {logical:.0f} logical")
    # And the density is really there: a 2x screen must get 2x the pixels, or
    # the glyph is crisp-looking in the test and blurry on the screen.
    if abs(pixmap.width() - asked * dpr) > dpr:
        failures.append(
            f"asked {asked} at dpr {dpr} -> {pixmap.width()}px physical, "
            f"expected ~{asked * dpr}"
        )
print("DPR", dpr, "FAILURES", failures)
assert not failures, failures
print("OK")
"""


@pytest.mark.parametrize("scale", ["1", "2", "3"])
def test_a_vector_icon_draws_at_the_size_it_was_asked_for(tmp_path, scale):
    env = {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(_REPO_ROOT),
        "QT_QPA_PLATFORM": "offscreen",
        "QT_SCALE_FACTOR": scale,
    }
    result = subprocess.run(
        [sys.executable, "-c", _CHILD], env=env, capture_output=True, text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"at QT_SCALE_FACTOR={scale}:\n{result.stdout}\n{result.stderr}"
    )
    assert "OK" in result.stdout, result.stdout


def test_the_sidebar_icon_is_smaller_than_the_channel_list_icon():
    """The relationship the owner could see was wrong, stated as an invariant.

    A sidebar row is ~20px and a channel-list row 40px+, so the sidebar glyph
    must be the smaller of the two. It was rendering LARGER, which is what
    surfaced the double-scaling.
    """
    from metatv.gui import channel_row_layout as _layout
    from metatv.gui.chip_row import ICON_PX

    assert ICON_PX < _layout.KIND_ICON, (
        f"the sidebar icon ({ICON_PX}px) is not smaller than the channel "
        f"list's ({_layout.KIND_ICON}px), in a row half the height"
    )
