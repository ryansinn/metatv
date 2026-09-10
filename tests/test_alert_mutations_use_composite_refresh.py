"""An alert-state MUTATION must refresh every surface, not just the Alerts section.

The defect this closes (owner report, 2026-09-09)
-------------------------------------------------
> removing the rule, doesn't remove the corresponding rule matches in the watch
> queue.

``Config.remove_vod_watch_alert`` deletes the rule dict — and its ``alerted_ids``
with it — so the matches really are gone from storage. But the handler refreshed
only ``_refresh_vod_alerts_section`` (the Alerts sidebar sub-list), while those
same matches are ALSO rendered by the Watch Queue's "Alerts Matched" group and
pinned count, the channel-list row badges, and the details-pane Alert button.
``_refresh_alert_visibility`` is the composite chokepoint that re-reads all of
them, and its own docstring says so.

Five handlers had it wrong and one had it right — ``_on_mark_series_seen``,
whose docstring names this exact failure mode ("so the Watch Queue sidebar's own
'Alerts Matched' matched-series rows clear their badge too"). The reasoning was
already written down; four siblings just never got it. That is the reader half
of docs/REFACTOR_PLAN.md's D60 made concrete.

The predicate
-------------
A method that CHANGES stored alert state — the watch-for rule list, the
monitored-series list, or a series' unseen count — and then refreshes must call
``_refresh_alert_visibility``, never only ``_refresh_vod_alerts_section``. Read-
only and display-only paths (a title backfill, opening a dialog) may use the
narrow one and are listed as such.
"""

from __future__ import annotations

import ast
import pathlib

GUI_ROOT = pathlib.Path(__file__).resolve().parents[1] / "metatv" / "gui"

#: Config mutations that change what the alert surfaces display.
ALERT_STATE_WRITES = frozenset({
    "remove_vod_watch_alert", "add_vod_watch_alert",
    "remove_monitored_series", "add_monitored_series",
    "clear_unseen", "record_vod_alert_match",
    "mark_vod_alert_match_viewed", "mark_all_vod_alerts_viewed",
})

NARROW = "_refresh_vod_alerts_section"
COMPOSITE = "_refresh_alert_visibility"

#: Display-only holdouts allowed to use the narrow refresh, with the reason.
#: Shrink-only: removing one is progress, adding one needs a stated reason.
NARROW_OK = {
    # Fills in display_title/region/language on already-stored entries. Changes
    # no membership and no count, so no other surface's content moves.
    "_backfill_series_display_titles",
}


def _methods():
    for path in sorted(GUI_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                yield path, node


def _calls(fn: ast.FunctionDef) -> tuple[set[str], bool, bool]:
    """Return (alert-state writes called, calls narrow, calls composite)."""
    writes: set[str] = set()
    narrow = composite = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        if name in ALERT_STATE_WRITES:
            writes.add(name)
        elif name == NARROW:
            narrow = True
        elif name == COMPOSITE:
            composite = True
    return writes, narrow, composite


def test_alert_state_mutations_refresh_every_surface() -> None:
    offenders: list[str] = []
    census = 0
    for path, fn in _methods():
        writes, narrow, composite = _calls(fn)
        # The census counts every mutation handler that refreshes AT ALL, not
        # just the offending ones — a census of offenders would read 0 once
        # they are fixed and could no longer tell "all clean" from "the names
        # moved and this guard matches nothing".
        if not writes or not (narrow or composite):
            continue
        census += 1
        if not narrow or composite or fn.name in NARROW_OK:
            continue
        rel = path.relative_to(GUI_ROOT.parents[1])
        offenders.append(f"{rel}:{fn.lineno} {fn.name}() writes {sorted(writes)}")

    assert census, (
        "this guard matched no alert-mutation handlers at all — the method "
        "names it keys on have moved and it is silently passing"
    )
    assert not offenders, (
        "these handlers change stored alert state but refresh only the Alerts "
        "sidebar section, leaving the Watch Queue's 'Alerts Matched' rows, the "
        "channel-list badges and the details Alert button showing the old "
        "state:\n  " + "\n  ".join(offenders) +
        f"\n\nCall {COMPOSITE}() — the composite chokepoint — instead of "
        f"{NARROW}(). If the handler genuinely changes nothing another surface "
        "renders, add it to NARROW_OK with the reason."
    )


def test_every_narrow_ok_entry_still_exists() -> None:
    """A holdout for a method that no longer exists is dead weight.

    Same shrink-only discipline as the code-health baseline: an exemption
    nobody removes is a permanent one.
    """
    names = {fn.name for _p, fn in _methods()}
    stale = sorted(NARROW_OK - names)
    assert not stale, f"NARROW_OK names methods that no longer exist: {stale}"


def test_the_guard_can_actually_fail() -> None:
    """The predicate must reject a mutation handler that uses the narrow refresh."""
    bad = ast.parse(
        "def _on_remove(self, rid):\n"
        "    self.config.remove_vod_watch_alert(rid)\n"
        "    self._refresh_vod_alerts_section()\n"
    ).body[0]
    writes, narrow, composite = _calls(bad)
    assert writes == {"remove_vod_watch_alert"} and narrow and not composite

    good = ast.parse(
        "def _on_remove(self, rid):\n"
        "    self.config.remove_vod_watch_alert(rid)\n"
        "    self._refresh_alert_visibility()\n"
    ).body[0]
    writes, narrow, composite = _calls(good)
    assert writes == {"remove_vod_watch_alert"} and composite
