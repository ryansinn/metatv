"""Tests for the in-app update checker (semver, DTO, gating, threading).

Network is always mocked — these tests never hit real GitHub.  The threading
test proves the worker result crosses back to the main thread via the Qt signal.
"""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

import metatv.core.update_checker as uc
from metatv.core.config import Config
from metatv.core.update_checker import (
    UpdateChecker,
    UpdateInfo,
    build_update_info,
    fetch_latest_release,
    is_newer_version,
)


# ── Semver comparison ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("0.11.0", "0.10.0", True),     # minor bump
        ("0.10.1", "0.10.0", True),     # patch bump
        ("0.10.0", "0.10.0", False),    # equal → not newer
        ("v0.11.0", "0.10.0", True),    # leading 'v' tolerated
        ("0.9.0", "0.10.0", False),     # older
        ("garbage", "0.10.0", False),   # malformed → not newer, no crash
        ("0.11.0-rc1", "0.11.0", False),  # a pre-release is older than its final
        ("0.11.0", "0.11.0-rc1", True),   # final is newer than its pre-release
        ("0.11.0-rc2", "0.11.0-rc1", True),  # later rc newer than earlier rc
    ],
)
def test_is_newer_version(latest, current, expected):
    assert is_newer_version(latest, current) is expected


# ── DTO construction from JSON ───────────────────────────────────────────────

def test_build_update_info_from_json():
    data = {
        "tag_name": "v0.12.0",
        "html_url": "https://github.com/ryansinn/metatv/releases/tag/v0.12.0",
        "assets": [
            {"name": "notes.zip", "browser_download_url": "https://x/notes.zip"},
            {"name": "MetaTV-0.12.0-arm64.dmg",
             "browser_download_url": "https://x/MetaTV-0.12.0-arm64.dmg"},
        ],
    }
    info = build_update_info(data, "0.10.0")
    assert info is not None
    assert info.current == "0.10.0"
    assert info.latest == "0.12.0"  # 'v' stripped for display
    assert info.is_newer is True
    assert info.release_url.endswith("/v0.12.0")
    assert info.dmg_url == "https://x/MetaTV-0.12.0-arm64.dmg"


def test_build_update_info_no_tag_returns_none():
    assert build_update_info({}, "0.10.0") is None
    assert build_update_info({"tag_name": ""}, "0.10.0") is None


# ── Network fetch (mocked urlopen) ───────────────────────────────────────────

class _FakeResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_latest_release_success(monkeypatch):
    payload = {
        "tag_name": "v0.11.0",
        "html_url": "https://github.com/ryansinn/metatv/releases/tag/v0.11.0",
        "assets": [
            {"name": "MetaTV-0.11.0-arm64.dmg",
             "browser_download_url": "https://x/MetaTV-0.11.0-arm64.dmg"},
        ],
    }
    monkeypatch.setattr(
        uc.urllib.request, "urlopen",
        lambda req, timeout=10: _FakeResponse(json.dumps(payload)),
    )
    info = fetch_latest_release("0.10.0")
    assert info is not None
    assert info.latest == "0.11.0"
    assert info.is_newer is True
    assert info.dmg_url.endswith(".dmg")


def test_fetch_latest_release_http_error_returns_none(monkeypatch):
    def _boom(req, timeout=10):
        raise uc.urllib.error.URLError("offline")

    monkeypatch.setattr(uc.urllib.request, "urlopen", _boom)
    assert fetch_latest_release("0.10.0") is None


def test_fetch_latest_release_bad_json_returns_none(monkeypatch):
    monkeypatch.setattr(
        uc.urllib.request, "urlopen",
        lambda req, timeout=10: _FakeResponse("not-json{"),
    )
    assert fetch_latest_release("0.10.0") is None


# ── Gating: enable flag + 24h throttle + manual bypass ───────────────────────

def test_check_async_gating(qtbot, monkeypatch):
    cfg = Config()
    cfg.update_check_enabled = True
    cfg.update_last_checked = datetime.now(timezone.utc).isoformat()
    checker = UpdateChecker(cfg)
    submitted: list = []
    monkeypatch.setattr(checker._executor, "submit", lambda *a, **k: submitted.append(a))
    try:
        # Recent check → throttled.
        checker.check_async(manual=False)
        assert submitted == []

        # >24h ago → runs.
        cfg.update_last_checked = (
            datetime.now(timezone.utc) - timedelta(hours=25)
        ).isoformat()
        checker.check_async(manual=False)
        assert len(submitted) == 1

        # Disabled → skipped even with no prior check.
        submitted.clear()
        cfg.update_check_enabled = False
        cfg.update_last_checked = ""
        checker.check_async(manual=False)
        assert submitted == []

        # Manual bypasses both gates.
        checker.check_async(manual=True)
        assert len(submitted) == 1
    finally:
        checker.shutdown()


# ── skip_version suppression (auto) + manual override ────────────────────────

def test_skip_version_suppresses_auto_banner(qtbot):
    cfg = Config()
    cfg.update_skip_version = "0.11.0"
    checker = UpdateChecker(cfg)
    seen: list = []
    checker.update_available.connect(seen.append)
    info = UpdateInfo("0.10.0", "0.11.0", True, "url", "dmg")
    try:
        # Auto check for a skipped version → suppressed.
        checker._on_result((info, False))
        assert seen == []

        # Clear the skip → auto banner shows.
        cfg.update_skip_version = ""
        checker._on_result((info, False))
        assert seen == [info]

        # Manual always shows, even for a skipped version.
        cfg.update_skip_version = "0.11.0"
        seen.clear()
        checker._on_result((info, True))
        assert seen == [info]
    finally:
        checker.shutdown()


def test_manual_up_to_date_emits_no_update(qtbot):
    cfg = Config()
    checker = UpdateChecker(cfg, current_version="0.10.0")
    events: list = []
    checker.no_update.connect(events.append)
    info = UpdateInfo("0.10.0", "0.10.0", False, "url", "")
    try:
        checker._on_result((info, True))
        assert events == [info]
    finally:
        checker.shutdown()


def test_manual_error_emits_no_update_none(qtbot):
    cfg = Config()
    checker = UpdateChecker(cfg)
    events: list = []
    checker.no_update.connect(events.append)
    try:
        checker._on_result((None, True))
        assert events == [None]
    finally:
        checker.shutdown()


def test_auto_error_is_silent(qtbot):
    cfg = Config()
    checker = UpdateChecker(cfg)
    avail: list = []
    none_events: list = []
    checker.update_available.connect(avail.append)
    checker.no_update.connect(none_events.append)
    try:
        checker._on_result((None, False))
        assert avail == []
        assert none_events == []
    finally:
        checker.shutdown()


def test_on_result_records_last_checked(qtbot):
    cfg = Config()
    cfg.update_last_checked = ""
    checker = UpdateChecker(cfg)
    try:
        checker._on_result((None, False))
        # Timestamp recorded so the throttle works next time.
        assert cfg.update_last_checked
        datetime.fromisoformat(cfg.update_last_checked)  # parses without error
    finally:
        checker.shutdown()


# ── Threading: worker off-thread, result on the main thread ──────────────────

def test_result_delivered_on_main_thread(qtbot, monkeypatch):
    main_id = threading.get_ident()
    worker_ids: list[int] = []
    info = UpdateInfo("0.10.0", "0.11.0", True, "url", "dmg")

    def _fake_fetch(current):
        worker_ids.append(threading.get_ident())
        return info

    monkeypatch.setattr(uc, "fetch_latest_release", _fake_fetch)

    cfg = Config()
    checker = UpdateChecker(cfg, current_version="0.10.0")
    slot_ids: list[int] = []
    checker.update_available.connect(lambda i: slot_ids.append(threading.get_ident()))
    try:
        with qtbot.waitSignal(checker.update_available, timeout=5000):
            checker.check_async(manual=True)
        assert worker_ids and worker_ids[0] != main_id  # fetch ran off-thread
        assert slot_ids == [main_id]                     # slot ran on main thread
    finally:
        checker.shutdown()
