"""The entry FILENAME must carry the same number as the entry id.

``tests/test_whats_new.py`` already asserts that ids are unique, and it caught
this: two entries shipped as 392 because each branch ran ``latest_id() + 1``
against a base that predated the other's merge, and a correct command against a
stale base returns a taken number.

What no guard covered is how it stayed invisible long enough to be merged. The
file was named ``0393_list_posters.py`` and held ``id=392``. The loader reads
``ENTRY.id`` and ignores the filename, so a directory listing — the thing a
human actually scans when picking the next number, and when reviewing the diff —
looked correct while the runtime was not.

This is the cheap half: it fails at the filename, before anyone has to reason
about the loader.
"""

from __future__ import annotations

import pathlib
import re

_ENTRIES_DIR = pathlib.Path(__file__).resolve().parent.parent / "metatv" / "whats_new" / "entries"


def test_the_filename_number_matches_the_entry_id():
    """`0393_x.py` holding `id=392` reads as correct and is not."""
    mismatched = []
    for path in sorted(_ENTRIES_DIR.glob("[0-9]*.py")):
        m = re.match(r"^(\d+)_", path.name)
        if not m:
            continue
        from_name = int(m.group(1))
        found = re.search(r"^\s*id=(\d+),", path.read_text(), re.M)
        assert found, f"{path.name} has no id= field"
        if int(found.group(1)) != from_name:
            mismatched.append((path.name, from_name, int(found.group(1))))

    assert not mismatched, (
        "filename number and entry id disagree: "
        + ", ".join(f"{n} is named {a} but holds id={b}" for n, a, b in mismatched)
        + ". Rename the file and the id together."
    )
