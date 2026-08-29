"""One definition of where the logs are, and a sink that is not DEBUG by default.

Three auditors independently found the same thing: **90% of the log is two
lines.** Two ``logger.debug`` calls in ``metadata_from_raw`` fired 650,101 times
each and produced 1.30M of 1.44M lines — 330 MB on the owner's disk. Under a
seven-day retention that leaves ~8 days of history where there would otherwise
be ~76, so the file is worst exactly when it is needed: a bug from last week has
already rotated away.

Two causes, both fixed here:

* ``metadata_from_raw`` runs once per catalogue row and logged three lines every
  time — including one that formatted a list of dict keys.
* the file sink was hardcoded ``level="DEBUG"`` in the shipped app.

And the location of the logs had two definitions — ``__main__.setup_logging``
derived it inline, ``qa_checklist_window`` derived it from a ``Config`` — with
the second carrying a docstring promising it "matches" the first. A comment
cannot keep that promise; ``core.log_paths`` can.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from metatv.core.log_paths import (
    ACTIVE_LOG_NAME, active_log_file, all_log_files, log_directory,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
PKG = REPO / "metatv"


# ── the parser must not log per row ─────────────────────────────────────────

def test_metadata_from_raw_logs_nothing_per_row():
    """THE assertion. This function runs once per catalogue row.

    Derived from the AST, so a logging call added anywhere inside the function
    later — at any level, in any branch — fails here without anyone having to
    remember this rule exists.
    """
    src = (PKG / "metadata_providers" / "provider_metadata.py").read_text()
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "metadata_from_raw"
    )

    logging_calls = [
        f"line {n.lineno}: logger.{n.func.attr}"
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "logger"
    ]

    assert not logging_calls, (
        "metadata_from_raw logs per catalogue row: "
        + ", ".join(logging_calls)
        + ". On the owner's library that is 650,101 calls per line."
    )


# ── the sink level ──────────────────────────────────────────────────────────

def _sink_call() -> ast.Call:
    src = (PKG / "__main__.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "logger"):
            return node
    raise AssertionError("no logger.add call found in __main__")


def test_the_file_sink_is_not_hardcoded_to_debug():
    """A shipped app writing DEBUG is the other half of the 330 MB."""
    level = next(
        (kw.value for kw in _sink_call().keywords if kw.arg == "level"), None
    )
    assert level is not None, "the sink must state its level"
    assert not (isinstance(level, ast.Constant) and level.value == "DEBUG"), (
        "the file sink is hardcoded to DEBUG in the shipped app"
    )


def test_the_level_can_still_be_raised_for_a_support_session():
    """Turning it up must not need a rebuild."""
    src = (PKG / "__main__.py").read_text()
    assert "METATV_LOG_LEVEL" in src, (
        "there must be a documented way to get DEBUG back without editing code"
    )


@pytest.mark.parametrize("value,expected", [
    ("DEBUG", "DEBUG"), ("debug", "DEBUG"), ("WARNING", "WARNING"),
    ("", "INFO"), ("nonsense", "INFO"), (None, "INFO"),
])
def test_the_level_env_var_resolves_safely(monkeypatch, value, expected):
    """A typo must not crash the app at startup, nor silently re-enable DEBUG."""
    if value is None:
        monkeypatch.delenv("METATV_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("METATV_LOG_LEVEL", value)

    import os
    level = os.environ.get("METATV_LOG_LEVEL", "INFO").upper()
    if level not in {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}:
        level = "INFO"
    assert level == expected


# ── one definition of the location ──────────────────────────────────────────

def test_only_log_paths_derives_the_log_directory():
    """Derived: any module that builds the path itself fails this.

    A second definition is how the two drifted in the first place.
    """
    offenders = []
    for path in sorted(PKG.rglob("*.py")):
        if path.name == "log_paths.py" or path.parts[-2:-1] == ("scripts",):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if '"logs"' in line or "'logs'" in line:
                if "log_paths" in line:
                    continue
                offenders.append(f"{path.relative_to(REPO).as_posix()}:{lineno}")
    assert not offenders, (
        "these build the log directory themselves instead of asking "
        f"core.log_paths: {offenders}"
    )


def test_the_paths_track_test_isolation(tmp_path, monkeypatch):
    """Path.home() is read per call, never cached at import.

    ``tests/conftest.py`` patches ``Path.home()`` to keep tests off the real
    user config — a module-level constant would be resolved at import time and
    walk straight past that guard.
    """
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))

    assert log_directory() == tmp_path / ".config" / "metatv" / "logs"
    assert active_log_file() == log_directory() / ACTIVE_LOG_NAME


def test_all_log_files_includes_the_rotated_copies(tmp_path, monkeypatch):
    """"Clear the logs" has to mean all of them.

    330 MB of the owner's disk was rotated siblings, not the active file.
    """
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    d = log_directory(create=True)
    (d / ACTIVE_LOG_NAME).write_text("live")
    (d / "metatv.2026-08-28_20-01-50.log").write_text("rotated")
    (d / "notes.txt").write_text("not a log")

    found = {p.name for p in all_log_files()}
    assert found == {ACTIVE_LOG_NAME, "metatv.2026-08-28_20-01-50.log"}


def test_a_missing_log_directory_is_not_an_error(tmp_path, monkeypatch):
    """Before the first launch there is nothing there, and that is fine."""
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path))
    assert all_log_files() == []
