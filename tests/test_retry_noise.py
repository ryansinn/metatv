"""Less retrying against a provider (owner, 2026-10-20: "stop the retry noise").

A one-connection account answered 458 for 22 minutes after a dropped stream,
and every attempt in that window hit it again: the background re-checker, the
other versions of the same title on the same account, and mpv's yt-dlp
fallback re-requesting the URL ffmpeg had just been refused.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def _manager(db, enabled: bool):
    from metatv.core.stream_retry_manager import StreamRetryManager

    m = StreamRetryManager(db, lambda url: (True, None), enabled=lambda: enabled)
    m._executor = MagicMock()
    return m


def test_background_rechecks_are_off_by_default(tmp_path):
    from metatv.core.config import Config

    assert Config(config_dir=tmp_path).stream_retry_checks_enabled is False


def test_a_disabled_checker_makes_no_connection(qapp, db):
    m = _manager(db, enabled=False)
    m._check_due()
    m.check_all_now()
    m._executor.submit.assert_not_called()
    assert m.get_all_display() == [], "the list promises re-checks; show none"
    m.stop()


def test_an_enabled_checker_still_checks(qapp, db):
    m = _manager(db, enabled=True)
    m.check_all_now()
    m._executor.submit.assert_called_once()
    m.stop()


def test_failures_are_still_counted_when_checks_are_off(qapp, db):
    """add_failure feeds the dead-stream gate; switching re-checks off must not stop it."""
    m = _manager(db, enabled=False)
    m._write = MagicMock()
    m.add_failure("c1", "Film", "http://h/movie/u/p/1.mp4", "HTTP 458")
    m._write.assert_called_once()
    m.stop()


def test_provider_streams_skip_the_ytdl_fallback_but_trailers_keep_it():
    import re

    from metatv.core.players.mpv_args import stream_args

    flag = next(a for a in stream_args() if a.startswith("--script-opts=ytdl_hook-exclude="))
    patterns = flag.split("=", 2)[2].split("|")

    def excluded(url: str) -> bool:     # mpv matches after the scheme, Lua-style
        rest = url.split("://", 1)[1]
        return any(re.search(re.escape(p), rest) for p in patterns)

    assert excluded("http://vpn.host.top/movie/u/p/1729522.mp4")
    assert excluded("http://host:8080/live/u/p/123.ts")
    assert excluded("http://host/series/u/p/55.mkv")
    assert not excluded("https://www.youtube.com/watch?v=abc123"), "trailers need yt-dlp"


def test_a_connection_limit_refusal_is_recognised():
    from metatv.core.stream_diagnostics import is_connection_limit_error as _is_connection_limit

    assert _is_connection_limit("HTTP 458") and _is_connection_limit("HTTP 509")
    assert not _is_connection_limit("HTTP 403")
    assert not _is_connection_limit("This channel is not available")
    assert not _is_connection_limit(None)


def test_settings_shows_the_switch_off_and_greys_the_refresh_option(qapp):
    """Real Settings dialog: the switch loads off, and the dependent option follows it."""
    from metatv.core.config import Config
    from metatv.gui.settings_dialog import SettingsDialog

    cfg = Config()
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._stream_retry_checks_check.isChecked() is False
        assert not dlg._recheck_failed_on_refresh_check.isEnabled()
        dlg._stream_retry_checks_check.setChecked(True)
        assert dlg._recheck_failed_on_refresh_check.isEnabled()
        dlg._save_values()
        assert cfg.stream_retry_checks_enabled is True
    finally:
        dlg.close()
