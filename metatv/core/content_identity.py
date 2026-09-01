"""Content identity — stable per-channel key for grouping same-production variants.

Slice 1 of the content-identity/dedup plan.  This module computes a
``content_key`` for a channel row using already-ingested stored fields
(``detected_tmdb_id``, ``detected_title``, ``media_type``, ``detected_year``).
It does NOT change any read/query/UI surface and adds no collapse logic — that
is Slice 2+.

TMDb-first identity (Slice 3)
-----------------------------
When the provider ships a canonical TMDb id (Xtream carries it in
``raw_data["tmdb"]``; captured once at ingestion into the stored
``detected_tmdb_id`` field — never re-parsed at read time), it is authoritative
and **takes precedence** over the heuristic title/year key:

    valid tmdb id  →  ``"tmdb:{id}|{media_type}"``
    otherwise      →  the existing title/year heuristic (unchanged)

**The key MUST be namespaced by ``media_type``.**  TMDb numbers movies and TV
series in *separate* id spaces, so the same integer id denotes an unrelated
movie and series.  In the measured library 1,388 tmdb ints span both movie and
series rows; a bare ``"tmdb:{id}"`` key would wrongly merge those unrelated
productions (e.g. the movie "The Host" with a same-numbered series).  Appending
``|{media_type}`` is the sole fix for that collision (verified against the
London Kills/The First Man and The Continental/The Host mistags in analysis).

Validation lives in one place — ``valid_tmdb_id()`` (this module) — imported by
both the ingestion writer (``providers/xtream.py``) and the key computation
below, so "what counts as a real tmdb id" has a single source of truth.  It
rejects the provider sentinels (``""`` / ``"0"`` / ``"null"`` / ``"None"``) and
any non-numeric value, falling back to the title/year key for those rows.

This module stays engine-pure: it READS the already-stored ``detected_tmdb_id``
(via ``getattr``) and never touches the DB, config, or ``raw_data`` blob.

Design rationale
----------------
The heuristic (fallback) key is **coarse by design**:

- ``detected_title`` is already prefix/suffix/year/quality-stripped at
  ingestion by ``update_detected_prefixes()``.  We normalize it further
  (lowercase, collapse whitespace, strip non-word characters) and use it as
  the title component.  We do NOT call ``content_dedup.normalize_title()`` or
  re-parse the raw name — this is the compute-once-at-ingestion principle.

- **Year handling is media_type-specific (v2, see QA bug 10bc0a7):**

  * **Series and live:** year is **omitted** from the key.  Key format:
    ``"{norm_title}|{media_type}"``.  Rationale: providers label the same
    series inconsistently — some embed a start year or a range (2015-2018),
    others omit it entirely.  All of these refer to the same production, so
    including year splits them instead of collapsing them.  This mirrors how
    ``content_dedup.build_dedup_key()`` already drops *director* for series.
    Trade-off: a rare same-title reboot (e.g. two different "The Office" series
    from different eras) will collapse into one card — accepted per DR-0006
    (false positive is visible and one-click-correctable; false negative is
    invisible).  A canonical TMDb id (see "TMDb-first identity" above), when the
    provider ships one, pre-empts this heuristic and disambiguates reboots; the
    coarse rule below only applies to rows *without* a tmdb id.

  * **Movies:** year is **kept but normalized to the start year** (first
    4-digit group extracted from ``detected_year``; junk/empty → omit).  Key
    format: ``"{norm_title}|movie|{start_year}"``.  Year is a meaningful
    remake discriminator for movies (same title, different year = different
    production), and movie years are typically clean (a single 4-digit year).
    Examples: ``"2015-2018"`` → ``"2015"``; ``"(2024)"`` → ``"2024"``.

- ``media_type`` is included so a channel named "Sherlock" (live) is kept
  separate from the movie and the series.

- **Director and metadata-year are deliberately excluded** from the ingestion
  key: metadata from TMDb/OMDb is not yet available at channel-upsert time, and
  TV series have many episode directors making the field unreliable.  A coarse
  key safely groups language/quality variants of the same production without
  over-splitting.  When the provider ships a canonical TMDb id it is preferred
  outright (see "TMDb-first identity" above); this heuristic is the fallback for
  the ~48% of VOD rows that carry no id.

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


from metatv.core.channel_name_utils import (
    AUDIO_KEY_NOISE_TOKENS as _AUDIO_KEY_NOISE_TOKENS,
    AUDIO_KEY_ANCHOR_TOKENS as _AUDIO_KEY_ANCHOR_TOKENS,
)


# ---------------------------------------------------------------------------
# Shared normalisation helper
# ---------------------------------------------------------------------------

_NONWORD_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")
# Matches the first four-digit year anywhere in detected_year (e.g. "2015-2018" → "2015").
_YEAR_RE = re.compile(r"\b(\d{4})\b")


def _strip_trailing_audio_noise(norm: str) -> str:
    """Drop a trailing run of bare audio-annotation tokens (the "MULTI" leak).

    Some providers append an audio-track marker as a bare trailing word with no
    bracket/paren delimiter — e.g. ``"the bridge multi"`` or
    ``"the killing multi sub"`` — which ``strip_title_qualifiers`` (bracket/paren
    only) leaves in ``detected_title``.  Those tokens denote the audio track, not
    the production, so two source variants of one title get split content_keys
    ("…|series" vs "…multi|series") and never collapse (QA flag 1ebe93bb).

    The trailing run is removed only when it contains a MULTI/MUTI *anchor*
    (``AUDIO_KEY_ANCHOR_TOKENS``), so standalone real-word titles ending in
    ``"sub"``/``"audio"``/``"dual"`` are preserved, and never when it would empty
    the title (a title literally named "Multi" keeps its key).

    Args:
        norm: An already lowercased, whitespace-collapsed, punctuation-stripped
            title (output of the first three normalisation steps).

    Returns:
        ``norm`` with a trailing MULTI-anchored audio-noise run removed, or
        ``norm`` unchanged when there is no such run.
    """
    tokens = norm.split()
    end = len(tokens)
    while end > 0 and tokens[end - 1] in _AUDIO_KEY_NOISE_TOKENS:
        end -= 1
    if 0 < end < len(tokens) and any(t in _AUDIO_KEY_ANCHOR_TOKENS for t in tokens[end:]):
        return " ".join(tokens[:end])
    return norm


def normalize_title_for_key(title: str) -> str:
    """Lowercase, strip non-word characters, collapse whitespace, drop audio noise.

    **This is THE definition of "same title" for content identity** — the single
    source of truth (CLAUDE.md: single chokepoint).  Anything that decides
    whether two rows describe the same production must call this, not a
    look-alike normaliser, or it will disagree with the key it is reasoning
    about.

    Do NOT substitute ``content_dedup.normalize_title()`` here.  That function
    cleans a **raw provider channel name** (``ChannelDB.name``) — it strips
    provider prefixes, trailing years and quality tokens.  ``detected_title`` has
    already had all of that removed at ingestion, so running it a second time
    double-strips real title words and merges unrelated productions:

    ==========================  ====================  =========================
    detected_title              normalize_title()     normalize_title_for_key()
    ==========================  ====================  =========================
    ``"Blade Runner 2049"``     ``"blade runner"``    ``"blade runner 2049"``
    ``"WWE: Unreal"``           ``"unreal"``          ``"wwe unreal"``
    ``"#Alive"``                ``"alive"``           ``"alive"``
    ==========================  ====================  =========================

    The first two collapse a 2017 sequel into its 1982 original and eat a show
    name mistaken for a provider prefix.  Using them as propagation buckets
    manufactured ambiguity that the remake guard then (correctly) refused to
    resolve — measured against the owner's library, switching the propagation
    pass to this function unlocked 498 previously-blocked adoptions and lost
    none (#284).

    Args:
        title: Raw (but already-stripped) title string, e.g. from
            ``channel.detected_title``.

    Returns:
        Normalised string suitable for use as a key component.  May be empty
        when the entire title is punctuation/whitespace.
    """
    lowered = title.lower()
    no_punct = _NONWORD_RE.sub(" ", lowered)
    collapsed = _WHITESPACE_RE.sub(" ", no_punct).strip()
    return _strip_trailing_audio_noise(collapsed)


def _start_year(detected_year: str) -> str:
    """Extract the first 4-digit year from *detected_year*, or return empty string.

    Handles ranges (``"2015-2018"`` → ``"2015"``), parenthesised years
    (``"(2024)"`` → ``"2024"``), and junk/empty values (``""`` → ``""``).

    Args:
        detected_year: Raw ``detected_year`` value from the channel row.

    Returns:
        The first 4-digit year as a string, or ``""`` when none is found.
    """
    m = _YEAR_RE.search(detected_year)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# TMDb id validation — single source of truth
# ---------------------------------------------------------------------------


def valid_tmdb_id(value) -> str | None:
    """Return a normalized TMDb id string, or ``None`` when *value* is not a real id.

    This is the **single source of truth** for "does the provider's ``tmdb``
    field carry a real canonical id?"  It is imported by both the ingestion
    writer (``providers/xtream.py::convert_to_channel``, which stores the result
    in ``detected_tmdb_id``) and the content-key computation
    (``_XtreamContentKeyStrategy.compute_key``, which reads it back), so the two
    never disagree on what counts.

    Rejects the sentinels providers use for "no id" — ``""``, ``"0"`` (and any
    all-zero string), ``"null"``, ``"None"`` — and any non-numeric value.
    Accepts ``int`` as well as ``str`` (Xtream sometimes ships the id as a
    JSON number); the returned value is always the stripped digit string.

    Args:
        value: The raw ``raw_data["tmdb"]`` value (``str`` / ``int`` / ``None``).

    Returns:
        The canonical id as a digit string (e.g. ``"603"``) when valid, else
        ``None``.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or not s.isdigit():
        return None
    # "0", "00", "000" … are provider sentinels for "no id", not real ids.
    if int(s) <= 0:
        return None
    return s


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

    **TMDb-first (precedence).**  When the row carries a valid stored
    ``detected_tmdb_id`` (populated at ingestion from ``raw_data["tmdb"]``), the
    key is ``"tmdb:{id}|{media_type}"`` and the title/year heuristic is skipped
    entirely.  The ``|{media_type}`` namespace is mandatory: TMDb numbers movies
    and TV series in separate id spaces, so the same integer denotes unrelated
    productions — a bare ``"tmdb:{id}"`` would wrongly merge a movie with a
    same-numbered series.

    Otherwise (no id / sentinel id) the key format varies by media_type:

    * **series / live:** ``"{norm_title}|{media_type}"`` — year omitted.
      Cross-provider year labelling for the same series is noisy (some embed
      a start year, others a range, others nothing), so including year
      over-splits same-production variants.  Mirrors ``content_dedup`` dropping
      director for series.

    * **movie (everything else):** ``"{norm_title}|{media_type}|{start_year}"``
      — year is the first 4-digit group from ``detected_year`` (e.g.
      ``"2015-2018"`` → ``"2015"``; absent/junk → empty string omitted).
      Year is a meaningful remake discriminator for movies.

    Fallback: when ``detected_title`` is empty/None the channel's own ``id``
    is used as the norm_title component so the row always gets a unique key and
    never collapses with unrelated rows.
    """

    def compute_key(self, channel) -> str:
        raw_title: str | None = getattr(channel, "detected_title", None)
        media_type: str = getattr(channel, "media_type", None) or ""
        raw_year: str = getattr(channel, "detected_year", None) or ""

        # TMDb-first: an authoritative provider id pre-empts the heuristic.
        # Namespaced by media_type because TMDb numbers movie vs TV separately —
        # the same int is an unrelated movie and series (never merge them).
        tmdb = valid_tmdb_id(getattr(channel, "detected_tmdb_id", None))
        if tmdb:
            return f"tmdb:{tmdb}|{media_type}"

        if raw_title:
            norm = normalize_title_for_key(raw_title)
        else:
            norm = ""

        if not norm:
            # Fallback: unique per channel so it never merges with anything.
            #
            # NOT logged. This function runs once per catalogue row — 785,163 on
            # the owner's library, and every one of them again on a reparse
            # migration — so a line here is a line per row. It is the same
            # mistake provider_metadata.metadata_from_raw carries a warning
            # about: three DEBUG lines in that function produced 1.30M of 1.44M
            # total log lines and 330 MB, leaving 8 days of history where seven
            # days' retention should have kept 76.
            #
            # It cost nothing to lose. The fallback is documented above, it is
            # deterministic, and the count is one SQL query when anybody wants
            # it (57 rows here — Flo Sports listings that are entirely bracket
            # metadata with no title outside it).
            norm = str(getattr(channel, "id", ""))

        # Series and live: omit year — cross-provider year labels are noisy.
        # Movies: include start year — it discriminates remakes.
        if media_type in ("series", "live"):
            return f"{norm}|{media_type}"
        else:
            year = _start_year(raw_year) if raw_year else ""
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
