"""Every channel-shaped context menu is built by the channel_menu.py registry.

MENU-1 killed nine hand-rolled ``QMenu``s that offered a different verb set per
surface for the same row (a mini "show N versions separately" menu duplicated
across Preferences/sidebar Recommended, twin monitored-series menus in the
Watch Alerts sidebar and Watch Queue, a full per-version menu in the details
pane). This is the guard that keeps a tenth one from growing back.

AST-based (like ``test_url_cycling_records_outcome.py`` and the theme
``setStyleSheet`` drift guard), never a text regex — a regex only knows one
shape and real sites have sailed past that kind of guard before (CLAUDE.md,
"Styling a widget"). Every ``QMenu(`` CONSTRUCTOR call outside
``channel_menu.py`` itself must be listed in the shrink-only
``tests/channel_menu_allowlist.json`` with a one-line reason — a section
header, a config-only aggregate a row doesn't back with a ChannelDB id, a
prefix/category axis, a filter dropdown, or a picker for something other than
a channel row. Everything else must come from ``build_channel_menu``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GUI_ROOT = _REPO_ROOT / "metatv" / "gui"
_ALLOWLIST_PATH = Path(__file__).resolve().parent / "channel_menu_allowlist.json"
_EXEMPT_FILE = _GUI_ROOT / "channel_menu.py"


class _QMenuVisitor(ast.NodeVisitor):
    """Collects one qualified name per ``QMenu(...)`` constructor call.

    The qualified name is the dotted chain of enclosing class/function scopes
    (e.g. ``WatchQueueSection._on_context_menu`` or, for a module-level
    function, just its own name) — precise enough to allowlist one function
    without silencing an entire file or class.
    """

    def __init__(self) -> None:
        self.sites: set[str] = set()
        self._scope: list[str] = []

    def _visit_scope(self, node: ast.AST) -> None:
        self._scope.append(node.name)  # type: ignore[attr-defined]
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        if name == "QMenu" and self._scope:
            self.sites.add(".".join(self._scope))
        self.generic_visit(node)


def _qmenu_construction_sites() -> dict[str, set[str]]:
    """Map ``relative/path.py`` -> set of qualified names constructing QMenu.

    Scans every ``*.py`` under ``metatv/gui/`` except ``channel_menu.py``
    itself (the registry's OWN composer is exempt — it is the one legitimate
    ``QMenu(`` in the tree).
    """
    found: dict[str, set[str]] = {}
    for path in sorted(_GUI_ROOT.rglob("*.py")):
        if path == _EXEMPT_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _QMenuVisitor()
        visitor.visit(tree)
        if visitor.sites:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            found[rel] = visitor.sites
    return found


def _flat_entries(sites: dict[str, set[str]]) -> set[str]:
    return {f"{rel}::{name}" for rel, names in sites.items() for name in names}


def _load_allowlist() -> dict[str, str]:
    data = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return {row["entry"]: row["reason"] for row in data["sites"]}


# ---------------------------------------------------------------------------
# Unit tests: the visitor against synthetic source, so these never depend on
# the real tree (mirrors test_code_health_ratchet.py's two-tier shape).
# ---------------------------------------------------------------------------


def _sites_in(source: str) -> set[str]:
    visitor = _QMenuVisitor()
    visitor.visit(ast.parse(source))
    return visitor.sites


def test_visitor_finds_a_method_level_construction() -> None:
    source = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        menu = QMenu(self)\n"
    )
    assert _sites_in(source) == {"Foo.bar"}


def test_visitor_finds_a_module_level_function_construction() -> None:
    source = (
        "def build(section):\n"
        "    menu = QMenu(section)\n"
        "    return menu\n"
    )
    assert _sites_in(source) == {"build"}


def test_visitor_ignores_calls_that_are_not_qmenu() -> None:
    source = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        act = QAction('x', self)\n"
    )
    assert _sites_in(source) == set()


def test_visitor_finds_a_nested_closure_construction() -> None:
    """A QMenu built inside an inner function is qualified through both scopes."""
    source = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        def _inner():\n"
        "            return QMenu(self)\n"
        "        return _inner\n"
    )
    assert _sites_in(source) == {"Foo.bar._inner"}


def test_visitor_handles_attribute_style_construction() -> None:
    """``widgets.QMenu(...)`` (attribute access) is caught the same as a bare name."""
    source = (
        "class Foo:\n"
        "    def bar(self):\n"
        "        menu = widgets.QMenu(self)\n"
    )
    assert _sites_in(source) == {"Foo.bar"}


# ---------------------------------------------------------------------------
# Integration tests: the real walk against the real, checked-in allowlist.
# ---------------------------------------------------------------------------


def test_every_qmenu_construction_is_registry_or_allowlisted() -> None:
    """Every hand-rolled ``QMenu(`` outside the registry is a known, reasoned exception.

    A failure here means a NEW hand-rolled channel-shaped menu was added
    instead of extending ``metatv/gui/channel_menu.py``'s ``ACTIONS`` +
    ``SURFACE_LAYOUTS`` — or a genuinely non-channel menu (section chrome, a
    filter dropdown, a config-only aggregate) that needs a one-line reason in
    ``tests/channel_menu_allowlist.json``.
    """
    found = _flat_entries(_qmenu_construction_sites())
    allowlist = _load_allowlist()
    unlisted = sorted(found - allowlist.keys())
    assert not unlisted, (
        f"{len(unlisted)} QMenu( construction site(s) outside channel_menu.py "
        "are not in tests/channel_menu_allowlist.json:\n  " + "\n  ".join(unlisted)
    )


def test_the_allowlist_only_shrinks() -> None:
    """An allowlisted site that migrated onto the registry must be REMOVED.

    Mirrors ``test_stored_fields_have_readers.py``'s
    ``test_the_allowlist_only_shrinks`` — a site left on the list after it
    stops constructing a raw ``QMenu`` rots the guard the same way a stale
    contrast/dead-field exemption does.
    """
    found = _flat_entries(_qmenu_construction_sites())
    allowlist = _load_allowlist()
    stale = sorted(entry for entry in allowlist if entry not in found)
    assert not stale, (
        "these are allowlisted but no longer construct a raw QMenu( — remove "
        "them from tests/channel_menu_allowlist.json:\n  " + "\n  ".join(stale)
    )


def test_the_walk_actually_reaches_the_gui_tree() -> None:
    """A visitor that silently matched nothing would read as a clean codebase.

    Pins that the walk still finds a non-trivial population of pre-existing,
    legitimately-exempt sites (section chrome, filter dropdowns, …) — if an
    AST/path change stops the walk from matching, this fails instead of the
    other two tests reporting zero problems forever.
    """
    found = _flat_entries(_qmenu_construction_sites())
    assert len(found) >= 10, (
        f"expected a substantial population of QMenu( sites, found {len(found)}: {found}"
    )


def test_channel_menu_py_itself_is_not_in_the_allowlist() -> None:
    """The registry's own composer is exempt by construction, not by listing."""
    allowlist = _load_allowlist()
    assert not any(entry.startswith("metatv/gui/channel_menu.py::") for entry in allowlist)
