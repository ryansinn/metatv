"""One gesture must render the details pane once, not twice.

Owner's log (2026-09-02 15:44:02): one selection produced TWO complete
render+fetch cycles for the same channel 185ms apart — two
``update_details_pane_for_channel`` calls, two ``fetch_metadata`` threads,
two pane renders. PR #680 fixed the LIST's own click/selection double
(``_show_details_for_clicked_row``, covered by
``test_details_pane_rendered_once.py``), but ``show_channel_details_by_id``
— the entry every sidebar section, ``version_selected``, and programmatic
path uses — has no dedupe of its own, so a gesture that reaches the pane
through two surfaces at once renders it twice.

The fix lives at ``update_details_pane_for_channel``, the ONE chokepoint
every path funnels through: suppress a re-render of the SAME channel that
starts within ``_RERENDER_DEBOUNCE_S`` (300ms) of the last one. Gated on
TIME, not on the channel id alone — #680's record is that id-gating breaks
click-again-to-refresh, the deliberate escape hatch a stale pane relies on.
A human re-click is seconds apart; the measured accidental double was
185ms, so 300ms catches the double without touching the escape hatch
(``test_rerender_after_window_is_honoured`` below pins that).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.models import MediaType


CHANNEL_A = "prov1_chA"
CHANNEL_B = "prov1_chB"


class _FakeFuture:
    def add_done_callback(self, cb):
        pass


class _RecordingExecutor:
    """Stands in for MainWindow.executor — records submissions without
    actually running fetch_metadata (no event loop / metadata_manager needed
    to prove the debounce, which fires before any of that is reached)."""

    def __init__(self):
        self.submit_calls = 0

    def submit(self, fn, *args, **kwargs):
        self.submit_calls += 1
        return _FakeFuture()


class _DetailsPaneDouble:
    def __init__(self):
        self.shown: list[str] = []

    def set_provider_urls(self, urls):
        pass

    def show_channel(self, channel, metadata=None):
        self.shown.append(channel.id)


@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'details_pane_debounce.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_host(db_obj):
    """A plain host with the real update_details_pane_for_channel bound —
    per CLAUDE.md's test-double rule, wired from the mixin itself rather than
    hand-copied, and using a real Database (session_scope work) on tmp_path.
    """
    from metatv.gui.main_window_metadata import _MetadataMixin

    host = SimpleNamespace()
    host.db = db_obj
    host.config = SimpleNamespace(metadata_auto_fetch=True)
    host.details_pane = _DetailsPaneDouble()
    host.executor = _RecordingExecutor()
    host.update_details_pane_for_channel = (
        _MetadataMixin.update_details_pane_for_channel.__get__(host)
    )
    return host


def _channel(channel_id: str):
    return SimpleNamespace(
        id=channel_id, name=channel_id, provider_id="prov1",
        media_type=MediaType.MOVIE,
    )


def test_duplicate_render_within_window_is_suppressed(db):
    """Two calls with the same channel back-to-back: the second is
    suppressed — no second render, no second fetch."""
    host = _make_host(db)
    ch = _channel(CHANNEL_A)

    host.update_details_pane_for_channel(ch)
    host.update_details_pane_for_channel(ch)

    assert host.details_pane.shown == [CHANNEL_A]
    assert host.executor.submit_calls == 1


def test_rerender_after_window_is_honoured(monkeypatch, db):
    """The click-again-to-refresh escape hatch (#680): once the debounce
    window has elapsed, the SAME channel renders again."""
    import metatv.gui.main_window_metadata as mod

    clock = [100.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])

    host = _make_host(db)
    ch = _channel(CHANNEL_A)

    host.update_details_pane_for_channel(ch)
    clock[0] += 0.5  # past _RERENDER_DEBOUNCE_S
    host.update_details_pane_for_channel(ch)

    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_A]
    assert host.executor.submit_calls == 2


def test_different_channel_renders_immediately(db):
    """Channel A then channel B immediately: both render — the debounce is
    keyed on the channel id, not a blanket cooldown."""
    host = _make_host(db)

    host.update_details_pane_for_channel(_channel(CHANNEL_A))
    host.update_details_pane_for_channel(_channel(CHANNEL_B))

    assert host.details_pane.shown == [CHANNEL_A, CHANNEL_B]
    assert host.executor.submit_calls == 2
