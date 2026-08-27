"""A blind ``except Exception`` may not swallow the failure without a word.

The external audit's sharpest runtime finding was 175 blind excepts. Read one at
a time that number is misleading: 134 of them log at some level, and a catch-all
at a worker-thread or Qt-slot boundary that reports what it caught is a
legitimate thing to write — narrowing those wholesale would be churn with real
risk and no defect behind it.

The 39 that reported NOTHING are the finding. Two ways they went wrong:

* The intent was narrow and the catch was not. ``ALTER TABLE ... ADD COLUMN``
  wrapped in ``except Exception: pass  # column already exists`` also swallows
  "database is locked", a full disk, and a malformed statement — every one of
  which then looks exactly like "already migrated".
* The failure mattered and nobody hears about it. ``main_window`` saved the
  splitter layout inside a blind handler, so a failing ``config.save()`` meant
  the layout silently stopped persisting, with nothing anywhere to say so.

THIS GUARD, NOT ruff's BLE001. BLE001 flags all 193 including the 134 that
already report, so switching it on means either 193 edits or an ignore that
teaches nothing. This asks the question the project actually cares about — *does
this handler tell anyone?* — and it accepts an explicit written reason for the
cases where silence is genuinely right.

To silence a handler deliberately, put ``# silent:`` and a reason in it::

    except Exception:  # silent: probe returns an ERROR result, which IS the report
        return ProbeResult(...)

An AST walk, so the word "except" in a comment or a docstring cannot trip it.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "metatv"

# Anything that makes the failure visible to a human or to the caller.
_REPORTING_ATTRS = frozenset({"exception", "error", "warning", "warn", "critical"})
_LOGGER_NAMES = frozenset({"logger", "logging", "log", "_logger"})

_ALLOW_MARKER = "# silent:"


def _is_blind(handler: ast.ExceptHandler) -> bool:
    """True for ``except:``, ``except Exception:`` and ``except BaseException:``."""
    node = handler.type
    if node is None:
        return True
    candidates = list(node.elts) if isinstance(node, ast.Tuple) else [node]
    return any(
        isinstance(n, ast.Name) and n.id in ("Exception", "BaseException")
        for n in candidates
    )


def _reports(handler: ast.ExceptHandler) -> bool:
    """True when the handler does anything with the failure.

    Logging and re-raising are the obvious forms. The third — *the handler
    references the bound exception* — matters as much and is easy to miss:
    ``provider_probe`` returns ``ProbeResult(..., ProbeStatus.ERROR, str(e))``
    and the enrichment queue stores ``reason = f"{type(exc).__name__}: {exc}"``.
    Neither writes a log line, and both hand the failure onward intact. A guard
    that called those silent would be pushing correct code toward a marker,
    which is how a rule stops meaning anything.

    Silence is the absence of all three: nothing logged, nothing raised, and the
    exception itself never looked at.
    """
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if handler.name and isinstance(node, ast.Name) and node.id == handler.name:
            return True
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in _LOGGER_NAMES:
                return True
            if func.attr in _REPORTING_ATTRS:
                return True
    return False


def _has_allow_marker(handler: ast.ExceptHandler, lines: list[str]) -> bool:
    """True when the handler carries an explicit ``# silent: <reason>``."""
    start = handler.lineno - 1
    end = max((n.end_lineno or n.lineno) for n in handler.body)
    return any(_ALLOW_MARKER in line for line in lines[start:end])


def _silent_handlers(path: pathlib.Path) -> list[int]:
    src = path.read_text()
    lines = src.splitlines()
    found = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_blind(node) or _reports(node):
            continue
        if _has_allow_marker(node, lines):
            continue
        found.append(node.lineno)
    return found


def test_no_blind_except_swallows_in_silence():
    """Every catch-all under metatv/ must report, re-raise, or say why not."""
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for lineno in _silent_handlers(path):
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}")

    assert not offenders, (
        f"{len(offenders)} blind `except` handler(s) discard the failure with no log, "
        "no re-raise and no stated reason:\n  "
        + "\n  ".join(offenders)
        + "\n\nNarrow the exception to what you actually expect, log what you caught, "
          f"or mark it `{_ALLOW_MARKER} <reason>` if silence is genuinely correct."
    )


def test_the_guard_can_see_a_silent_handler():
    """The detector must fail on a silent handler, or the test above proves nothing."""
    tree = ast.parse("try:\n    x()\nexcept Exception:\n    pass\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert _is_blind(handler)
    assert not _reports(handler)


def test_the_guard_accepts_a_handler_that_logs():
    """A catch-all that reports is fine — that is the whole distinction."""
    tree = ast.parse("try:\n    x()\nexcept Exception as e:\n    logger.warning(e)\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert _reports(handler)


def test_the_guard_accepts_a_handler_that_passes_the_error_on():
    """Handing the failure to the caller counts, even with no log line.

    This arm was missing at first, and it wrongly called five correct handlers
    silent — including one that returns a ProbeResult carrying the message.
    """
    tree = ast.parse(
        "try:\n    x()\nexcept Exception as e:\n    return Result(False, str(e))\n"
    )
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert _reports(handler)


def test_the_guard_still_catches_an_unused_exception_variable():
    """Binding `as e` and never using it is exactly as silent as `except Exception`."""
    tree = ast.parse("try:\n    x()\nexcept Exception as e:\n    return []\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert not _reports(handler)


def test_the_guard_accepts_a_narrowed_handler():
    """Naming the expected error is the preferred fix, not the marker."""
    tree = ast.parse("try:\n    x()\nexcept (ValueError, TypeError):\n    pass\n")
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert not _is_blind(handler)


def test_the_marker_is_read_from_the_handler_only():
    """A `# silent:` elsewhere in the file must not excuse an unrelated handler."""
    src = (
        "# silent: this comment is at module level\n"
        "try:\n    x()\nexcept Exception:\n    pass\n"
    )
    tree = ast.parse(src)
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler))
    assert not _has_allow_marker(handler, src.splitlines())
