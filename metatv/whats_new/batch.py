"""Which commit the open What's New batch was opened at.

Why this file exists
--------------------
``metatv/__init__.py``'s ``__version__`` is the label a batch of What's New
entries ships under. Under rolling releases it stopped moving: the bump lived
inside ``scripts/ship_batch.sh``'s "release chore", rolling made that script's
tag-and-publish ceremony obsolete, the day-to-day merge stopped calling it, and
the bump went out with the ceremony nobody needed any more. Sixty-one entries
accumulated under ``0.41.0`` across four days and nine merges, so the label
identified nothing.

What this records
-----------------
Not a version — ``__version__`` is still the version. This records the point on
``main`` the current label was opened at, which is what makes the bump decidable
by a script instead of by memory:

* ``OPENED_AT_SHA`` — ``main``'s HEAD when the label was opened. A build of THAT
  commit is a rebuild of what already shipped under this label, so it must not
  bump. The build identifier already distinguishes rebuilds
  (``<version>+<UTC date>.<short sha>``); a second label for the same code would
  be a lie.
* ``OPENED_AT_ID`` — the highest What's New id at that moment. If
  ``latest_id()`` has grown past it, this label now covers entries that were
  never in the build it names, and the next public build owes a bump.

``scripts/open_batch.sh`` reads and rewrites both.
"""

from __future__ import annotations

# main's HEAD when the current __version__ label was opened.
OPENED_AT_SHA: str = "a23de5f"

# The highest What's New entry id at that moment.
OPENED_AT_ID: int = 392
