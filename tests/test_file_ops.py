"""``core/file_ops``: Windows' refusals handled once, POSIX untouched.

The Windows branches are driven on any platform by patching
``runtime_env.is_windows`` and making the OS call raise the
``PermissionError`` a sharing violation produces there.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from metatv.core import file_ops, runtime_env


def _windows(monkeypatch):
    monkeypatch.setattr(runtime_env, "is_windows", lambda: True)
    monkeypatch.setattr(file_ops.time, "sleep", lambda s: None)


def test_replace_outlasts_a_brief_scanner_lock_on_windows(tmp_path, monkeypatch):
    _windows(monkeypatch)
    src, dst = tmp_path / "a.part", tmp_path / "a.mp4"
    src.write_text("done")
    real, refusals = os.replace, iter([PermissionError, PermissionError])

    def scanner_holds_it_twice(a, b):
        error = next(refusals, None)
        if error:
            raise error("sharing violation")
        real(a, b)

    monkeypatch.setattr(file_ops.os, "replace", scanner_holds_it_twice)
    file_ops.replace(src, dst)
    assert dst.read_text() == "done" and not src.exists()


def test_replace_gives_up_on_a_lock_that_never_clears(tmp_path, monkeypatch):
    _windows(monkeypatch)
    monkeypatch.setattr(file_ops.os, "replace",
                        lambda a, b: (_ for _ in ()).throw(PermissionError("held")))
    with pytest.raises(PermissionError):
        file_ops.replace(tmp_path / "a", tmp_path / "b")


def test_replace_does_not_retry_off_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_env, "is_windows", lambda: False)
    calls = []
    monkeypatch.setattr(file_ops.os, "replace",
                        lambda a, b: calls.append(1) or (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(PermissionError):
        file_ops.replace(tmp_path / "a", tmp_path / "b")
    assert len(calls) == 1


def test_remove_reports_in_use_on_windows_and_raises_elsewhere(tmp_path, monkeypatch):
    target = tmp_path / "movie.mp4"
    target.write_text("x")
    monkeypatch.setattr(Path, "unlink",
                        lambda self, missing_ok=False: (_ for _ in ()).throw(PermissionError()))
    monkeypatch.setattr(runtime_env, "is_windows", lambda: True)
    assert file_ops.remove(target) is False
    monkeypatch.setattr(runtime_env, "is_windows", lambda: False)
    with pytest.raises(PermissionError):
        file_ops.remove(target)


def test_remove_deletes_and_tolerates_a_missing_file(tmp_path):
    target = tmp_path / "x"
    target.write_text("x")
    assert file_ops.remove(target) is True and not target.exists()
    assert file_ops.remove(target) is True


def test_atomic_write_is_utf8_and_leaves_no_temp_on_failure(tmp_path):
    target = tmp_path / "c.yaml"
    file_ops.atomic_write(target, lambda f: f.write("é📺"), suffix=".yaml")
    assert target.read_bytes() == "é📺".encode("utf-8")

    def half_written(f):
        f.write("partial")
        raise RuntimeError("crash mid-write")

    with pytest.raises(RuntimeError):
        file_ops.atomic_write(target, half_written, suffix=".yaml")
    assert target.read_text(encoding="utf-8") == "é📺", "the old file must survive"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.yaml"], "temp file left behind"
