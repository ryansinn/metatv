"""Tags Slice T2 — the shared decomposer (DR-0005).

Single classification chokepoint: turns a raw feeder string into typed
``(type, value)`` tag pairs by **reusing** the classifiers the codebase
already owns.  Pure — no DB, no Qt.

Feeders
-------
``provider_category``
    The raw ``ChannelDB.category`` string from the Xtream API.
    May be a compound like ``"USA | NETFLIX | HD"`` or a plain label.

``header``
    A ``##…##`` section-header label (stripped of hashes) as stored in
    ``ChannelDB.source_category``.  Also compound-style.

``name_parse``
    Already-typed fields from ``parse_channel_name`` / ``update_detected_prefixes``:
    ``detected_prefix``, ``detected_quality``, ``detected_region``,
    ``detected_year``.  These are *passed* as the ``raw`` argument in the
    format ``"PREFIX|QUALITY|REGION|YEAR"`` (pipe-joined, empty string for
    missing fields); the caller must use ``decompose_name_parse()`` instead
    of the raw ``decompose()`` entry point.

``genre``
    A raw genre string from ``raw_data["genre"]`` or a split element from it.

``epg``
    An EPG programme ``category`` or ``genre`` string.

Tag types (fixed namespaces)
----------------------------
- ``region``       — geographic / ISO code (e.g. ``"US"``, ``"ARG"``)
- ``language``     — language group name from config (e.g. ``"English"``)
- ``platform``     — platform group name from config (e.g. ``"Netflix"``)
- ``quality``      — quality group name from config (e.g. ``"HD"``)
- ``genre``        — canonical English genre (e.g. ``"Drama"``)
- ``collection``   — cleaned residual label from header / provider-category
- ``content_type`` — special-content type (``"ppv"``, ``"live_event"``, ``"sports"``)
- ``decade``       — decade string (e.g. ``"1990s"``)

Classifier reuse map
--------------------
- region   ← :func:`~metatv.core.channel_name_utils.normalize_region_code`
             + :data:`~metatv.core.channel_name_utils.REGION_FULL_NAMES`
- language + platform ← config ``filter_language_groups`` / ``filter_platform_groups``
             via :func:`~metatv.core.filter_utils.categorize_prefix`
- quality  ← config ``filter_quality_groups`` via ``categorize_prefix``; also
             :data:`~metatv.core.channel_name_utils.QUALITY_TOKENS` as gate
- genre    ← :func:`~metatv.core.filter_utils.normalize_genre`
- content_type ← :func:`~metatv.core.special_content.detect_and_categorize_channel`
             (name + category string-based sub-classifiers only; no DB object needed)
- collection ← residual token after region/quality/platform tokens are extracted
- decade   ← ``(int(year) // 10) * 10`` from the ``detected_year`` field
"""

from __future__ import annotations

import re
from typing import Sequence

from loguru import logger

from metatv.core.channel_name_utils import (
    PLATFORM_CODES,
    QUALITY_TOKENS,
    REGION_FULL_NAMES,
    normalize_region_code,
)
from metatv.core.filter_utils import DEFAULT_PREFIX_SEPARATORS, categorize_prefix, normalize_genre

# ── Compound-token splitters ────────────────────────────────────────────────── #
# Provider categories / header labels are compound strings like:
#   "USA | NETFLIX | HD"  "FR  ★  MOVIES"  "SPORTS: FOOTBALL"
#   "### WOW SPORT ###"   "DE - ENTERTAINMENT"
# We split on the same separators filter_utils uses plus "|" and "★".

# Additional splitters beyond DEFAULT_PREFIX_SEPARATORS that appear in headers:
_EXTRA_SEPS: list[str] = ["|", "★", ":", " - "]

# Ordered split list: longer/more-specific first (same policy as filter_utils).
_COMPOUND_SEPS: list[str] = sorted(
    set(DEFAULT_PREFIX_SEPARATORS) | set(_EXTRA_SEPS),
    key=len,
    reverse=True,
)

# Noise tokens that should never become a ``collection`` value.
_JUNK_TOKENS: frozenset[str] = frozenset({
    "", "#", "##", "###", "####", "ALL", "LIVE", "END", "MISC",
    "VARIOUS", "OTHER", "GENERAL", "COMMON",
})

# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #


def decompose(
    feeder: str,
    raw: str,
    *,
    config,
) -> list[tuple[str, str]]:
    """Return canonical ``(type, value)`` tags extracted from *raw*.

    Args:
        feeder:  Which pipeline produced *raw*.  One of:
                 ``"provider_category"``, ``"header"``,
                 ``"genre"``, ``"epg"``.
                 Use :func:`decompose_name_parse` for pre-typed ``name_parse`` data.
        raw:     The raw string to classify.
        config:  Live ``Config`` instance (provides ``filter_*_groups``).

    Returns:
        Deduplicated list of ``(type, value)`` pairs.  Unrecognised tokens
        are silently dropped — never mis-typed.

    Pure — no DB, no Qt.
    """
    if not raw or not raw.strip():
        return []

    try:
        if feeder in ("provider_category", "header"):
            tags = _decompose_compound(raw, config)
        elif feeder == "genre":
            tags = _decompose_genre(raw)
        elif feeder == "epg":
            tags = _decompose_epg(raw)
        else:
            logger.warning(
                "tag_decomposer.decompose: unknown feeder {!r} — treating as genre",
                feeder,
            )
            tags = _decompose_genre(raw)
    except Exception:
        logger.exception(
            "tag_decomposer.decompose: error on feeder={!r} raw={!r}", feeder, raw
        )
        return []

    return _dedup(tags)


def decompose_name_parse(
    *,
    detected_prefix: str | None,
    detected_quality: str | None,
    detected_region: str | None,
    detected_year: str | None,
    config,
) -> list[tuple[str, str]]:
    """Return tags from the already-typed ``detected_*`` name-parse fields.

    These fields are computed at ingestion time by ``update_detected_prefixes()``
    and are already parsed / normalized — no re-parsing needed.  We only need to
    promote each to the correct tag type.

    Args:
        detected_prefix:  e.g. ``"EN"``, ``"NF"``, ``"ARG"`` — maps to
                          region / language / platform / quality as appropriate.
        detected_quality: e.g. ``"HD"``, ``"4K"`` — maps to ``quality``.
        detected_region:  secondary lang/region suffix — maps to ``region``/``language``.
        detected_year:    e.g. ``"2024"``, ``"1993-2002"`` — maps to ``decade``.
        config:           Live ``Config`` instance.

    Returns:
        Deduplicated list of ``(type, value)`` pairs.
    """
    tags: list[tuple[str, str]] = []

    if detected_prefix:
        tags.extend(_classify_prefix_token(detected_prefix, config))

    if detected_quality:
        tags.extend(_classify_quality_token(detected_quality, config))

    if detected_region:
        # Secondary lang/region suffix — classify just like a prefix token.
        tags.extend(_classify_prefix_token(detected_region, config))

    if detected_year:
        decade_tag = _year_to_decade(detected_year)
        if decade_tag:
            tags.append(decade_tag)

    return _dedup(tags)


# --------------------------------------------------------------------------- #
#  Per-feeder decomposers (private)                                            #
# --------------------------------------------------------------------------- #


def _decompose_compound(raw: str, config) -> list[tuple[str, str]]:
    """Decompose a compound provider-category or header string.

    Splits on separators and classifies each token.  Any token that is not
    recognized as region / language / platform / quality becomes a candidate
    for ``collection``.

    Examples::

        "USA | NETFLIX | HD"   → [(region,US),(platform,Netflix),(quality,HD)]
        "FR  ★  SERIES"        → [(region,FR),(collection,Series)]
        "### WOW SPORT ###"    → [(collection,Wow Sport)]
        "EN - ENTERTAINMENT"   → [(language,English),(collection,Entertainment)]
    """
    # Strip leading/trailing hash blocks (header format: "## LABEL ##", "###")
    cleaned = re.sub(r"^#+\s*|\s*#+$", "", raw).strip()

    tokens = _split_compound(cleaned)

    tags: list[tuple[str, str]] = []
    residual_parts: list[str] = []

    for tok in tokens:
        tok_upper = tok.upper()

        # Try as quality first (quality tokens are a closed set).
        if tok_upper in QUALITY_TOKENS:
            qtags = _classify_quality_token(tok_upper, config)
            if qtags:
                tags.extend(qtags)
                continue
            # Quality token but no config group → drop, not mis-typed.
            continue

        # Try as region / language / platform via prefix classifier.
        prefix_tags = _classify_prefix_token(tok, config)
        if prefix_tags:
            tags.extend(prefix_tags)
            continue

        # Unclassified → candidate for collection residual.
        residual_parts.append(tok)

    # Build collection from the unclassified residual tokens.
    collection_label = _build_collection(residual_parts)
    if collection_label:
        tags.append(("collection", collection_label))

    return tags


def _decompose_genre(raw: str) -> list[tuple[str, str]]:
    """Decompose a genre string (possibly comma- or slash-delimited).

    Each leaf is normalized via :func:`~metatv.core.filter_utils.normalize_genre`.
    Empty / whitespace leaves are dropped.

    Examples::

        "Drama"          → [(genre,Drama)]
        "Drame"          → [(genre,Drama)]
        "Drama/Comedy"   → [(genre,Drama),(genre,Comedy)]
        "Action, Crime"  → [(genre,Action),(genre,Crime)]
    """
    tags: list[tuple[str, str]] = []
    for leaf in re.split(r"[,/]", raw):
        leaf = leaf.strip()
        if not leaf:
            continue
        canon = normalize_genre(leaf)
        if canon:
            tags.append(("genre", canon))
    return tags


def _decompose_epg(raw: str) -> list[tuple[str, str]]:
    """Decompose an EPG programme category/genre string.

    EPG categories can be genre-like (``"Drama"``, ``"Sport"``) or
    content-type-like (``"News"``, ``"Movies"``).  We try genre first and
    emit ``genre`` for recognised values; unknown strings are dropped
    (not mis-typed as collection — EPG labels are too noisy for that).

    This is intentionally minimal / best-effort as the spec requires.
    """
    tags: list[tuple[str, str]] = []
    for leaf in re.split(r"[,/]", raw):
        leaf = leaf.strip()
        if not leaf:
            continue
        canon = normalize_genre(leaf)
        # If normalize_genre returned a different value, it recognized the genre.
        # If it returned the leaf unchanged, it may still be a valid English genre —
        # include it as-is (pass-through behaviour of normalize_genre).
        if canon:
            tags.append(("genre", canon))
    return tags


# --------------------------------------------------------------------------- #
#  Token classifiers (private helpers)                                         #
# --------------------------------------------------------------------------- #


def _classify_prefix_token(
    token: str,
    config,
) -> list[tuple[str, str]]:
    """Classify a single prefix token into region / language / platform tags.

    Resolution order:
    1. ``categorize_prefix`` against config groups → language / platform.
    2. ``normalize_region_code`` + ``REGION_FULL_NAMES`` → region.
    3. Unrecognized → empty list (dropped, not mis-typed).

    A single token can produce both a ``language`` tag (from its language
    group) AND a ``region`` tag (it's in REGION_FULL_NAMES) — this is
    intentional for codes like ``"EN"`` which is both the English language
    and a region-as-language code in IPTV convention.

    However, we do *not* emit both ``language`` and ``region`` for the same
    token when it maps to a streaming *platform* (e.g. ``"NF"``): platform
    codes are in REGION_FULL_NAMES but are NOT geographic regions.
    """
    tags: list[tuple[str, str]] = []
    tok_upper = token.upper().strip()

    if not tok_upper:
        return tags

    # Quality tokens must never be mis-typed as region/language/platform.
    if tok_upper in QUALITY_TOKENS:
        return tags

    # Ask the config-aware categorizer.
    cats = categorize_prefix(
        tok_upper,
        config.filter_language_groups,
        config.filter_quality_groups,
        config.filter_platform_groups,
    )

    if cats["platform"]:
        # It's a streaming platform — emit platform tag only.
        tags.append(("platform", cats["platform"]))
        return tags

    if cats["language"]:
        tags.append(("language", cats["language"]))

    # Also check region (a code can be in both language and region tables).
    norm = normalize_region_code(tok_upper)
    if norm in REGION_FULL_NAMES and norm not in PLATFORM_CODES:
        tags.append(("region", norm))
        return tags

    # If we found a language group but no region lookup — return language only.
    if tags:
        return tags

    # Pure region lookup (codes not in any config group).
    norm = normalize_region_code(tok_upper)
    if norm in REGION_FULL_NAMES:
        if norm in PLATFORM_CODES:
            # Should have been caught above but be safe: don't mis-type platform as region.
            tags.append(("platform", REGION_FULL_NAMES[norm]))
        else:
            tags.append(("region", norm))

    return tags


def _classify_quality_token(
    token: str,
    config,
) -> list[tuple[str, str]]:
    """Classify a quality token into a ``quality`` tag using config groups.

    If the token is in ``QUALITY_TOKENS`` but not in any configured quality
    group, it is dropped (rather than emitting a raw token that hasn't been
    curated by the user).
    """
    tok_upper = token.upper().strip()
    cats = categorize_prefix(
        tok_upper,
        config.filter_language_groups,
        config.filter_quality_groups,
        config.filter_platform_groups,
    )
    if cats["quality"]:
        return [("quality", cats["quality"])]
    # Token is a known quality literal but has no config group → drop.
    return []


# --------------------------------------------------------------------------- #
#  Helper utilities                                                            #
# --------------------------------------------------------------------------- #


def _split_compound(text: str) -> list[str]:
    """Split a compound token string on known separators.

    Uses the same ordered separator list as filter_utils so that longer /
    more-specific patterns win over shorter ones.

    Returns a list of non-empty, stripped tokens.
    """
    # Replace each separator with a canonical pipe, then split.
    result = text
    for sep in _COMPOUND_SEPS:
        result = result.replace(sep, "\x00")
    parts = [p.strip() for p in result.split("\x00")]
    return [p for p in parts if p]


def _build_collection(parts: Sequence[str]) -> str | None:
    """Produce a ``collection`` value from residual unclassified tokens.

    Filters out noise / punctuation-only tokens, then title-cases and joins.
    Returns ``None`` when nothing meaningful remains.
    """
    cleaned: list[str] = []
    for p in parts:
        upper = p.upper().strip("#").strip()
        if upper in _JUNK_TOKENS:
            continue
        if not upper:
            continue
        # Remove purely-punctuation tokens.
        if re.match(r'^[^\w]+$', upper):
            continue
        # Title-case the token for a clean display label.
        cleaned.append(p.strip("#").strip().title())
    if not cleaned:
        return None
    return " ".join(cleaned)


def _year_to_decade(year_str: str) -> tuple[str, str] | None:
    """Extract a ``decade`` tag from a year or year-range string.

    Accepts ``"2024"``, ``"1993-2002"``, ``"1993–2002"`` (en-dash).
    Uses the *start* year of a range.  Returns ``None`` for unparseable input.

    The decade value follows the convention used in ``discovery_engine``
    (e.g. year 1994 → decade ``"1990s"``).
    """
    if not year_str:
        return None
    # Strip range suffix (e.g. "1993-2002" → "1993", "1993–2002" → "1993")
    m = re.match(r"(\d{4})", year_str)
    if not m:
        return None
    try:
        year = int(m.group(1))
    except ValueError:
        return None
    if year < 1900 or year > 2100:
        return None
    decade = (year // 10) * 10
    return ("decade", f"{decade}s")


def _dedup(tags: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Remove duplicate ``(type, value)`` pairs while preserving order."""
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result
