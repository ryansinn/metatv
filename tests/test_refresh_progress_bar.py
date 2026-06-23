"""Behavioral tests for the refresh-notification progress bar fixes.

Covers three regressions that caused the bars to be stuck at 0% forever:

A) Active notification bar — ``_on_progress`` must call ``update_progress`` on the
   active notification each time it fires, so the bar advances as sub-tasks complete.
   Previously ``_on_progress`` only called ``set_steps`` (the checklist) and never
   touched the bar's ``progress_current`` / ``progress_total`` fields.

B) Overview notification — must be created with ``show_bar=False`` so the permanently-
   indeterminate bar is suppressed entirely.  The steps list is already the progress
   indicator for the overview; a forever-0% bar adds no information.

C) ``_update_tags_in_thread`` and ``_update_prefixes_in_thread`` — must emit rising
   ``progress`` values per batch so the active-notification bar actually moves during
   the long parse phase instead of sitting frozen until the phase ends.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from PyQt6.QtCore import QCoreApplication, QThread, pyqtSignal


# ---------------------------------------------------------------------------
# Minimal QApplication for signal delivery
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def qapp():
    import sys
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# Helpers copied from test_refresh_queue_manager so this file is self-contained
# ---------------------------------------------------------------------------

class _FakeThread(QThread):
    """Fake ProviderLoadThread — drive via fire helpers; no real thread spawned."""
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, provider, db, **kwargs):
        super().__init__()
        self.provider_id = provider.id
        self.prefix_stats: dict | None = None

    def run(self) -> None:
        pass

    def start(self) -> None:
        pass

    def _fire_progress(self, cur: int, tot: int, msg: str) -> None:
        self.progress.emit(cur, tot, msg)

    def _fire_finished(self, success: bool = True, msg: str = "Loaded 100 channels") -> None:
        self.finished.emit(success, msg)


def _make_db_provider(pid: str, name: str) -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.name = name
    p.type = "xtream"
    p.url = "http://example.com"
    p.epg_enabled = False
    return p


def _make_provider_model(pid: str, name: str) -> MagicMock:
    m = MagicMock()
    m.id = pid
    m.name = name
    return m


def _build_manager_tracking_nm(threads_by_pid: dict, providers: list):
    """Build a manager where the NotificationManager mock tracks update_progress calls.

    Returns (manager, repo_factory, thread_factory, nm, update_progress_calls).
    ``update_progress_calls`` is a list that receives (notif_id, cur, tot) on each call.
    """
    from metatv.gui.refresh_queue_manager import RefreshQueueManager

    db = MagicMock()
    config = MagicMock()
    config.prefix_separators = []
    config.filter_language_groups = {}
    config.filter_quality_groups = {}
    config.filter_platform_groups = {}
    config.filter_regional_groups = {}

    nm = MagicMock()
    _counter = [0]

    def _show_progress(**kwargs):
        _counter[0] += 1
        return f"notif-{_counter[0]}"

    nm.show_progress.side_effect = _show_progress
    nm.complete_progress.side_effect = lambda nid, msg: None
    nm.set_steps.side_effect = lambda nid, steps: None
    nm.update.side_effect = lambda nid, **kwargs: None
    nm.dismiss.side_effect = lambda nid: None

    update_progress_calls: list[tuple] = []

    def _update_progress(nid, cur, tot=None, msg=None):
        update_progress_calls.append((nid, cur, tot))

    nm.update_progress.side_effect = _update_progress

    # Mock DB session / repos
    session = MagicMock()
    repos = MagicMock()
    provider_map = {p.id: p for p in providers}

    repos.providers.get_by_id.side_effect = lambda pid: provider_map.get(pid)
    repos.providers.to_model.side_effect = lambda p: _make_provider_model(p.id, p.name)

    db.get_session.return_value = session

    repo_factory_mock = MagicMock(return_value=repos)

    manager = RefreshQueueManager(db, config, nm, parent=None)

    def _fake_thread_factory(provider_model, db, **kwargs):
        return threads_by_pid[provider_model.id]

    return manager, repo_factory_mock, _fake_thread_factory, nm, update_progress_calls


# ---------------------------------------------------------------------------
# A) Active-notification bar must move when _on_progress fires
# ---------------------------------------------------------------------------

class TestActiveNotificationBarUpdates:
    """_on_progress must call update_progress (not only set_steps) so the bar moves."""

    def test_update_progress_called_on_each_progress_signal(self, qapp):
        """Every progress emit from the thread must reach update_progress on the active toast."""
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm, up_calls = _build_manager_tracking_nm(
            {"p1": t1}, [p1]
        )

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            # Fire several distinct progress signals
            t1._fire_progress(10, 100, "Fetching live channels…")
            t1._fire_progress(50, 100, "Storing channels (5,000/10,000)…")
            t1._fire_progress(87, 100, "Detecting channel prefixes…")
            qapp.processEvents()

        # update_progress must have been called for each emit
        assert len(up_calls) >= 3, (
            f"update_progress must be called for every progress signal; got {len(up_calls)}"
        )

    def test_bar_value_increases_with_progress(self, qapp):
        """The ``cur`` value passed to update_progress must rise as the thread advances."""
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm, up_calls = _build_manager_tracking_nm(
            {"p1": t1}, [p1]
        )

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            t1._fire_progress(10, 100, "Fetching…")
            t1._fire_progress(70, 100, "Stored 10,000 channels")
            t1._fire_progress(93, 100, "Computing content tags…")
            qapp.processEvents()

        cur_values = [c for _nid, c, _tot in up_calls]
        assert cur_values == sorted(cur_values), (
            "cur values passed to update_progress must be non-decreasing "
            f"(got {cur_values})"
        )

    def test_update_progress_targets_active_notification_not_overview(self, qapp):
        """update_progress must be called on the ACTIVE toast id, not the overview id."""
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm, up_calls = _build_manager_tracking_nm(
            {"p1": t1}, [p1]
        )

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")
            overview_id = manager._overview_notif_id

            t1._fire_progress(50, 100, "Storing channels…")
            qapp.processEvents()

        # All update_progress calls must be for the active notification, not overview
        for nid, _cur, _tot in up_calls:
            assert nid != overview_id, (
                f"update_progress must not target the overview notification; got nid={nid!r}, "
                f"overview_id={overview_id!r}"
            )


# ---------------------------------------------------------------------------
# B) Overview notification must suppress the progress bar (show_bar=False)
# ---------------------------------------------------------------------------

class TestOverviewHasNoProgressBar:
    """Overview notification must be created with show_bar=False.

    The overview uses total=None (indeterminate); the bar stays 0% forever.
    The steps list already shows per-source progress — the bar is noise.
    """

    def test_overview_show_progress_called_with_show_bar_false(self, qapp):
        """show_progress for the overview must pass show_bar=False."""
        p1 = _make_db_provider("p1", "Provider 1")
        t1 = _FakeThread(_make_provider_model("p1", "Provider 1"), None)
        t1.start = lambda: None

        manager, repo_factory, thread_factory, nm, _up_calls = _build_manager_tracking_nm(
            {"p1": t1}, [p1]
        )

        show_calls: list[dict] = []

        def _show_progress(**kwargs):
            show_calls.append(kwargs)
            return f"notif-{len(show_calls)}"

        nm.show_progress.side_effect = _show_progress

        with (
            patch("metatv.gui.refresh_queue_manager.RepositoryFactory", repo_factory),
            patch("metatv.gui.refresh_queue_manager.ProviderLoadThread", side_effect=thread_factory),
        ):
            manager.enqueue("p1", "Provider 1")

        # First show_progress = overview (no total); second = active toast (total=100)
        overview_call = next((c for c in show_calls if c.get("total") is None), None)
        assert overview_call is not None, "Overview show_progress call not found (total=None)"
        assert overview_call.get("show_bar") is False, (
            "Overview show_progress must pass show_bar=False to suppress the 0%-forever bar; "
            f"got show_bar={overview_call.get('show_bar')!r}"
        )

    def test_notification_dataclass_default_show_bar_true(self):
        """Notification.show_progress_bar defaults to True (backward-compatible)."""
        from metatv.core.notifications import Notification, NotificationType

        notif = Notification(
            title="Refreshing Source",
            type=NotificationType.PROGRESS,
        )
        assert notif.show_progress_bar is True, (
            "Notification.show_progress_bar must default to True so existing PROGRESS "
            "notifications are unaffected"
        )

    def test_notification_dataclass_show_bar_false_stored(self):
        """Notification.show_progress_bar=False is stored on the dataclass."""
        from metatv.core.notifications import Notification, NotificationType

        notif = Notification(
            title="Source refresh queue",
            type=NotificationType.PROGRESS,
            show_progress_bar=False,
        )
        assert notif.show_progress_bar is False, (
            "Notification.show_progress_bar=False must be stored and readable"
        )

    def test_show_progress_passes_show_bar_false_to_notification(self):
        """NotificationManager.show_progress(show_bar=False) must store show_progress_bar=False."""
        from metatv.core.notifications import NotificationManager

        nm = NotificationManager()
        nid = nm.show_progress(title="Queue", total=None, show_bar=False)
        notif = next(n for n in nm.notifications if n.id == nid)
        assert notif.show_progress_bar is False, (
            "show_progress(show_bar=False) must set show_progress_bar=False on the Notification"
        )

    def test_show_progress_default_show_bar_true(self):
        """NotificationManager.show_progress() without show_bar must default to True."""
        from metatv.core.notifications import NotificationManager

        nm = NotificationManager()
        nid = nm.show_progress(title="Active", total=100)
        notif = next(n for n in nm.notifications if n.id == nid)
        assert notif.show_progress_bar is True


# ---------------------------------------------------------------------------
# C) Per-batch sub-progress in the tag/prefix phases
# ---------------------------------------------------------------------------

class TestTaggingProgressMessages:
    """_advance_steps must keep PARSE active for per-batch 'Tagging N / M channels…' messages."""

    def test_tagging_batch_message_keeps_parse_active(self):
        """'Tagging N / M channels…' must map to PARSE=active (not done, not pending)."""
        from metatv.core.notifications import StepStatus
        from metatv.gui.main_window_providers import _advance_steps, _make_steps, _STEP_PARSE

        steps = _advance_steps(
            _make_steps(epg=False), "Tagging 45,200 / 290,000 channels…", 95
        )
        step_map = dict(steps)
        assert step_map[_STEP_PARSE] == StepStatus.ACTIVE, (
            "'Tagging N / M channels…' must keep PARSE as active (not done)"
        )

    def test_tagging_message_marks_fetch_and_store_done(self):
        """FETCH and STORE must be DONE during the tagging phase."""
        from metatv.core.notifications import StepStatus
        from metatv.gui.main_window_providers import (
            _advance_steps, _make_steps, _STEP_FETCH, _STEP_STORE
        )

        steps = _advance_steps(
            _make_steps(epg=False), "Tagging 100,000 / 200,000 channels…", 94
        )
        step_map = dict(steps)
        assert step_map[_STEP_FETCH] == StepStatus.DONE
        assert step_map[_STEP_STORE] == StepStatus.DONE

    def test_detecting_prefixes_batch_message_keeps_parse_active(self):
        """'Detecting prefixes (N / M channels)…' must also keep PARSE active."""
        from metatv.core.notifications import StepStatus
        from metatv.gui.main_window_providers import _advance_steps, _make_steps, _STEP_PARSE

        steps = _advance_steps(
            _make_steps(epg=False), "Detecting prefixes (10,000 / 50,000 channels)…", 90
        )
        step_map = dict(steps)
        assert step_map[_STEP_PARSE] == StepStatus.ACTIVE


class TestTaggingThreadEmitsProgress:
    """_update_tags_in_thread must emit rising progress values per batch."""

    def test_tags_thread_emits_increasing_progress_per_batch(self, tmp_path):
        """With more channels than one batch, progress emissions must be strictly rising."""
        import uuid
        from metatv.core.config import Config
        from metatv.core.database import ChannelDB, Database
        from metatv.core.provider_loader import ProviderLoadThread

        db_path = tmp_path / "tagging_progress.db"
        db = Database(f"sqlite:///{db_path}")
        db.create_tables()

        pid = f"prov_{uuid.uuid4().hex[:8]}"
        # Create 600 channels (> _TAG_BATCH=500 → two batch iterations)
        with db.session_scope() as session:
            for i in range(600):
                session.add(ChannelDB(
                    id=str(uuid.uuid4()),
                    source_id=str(uuid.uuid4()),
                    provider_id=pid,
                    name=f"Channel {i:04d}",
                    raw_data={"genre": "Action"},
                ))

        # Collect progress emissions
        emitted: list[tuple[int, int, str]] = []

        provider = SimpleNamespace(id=pid, name="TestProvider")
        thread = ProviderLoadThread.__new__(ProviderLoadThread)
        thread.db = db
        thread.provider = provider

        # Capture emissions via _try_emit_progress override
        def _capture(cur: int, tot: int, msg: str) -> None:
            if "Tagging" in msg:
                emitted.append((cur, tot, msg))

        thread._try_emit_progress = _capture

        # Use a real isolated Config (tmp_path guarded by conftest's _isolate_user_config).
        cfg = Config(config_dir=tmp_path / "cfg")

        with patch("metatv.core.config.Config.load", return_value=(cfg, False)):
            thread._update_tags_in_thread()

        db.close()

        assert len(emitted) >= 2, (
            f"Expected at least 2 tagging progress emits for 600 channels (_TAG_BATCH=500); "
            f"got {len(emitted)}"
        )
        cur_values = [c for c, _t, _m in emitted]
        assert cur_values == sorted(cur_values), (
            f"Tagging progress must be non-decreasing; got {cur_values}"
        )
        # All values must be in the _BAND_TAGS range (60-97).
        # At ~50% through the tag phase the bar must be in the 70s — NOT the 90s.
        from metatv.core.provider_loader import _BAND_TAGS
        _tag_start, _tag_end = _BAND_TAGS
        assert all(_tag_start <= c <= _tag_end for c in cur_values), (
            f"Tagging progress must stay in {_tag_start}–{_tag_end} band; got {cur_values}"
        )
        # The first batch completes at 500/600 ≈ 83% through; with _BAND_TAGS=(60,97)
        # that places the first emit near int(60 + 0.83*37) = ~91. The second (600/600)
        # lands at 97.  Both are in the 60-97 range — crucially NOT stuck in the 90s
        # for the bulk of the work.  We assert the midpoint behaviour: with 600 channels
        # and _TAG_BATCH=500, the first batch covers 500/600≈83% of the work; the bar
        # should read well below 97 at that point (more than 4 units of headroom remain).
        assert min(cur_values) < _tag_end, (
            f"First tagging emit must be below the band ceiling ({_tag_end}); "
            f"got first={min(cur_values)}"
        )


class TestBandConstantsMonotonicAndCorrectRange:
    """The band constants in provider_loader must be monotonically non-decreasing
    end-to-end and the tag band must occupy the lion's share of 0-100.

    These tests catch a regression where re-weighting accidentally violated
    the monotonic invariant or left the tag band too narrow.
    """

    def test_band_sequence_is_non_decreasing(self):
        """The sequence fetch→store→categorize→prefix→tags→stats must be
        non-decreasing so the progress bar never jumps backward.
        """
        from metatv.core.provider_loader import (
            _BAND_FETCH, _BAND_STORE, _BAND_CATEGORIZE,
            _BAND_PREFIX, _BAND_TAGS, _BAND_STATS,
        )
        bands = [_BAND_FETCH, _BAND_STORE, _BAND_CATEGORIZE,
                 _BAND_PREFIX, _BAND_TAGS, _BAND_STATS]

        # Each band's start must equal the previous band's end (contiguous).
        for i in range(1, len(bands)):
            prev_end = bands[i - 1][1]
            cur_start = bands[i][0]
            assert cur_start == prev_end, (
                f"Band {i} start ({cur_start}) != band {i-1} end ({prev_end}): "
                f"bands must be contiguous and non-decreasing"
            )

        # Last band must end at 100 (the stats phase fills up to 100; done emits 100 too).
        assert _BAND_STATS[1] == 100, (
            f"_BAND_STATS must end at 100; got {_BAND_STATS[1]}"
        )

    def test_tag_band_at_50pct_through_is_in_70s(self):
        """At exactly 50% through the tag phase, the emitted bar value must be
        in the 70s — NOT the 90s (the bug this PR fixes).

        With _BAND_TAGS=(60, 97): 50% → int(60 + 0.5 * 37) = 78.
        """
        from metatv.core.provider_loader import _BAND_TAGS
        _tag_start, _tag_end = _BAND_TAGS
        midpoint = int(_tag_start + 0.5 * (_tag_end - _tag_start))
        assert 70 <= midpoint <= 79, (
            f"At 50% through the tag phase the bar must read 70-79 (was stuck in 90s "
            f"before this fix); got {midpoint} from _BAND_TAGS={_BAND_TAGS}"
        )

    def test_tag_band_is_widest_band(self):
        """The tag band must be the widest of all six bands — it dominates wall-clock."""
        from metatv.core.provider_loader import (
            _BAND_FETCH, _BAND_STORE, _BAND_CATEGORIZE,
            _BAND_PREFIX, _BAND_TAGS, _BAND_STATS,
        )
        bands = {
            "FETCH": _BAND_FETCH,
            "STORE": _BAND_STORE,
            "CATEGORIZE": _BAND_CATEGORIZE,
            "PREFIX": _BAND_PREFIX,
            "TAGS": _BAND_TAGS,
            "STATS": _BAND_STATS,
        }
        widths = {name: end - start for name, (start, end) in bands.items()}
        widest = max(widths, key=lambda n: widths[n])
        assert widest == "TAGS", (
            f"_BAND_TAGS must be the widest band (it dominates wall-clock); "
            f"widths={widths}, widest={widest}"
        )
