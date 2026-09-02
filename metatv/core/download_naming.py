"""Where a downloaded file goes on disk. One decision, one place.

Settled in "Catch, Keep, Record" (2026-08-30), feature 2 — Layout:

    Option A default, Option B as a choice — plus the per-item fallback: an
    item whose metadata cannot fill the tree lands flat rather than in
    Series/Unknown/Season 00/.

Option A is the media-server layout Plex, Jellyfin and Kodi read without any
configuration::

    Movies/Dune Part Two (2024).mkv
    Series/Severance/Season 02/Severance - S02E01.mkv

Option B is one flat folder. **The per-item fallback is the load-bearing
part**, not a nicety: most of this library's VOD has thin metadata, and a tree
assembled from guesses is both harder to browse and harder to trust than a flat
list. ``Series/Unknown/Season 00/`` is worse than a filename.

Every field is read from the stored ``detected_*`` columns, computed once at
ingestion. Nothing here calls ``parse_channel_name`` — that is the project's
compute-once-at-ingestion rule, and a download that re-parsed the name would be
a second answer to a question the database has already answered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

#: Values for ``config.download_layout``.
LAYOUT_TREE = "tree"   #: Movies/ and Series/Show/Season NN/ — the default
LAYOUT_FLAT = "flat"   #: one folder
LAYOUTS = (LAYOUT_TREE, LAYOUT_FLAT)

#: Characters no path component may carry. Deliberately the INTERSECTION of
#: what Linux, macOS and Windows dislike rather than what the local filesystem
#: happens to allow — a library is copied to a NAS or a USB stick, and a name
#: that only works here is a name that breaks on the trip.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Cap for one component. The common filesystem limit is 255 bytes; the margin
#: leaves room for the extension and for a de-duplicating suffix.
_MAX_COMPONENT = 120


@dataclass(frozen=True)
class MediaFacts:
    """What a stored row knows about a title, as the naming layer needs it.

    A frozen bag rather than the ORM object: this module is then testable
    without a database, and nothing here can lazily load a detached row.
    """

    name: str
    title: str = ""
    year: "int | None" = None
    season: "int | None" = None
    episode: "int | None" = None
    quality: str = ""

    @property
    def is_episode(self) -> bool:
        """Enough to file under Series/Show/Season NN/ without inventing anything."""
        return bool(self.title) and self.season is not None and self.episode is not None

    @property
    def is_movie(self) -> bool:
        """Enough to file under Movies/ without inventing anything.

        The YEAR is required rather than decorative: ``Dune Part Two.mkv`` and
        ``Dune Part Two (2024).mkv`` are different claims to a media scanner,
        and the yearless one matches the wrong film often enough to matter.
        """
        return bool(self.title) and self.year is not None


def facts_from_channel(channel) -> MediaFacts:
    """Read a ``ChannelDB`` row into :class:`MediaFacts`.

    The single place that knows which stored column answers which naming
    question. Reads ``detected_*`` directly — never ``parse_channel_name``.
    """
    return MediaFacts(
        name=channel.name or "",
        title=(channel.detected_title or "").strip(),
        year=_as_int(channel.detected_year),
        season=_as_int(channel.detected_season),
        episode=_as_int(channel.detected_episode),
        quality=(channel.detected_quality or "").strip(),
    )


def relative_path(facts: MediaFacts, suffix: str,
                  layout: str = LAYOUT_TREE) -> Path:
    """The path for this title, relative to the library root.

    Returns a path rather than raising when the metadata is thin: the item
    still has to land somewhere sensible. That fallback is per ITEM, so a
    library can be mostly-tree with a flat tail, which is exactly what a
    catalogue with uneven metadata should look like.
    """
    if layout != LAYOUT_TREE:
        return Path(_flat_name(facts, suffix))

    if facts.is_episode:
        show = _component(facts.title)
        stem = f"{facts.title} - S{facts.season:02d}E{facts.episode:02d}"
        return Path("Series") / show / f"Season {facts.season:02d}" / (
            _component(stem) + suffix)

    if facts.is_movie:
        stem = f"{facts.title} ({facts.year})"
        if facts.quality:
            stem = f"{stem} - {facts.quality}"
        return Path("Movies") / (_component(stem) + suffix)

    logger.debug(
        "download_naming: {!r} cannot fill the tree (title={!r} year={} "
        "season={} episode={}) — filing it flat",
        facts.name, facts.title, facts.year, facts.season, facts.episode)
    return Path(_flat_name(facts, suffix))


def _flat_name(facts: MediaFacts, suffix: str) -> str:
    """Option B: one readable filename, no directories.

    Prefers the derived title over the raw provider name when there is one —
    the raw name carries the source's prefix and quality tags, which is exactly
    the noise a filename should not have. It never invents a field: a title
    with no year stays a bare title.
    """
    if facts.title and facts.season is not None and facts.episode is not None:
        stem = f"{facts.title} - S{facts.season:02d}E{facts.episode:02d}"
    elif facts.title and facts.year is not None:
        stem = f"{facts.title} ({facts.year})"
    else:
        stem = facts.title or facts.name or "download"
    return f"{_component(stem)}{suffix}"


def _component(text: str) -> str:
    """One safe path component: no separators, no control characters, bounded.

    Trailing dots and spaces are stripped because Windows silently drops them,
    which turns ``Show. `` and ``Show`` into the same directory on a shared
    drive and a different one here.
    """
    cleaned = _UNSAFE.sub("_", text or "")
    cleaned = " ".join(cleaned.split()).strip(" .")
    return (cleaned or "download")[:_MAX_COMPONENT]


def _as_int(value) -> "int | None":
    try:
        text = str(value).strip()
        return int(text) if text else None
    except (TypeError, ValueError):
        return None
