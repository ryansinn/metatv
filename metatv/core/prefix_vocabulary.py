"""What a channel-name prefix means — the one test for "does the parser know it?".

A prefix is either one token ("NL", "4K", "ENDED") or a compound a provider
glued with a dash or slash ("BLURAY-DE", "UK-NOWTV", "SD/CAM"). A compound is known
when every part is; each part is looked up in the table that owns its kind —
quality/source in ``quality_vocab``, regions and platforms in ``region_codes``
and the shipped config groups, status and content-type words in
``content_labels``, genres via ``filter_utils.recognized_genre``. Nothing here
holds vocabulary of its own.

Source Analytics' "Unrecognized prefixes" list used to test a prefix against
quality ∪ region ∪ platform only, so status words (LIVE/NEXT/END/ENDED), source
tags (BLURAY), genres (WESTERN), the config groups (AFR) and every compound
were reported as unknown while the parser handled them.
"""

from __future__ import annotations

import re
from functools import lru_cache

from metatv.core.content_labels import CURATED_LIST_PREFIXES, EVENT_STATUS_PREFIXES, LIVE_TV_PREFIXES
from metatv.core.quality_vocab import (
    _AUDIO_NORM, ENCODING_NORM, PREFIX_TIER_TOKENS, QUALITY_TOKENS, SOURCE_TAG_TOKENS, TIER_TOKENS,
)
from metatv.core.region_codes import PLATFORM_CODES, REGION_FULL_NAMES, normalize_region_code


@lru_cache(maxsize=1)
def _group_codes() -> tuple[frozenset[str], frozenset[str]]:
    """(platform codes, locale codes) named by the shipped config groups."""
    from metatv.core.config import BASE_PLATFORM_GROUPS, BASE_PREFIX_GROUPS, BASE_REGIONAL_GROUPS

    def codes(*groups: dict[str, list[str]]) -> frozenset[str]:
        return frozenset(c.upper() for g in groups for members in g.values() for c in members)

    return codes(BASE_PLATFORM_GROUPS), codes(BASE_PREFIX_GROUPS, BASE_REGIONAL_GROUPS)


def _genre(token: str) -> str | None:
    from metatv.core.filter_utils import recognized_genre
    return recognized_genre(token)


def prefix_part_kind(token: str) -> str | None:
    """The kind of one prefix token, or None when no table knows it.

    One of ``"status"``, ``"type"``, ``"quality"``, ``"audio"``, ``"source"``,
    ``"platform"``, ``"region"``, ``"genre"``, ``"list"``. Status is checked before
    platform on purpose: NEXT is also the "Next TV" platform code, but as a
    prefix on an event listing it means "coming up".
    """
    tok = token.strip().upper()
    if not tok:
        return None
    if tok in EVENT_STATUS_PREFIXES:
        return "status"
    if tok in LIVE_TV_PREFIXES:
        return "type"
    if tok in CURATED_LIST_PREFIXES:
        return "list"
    if tok in QUALITY_TOKENS or tok in TIER_TOKENS or tok in PREFIX_TIER_TOKENS or tok in ENCODING_NORM:
        return "quality"
    if tok in _AUDIO_NORM:
        return "audio"
    if tok in SOURCE_TAG_TOKENS:
        return "source"
    platforms, locales = _group_codes()
    if tok in PLATFORM_CODES or tok in platforms:
        return "platform"
    if normalize_region_code(tok) in REGION_FULL_NAMES or tok in locales:
        return "region"
    if _genre(tok):
        return "genre"
    return None


#: What a provider glues a compound prefix with: "BLURAY-DE", "SD/CAM".
_JOINERS = re.compile(r"[-/]")


def _parts(prefix: str) -> list[str]:
    """The whole token when a table knows it, else its dash/slash-separated parts."""
    tok = prefix.strip().upper()
    if prefix_part_kind(tok) or not _JOINERS.search(tok):
        return [tok]
    return _JOINERS.split(tok)


def is_known_prefix(prefix: str) -> bool:
    """True when every part of *prefix* is known vocabulary."""
    parts = _parts(prefix)
    return all(p and prefix_part_kind(p) for p in parts)


def prefix_quality_tokens(prefix: str) -> list[str]:
    """Quality parts of a compound prefix ("SD/CAM" → ["SD", "CAM"]): the tagger
    files each, so a camcorder copy carries CAM even when its chip says SD."""
    parts = _parts(prefix)
    if len(parts) < 2:
        return []        # a lone quality prefix is the parser's detected_quality already
    return [p for p in parts if prefix_part_kind(p) == "quality"]


def prefix_genres(prefix: str) -> list[str]:
    """Canonical genres a prefix names ("WESTERN-DE" → ["Western"])."""
    return [g for p in _parts(prefix) if prefix_part_kind(p) == "genre" and (g := _genre(p))]
