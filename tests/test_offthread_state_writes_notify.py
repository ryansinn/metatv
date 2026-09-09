"""A worker that writes user state must tell the UI — AST guard (#836).

The defect this closes
----------------------
``_bg_finalise_episode`` marked each auto-advanced episode 100%-complete from a
worker while the series tree was already on screen.  Nothing told the tree, so
the same window held two disagreeing answers about the same rows, and the user
acted on the stale one — unmarking the episodes it showed as watched, leaving
the ones it did not, and finding a season with an unwatched hole in the middle
of a watched run on the next visit.

Why a guard and not a note
--------------------------
This is the shape CLAUDE.md names three ways — "a wrong pairing has a
population", "an enumeration never sees what nobody remembered to add" — and it
is *checkable*: a background write that never notifies is visible in the AST.
The census when this landed was six workers; a note would have covered the one
site that was found by accident.  Prefer closing the class.

What is NOT covered, deliberately
---------------------------------
This is the WRITER half only: it proves the notification is sent, never that a
given surface subscribed to it.  "Every view showing watched/queued/favourite
state re-reads when it changes" is the reader half — an audit, logged as class
D55 in docs/REFACTOR_PLAN.md, not something an AST walk can decide.
"""

from __future__ import annotations

import ast
import pathlib

GUI_ROOT = pathlib.Path(__file__).resolve().parents[1] / "metatv" / "gui"

#: Repository methods that change what a user sees about a title or episode.
#: A worker calling one of these has moved state the interface is displaying.
STATE_WRITES = frozenset({
    "mark_watched", "mark_watched_bulk", "mark_played", "record_watch_progress",
    "mark_episodes_as_engaged", "set_rating", "toggle_favorite", "set_favorite",
    "mark_series_seen", "set_hidden", "hide_channel", "unhide_channel",
    "add_to_queue", "remove_from_queue", "set_suppressed", "update_progress",
    "mark_not_interested", "set_user_rating",
})

#: How a worker is allowed to hand the change back to the main thread. Direct
#: ``signal.emit`` / ``bus.publish``, or a ``_notify_*`` helper that does one of
#: those on its behalf (``watch_capture._notify_episode_watch_state``).
NOTIFY_ATTRS = frozenset({"emit", "publish"})
NOTIFY_PREFIX = "_notify_"


def _worker_functions():
    """Yield ``(path, FunctionDef)`` for every ``_bg_*`` worker under gui/.

    ``_bg_`` is this codebase's own naming for "submitted to an executor" — the
    functions that are, by construction, unable to touch a widget.
    """
    for path in sorted(GUI_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("_bg_"):
                yield path, node


def _calls(fn: ast.FunctionDef) -> tuple[set[str], bool]:
    """Return (state-write method names called, whether the body notifies)."""
    writes: set[str] = set()
    notifies = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        if name is None:
            continue
        if name in STATE_WRITES:
            writes.add(name)
        if name in NOTIFY_ATTRS or name.startswith(NOTIFY_PREFIX):
            notifies = True
    return writes, notifies


def test_every_background_state_write_notifies_the_ui() -> None:
    """A ``_bg_*`` worker that writes user state must also notify."""
    offenders: list[str] = []
    census = 0
    for path, fn in _worker_functions():
        writes, notifies = _calls(fn)
        if not writes:
            continue
        census += 1
        if not notifies:
            rel = path.relative_to(GUI_ROOT.parents[1])
            offenders.append(f"{rel}:{fn.lineno} {fn.name}() writes {sorted(writes)}")

    assert census, (
        "this guard found no background state writes at all — the naming "
        "convention it keys on (_bg_*) has moved and it is silently passing"
    )
    assert not offenders, (
        "these background workers change user state and never tell the main "
        "thread, so any view already on screen keeps showing the old value "
        "(#836):\n  " + "\n  ".join(offenders) +
        "\n\nEnd the worker with the signal its surface listens on (e.g. "
        "self._episode_watch_state_changed.emit(ids), "
        "self.channel_state_bus.publish(channel_id, **delta)), or a _notify_* "
        "helper that does. Never a hand-picked list of views to refresh."
    )


def test_the_guard_can_actually_fail() -> None:
    """The predicate must reject a worker that writes without notifying.

    A guard whose only evidence is a green run proves nothing about whether it
    can go red (CLAUDE.md: "a runner that ran nothing exits 0").
    """
    bad = ast.parse(
        "def _bg_write(self, cid):\n"
        "    with self.db.session_scope() as s:\n"
        "        s.repo.mark_watched_bulk([cid], True)\n"
    ).body[0]
    writes, notifies = _calls(bad)
    assert writes == {"mark_watched_bulk"} and not notifies

    good = ast.parse(
        "def _bg_write(self, cid):\n"
        "    with self.db.session_scope() as s:\n"
        "        s.repo.mark_watched_bulk([cid], True)\n"
        "    self._episode_watch_state_changed.emit([cid])\n"
    ).body[0]
    writes, notifies = _calls(good)
    assert writes == {"mark_watched_bulk"} and notifies
