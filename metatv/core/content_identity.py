"""Content identity — stable per-channel key for grouping same-production variants.

Slice 1 of the content-identity/dedup plan.  This module computes a
``content_key`` for a channel row using already-ingested stored fields
(``detected_title``, ``media_type``, ``detected_year``).  It does NOT change
any read/query/UI surface and adds no collapse logic — that is Slice 2+.

Design rationale
----------------
The key is **coarse by design**:

- ``detected_title`` is already prefix/suffix/year/quality-stripped at
  ingestion by ``update_detected_prefixes()``.  We normalize it further
  (lowercase, collapse whitespace, strip non-word characters) and use it as
  the title component.  We do NOT call ``content_dedup.normalize_title()`` or
  re-parse the raw name — this is the compute-once-at-ingestion principle.

- ``detected_year`` is included so reboots/remakes with the same title but a
  different year get distinct keys.

- ``media_type`` is included so a channel named "Sherlock" (live) is kept
  separate from the movie and the series.

- **Director and metadata-year are deliberately excluded** from the ingestion
  key: metadata from TMDb/OMDb is not yet available at channel-upsert time, and
  TV series have many episode directors making the field unreliable.  A coarse
  key safely groups language/quality variants of the same production without
  over-splitting.  Slice 3+ can refine using canonical IDs once TMDb is wired.

Per-domain strategy seam
------------------------
``content_key_for()`` dispatches on a ``_ContentKeyStrategy`` that can be
swapped per media source domain.  Today only the Xtream/IPTV strategy is
implemented; Spotify, YouTube, and Plex strategies can slot in later by
subclassing ``_ContentKeyStrategy`` and registering a domain via
``register_strategy()``.

Engine-layer contract (DR-0007)
--------------------------------
This module is preference-free and pure: same inputs → same output, no DB
access, no config dependency.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from loguru import logger


# ---------------------------------------------------------------------------
# Shared normalisation helper
# ---------------------------------------------------------------------------

_NONWORD_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_for_key(title: str) -> str:
    """Lowercase, strip non-word characters, collapse whitespace.

    Mirrors the final three steps of ``content_dedup.normalize_title()`` so
    two ``detected_title`` values that differ only in punctuation or spacing
    collapse to the same key component.

    Args:
        title: Raw (but already-stripped) title string, e.g. from
            ``channel.detected_title``.

    Returns:
        Normalised string suitable for use as a key component.  May be empty
        when the entire title is punctuation/whitespace.
    """
    lowered = title.lower()
    no_punct = _NONWORD_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", no_punct).strip()


# ---------------------------------------------------------------------------
# Strategy interface
# ---------------------------------------------------------------------------


class _ContentKeyStrategy(ABC):
    """Abstract base for per-source-domain content key strategies.

    Implementations must be stateless and pure (no DB or config access).
    """

    @abstractmethod
    def compute_key(self, channel) -> str:
        """Return a stable content_key string for *channel*.

        Args:
            channel: A ``ChannelDB`` ORM object (or any object with
                ``detected_title``, ``media_type``, ``detected_year``, and
                ``id`` attributes).

        Returns:
            A non-empty string.  Two channels with the same key are considered
            same-production variants.  Two channels with different keys are
            considered distinct productions.
        """


# ---------------------------------------------------------------------------
# Xtream / IPTV strategy (the only implementation for Slice 1)
# ---------------------------------------------------------------------------


class _XtreamContentKeyStrategy(_ContentKeyStrategy):
    """Content key strategy for Xtream/IPTV channel rows.

    Key format: ``"{norm_title}|{media_type}|{year}"``.

    Fallback: when ``detected_title`` is empty/None the channel's own ``id``
    is used as the norm_title component so the row always gets a unique key and
    never collapses with unrelated rows.
    """

    def compute_key(self, channel) -> str:
        raw_title: str | None = getattr(channel, "detected_title", None)
        media_type: str = getattr(channel, "media_type", None) or ""
        year: str = getattr(channel, "detected_year", None) or ""

        if raw_title:
            norm = _normalize_for_key(raw_title)
        else:
            norm = ""

        if not norm:
            # Fallback: unique per channel so it never merges with anything
            norm = str(getattr(channel, "id", ""))
            logger.debug(
                "content_identity: empty detected_title for channel {!r} — "
                "using id as fallback key component",
                norm,
            )

        return f"{norm}|{media_type}|{year}"


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

_DEFAULT_STRATEGY: _ContentKeyStrategy = _XtreamContentKeyStrategy()

# Map of source-domain name → strategy instance.  Only the default (Xtream/IPTV)
# is registered here; future domains (Spotify, YouTube, Plex) add an entry via
# ``register_strategy()`` without changing anything else.
_STRATEGY_REGISTRY: dict[str, _ContentKeyStrategy] = {}


def register_strategy(domain: str, strategy: _ContentKeyStrategy) -> None:
    """Register a per-domain content key strategy.

    Args:
        domain: Opaque domain identifier (e.g. ``"spotify"``, ``"youtube"``).
            The channel must have a matching ``source_domain`` attribute for
            the strategy to be selected.
        strategy: Stateless strategy instance.
    """
    _STRATEGY_REGISTRY[domain] = strategy


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def content_key_for(channel) -> str:
    """Return the stable ``content_key`` for *channel*.

    Dispatches on ``channel.source_domain`` when present; falls back to the
    Xtream/IPTV strategy for channels without an explicit domain (the common
    case today).

    Args:
        channel: A ``ChannelDB`` ORM object (or duck-typed substitute with
            ``detected_title``, ``media_type``, ``detected_year``, ``id``
            attributes).

    Returns:
        A non-empty string.  This is an engine-layer pure function — same
        inputs always produce the same output.
    """
    domain: str | None = getattr(channel, "source_domain", None)
    strategy = _STRATEGY_REGISTRY.get(domain, _DEFAULT_STRATEGY) if domain else _DEFAULT_STRATEGY
    return strategy.compute_key(channel)
