"""The signal check is parked, and stays parked until someone opts in.

It shipped in #617 and was switched off the same day, for two independent
reasons measured on the owner's account within minutes:

* **It jams the only connection.** A probe holds the source's connection for the
  length of its sample, and both of their sources report ``max_connections=1``.
  The worker started unconditionally and probed every few seconds, so playback
  competed with it and probes competed with each other.
* **The verdicts are wrong in the common case.** Channels they were watching came
  back ``dead``, because ffmpeg exits 145/146 when it cannot OPEN the input — on
  a one-connection account usually "the slot was busy" — and that stderr matched
  no recognized pattern, so it fell through to "no video".

These tests pin the OFF state rather than the feature: the code, the settings
tab and #617's own tests all remain, and re-enabling is a deliberate act.
"""

from __future__ import annotations

from metatv.core.config import Config
from metatv.core.signal_check_manager import SignalCheckManager


def test_the_feature_is_off_by_default():
    """A fresh config must not probe. The default IS the fix."""
    assert Config().signal_check_enabled is False, (
        "signal checking is on by default again — it takes the source's only "
        "connection every few seconds and its verdicts are not trustworthy yet")


def test_start_does_nothing_while_disabled(tmp_path):
    """Asserted through start(), because that is what MainWindow calls.

    A test on the config flag alone would pass while the manager ignored it —
    which is exactly what the shipped version did: there was no flag to ignore
    and start() ran unconditionally.
    """
    mgr = SignalCheckManager(None, Config(), None)
    mgr.start()
    try:
        assert mgr._thread is None, (
            "the worker started despite the feature being disabled")
    finally:
        mgr.shutdown(timeout=1)


def test_enabling_it_is_what_starts_the_worker(tmp_path, monkeypatch):
    """Non-degeneracy: a manager that never starts would pass the test above
    forever, including after someone fixes the classifier and turns it on."""
    import metatv.core.signal_check_manager as scm

    monkeypatch.setattr(scm, "ffmpeg_available", lambda: True)
    cfg = Config()
    cfg.signal_check_enabled = True
    mgr = SignalCheckManager(None, cfg, None)
    mgr.start()
    try:
        assert mgr._thread is not None, (
            "the worker no longer starts even when explicitly enabled — the "
            "feature is broken rather than parked")
    finally:
        mgr.shutdown(timeout=2)
