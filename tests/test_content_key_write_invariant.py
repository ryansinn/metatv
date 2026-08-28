"""A write of ``detected_tmdb_id`` recomputes ``content_key`` in the same statement.

The two fields are one fact. ``content_key`` is tmdb-first, so the moment a row
gains an id its stored key is stale — and a row carrying an id under a
title/year key stops matching its own variants. Nothing raises, nothing logs;
"Other Versions" quietly omits copies and taste collapse counts one title twice.

That bug shipped once. The ordering it relied on could not hold: the id backfill
and the key recompute are independently version-gated, and the id backfill leaves
its version unbumped when cancelled so it resumes on the next launch — by which
point the key task is version-satisfied and sits out. Every row the resumed pass
filled carried an id under a stale key.

The repair was to make each writer maintain the invariant itself. This is the
guard for that repair, and it is derived: it finds the writes rather than listing
them, so a new one is covered without anyone remembering this file exists.
Without it the rule is convention, and the measured history of this codebase is
that every invariant left to convention regressed while every one with a
mechanical guard held.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCANNED = REPO / "metatv"

#: Writes that set the id WITHOUT the key, each with the reason it is sound.
#: Adding to this is a decision, not a formality — say why the row's key is
#: correct without being recomputed here.
EXEMPT: dict[str, str] = {
    # Provider ingestion constructs a NEW Channel model rather than updating a
    # stored row; content_key is computed for it moments later by
    # update_detected_prefixes, which sees the id this line just set.
    "metatv/providers/xtream.py": "model construction at ingest, keyed downstream",
}


def _writes_id_without_key(call: ast.Call) -> bool:
    """True for a ``.values(...)`` that names the id but not the key."""
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "values":
        return False
    named = {k.arg for k in call.keywords if k.arg}
    return "detected_tmdb_id" in named and "content_key" not in named


def _orm_assignments(tree: ast.Module) -> list[ast.Assign]:
    """``row.detected_tmdb_id = ...`` — the non-bulk way to break the invariant.

    ``self.detected_tmdb_id = ...`` is excluded deliberately. In this codebase
    that form is always a duck-typed proxy being CONSTRUCTED to hand to
    ``content_key_for`` — the object exists to compute the key, so demanding it
    also carry one is backwards. Mutating a fetched row reads
    ``channel.detected_tmdb_id = ...``, and that is what this looks for.
    """
    out = []
    for node in ast.walk(tree):
        for t in getattr(node, "targets", []):
            if (isinstance(t, ast.Attribute) and t.attr == "detected_tmdb_id"
                    and not (isinstance(t.value, ast.Name) and t.value.id == "self")):
                out.append(node)
    return out


def _sources():
    for path in sorted(SCANNED.rglob("*.py")):
        rel = str(path.relative_to(REPO))
        if rel in EXEMPT:
            continue
        yield rel, path.read_text(encoding="utf-8")


def test_no_bulk_update_sets_the_id_without_the_key():
    offenders = []
    for rel, src in _sources():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and _writes_id_without_key(node):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "these UPDATEs set detected_tmdb_id without recomputing content_key, "
        f"leaving the row orphaned from its own variants: {offenders}. Add "
        "content_key=content_key_for(...) to the same .values(), or add the "
        "file to EXEMPT with the reason its key is already correct."
    )


def test_no_orm_assignment_sets_the_id_alone():
    """An attribute write must be followed by a key write in the same block."""
    offenders = []
    for rel, src in _sources():
        tree = ast.parse(src)
        for node in _orm_assignments(tree):
            # Look for a content_key assignment on the same object nearby: the
            # pattern in-tree assigns both fields adjacently.
            window = [
                n for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and abs(n.lineno - node.lineno) <= 4
                and any(isinstance(t, ast.Attribute) and t.attr == "content_key"
                        for t in n.targets)
            ]
            if not window:
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "these assign detected_tmdb_id without assigning content_key beside it: "
        f"{offenders}"
    )


def test_the_guard_can_see_a_violation():
    """The guard's own detector, exercised on a synthetic break.

    A guard that cannot fail is decoration. This proves the matcher fires
    without needing a real regression in the tree to test against.
    """
    bad = ast.parse(
        "session.execute(update(ChannelDB).where(x).values(detected_tmdb_id=t))"
    )
    good = ast.parse(
        "session.execute(update(ChannelDB).where(x)"
        ".values(detected_tmdb_id=t, content_key=k))"
    )
    assert any(isinstance(n, ast.Call) and _writes_id_without_key(n)
               for n in ast.walk(bad)), "the matcher missed a real violation"
    assert not any(isinstance(n, ast.Call) and _writes_id_without_key(n)
                   for n in ast.walk(good)), "the matcher flagged a correct write"


@pytest.mark.parametrize("rel,reason", sorted(EXEMPT.items()))
def test_every_exemption_names_a_file_that_exists(rel, reason):
    """An exemption for a deleted file silently widens the guard."""
    assert (REPO / rel).exists(), f"EXEMPT names a missing file: {rel}"
    assert reason.strip(), f"EXEMPT entry for {rel} has no reason"
