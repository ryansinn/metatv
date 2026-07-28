"""Pure (Qt-free) helpers for identifying monitored-series entries.

Two different monitored series can share the same *cleaned* ``display_title`` (the
region/language get stripped at ingestion), so "Fallout" and "Fallout" become
indistinguishable in the Watch Alerts list.  These helpers give both the sidebar
(:mod:`metatv.gui.sidebar.alerts`) and the manage dialog
(:mod:`metatv.gui.vod_watch_alert_dialog`) a single source of truth for:

- the always-on identity tooltip (Language + Region + Source), and
- the collision-only inline disambiguator suffix.

Everything here reads the *stored* fields persisted at monitor-add time /
backfilled from the channel's ingestion-computed ``detected_*`` (``region`` from
``detected_region``, ``language`` from ``detected_prefix``, ``source`` = provider
name).  Nothing re-parses a raw channel name at render — that is the
compute-at-ingestion rule.

No Qt / theme imports: the module stays trivially unit-testable.
"""

from __future__ import annotations

# Attributes tried, in order, to tell apart two entries that share a cleaned
# title.  The first one that actually differs across the colliding set wins.
_DISAMBIGUATION_ORDER = ("region", "language", "source")


def _clean_title(entry: dict) -> str:
    """Cleaned display title for grouping (stored ``display_title``, else raw)."""
    return (entry.get("display_title") or entry.get("title") or "Unknown series").strip()


def _attr(entry: dict, key: str) -> str:
    """Stripped string value for a stored attribute, ``""`` when absent/None."""
    return (entry.get(key) or "").strip()


def normalize_entry(entry: dict) -> dict:
    """Project a raw ``monitored_series`` config dict onto the identity fields.

    Args:
        entry: A raw monitored-series config entry.

    Returns:
        ``{"clean", "region", "language", "source", "raw"}`` — all stripped
        strings (``raw`` is the raw stored ``title`` used as the last-resort
        disambiguator).
    """
    return {
        "clean": _clean_title(entry),
        "region": _attr(entry, "region"),
        "language": _attr(entry, "language"),
        "source": _attr(entry, "source"),
        "raw": _attr(entry, "title"),
    }


def identity_lines(*, language: str, region: str, source: str) -> str:
    """A 3-line identity block for a tooltip: Language / Region / Source.

    Every monitored-series row shows this (always, not only on collisions) so any
    series is fully identifiable on hover.  Empty values render as an em dash.

    Args:
        language: Stored language/prefix code (e.g. ``"EN"``).
        region: Stored region code (e.g. ``"US"``).
        source: Provider display name.

    Returns:
        A newline-joined ``"Language: …\\nRegion: …\\nSource: …"`` string.
    """
    return (
        f"Language: {(language or '').strip() or '—'}\n"
        f"Region: {(region or '').strip() or '—'}\n"
        f"Source: {(source or '').strip() or '—'}"
    )


def disambiguation_suffixes(entries: list[dict]) -> list[str]:
    """Per-entry inline disambiguator suffixes, aligned to ``entries`` order.

    A suffix is **non-empty only** when the entry's cleaned title collides
    (case-insensitive) with at least one other entry's.  Among a colliding set,
    the first attribute that actually DIFFERS is used — ``region`` → ``language``
    → ``source`` — with each colliding row showing its own value.  When none of
    those differ, the raw stored ``title`` is the fallback.  Rows whose cleaned
    title is unique get ``""`` (they stay clean).

    Args:
        entries: Raw ``monitored_series`` config dicts.

    Returns:
        A list of suffix strings, one per input entry, in the same order.
    """
    norm = [normalize_entry(e) for e in entries]
    suffixes = [""] * len(norm)

    groups: dict[str, list[int]] = {}
    for i, n in enumerate(norm):
        groups.setdefault(n["clean"].casefold(), []).append(i)

    for idxs in groups.values():
        if len(idxs) < 2:
            continue  # unique cleaned title — no disambiguator needed
        chosen: str | None = None
        for attr in _DISAMBIGUATION_ORDER:
            values = [norm[i][attr] for i in idxs]
            if len(set(values)) > 1:
                chosen = attr
                break
        for i in idxs:
            if chosen is not None:
                suffixes[i] = norm[i][chosen] or norm[i]["raw"]
            else:
                suffixes[i] = norm[i]["raw"]
    return suffixes
