"""A burst of filter changes must produce ONE reload, not one each.

Every filter widget connects to ``on_filter_changed`` and it reloaded
immediately — so one gesture touching several widgets (a state restore, a
Clear, a chip that implies others) fired a full reload per widget. From the
owner's startup log, five reloads inside seven seconds, each a query over
785,162 channels, all but the last discarded:

    15:01:12.895  set_channels gen=2
    15:01:18.393  set_channels gen=3
    15:01:18.832  set_channels gen=4
    15:01:19.406  set_channels gen=5
    15:01:32.223  set_channels gen=6
"""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

from metatv.gui.main_window_channels import _ChannelListMixin


class _Host(_ChannelListMixin, QWidget):
    """The smallest host that can run on_filter_changed."""

    def __init__(self) -> None:
        super().__init__()
        self.reloads: list = []
        self.current_filter_state: dict = {}
        self.selected_provider_id = None
        self._bypass_tier1_filters = True

    def load_channels(self, provider_id=None):
        self.reloads.append(provider_id)

    def _clear_id_filter(self):
        pass

    def _sync_filter_chips(self):
        pass


def _settle(qapp, ms: int = 400) -> None:
    """Run the event loop long enough for the debounce to fire."""
    done = []
    QTimer.singleShot(ms, lambda: (done.append(True), qapp.quit()))
    qapp.exec()


def test_five_changes_in_a_burst_cause_one_reload(qtbot, qapp) -> None:
    """THE assertion. Pre-fix this was five reloads of 785,162 channels."""
    host = _Host()
    qtbot.addWidget(host)

    for _ in range(5):
        host.on_filter_changed()

    assert host.reloads == [], "a reload ran before the burst had settled"
    _settle(qapp)
    assert host.reloads == [None], f"expected one reload, got {len(host.reloads)}"


def test_a_single_change_still_reloads(qtbot, qapp) -> None:
    """Coalescing must not mean 'skip'."""
    host = _Host()
    qtbot.addWidget(host)

    host.on_filter_changed()
    _settle(qapp)

    assert host.reloads == [None]


def test_the_state_is_captured_on_every_change_not_just_the_last(qtbot, qapp) -> None:
    """Only the QUERY is deferred.

    Anything reading ``current_filter_state`` between the change and the reload
    must see the truth — deferring the capture as well would hand a stale state
    to whatever asked.
    """
    host = _Host()
    qtbot.addWidget(host)
    host._bypass_tier1_filters = True

    host.on_filter_changed()

    assert host._bypass_tier1_filters is False, (
        "state capture was deferred along with the reload"
    )
    assert host.selected_provider_id is None


def test_changes_further_apart_than_the_window_each_reload(qtbot, qapp) -> None:
    """The debounce coalesces a burst; it does not merge separate gestures."""
    host = _Host()
    qtbot.addWidget(host)

    host.on_filter_changed()
    _settle(qapp)
    host.on_filter_changed()
    _settle(qapp)

    assert host.reloads == [None, None], (
        f"two deliberate gestures collapsed into {len(host.reloads)} reload(s)"
    )
