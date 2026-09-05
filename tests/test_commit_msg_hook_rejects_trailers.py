"""The commit-msg hook is the trailer guard — and it has to be commit-msg.

The check used to live in ``.githooks/pre-commit``, which git invokes with no
arguments, so ``msg_file="${1:-}"`` was always empty and the guard never ran:
three agent commits carried ``Co-Authored-By`` / ``Claude-Session`` trailers
past it on 2026-09-05. ``commit-msg`` is the hook that receives the message
file. These tests execute the hook the way git does.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_HOOK = _ROOT / ".githooks" / "commit-msg"


def _run(msg: str, tmp_path: Path) -> subprocess.CompletedProcess:
    f = tmp_path / "COMMIT_EDITMSG"
    f.write_text(msg, encoding="utf-8")
    return subprocess.run(
        ["bash", str(_HOOK), str(f)], capture_output=True, text=True, check=False,
    )


def test_the_hook_exists_and_is_the_commit_msg_hook():
    assert _HOOK.is_file(), "the trailer guard must be .githooks/commit-msg"
    pre_commit = (_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "Co-Authored-By:'" not in pre_commit, (
        "the trailer check must not live in pre-commit — git passes it no "
        "message file, so it never runs there"
    )


@pytest.mark.parametrize("trailer", [
    "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>",
    "co-authored-by: Someone <x@y>",
    "Claude-Session: https://claude.ai/code/session_x",
    "   Co-Authored-By: indented <x@y>",
])
def test_a_trailer_is_rejected(tmp_path, trailer):
    r = _run(f"Fix a thing\n\nBody.\n\n{trailer}\n", tmp_path)
    assert r.returncode == 1, r.stderr
    assert "COMMIT BLOCKED" in r.stderr


def test_a_plain_message_passes(tmp_path):
    r = _run("Fix a thing\n\nBody mentioning co-authored work in prose.\n", tmp_path)
    assert r.returncode == 0, r.stderr


def test_no_message_file_is_a_no_op(tmp_path):
    r = subprocess.run(["bash", str(_HOOK)], capture_output=True, text=True, check=False)
    assert r.returncode == 0
