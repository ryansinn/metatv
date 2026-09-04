"""The Downloaded channel-list scope (DL-5) — the ``downloaded_only`` axis.

Downloaded is a record/engaged view (DR-0007), same family as History/
Favorites/Queue: it lists channels with at least one COMPLETED download whose
file still exists on disk (DL-2), regardless of the source's active state or
Global Exclusions — a file already saved to disk is the definition of engaged
content, and it stays playable even when its source is disabled.

**DL-2 — truth, not a stored boolean.** ``state == "completed"`` says a
transfer finished; it says nothing about whether the file is still there a
week later. ``predicate()`` stats every completed row's ``dest_path`` so a
file deleted outside the app drops out of this scope on the next refresh,
same as the "Downloaded" scope tab's count and the folder/reveal affordances
in ``file_reveal.py``.

Split out of ``channel.py`` rather than grown in place: that file is pinned
at its code-health ratchet ceiling, and CLAUDE.md's size rule is explicit —
"a pinned file at its ceiling means extract to a cohesive new module, not
rebaseline". ``_apply_channel_filters`` calls the two functions here; the
predicates themselves, and the reasoning for them, live here instead.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import false as sql_false

from metatv.core.database import ChannelDB, DownloadDB


def _file_exists(dest_path: "str | None") -> bool:
    """Real filesystem check — the ONLY source of truth for "downloaded".

    *Catch, Keep, Record* (DL-2) is explicit that a "downloaded" claim must
    come from the disk, never from the stored ``state`` column: a file can be
    deleted (or moved, or the drive unmounted) outside the app, and the row
    would otherwise go on claiming it forever.
    """
    if not dest_path:
        return False
    try:
        return Path(os.path.expanduser(dest_path)).is_file()
    except OSError:
        return False


def predicate(session):
    """WHERE clause: this channel has >=1 completed download whose file still
    exists on disk.

    ``state == "completed"`` alone is the stale-boolean failure DL-2 exists to
    fix — a completed row survives a file the user deleted in their file
    manager. This stats every completed row's ``dest_path`` once, here, rather
    than filtering in SQL (a filesystem check has no SQL form) — cheap because
    the query this feeds runs per REFRESH (the async background-read seam),
    never per paint of a row.

    Args:
        session: The caller's session — reused rather than opened fresh, same
            as the rest of ``_apply_channel_filters``.
    """
    rows = (session.query(DownloadDB.channel_id, DownloadDB.dest_path)
            .filter(DownloadDB.state == "completed").all())
    verified_ids = {channel_id for channel_id, dest_path in rows
                    if _file_exists(dest_path)}
    if not verified_ids:
        return sql_false()
    return ChannelDB.id.in_(verified_ids)


def visibility_overrides(downloaded_only: bool, excluded_provider_ids, excluded_keywords) -> dict:
    """``VisibilityScope`` kwargs for the provider/keyword exclusion axes.

    Forced empty when *downloaded_only* is set — regardless of what the
    caller passed — so the engine itself enforces the DR-0007/DL-5 exemption
    from active-source scoping and the Global Exclusions keyword axis, even
    if a caller forgets to omit them. ``hidden_only`` gets no such override;
    it stays scoped to active sources. Splat into ``VisibilityScope(**...)``.
    """
    if downloaded_only:
        return {"excluded_provider_ids": [], "excluded_keywords": set()}
    return {
        "excluded_provider_ids": list(excluded_provider_ids or []),
        "excluded_keywords": set(excluded_keywords or []),
    }
