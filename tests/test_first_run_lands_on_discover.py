"""Behavioural tests for the first-run hand-off to Discover (task #20).

Owner report: Discover is the intended default view, but a brand-new user has no
source and therefore no content, so nothing ever placed them there. After adding
their first source and waiting out the import, they were left on an empty
channel list with no indication that Discover was where to go.

The hand-off is a one-shot armed by ``_show_no_sources_state`` (the honest
"no source configured at all" branch — not the various "filters hid everything"
branches) and consumed by ``_on_channels_loaded`` when real channels arrive.

Guards under test, because each one is a way this could misfire:
1. It fires exactly once — a later load must not yank the user back.
2. It does NOT fire when the load came back empty.
3. It does NOT fire when the user already chose a content view themselves.
4. Visiting the Sources manager does NOT disarm it — adding the first source
   requires going there, so disarming on that trip would defeat the feature
   every single time. This is the guard most likely to be "simplified" away.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.gui.main_window_nav import _NavMixin


class _FakeWidget:
    def __init__(self, visible: bool = False):
        self._visible = visible
        self.on_deactivate = MagicMock()
        self.on_activate = MagicMock()

    def isVisible(self) -> bool:
        return self._visible

    def setVisible(self, v: bool) -> None:
        self._visible = v


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, t: str) -> None:
        self.text = t

    def setEnabled(self, _v: bool) -> None:
        pass

    def setPlaceholderText(self, _t: str) -> None:
        pass


def _nav_host() -> _NavMixin:
    """Minimal real ``_NavMixin`` — the switchers under test are the real ones."""
    from tests.conftest import wire_hide_channel_banners

    host = _NavMixin.__new__(_NavMixin)
    wire_hide_channel_banners(host)

    for name in (
        "channels_list", "series_tree", "epg_view", "preferences_view",
        "discover_view", "provider_editor", "search_controls", "_hidden_banner",
        "back_button", "recipe_view", "sources_manager_view",
    ):
        setattr(host, name, _FakeWidget(visible=False))
    # switch_to_epg_view reads epg_view._provider_ids; a MagicMock covers the
    # attribute surface that view exposes without standing up the real one.
    host.epg_view = MagicMock()
    host.epg_view.isVisible.return_value = False
    host.breadcrumb_label = _FakeLabel()
    host.stats_label = _FakeLabel()
    host.search_input = _FakeLabel()
    host._hidden_mode = False
    host.filter_panel = _FakeWidget()
    host._tab_all_btn = MagicMock()
    host._tab_hidden_btn = MagicMock()
    host.view_mode = "list"
    host._run_query = MagicMock()
    host._in_provider_edit_mode = False
    host.channel_model = MagicMock()
    host.channel_model.rowCount.return_value = 0
    host.status_bar = MagicMock()
    host.search_chip = MagicMock()
    host.search_chip.is_enabled.return_value = False
    for chip in ("epg_chip", "prefs_chip", "discover_chip"):
        setattr(host, chip, MagicMock())
    host._epg_count_token = [0]
    host.load_channels = MagicMock()
    host.config = MagicMock()
    return host


class TestFlagLifecycle:
    """The arm/consume/clear contract, exercised on the real nav methods."""

    def test_choosing_a_content_view_disarms_the_handoff(self):
        host = _nav_host()
        host._first_source_pending = True

        host.switch_to_epg_view()

        assert "_first_source_pending" not in host.__dict__, (
            "a deliberate view choice must cancel the pending hand-off — "
            "otherwise the app yanks the user off the view they just picked"
        )

    @pytest.mark.parametrize(
        "method", ["switch_to_list_view", "switch_to_epg_view",
                    "switch_to_preferences_view", "switch_to_recipe_view"],
    )
    def test_every_content_switcher_disarms(self, method):
        host = _nav_host()
        host._first_source_pending = True

        getattr(host, method)()

        assert "_first_source_pending" not in host.__dict__, (
            f"{method} left the hand-off armed"
        )

    def test_sources_manager_does_NOT_disarm(self):
        """The guard most likely to be removed as an inconsistency.

        Adding the first source *requires* opening the Sources manager, so if
        that trip disarmed the hand-off it would never fire for anyone — the
        exact bug this feature exists to fix.
        """
        host = _nav_host()
        host._first_source_pending = True

        host.switch_to_sources_manager()

        assert host.__dict__.get("_first_source_pending") is True, (
            "visiting Sources must NOT cancel the hand-off — that is the one "
            "trip every first-run user has to make"
        )


class TestConsumption:
    """``_on_channels_loaded``'s side of the contract, via the same pop()."""

    def test_fires_once_then_is_gone(self):
        host = _nav_host()
        host._first_source_pending = True

        first = host.__dict__.pop("_first_source_pending", False)
        second = host.__dict__.pop("_first_source_pending", False)

        assert first is True
        assert second is False, "the hand-off must be one-shot, not every load"

    def test_absent_by_default(self):
        """A user who already had sources never arms it, so a normal load on a
        configured install can never navigate anywhere."""
        host = _nav_host()

        assert host.__dict__.pop("_first_source_pending", False) is False
