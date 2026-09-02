"""Guards for the ACCEPTANCE claims of the watchlist design, not its mechanism.

Why this file exists, stated generally because the specific misses were only
symptoms:

    An artifact gets read for the part you are about to build. The section that
    says what must be TRUE when it is done, and the section that shows what it
    must LOOK like, get skipped as not-yet-relevant. The tests are then written
    from the same partial reading, so they pass — green means "consistent with
    what I understood", not "conforms to the design". The gap surfaces when the
    owner opens the app, which is the most expensive place to find it.

The repo's own record is that prose does not stop this and mechanical gates do
(``scripts/rebaseline_code_health.py``'s docstring: every finding that shipped
with a guard stayed at zero, every finding relying on discipline regressed). So
the settled claims get executable form here.

Two concrete misses paid for this file:

* Q4 says *"One list, two surfaces. A rule is stored once and rendered by both
  Watch Alerts and the EPG watchlist. Two lists would mean two edit paths, two
  match counts, and the inevitable question of which one is authoritative."*
  WL-1 was built on ``AlertPatternDB`` and declared done while the "Watch for…"
  dialog kept writing ``config.vod_watch_alerts`` — so the owner's create path
  got none of the feature.
* The mockup shows Match as a SEGMENTED track and Look-in as a Title/
  Description pair. It shipped as a dropdown and two checkboxes, because the
  settled Q&A was read and the picture was not.
"""
from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Every place a watch-list entry is PERSISTED today.
#:
#: Shrink-only, exactly like the code-health ratchet: a third store may never
#: appear, and removing the second is the open work. Recording the number here
#: puts the debt in CI instead of in an artifact nobody re-reads.
#:
#: ``alert_patterns``  — AlertPatternDB, via core/watchlist.py. The real one:
#:                       it carries whole_word, match_mode, exclude_terms,
#:                       search_description and action.
#: ``vod_watch_alerts`` — a list of dicts on Config, written by the "Watch
#:                       for…" dialog. Has none of those fields, so an entry
#:                       created there silently matches by the old rules.
_KNOWN_WATCH_RULE_STORES = {"alert_patterns", "vod_watch_alerts"}


def _python_sources():
    for path in sorted((_ROOT / "metatv").rglob("*.py")):
        yield path, path.read_text(encoding="utf-8")


def test_no_third_watch_rule_store_appears():
    """Q4 in executable form: one list, two surfaces — never a new list.

    Detects a store by the shape that created the current pair: a Config field
    or a DB table whose name says it holds watch/alert rules.
    """
    found: set[str] = set()

    config_src = (_ROOT / "metatv/core/config.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(config_src)):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            # A STORE, not a label for one: an icon/glyph/flag named after the
            # section is not a second list. Detected by suffix because that is
            # how the false positive arrived (watch_alerts_icon).
            if name.endswith(("_icon", "_glyph", "_enabled", "_version")):
                continue
            if ("watch" in name and "alert" in name) or name.endswith("_rules"):
                found.add(name)

    db_src = (_ROOT / "metatv/core/database.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(db_src)):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__tablename__"
                            for t in stmt.targets)
                    and isinstance(stmt.value, ast.Constant)):
                table = str(stmt.value.value)
                if "alert_pattern" in table or ("watch" in table and "alert" in table):
                    found.add(table)

    extra = found - _KNOWN_WATCH_RULE_STORES
    assert not extra, (
        f"a new place to store watch-list entries appeared: {sorted(extra)}. "
        "The settled design is ONE list rendered by two surfaces — a second "
        "list means two edit paths, two match counts, and no answer to which "
        "is authoritative. Extend the existing store instead.")

    gone = _KNOWN_WATCH_RULE_STORES - found
    assert not gone, (
        f"{sorted(gone)} no longer exists — good, that is the open work. "
        "Remove it from _KNOWN_WATCH_RULE_STORES so the guard tightens.")


def test_the_second_store_is_recorded_as_debt_not_forgotten():
    """The point of a shrink-only set: it must stay uncomfortable.

    If this ever reads 1, the two-store problem is solved and the assertion
    below should be deleted along with the entry.
    """
    assert len(_KNOWN_WATCH_RULE_STORES) == 2, (
        "the number of watch-rule stores changed; update this file "
        "deliberately rather than letting it drift")


def test_the_match_controls_are_a_segmented_track_not_a_dropdown():
    """The mockup's shape, pinned.

    A dropdown hides two thirds of the choice behind a click and makes the
    current mode read as a setting rather than a decision. This is asserted
    against the SOURCE rather than a rendered widget so it also fails when
    somebody reintroduces a QComboBox without running the UI tests.
    """
    src = (_ROOT / "metatv/gui/watch_rule_editor.py").read_text(encoding="utf-8")
    assert "QComboBox" not in src, (
        "the watch-rule editor grew a dropdown again; the settled design shows "
        "Match as a segmented track of three visible options")
    assert "QCheckBox" not in src, (
        "Look-in is a Title/Description segmented pair in the design, not a "
        "checkbox under an 'Options' heading the mockup does not have")
    assert "ToggleChip" in src, (
        "the segmented track must reuse ToggleChip — Sports already renders "
        "one, and a second segmented-control implementation is the parallel "
        "path this repo keeps paying for")


def test_the_watchlist_add_affordance_is_not_a_bare_text_box():
    """The compose form must be the SAME editor that edits.

    A one-line box cannot express a mode, several terms, exclusions and a
    scope — which is exactly what it was still doing after those fields
    shipped.
    """
    src = (_ROOT / "metatv/gui/epg_watchlist_mixin.py").read_text(encoding="utf-8")
    assert "add_pattern_input" not in src, (
        "the single-line add box is back; composing and editing must share "
        "WatchRuleEditor or the create path silently drops every field")
    assert "WatchRuleEditor(compose=True)" in src


def test_the_watchlist_surface_does_not_call_an_entry_a_rule():
    """Vocabulary the app does not otherwise use.

    Owner: *"since we don't call them rules anywhere."* The internal class is
    ``WatchRule``; the user-facing words are Track and Watchlist.

    Scoped to the two files this design covers. The VOD watch-alert surface
    still says "rule" in two tooltips — that surface is the SECOND store and
    is being merged away, so renaming its text now would be polishing
    something scheduled for deletion. Recorded rather than silently narrowed.
    """
    owned = ("metatv/gui/watch_rule_editor.py",
             "metatv/gui/epg_watchlist_mixin.py")
    offenders = []
    for rel in owned:
        src = (_ROOT / rel).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("setText", "setToolTip",
                                           "setPlaceholderText", "addItem")):
                continue
            for arg in node.args:
                if (isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and "rule" in arg.value.lower()):
                    offenders.append(f"{rel}:{node.lineno}: {arg.value!r}")
    assert not offenders, (
        "user-facing text on the watchlist calls an entry a 'rule', a word "
        "the app uses nowhere else:\n  " + "\n  ".join(offenders))
