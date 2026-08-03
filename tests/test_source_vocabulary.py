"""Drift guard: "Source" is the user-facing term, "Provider" is the code term.

Owner rule (v0.26.0, task #18): a person using MetaTV adds a *Source*. The
codebase keeps *Provider* everywhere it is a code identity — ``ProviderDB``,
``provider_id``, ``ProviderPlugin``, the ``providers/`` package — because
renaming those buys nothing and churns every module. The split is deliberate,
so the guard has to distinguish the two rather than banning the word outright.

What this asserts: no string that a user can READ contains "provider". Logger
calls and raised exceptions are exempt — those are read by developers, and their
subject genuinely is the provider record.

This is the same shape as the ``PointingHandCursor`` drift guard: the rule only
holds if something fails when it is broken.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest


#: Call targets whose string arguments reach a human using the app.
_USER_FACING_CALLS = {
    "setText", "setToolTip", "setPlaceholderText", "setWindowTitle", "setTitle",
    "showMessage", "setStatusTip", "addAction", "setItemText", "setLabelText",
    "information", "warning", "critical", "question", "setInformativeText",
}

#: Calls whose strings are for developers, not users.
_DEV_FACING = {"debug", "info", "warning", "error", "exception", "critical", "success"}


def _gui_files() -> list[pathlib.Path]:
    return sorted(pathlib.Path("metatv/gui").rglob("*.py"))


def _string_parts(node: ast.AST) -> list[tuple[int, str]]:
    """Every literal string inside *node*, including f-string fragments."""
    out: list[tuple[int, str]] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append((getattr(sub, "lineno", 0), sub.value))
    return out


def _is_logger_call(node: ast.Call) -> bool:
    """True for ``logger.info(...)`` / ``logging.warning(...)`` style calls."""
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _DEV_FACING:
        value = func.value
        if isinstance(value, ast.Name) and value.id in {"logger", "logging", "log"}:
            return True
    return False


def _collect_offenders() -> list[str]:
    offenders: list[str] = []
    for path in _gui_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a parse failure is its own bug
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_logger_call(node):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in _USER_FACING_CALLS:
                continue
            for lineno, text in _string_parts(node):
                if re.search(r"\bprovider\b", text, re.IGNORECASE):
                    offenders.append(f"{path}:{lineno}: {text!r}")
    return offenders


def test_no_user_facing_provider_wording():
    """A user reads "Source"; "Provider" is reserved for code identities."""
    offenders = _collect_offenders()
    assert not offenders, (
        "User-facing text says 'provider' — the user-facing term is 'Source' "
        "(Provider stays the CODE term: ProviderDB, provider_id, "
        "ProviderPlugin). Offending strings:\n  " + "\n  ".join(offenders)
    )


def test_guard_actually_detects_a_violation(tmp_path, monkeypatch):
    """The guard above is worthless if it cannot fail.

    Plants a real violation in a throwaway GUI file and asserts the collector
    reports it — otherwise a broken matcher would read as a clean codebase
    forever, which is exactly how a "green" drift guard hides drift.
    """
    fake_gui = tmp_path / "gui"
    fake_gui.mkdir()
    (fake_gui / "bad_widget.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def build(btn):\n"
        "    btn.setToolTip('Edit provider settings')\n"
        "    logger.info('Provider %s saved', 1)\n"
    )
    monkeypatch.setattr(
        __name__ + "._gui_files", lambda: sorted(fake_gui.rglob("*.py"))
    )

    offenders = _collect_offenders()

    assert len(offenders) == 1, f"expected exactly the setToolTip hit, got {offenders}"
    assert "setToolTip" not in offenders[0]  # reported as the string, not the call
    assert "Edit provider settings" in offenders[0]
    assert "saved" not in offenders[0], "logger call must be exempt, not reported"


@pytest.mark.parametrize("code_term", ["provider_id", "ProviderDB", "ProviderPlugin"])
def test_code_terms_are_untouched(code_term):
    """The rename must not have leaked into code identities."""
    found = any(
        code_term in path.read_text()
        for path in pathlib.Path("metatv").rglob("*.py")
    )
    assert found, (
        f"{code_term} disappeared from the codebase — the user-facing rename "
        f"must not touch code identities"
    )
