"""A chip deselected programmatically must stop looking selected.

Owner, 2026-09-01, on the Sports lane tabs: *"you can see the state of the
button didn't change, it looks selected either way"*, and *"clicking On Now and
Upcoming a few times will blank the results field even with Channels untouched
and still selected"* — the highlight had stopped telling you which lane you
were in.

``ToggleChip`` carries TWO notions of "on": Qt's ``isChecked()`` and its own
``_enabled``, which is the one ``update_appearance()`` paints from.
``on_clicked`` synced them, so the chip the USER clicked looked right. Plain
``setChecked`` — which is how one chip in a group clears the others — touched
neither ``_enabled`` nor the paint, so the outgoing chip stayed lit and two
lanes looked active at once.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


_CHIPS: list = []


@pytest.fixture(autouse=True)
def _destroy_chips():
    """Every chip _chip builds is a parentless top-level; free it at teardown —
    left to garbage collection it leaked on some test orders (four allowlist
    entries, then a fifth on CI)."""
    from tests.conftest import destroy_widget

    yield
    destroy_widget(*_CHIPS)
    _CHIPS.clear()


def _chip(label, enabled):
    from metatv.gui.chips import ToggleChip

    chip = ToggleChip(label, enabled=enabled, segment="middle")
    _CHIPS.append(chip)
    return chip


class TestPaintedStateFollowsSetChecked:

    def test_deselecting_repaints(self, qapp):
        chip = _chip("On now", True)
        chip.setChecked(False)
        assert chip._enabled is False, (
            "the chip still paints as selected after being cleared — this is "
            "the two-lanes-look-active bug")
        assert chip.isChecked() is False

    def test_selecting_repaints(self, qapp):
        chip = _chip("Channels", False)
        chip.setChecked(True)
        assert chip._enabled is True
        assert chip.isChecked() is True

    def test_a_lane_switch_leaves_exactly_one_lit(self, qapp):
        """The real sequence: handler sets the new lane and clears the rest."""
        lanes = {k: _chip(k, k == "live") for k in
                 ("live", "upcoming", "channels", "finished", "placeholders")}
        for key, chip in lanes.items():          # what _on_lane_clicked does
            chip.setChecked(key == "channels")

        lit = [k for k, c in lanes.items() if c._enabled]
        assert lit == ["channels"], f"expected exactly one lit lane, got {lit}"

    def test_clicking_still_works(self, qapp):
        """Non-degeneracy: the override must not break the user-click path."""
        chip = _chip("On now", False)
        seen = []
        chip.toggled_changed.connect(seen.append)
        chip.click()
        assert chip._enabled is True and chip.isChecked() is True
        assert seen == [True], "the toggled_changed signal stopped firing"

    def test_setting_the_same_state_twice_is_harmless(self, qapp):
        chip = _chip("Finished", True)
        chip.setChecked(True)
        chip.setChecked(True)
        assert chip._enabled is True
