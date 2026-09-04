"""GUARD-4: every stored field needs a reader OUTSIDE its own plumbing.

The problem this closes
------------------------
Four stored fields shipped with a working-looking editor and ZERO readers:
``ProviderDB.refresh_schedule`` (a Settings combo, loaded and saved by two
dialogs, read by nothing for months — users who picked "Daily" silently got
nothing, fixed in #710), the ``filters`` table (presets, 0 rows ever),
``config.vod_watch_alerts`` vs ``alert_patterns`` (a second store nobody
reads), and a sports ORM query with no callers. Nine prior audits missed all
of this because every one of them interrogated code that RUNS — a dialog that
reads a field, writes it back, and whose tests pass looks identical to a
production consumer to any lens that doesn't ask "who reads this OUTSIDE the
plumbing?". This guard is that question, mechanized, so it runs on every PR
instead of once by hand.

Two tiers, same shape as ``test_code_health_ratchet.py`` /
``test_widget_composed_contrast.py``:

1. Unit tests against ``is_plumbing``/``candidate_names_in_file`` with
   synthetic input — these never depend on the real tree.
2. Integration tests that run the real census against the real, checked-in
   tree and allowlist — what makes the guard live rather than merely
   plausible.

How the census works
---------------------
**Stored fields** (the population) are derived, never hand-listed: every
field of the pydantic ``Config`` model (``Config.model_fields``) plus every
column of ``ProviderDB``, ``ChannelDB``, ``AlertPatternDB`` and
``RecordingDB`` (``Model.__table__.columns`` — the WL-1/WL-2 and REC families
are the most recently-shipped state most likely to be half-wired). A tiny,
in-code exclusion list drops names that are Python/SQL-universal and would
match everywhere (``id``, ``name``, ``created_at``, ``updated_at``) — see
``UNIVERSAL_EXCLUDED_NAMES``.

**A reader** is, in any ``metatv/`` module that is NOT plumbing: an
``ast.Attribute`` whose ``.attr`` equals the field name (any receiver — recall
over precision, so a false negative costs nothing and a false positive just
means a field earns its allowlist entry for the wrong reason), or a string
``ast.Constant`` equal to the field name that is an argument of
``getattr``/``setattr``/``hasattr`` or a subscript key. This is deliberately
narrow on the string-constant path: a name built at runtime (an f-string, a
loop variable pulled from a table of field names, a bespoke ``_dial(name)``
wrapper around ``getattr``) is invisible to it. That is a known, accepted
blind spot — several such cases were found and are annotated in the seed
allowlist rather than silently "fixed" by widening the rule, because widening
it to "any string constant anywhere" would swallow docstrings, comments-as-
strings and unrelated literals and defeat the census entirely.

**Plumbing** is the editor<->store loop itself — reads there prove nothing,
because that is exactly the loop that closed on itself for ``refresh_schedule``
for months. See ``PLUMBING_FILES``/``PLUMBING_DIR_PREFIXES``/
``PLUMBING_GLOB_PATTERNS`` below; the per-file decisions (which repositories
and dialogs are/aren't plumbing) are recorded in the PR body that introduced
this guard, not here — grep for "plumbing" in that PR's description for the
reasoning on each borderline module (``core/repositories/provider.py`` in
particular: it has a ``to_model()`` mapper but is NOT on the plumbing list,
because it is a full repository with real business logic, and because keeping
it off the list is what lets ``refresh_schedule`` prove the guard actually
works — see ``test_refresh_schedule_is_wired_not_allowlisted`` below).

On a violation: either the field is genuinely unwired (wire it up, in its own
slice — never in this guard's PR) or it is a census blind spot (add it to
``tests/unwired_stored_fields_allowlist.json`` with a one-line reason).
"""

from __future__ import annotations

import ast
import fnmatch
import functools
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
METATV_ROOT = REPO_ROOT / "metatv"
ALLOWLIST_PATH = Path(__file__).resolve().parent / "unwired_stored_fields_allowlist.json"

#: Names that are Python/SQL-universal and would match everywhere, proving
#: nothing about the specific field. Keep this list TINY — every name on it
#: is a name the guard cannot see through.
UNIVERSAL_EXCLUDED_NAMES = {"id", "name", "created_at", "updated_at"}

#: The editor<->store loop: a dialog/mapper that only loads and saves these
#: fields. A read found ONLY inside one of these proves nothing — it is the
#: same loop that left ``refresh_schedule`` unwired for months.
PLUMBING_FILES = {
    "metatv/core/config.py",
    "metatv/core/database.py",
    "metatv/core/profile_store.py",
    "metatv/core/repositories/dtos.py",
    "metatv/gui/provider_editor.py",
    "metatv/gui/provider_settings_dialog.py",
    "metatv/gui/global_filter_dialog.py",
    "metatv/gui/qa_checklist_window.py",
}
PLUMBING_DIR_PREFIXES = (
    "metatv/core/migrations/",
    "metatv/whats_new/",
)
PLUMBING_GLOB_PATTERNS = (
    "metatv/gui/settings_dialog*.py",
    "metatv/gui/settings_*_tab.py",
)

#: A stored field's reader must be found in at least this many distinct
#: modules across the whole census for the resolver to be trusted (see
#: ``test_the_census_actually_reaches_the_tree``); the population floor.
_MIN_FIELDS = 200
_MIN_READER_MODULES = 40


def is_plumbing(relpath: str) -> bool:
    """Whether *relpath* (posix, repo-root-relative) is plumbing.

    Checked against an exact-file set first (cheap, unambiguous), then a
    directory-prefix tuple (whole subtrees: migrations, What's New entries),
    then glob patterns (settings dialog tabs that don't exist yet but would
    match the family this guard already excludes).
    """
    if relpath in PLUMBING_FILES:
        return True
    if any(relpath.startswith(prefix) for prefix in PLUMBING_DIR_PREFIXES):
        return True
    return any(fnmatch.fnmatch(relpath, pat) for pat in PLUMBING_GLOB_PATTERNS)


def candidate_names_in_file(tree: ast.AST) -> set[str]:
    """Every name this file could be "reading" a stored field by.

    Two shapes, one walk: an ``ast.Attribute.attr`` (any receiver — recall
    over precision), or a string ``ast.Constant`` that is either an argument
    of ``getattr``/``setattr``/``hasattr`` or a subscript key.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                fname = func.attr
            elif isinstance(func, ast.Name):
                fname = func.id
            else:
                fname = None
            if fname in ("getattr", "setattr", "hasattr"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        names.add(arg.value)
        elif isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                names.add(sl.value)
    return names


def _source_files() -> list[Path]:
    return sorted(p for p in METATV_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


@functools.lru_cache(maxsize=None)
def stored_fields() -> tuple[tuple[str, str], ...]:
    """``(("Model.field", "field"), ...)`` — the census population.

    Importing ``metatv.core.config``/``metatv.core.database`` to enumerate
    fields is fine (CLAUDE.md scope for this guard) — the census itself never
    imports a GUI module; it only reads source text for the reader scan.
    """
    from metatv.core.config import Config
    from metatv.core.database import AlertPatternDB, ChannelDB, ProviderDB, RecordingDB

    out: list[tuple[str, str]] = []
    for field in Config.model_fields:
        if field in UNIVERSAL_EXCLUDED_NAMES:
            continue
        out.append((f"Config.{field}", field))
    for model in (ProviderDB, ChannelDB, AlertPatternDB, RecordingDB):
        for col in model.__table__.columns:
            if col.name in UNIVERSAL_EXCLUDED_NAMES:
                continue
            out.append((f"{model.__name__}.{col.name}", col.name))
    return tuple(out)


@functools.lru_cache(maxsize=None)
def reader_map() -> "dict[str, frozenset[str]]":
    """``bare field name -> {relpath, ...}`` for every non-plumbing reader hit.

    One AST parse and one walk per file (cached via this same
    ``lru_cache``-wrapped function, so every test in this module pays for the
    scan once, not once per test).
    """
    out: dict[str, set[str]] = {}
    for path in _source_files():
        relpath = path.relative_to(REPO_ROOT).as_posix()
        if is_plumbing(relpath):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - all tracked files parse
            continue
        for candidate in candidate_names_in_file(tree):
            out.setdefault(candidate, set()).add(relpath)
    return {k: frozenset(v) for k, v in out.items()}


def load_allowlist() -> set[str]:
    data = json.loads(ALLOWLIST_PATH.read_text())
    return set(data.get("fields", []))


# ---------------------------------------------------------------------------
# Unit tests: is_plumbing / candidate_names_in_file against synthetic input
# ---------------------------------------------------------------------------


def test_is_plumbing_matches_exact_files() -> None:
    assert is_plumbing("metatv/core/config.py")
    assert is_plumbing("metatv/core/database.py")
    assert not is_plumbing("metatv/core/repositories/provider.py")
    assert not is_plumbing("metatv/gui/settings_apply.py")


def test_is_plumbing_matches_directory_prefixes() -> None:
    assert is_plumbing("metatv/core/migrations/tag_backfill.py")
    assert is_plumbing("metatv/whats_new/entries/0001_x.py")
    assert not is_plumbing("metatv/core/migration_progress.py")  # prefix, not the dir


def test_is_plumbing_matches_settings_dialog_globs() -> None:
    assert is_plumbing("metatv/gui/settings_dialog.py")
    assert is_plumbing("metatv/gui/settings_dialog_tabs.py")
    assert is_plumbing("metatv/gui/settings_playback_tab.py")
    assert not is_plumbing("metatv/gui/settings_apply.py")
    assert not is_plumbing("metatv/gui/main_window.py")


def test_candidate_names_finds_plain_attribute_any_receiver() -> None:
    tree = ast.parse("x = some_row.refresh_schedule\ny = other.refresh_schedule")
    assert "refresh_schedule" in candidate_names_in_file(tree)


def test_candidate_names_finds_getattr_setattr_hasattr_string_args() -> None:
    tree = ast.parse(
        "getattr(cfg, 'font_size', None)\n"
        "setattr(cfg, 'chunk_size', 5)\n"
        "hasattr(cfg, 'theme')\n"
    )
    found = candidate_names_in_file(tree)
    assert {"font_size", "chunk_size", "theme"} <= found


def test_candidate_names_finds_subscript_string_keys() -> None:
    tree = ast.parse("d = {}\nv = d['vod_watch_alerts']")
    assert "vod_watch_alerts" in candidate_names_in_file(tree)


def test_candidate_names_does_not_match_a_dynamically_built_name() -> None:
    """The known, accepted blind spot: a runtime-built name is invisible.

    ``getattr(cfg, attr, [])`` where ``attr`` is a variable, not a literal —
    exactly the ``filter_known_*``/``discover_shelf_order`` pattern found live
    in the tree (see the seed allowlist notes). Pinned here so nobody
    "fixes" this test by widening the resolver in a way that reintroduces the
    docstring/comment false-positive flood the narrow rule exists to avoid.
    """
    tree = ast.parse("attr = 'font_size'\ngetattr(cfg, attr, None)")
    assert "font_size" not in candidate_names_in_file(tree)


def test_candidate_names_ignores_a_bare_string_constant() -> None:
    """A field name appearing in a docstring/comment-as-string is not a read."""
    tree = ast.parse("'refresh_schedule is not a read here'\nx = 'font_size'")
    found = candidate_names_in_file(tree)
    assert "refresh_schedule" not in found
    assert "font_size" not in found


# ---------------------------------------------------------------------------
# Integration tests: the real census against the real, checked-in tree
# ---------------------------------------------------------------------------


def test_every_stored_field_has_a_reader_or_is_allowlisted() -> None:
    """Every stored field has >=1 reader outside plumbing, or is allowlisted.

    A failure here means a NEW stored field was added with no real consumer —
    exactly the ``refresh_schedule`` shape. Either wire it up (a separate
    slice) or add it to ``tests/unwired_stored_fields_allowlist.json`` with a
    one-line reason.
    """
    fields = stored_fields()
    readers = reader_map()
    allowlist = load_allowlist()

    unwired = sorted(
        label for label, bare in fields
        if not readers.get(bare) and label not in allowlist
    )
    assert not unwired, (
        f"{len(unwired)} stored field(s) have no reader outside plumbing and "
        "are not in tests/unwired_stored_fields_allowlist.json:\n  "
        + "\n  ".join(unwired)
    )


def test_the_allowlist_only_shrinks() -> None:
    """An allowlisted field that now has a real reader must be REMOVED.

    Mirrors ``test_widget_composed_contrast.py``'s
    ``test_the_allowlist_only_shrinks`` — a field that starts passing and is
    left on the list rots the guard the same way a stale contrast exemption
    does.
    """
    fields = dict(stored_fields())
    readers = reader_map()
    allowlist = load_allowlist()

    now_wired = sorted(
        label for label in allowlist
        if label in fields and readers.get(fields[label])
    )
    assert not now_wired, (
        "these are allowlisted but now have a reader outside plumbing — "
        "remove them from tests/unwired_stored_fields_allowlist.json:\n  "
        + "\n  ".join(now_wired)
    )


def test_the_census_actually_reaches_the_tree() -> None:
    """A resolver that silently returns nothing would read as a clean codebase.

    Pins that the census still finds a substantial population and that reader
    hits are spread across a real slice of the tree, not just a couple of
    files — if a refactor changes how fields are declared or read and the
    resolver stops matching, this fails instead of reporting zero problems
    forever (same role as ``test_the_sweep_actually_reaches_widget_modules``).
    """
    fields = stored_fields()
    readers = reader_map()

    assert len(fields) >= _MIN_FIELDS, (
        f"only {len(fields)} stored fields found — the Config/ORM imports "
        "probably broke"
    )

    modules_touched: set[str] = set()
    for _label, bare in fields:
        modules_touched |= readers.get(bare, frozenset())
    assert len(modules_touched) >= _MIN_READER_MODULES, (
        f"readers found in only {len(modules_touched)} modules — the AST "
        "reader scan has probably stopped matching"
    )


def test_refresh_schedule_is_wired_not_allowlisted() -> None:
    """#710 wired ``ProviderDB.refresh_schedule`` — proof the guard works.

    This is the field GUARD-4's own worklog names as the motivating case: a
    Settings combo that was loaded and saved by two dialogs and read by
    nothing for months. It was wired in #710
    (``core/repositories/provider.py``'s ``get_active_providers_with_refresh_schedule``
    plus ``gui/catalog_refresh_tick.py``, neither of which is on the plumbing
    list). If this fails, either the guard's resolver has gone blind, or
    ``core/repositories/provider.py`` was added to ``PLUMBING_FILES`` — both
    are reasons to stop and look, not to allowlist ``refresh_schedule`` again.
    """
    allowlist = load_allowlist()
    assert "ProviderDB.refresh_schedule" not in allowlist

    readers = reader_map()
    assert readers.get("refresh_schedule"), (
        "refresh_schedule now shows as unwired — the guard's resolver may "
        "have gone blind; investigate before trusting any other result here"
    )
