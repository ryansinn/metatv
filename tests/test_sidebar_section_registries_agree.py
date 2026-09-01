"""Adding a sidebar section means touching four places. This is the fourth.

Owner, 2026-09-01: *"always remember to grep before writing new code."* Doing
that for Downloads and Recordings turned up four separate lists that must all
learn a new section id:

1. ``Config.sidebar_sections`` / ``sidebar_visible_sections`` — the defaults.
2. ``Config._inject_new_sections`` — so configs that PREDATE the section get
   it, which is every existing install.
3. ``settings_dialog._SIDEBAR_SECTION_LABELS`` — the reorder/show-hide UI.
   (``_ALL_SIDEBAR_SECTIONS`` derives from it, so it is not a fifth.)
4. ``MainWindow.create_section`` — the factory that actually builds it.

Miss #2 and the section is invisible to everyone who already uses the app,
while being perfectly visible to a fresh install and to every test — which is
the shape of bug that survives review. Miss #4 and the sidebar tries to build
a section that does not exist.

Four hand-maintained lists is exactly the enumeration this codebase keeps
paying for, so this test IS the fifth place: it fails when they disagree,
rather than waiting for someone to notice one of them is short.
"""
from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Sections that shipped in the first release. No config has ever lacked
#: them, so _inject_new_sections has nothing to add them to. Anything NOT
#: in here was added later and must be injected, or existing installs
#: never see it. Do not add to this list to silence the test — that is
#: the bug it exists to catch.
_ORIGINAL_SECTIONS = {"alerts", "favorites", "history"}


def _factory_ids() -> set[str]:
    """Section ids ``MainWindow.create_section`` can actually build.

    Read from the AST rather than by calling it — building a section needs a
    real window — so this stays a structural check that cannot be defeated by
    an import-time failure elsewhere.
    """
    tree = ast.parse((_ROOT / "metatv/gui/main_window.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "create_section")
    ids: set[str] = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Name)
                and node.left.id == "section_id"
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Constant)):
            ids.add(node.comparators[0].value)
    return ids


def _injected_ids() -> set[str]:
    """Ids ``_inject_new_sections`` adds to configs that predate them."""
    tree = ast.parse((_ROOT / "metatv/core/config.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_inject_new_sections")
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "new_sections"
                        for t in node.targets)
                and isinstance(node.value, ast.List)):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return set()


def test_every_labelled_section_can_be_built():
    """A section offered in Settings must be one the factory knows how to make."""
    from metatv.gui.settings_dialog import _SIDEBAR_SECTION_LABELS

    labelled = set(_SIDEBAR_SECTION_LABELS)
    missing = labelled - _factory_ids()
    assert not missing, (
        f"Settings offers {sorted(missing)} but MainWindow.create_section cannot "
        "build them — the sidebar would silently drop the section")


def test_every_default_section_is_labelled():
    """A section shipped on by default must be reorderable and hideable."""
    from metatv.core.config import Config
    from metatv.gui.settings_dialog import _SIDEBAR_SECTION_LABELS

    defaults = set(Config.model_fields["sidebar_sections"].default_factory())
    missing = defaults - set(_SIDEBAR_SECTION_LABELS)
    assert not missing, (
        f"{sorted(missing)} ships in the sidebar but has no label, so it cannot "
        "be reordered, hidden or shown in Settings")


def test_the_two_default_lists_agree():
    """Order and visibility must ship with the same members."""
    from metatv.core.config import Config

    order = Config.model_fields["sidebar_sections"].default_factory()
    visible = Config.model_fields["sidebar_visible_sections"].default_factory()
    assert set(order) == set(visible), (
        "a section present in one default list and not the other is either "
        "invisible or unorderable out of the box")


def test_sections_added_since_the_first_release_are_injected():
    """Existing configs must LEARN a new section, not just fresh installs.

    The bug this prevents is quiet: a new section works perfectly for every
    test and every new install, and is missing for everyone who already has a
    config — which is everyone who would notice.

    ``_ORIGINAL_SECTIONS`` are the ones every config has ever had — there was
    never a version without them, so there is nothing to inject them INTO.
    Everything added since needs a migration entry, and the point of naming the
    originals explicitly is that the list cannot quietly grow: a new section
    added to it would be exempting itself from the check.
    """
    from metatv.core.config import Config

    defaults = set(Config.model_fields["sidebar_sections"].default_factory())
    injected = _injected_ids()
    never_injected = defaults - injected - _ORIGINAL_SECTIONS
    assert not never_injected, (
        f"{sorted(never_injected)} ships by default but _inject_new_sections "
        "does not add it, so an existing config will never show it")


def test_downloads_and_recordings_are_registered_everywhere():
    """The two this slice adds, asserted by name in all four places."""
    from metatv.core.config import Config
    from metatv.gui.settings_dialog import _SIDEBAR_SECTION_LABELS

    order = set(Config.model_fields["sidebar_sections"].default_factory())
    visible = set(Config.model_fields["sidebar_visible_sections"].default_factory())
    factory, injected = _factory_ids(), _injected_ids()

    for sid in ("downloads", "recordings"):
        assert sid in order, f"{sid} missing from sidebar_sections"
        assert sid in visible, f"{sid} missing from sidebar_visible_sections"
        assert sid in injected, f"{sid} missing from _inject_new_sections"
        assert sid in _SIDEBAR_SECTION_LABELS, f"{sid} missing from the Settings labels"
        assert sid in factory, f"{sid} missing from create_section"
