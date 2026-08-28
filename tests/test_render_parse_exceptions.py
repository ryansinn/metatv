"""Render code reads stored ``detected_*`` fields; it does not re-parse names.

Name-derived fields are computed once at ingestion and stored, so display, query
and scoring read the stored value. Re-parsing at render puts string work in a
paint path, and — the reason that actually bites — it DISAGREES with the stored
value whenever the field was filled from something other than the name. A
``detected_region`` taken from the provider category or a sibling channel is
invisible to a re-parse, so a re-parsing surface silently drops a tag every
other surface shows.

The rule lived in prose with one named exception. It had drifted to three
call sites, none of which was the one named. That is the failure mode this
codebase keeps meeting: a list a human maintains covers less than it claims,
and nothing says so.

So the exceptions are enumerated HERE, mechanically, each with the reason it is
sound. A fourth call site fails this test until someone decides it belongs.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GUI = REPO / "metatv" / "gui"

#: file -> why parsing at render is correct there. Every entry is a case where
#: NO stored field exists to read, which is the only sound reason.
ACCEPTED: dict[str, str] = {
    "sidebar/base.py": (
        "explicit fallback arm: the stored-field path is taken whenever "
        "detected_title is not None, and this branch runs only for a raw string "
        "with no row behind it (a live EPG programme title in Alerts)"
    ),
    "main_window_series.py": (
        "episode failure toast — an EPISODE has no detected_* fields; they are "
        "computed for channels, and the episode row carries only a raw title"
    ),
    "main_window_streaming.py": (
        "stream failure toast built from a channel_name string handed in by the "
        "player callback, which does not carry the row"
    ),
}


def _parse_sites() -> dict[str, list[int]]:
    """Every call to parse_channel_name (under any alias) in the GUI layer."""
    found: dict[str, list[int]] = {}
    for path in sorted(GUI.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        # Local aliases, e.g. `from ... import parse_channel_name as _pcn`
        aliases = {"parse_channel_name"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "parse_channel_name" and a.asname:
                        aliases.add(a.asname)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in aliases):
                rel = str(path.relative_to(GUI))
                found.setdefault(rel, []).append(node.lineno)
    return found


def test_only_accepted_files_parse_at_render():
    sites = _parse_sites()
    unexpected = {f: ls for f, ls in sites.items() if f not in ACCEPTED}
    assert not unexpected, (
        "these render-layer files call parse_channel_name, which disagrees with "
        f"the stored detected_* fields: {unexpected}. Read the stored field "
        "instead, or add the file to ACCEPTED with the reason no stored field "
        "exists to read."
    )


def test_every_accepted_file_still_parses():
    """An exception for a site that stopped parsing quietly widens the rule."""
    sites = _parse_sites()
    stale = [f for f in ACCEPTED if f not in sites]
    assert not stale, (
        f"ACCEPTED lists files that no longer parse at render: {stale} — "
        "remove them so the list keeps meaning what it says"
    )


@pytest.mark.parametrize("rel,reason", sorted(ACCEPTED.items()))
def test_every_exception_names_a_real_file_and_a_reason(rel, reason):
    assert (GUI / rel).exists(), f"ACCEPTED names a missing file: {rel}"
    assert len(reason.strip()) > 20, f"{rel} needs a real reason, got {reason!r}"


def test_the_detector_follows_import_aliases():
    """main_window_streaming imports it as _pcn; a name-only matcher misses it."""
    assert "main_window_streaming.py" in _parse_sites(), (
        "the alias form was not detected — a file could evade this guard by "
        "renaming the import"
    )
