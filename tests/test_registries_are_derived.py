"""Registries someone has to remember to update — asserted against their source.

CLAUDE.md's own lesson: *an enumeration never sees what nobody remembered to
add*. Each test below pairs a hand-listed registry with the thing it is supposed
to track, so the list cannot silently fall behind. None of them replaces the
list with a derivation — in every case ordering or extra data makes the list
worth keeping — they just make forgetting it a red test instead of a silent gap.
"""

import ast
import pathlib

import pytest


def test_every_switcher_chip_has_a_deep_link_target():
    """A ``test_steps`` entry using ``view:sports`` must actually navigate.

    ``_NAV_VIEW_TARGETS`` calls itself "single source of truth" but is a second
    hand-listed dict beside ``NAV_CHIP_SPECS``, which builds the visible nav
    bar. Sports and Events were added to the bar and never to the dict, so a
    "Go ▸" button for either rendered and silently did nothing — and the
    existing test for unknown targets asserts that doing nothing is CORRECT,
    so the suite could not tell "Sports has no deep link" from "garbage string
    has no deep link".

    ``search`` is excluded because it is the default list view rather than a
    view of its own.
    """
    from metatv.gui.app_header import NAV_CHIP_SPECS
    from metatv.gui.explore_view import EXPLORE_SOURCES
    from metatv.gui.main_window_nav import _NAV_VIEW_TARGETS

    roles = {spec[2] for spec in NAV_CHIP_SPECS} - {"search"}
    missing = [r for r in sorted(roles)
               if r not in _NAV_VIEW_TARGETS and r not in EXPLORE_SOURCES]
    assert not missing, (
        f"nav chips with no deep-link target: {missing} — a What's New step "
        f"using view:{missing[0]} would render a dead button")


def test_every_deep_link_target_names_a_real_method():
    """A target pointing at a method that does not exist fails just as silently."""
    from metatv.gui.main_window import MainWindow
    from metatv.gui.main_window_nav import _NAV_VIEW_TARGETS

    for name, (method, _chip) in sorted(_NAV_VIEW_TARGETS.items()):
        assert hasattr(MainWindow, method), (
            f"deep-link target {name!r} names {method}(), which MainWindow "
            f"does not define")


def test_every_migration_task_is_registered():
    """An unregistered migration never runs, never errors, and never logs.

    ``needs_run`` is only consulted for a REGISTERED task, so a migration file
    added without its ``register()`` call silently never completes its backfill
    — for every user, forever, with no symptom that points back here. Order
    matters between these tasks (reparse before content-key backfill, tmdb-id
    before sibling propagation), so this is a coverage check rather than an
    attempt to auto-discover them.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    mig_dir = root / "metatv" / "core" / "migrations"

    defined: set[str] = set()
    for path in sorted(mig_dir.glob("*.py")):
        if path.name in {"__init__.py", "base.py"} or path.name[0].isdigit():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Task"):
                defined.add(node.name)

    registered = set()
    main_src = (root / "metatv" / "gui" / "main_window.py").read_text()
    for node in ast.walk(ast.parse(main_src)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "register"):
            for arg in node.args:
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                    registered.add(arg.func.id)

    assert defined, "no migration tasks found — the AST walk broke, not the app"
    missing = sorted(defined - registered)
    assert not missing, (
        f"migration task(s) defined but never registered: {missing}. An "
        f"unregistered migration silently never runs.")


@pytest.mark.parametrize("entry_path", sorted(
    (pathlib.Path(__file__).resolve().parent.parent
     / "metatv" / "whats_new" / "entries").glob("[0-9]*.py")))
def test_whats_new_step_targets_resolve(entry_path):
    """A QA step's ``view:`` target must be one the app can navigate to.

    The deep-link gap above shipped because nothing checked this end of it
    either — the button is only exercised when a human clicks it.

    A target in ``_RETIRED_NAV_VIEW_TARGETS`` also resolves: What's New
    entries are an append-only historical record (CLAUDE.md — "never edit
    the shared list"), so a step written while the Sports/Events views still
    existed keeps saying ``view:sports``/``view:events`` forever. navigate_to
    itself resolves a retired name (to the current replacement target), so
    checking that registry here is checking the SAME thing navigate_to
    actually does, not a narrower stand-in for it.
    """
    from metatv.gui.explore_view import EXPLORE_SOURCES
    from metatv.gui.main_window_nav import _NAV_VIEW_TARGETS, _RETIRED_NAV_VIEW_TARGETS

    for node in ast.walk(ast.parse(entry_path.read_text())):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if not node.value.startswith("view:"):
            continue
        target = node.value.split(":", 1)[1]
        assert (target in _NAV_VIEW_TARGETS or target in EXPLORE_SOURCES
                or target in _RETIRED_NAV_VIEW_TARGETS), (
            f"{entry_path.name} has step target {node.value!r}, which "
            f"navigate_to cannot resolve")
