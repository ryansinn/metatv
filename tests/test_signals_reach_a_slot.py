"""Every custom Qt signal that is CONNECTED must have something that emits it.

Two independent audits (2026-09-07) found the Recordings sidebar section with
no context menu — ``watchRequested``/``cancelRequested``/``extendRequested``
were connected in ``main_window.py`` and never fired by anything, because
nothing ever called ``.emit()`` on them. The same shape turned up ten more
times across the sidebar: four ``DownloadsSection`` signals, four
``WatchAlertsSection`` signals, ``FilterPanel.settings_requested`` and
``ProviderEditor.provider_deleted`` — a connection that LOOKS live (it is
right there next to the real ones) but is wiring to nothing, because the
thing on the other end never happens.

This is a chokepoint problem, not a one-off: a signal definition, its
``.connect()`` and its ``.emit()`` can live in three different files, so no
single-file review catches a signal that quietly stopped being fired (or
never started). An AST sweep over the whole ``metatv/gui`` tree is the only
thing that sees all three sites at once.

What counts as an emit path
----------------------------
Four shapes, because a signal can leave a live wire in more than one way:

1. ``sig.emit(...)`` — the ordinary call.
2. ``sig.emit`` handed over as a bound callable (e.g. a notification action's
   ``("Watch", section.watchRequested.emit)``) — never itself called at the
   read site, so it must be recognised without seeing a ``Call`` wrapping it.
3. The bare signal object passed straight into ANOTHER ``.connect(...)`` —
   signal-to-signal forwarding, so firing the first one re-fires this one.
4. The bare signal object passed as an argument to any other function — the
   ``_emit_or_abort(self.mySignal, ...)`` idiom, where a shared helper does
   the actual ``.emit()`` call the AST would otherwise never see here.

Matching is by ATTRIBUTE NAME, not by inferring which class instance a given
``.connect()``/``.emit()`` call site holds — real type inference is out of
reach for a plain AST walk, and every signal name in this codebase is
distinctive enough (``retryClearAllRequested``, not ``clicked``) that a
same-name collision between a live signal and a dead one is not a real risk
in practice. If one ever legitimately survives a connected-but-never-emitted
state (a signal wired for a feature not built yet, say), name it in
``_KNOWN_CONNECTED_NEVER_EMITTED`` with a one-line reason — that set may only
grow by a deliberate, reasoned entry, never as a way to silence a genuine miss.
"""

from __future__ import annotations

import ast
import pathlib

_GUI = pathlib.Path("metatv/gui")

#: Shrink-only allowlist: a signal that is connected somewhere but has no
#: emit path ANYWHERE in metatv/gui, and is legitimately meant to stay that
#: way. Seeded empty — every entry here must carry the reason.
_KNOWN_CONNECTED_NEVER_EMITTED: set[str] = set()


class _SignalDefVisitor(ast.NodeVisitor):
    """Collects every ``name = pyqtSignal(...)`` at class scope.

    Only direct class-body assignments count (every real signal in this
    codebase is written that way — never inside an ``if``/``for`` at class
    scope), so this deliberately does not use a general ``ast.walk``.
    """

    def __init__(self) -> None:
        self._class_stack: list[str] = []
        self.defs: list[tuple[str, str, int]] = []  # (qualname, signal_name, lineno)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        for stmt in node.body:
            self._check_assign(stmt)
        self.generic_visit(node)
        self._class_stack.pop()

    def _check_assign(self, stmt: ast.stmt) -> None:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        if not (isinstance(target, ast.Name) and isinstance(value, ast.Call)):
            return
        func = value.func
        is_signal = (
            (isinstance(func, ast.Name) and func.id == "pyqtSignal")
            or (isinstance(func, ast.Attribute) and func.attr == "pyqtSignal")
        )
        if is_signal:
            qualname = ".".join(self._class_stack) if self._class_stack else "<module>"
            self.defs.append((qualname, target.id, stmt.lineno))


def _parsed_gui_files(root: pathlib.Path) -> list[tuple[pathlib.Path, ast.Module]]:
    out = []
    for path in sorted(root.rglob("*.py")):
        out.append((path, ast.parse(path.read_text(), filename=str(path))))
    return out


def _collect(root: pathlib.Path = _GUI) -> tuple[
        dict[str, list[tuple[str, str, int]]], set[str], set[str]]:
    """(defs_by_name, connected_names, emitted_names) over every file in *root*."""
    trees = _parsed_gui_files(root)

    defs_by_name: dict[str, list[tuple[str, str, int]]] = {}
    for path, tree in trees:
        visitor = _SignalDefVisitor()
        visitor.visit(tree)
        for qualname, name, lineno in visitor.defs:
            defs_by_name.setdefault(name, []).append((qualname, str(path), lineno))
    known = set(defs_by_name)

    connected_names: set[str] = set()
    emitted_names: set[str] = set()
    for _path, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # sig.connect(slot) — the receiver of .connect() IS the signal.
                # Gated on an Attribute func (a plain Name func, e.g. a bare
                # module-level connect()-like helper, is not this shape).
                if (isinstance(node.func, ast.Attribute) and node.func.attr == "connect"
                        and isinstance(node.func.value, ast.Attribute)
                        and node.func.value.attr in known):
                    connected_names.add(node.func.value.attr)
                # The bare signal handed to ANY call — connect() forwarding
                # (host.outerClicked.connect(section.thingRequested)) or a
                # shared _emit_or_abort(sig, ...)-shaped helper. Applies
                # whatever the called function's own shape is — never gated
                # on node.func being an Attribute, or a bare-name helper like
                # _emit_or_abort(...) is invisible here. Never sig.emit itself,
                # that is handled by the Attribute branch below.
                for arg in (*node.args, *(kw.value for kw in node.keywords)):
                    if (isinstance(arg, ast.Attribute) and arg.attr != "emit"
                            and arg.attr in known):
                        emitted_names.add(arg.attr)
            # sig.emit(...) AND sig.emit handed over uncalled both show up as
            # this same Attribute node — whether a Call wraps it is irrelevant.
            if (isinstance(node, ast.Attribute) and node.attr == "emit"
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr in known):
                emitted_names.add(node.value.attr)

    return defs_by_name, connected_names, emitted_names


def _offenders(root: pathlib.Path = _GUI) -> list[str]:
    defs_by_name, connected_names, emitted_names = _collect(root)
    out = []
    for name in sorted(connected_names):
        if name in emitted_names or name in _KNOWN_CONNECTED_NEVER_EMITTED:
            continue
        for qualname, path, lineno in defs_by_name.get(name, ()):
            out.append(f"{qualname}.{name} ({path}:{lineno})")
    return sorted(out)


def test_every_connected_signal_has_an_emit_path() -> None:
    """FAILS against the pre-fix tree, naming all eleven + the two siblings.

    (RecordingsSection.watchRequested/cancelRequested/extendRequested,
    DownloadsSection.revealItemRequested/pauseRequested/resumeRequested/
    cancelRequested, WatchAlertsSection.retryRemoveRequested/
    retryClearAllRequested/vodAlertClicked/vodRuleViewMatchesRequested,
    FilterPanel.settings_requested, ProviderEditor.provider_deleted.)
    """
    offenders = _offenders()
    assert not offenders, (
        "these signals are connected somewhere but nothing ever emits them — "
        "a wire that LOOKS live and never fires:\n  " + "\n  ".join(offenders)
    )


def test_the_sweep_actually_finds_signal_definitions() -> None:
    """A collector that finds nothing reads as a clean codebase forever."""
    defs_by_name, _connected, _emitted = _collect()
    total = sum(len(v) for v in defs_by_name.values())
    assert total >= 100, (
        f"only found {total} pyqtSignal definitions under {_GUI} — "
        "the AST walk is probably broken, not the codebase suddenly thin"
    )


def _write_probe(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    gui = tmp_path / "metatv" / "gui"
    gui.mkdir(parents=True)
    probe = gui / "probe.py"
    probe.write_text(source)
    return tmp_path / "metatv" / "gui"


class TestGuardMechanism:
    """Proves the collector actually distinguishes live wiring from dead —
    the guard must be able to fail, not just currently pass."""

    def test_catches_a_connected_signal_with_no_emit_anywhere(self, tmp_path):
        root = _write_probe(tmp_path, """
from PyQt6.QtCore import pyqtSignal

class Section:
    thingRequested = pyqtSignal(str)

def wire(section, host):
    section.thingRequested.connect(host._on_thing)
""")
        offenders = _offenders(root)
        assert any("thingRequested" in o for o in offenders), offenders

    def test_does_not_flag_a_plain_emit_call(self, tmp_path):
        root = _write_probe(tmp_path, """
from PyQt6.QtCore import pyqtSignal

class Section:
    thingRequested = pyqtSignal(str)

    def _fire(self):
        self.thingRequested.emit("x")

def wire(section, host):
    section.thingRequested.connect(host._on_thing)
""")
        assert _offenders(root) == []

    def test_does_not_flag_a_bound_emit_passed_as_a_callable(self, tmp_path):
        root = _write_probe(tmp_path, """
from PyQt6.QtCore import pyqtSignal

class Section:
    thingRequested = pyqtSignal(str)

def wire(section, host):
    section.thingRequested.connect(host._on_thing)

def show_notice(section):
    return [("Do it", section.thingRequested.emit)]
""")
        assert _offenders(root) == []

    def test_does_not_flag_signal_to_signal_forwarding(self, tmp_path):
        root = _write_probe(tmp_path, """
from PyQt6.QtCore import pyqtSignal

class Section:
    thingRequested = pyqtSignal(str)

class Host:
    outerClicked = pyqtSignal(str)

    def _fire(self):
        self.outerClicked.emit("y")

def wire(section, host):
    section.thingRequested.connect(host._on_thing)
    host.outerClicked.connect(section.thingRequested)
""")
        assert _offenders(root) == []

    def test_does_not_flag_the_emit_or_abort_idiom(self, tmp_path):
        root = _write_probe(tmp_path, """
from PyQt6.QtCore import pyqtSignal

def _emit_or_abort(signal, *args):
    signal.emit(*args)

class Section:
    thingRequested = pyqtSignal(str)

def wire(section, host):
    section.thingRequested.connect(host._on_thing)

def fire(section):
    _emit_or_abort(section.thingRequested, "x")
""")
        assert _offenders(root) == []

    def test_an_unconnected_signal_is_never_flagged(self, tmp_path):
        """Emitted-but-unconnected (sizeChanged's shape) is a different bug
        this guard does not police — connect-with-nothing-firing is the one
        that reads as live wiring and is not."""
        root = _write_probe(tmp_path, """
from PyQt6.QtCore import pyqtSignal

class Section:
    neverConnected = pyqtSignal()

    def _fire(self):
        self.neverConnected.emit()
""")
        assert _offenders(root) == []
