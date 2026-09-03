"""Ingestion and backfill: the WRITE path of the channel repository.

Everything here computes and stores the ``detected_*`` fields, ``content_key``
and the tmdb id — CLAUDE.md's "compute once at ingestion, read everywhere else"
rule, which is why none of it belongs beside the read surface it feeds.

Why this is a mixin and not free functions
------------------------------------------
``channel_lens.py`` — the extraction this one follows — is a module of PURE
functions because a lens is a query over rows and holds no session state. The
ingestion path is the opposite: it commits in batches, retries a locked write,
and calls its own siblings. Rewriting 1,000 lines of ``self.session`` into
explicit parameters would be a large edit to code whose whole claim is that it
did not change, and every rewritten reference is somewhere behaviour could
silently move. A mixin moves the methods VERBATIM — ``self`` still resolves,
``ChannelRepository`` still answers every call it did before, and no caller
learns a new import. Mixins are already the pattern for this in-tree
(``_AsyncMixin``, ``BackgroundRefreshMixin``).

What stayed behind, and why
---------------------------
``_retry_on_lock`` and its two constants live on ``ChannelRepository``. Every
caller of it is in this file, so moving it was tempting — but the mixin is mixed
INTO the repository, so ``self._retry_on_lock`` resolves either way, and leaving
it keeps ``tests/test_migration_center.py``'s ``channel_mod._LOCK_RETRY_ATTEMPTS``
reference pointing at the module that still defines it.

``_TmdbKeyProxy`` came WITH the move even though ``apply_tmdb_enrichment`` (which
stayed) uses it. Leaving it would have made this module import from
``channel.py`` while ``channel.py`` imports this one — a cycle. Moving it makes
the dependency one-way, and ``channel.py``'s use is genuine, so ruff's F401 is
satisfied without an ``__all__`` re-export.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger
from sqlalchemy import func, or_, update

from metatv.core.channel_name_utils import (
    AI_VOICEOVER_VALUE,
    _COMPOUND_PREFIX_RE,
    _PAREN_PREFIX_RE,
    AUDIO_LANG_WORD_MAP,
    QUALITY_TOKENS,
    detect_ai_provenance,
    is_restricted,
    normalize_region_code,
    parse_category_marker,
    parse_channel_name,
    strip_collection_noise_tokens,
)
from metatv.core.content_identity import content_key_for, valid_tmdb_id
from metatv.core.fixture_titles import fixture_ingest_title
from metatv.core.repositories.sweep_guard import single_flight
from metatv.core.database import ChannelDB, MetadataDB
from metatv.core.filter_utils import extract_prefix, genres_from_raw
from metatv.core.tag_decomposer import region_code_from_category

# Moved here WITH _start_year_int, its only user (CLAUDE.md: take the private
# helpers with the concern — a move that leaves them behind grows the total).
_YEAR4_RE = re.compile(r"\b(\d{4})\b")

class _TmdbKeyProxy:
    """Minimal duck-typed channel for :func:`content_key_for` (tmdb-first path).

    ``content_key_for`` reads its inputs via ``getattr(..., default)``; a valid
    ``detected_tmdb_id`` short-circuits to ``"tmdb:{id}|{media_type}"`` before the
    title/year fields are consulted, so only these three attributes are needed to
    recompute the key when the enrichment discovers an id.
    """

    __slots__ = ("detected_tmdb_id", "media_type", "id")

    def __init__(self, detected_tmdb_id: str, media_type: str, id: str) -> None:
        self.detected_tmdb_id = detected_tmdb_id
        self.media_type = media_type
        self.id = id

def _start_year_int(detected_year) -> Optional[int]:
    """Return the first 4-digit year in *detected_year* as an int, or ``None``.

    Mirrors ``content_identity._start_year`` (ranges ``"2015-2018"`` → 2015,
    ``"(2024)"`` → 2024, junk/empty → ``None``) but yields an ``int`` for the
    ``abs(a - b) <= 1`` remake-compatibility comparison used by the tmdb
    title-sibling propagation.
    """
    if not detected_year:
        return None
    m = _YEAR4_RE.search(str(detected_year))
    return int(m.group(1)) if m else None

def _contradicts_own_locale(own_prefix: str | None, candidate_region: str) -> bool:
    """True when *candidate_region* would contradict the row's own locale prefix.

    A row prefixed ``|EN|`` or ``|AR|`` already states its locale. Its
    ``detected_region`` is empty for a specific reason — ``EN`` is a
    language-only code (:data:`CODE_FACETS` documents that there is no place
    called "EN"), not because the row lacks evidence. Treating that emptiness as
    a gap and filling it from the sibling majority actively mislabels the row.

    This matters because ``content_key`` is deliberately generous: the key
    ``"aladdin|movie|"`` (no year, no TMDb id) collapses 15 unrelated releases,
    so the "most common sibling region" is whichever locale happens to dominate
    the user's library — which stamped ``DE`` onto the ``|EN|`` and ``|AR|``
    Aladdin rows, reporting an Arabic release as German.

    Returns False when the prefix is absent or is not a recognised locale code
    (e.g. ``MULTI``, ``4K``), where the row genuinely has no locale of its own
    and inheriting a sibling's region is the intended behaviour.

    Args:
        own_prefix: The row's ``detected_prefix``.
        candidate_region: The region the sibling majority would write.

    Returns:
        True if the fill should be skipped.
    """
    from metatv.core.channel_name_utils import CODE_FACETS, normalize_region_code

    code = normalize_region_code((own_prefix or "").strip())
    if not code or code not in CODE_FACETS:
        return False
    # The prefix IS a known locale code. Allow only the case where the sibling
    # agrees with a region this very code implies (e.g. "IT" → region IT).
    implied = {
        value for facet, value, _conf in CODE_FACETS[code] if facet == "region"
    }
    return normalize_region_code(candidate_region) not in implied


class _FullKeyProxy:
    """Duck-typed row for ``content_key_for`` when there may be NO tmdb id.

    Sibling of :class:`_TmdbKeyProxy`, and deliberately not merged with it: that
    one carries three attributes because a row WITH a tmdb id keys on the id
    alone, while this one must also carry title/year for the fallback key. Same
    shape, different policy — collapsing them would quietly widen what the tmdb
    path reads.

    It was previously declared INSIDE the per-row loop, so the class object was
    rebuilt once per channel across a 484k-row pass.
    """

    __slots__ = ("detected_title", "media_type", "detected_year",
                 "detected_tmdb_id", "id")

    def __init__(self, t, m, y, tmdb, i) -> None:
        self.detected_title = t
        self.media_type = m
        self.detected_year = y
        self.detected_tmdb_id = tmdb
        self.id = i


class ChannelIngestionMixin:
    """The ingestion/backfill half of :class:`ChannelRepository`.

    Mixed into the repository, so every method below sees the same ``self``
    it always did — ``self.session``, ``self._retry_on_lock``, and its own
    siblings. Nothing here is called directly off this class.
    """

    def update_detected_prefixes(
        self,
        provider_id: Optional[str] = None,
        separators: list[str] | None = None,
        progress_cb=None,
        is_cancelled=None,
        config=None,
    ):
        """Update detected_prefix, detected_quality, and detected_region for all channels.

        - detected_prefix: raw separator-delimited prefix token (e.g. "EN", "4K")
        - detected_quality: quality token found anywhere in the name (suffix or quality-prefix)
        - detected_region: parenthetical lang/region qualifier at end of name (e.g. "(US)"→"US")

        ``detected_region`` precedence (each step is **fill-empty-only** — a value
        set by an earlier step is never overwritten by a later one):

        1. **Name token** — bracket secondary / parenthetical lang-region suffix
           parsed from the channel name (highest priority, unchanged behavior).
        2. **Own provider-category code** — when the name yields no region, derive
           it from ``channel.category`` (e.g. ``"|FR|"`` → ``"FR"``) via
           :func:`~metatv.core.tag_decomposer.region_code_from_category` (the same
           extraction that produces the region tag facet — single source of truth).
        3. **content_key sibling** — a final cross-source pass copies a region onto
           any still-empty row from a sibling sharing the same (non-NULL)
           ``content_key``.  See :meth:`_propagate_region_from_siblings`.

        Args:
            provider_id: Only update channels for this provider, or None for all.
            separators: Ordered list of separator strings to try. Defaults to
                ``DEFAULT_PREFIX_SEPARATORS`` from filter_utils when None.
            progress_cb: Optional ``(done: int, total: int) -> None`` called after
                each batch commit.  ``done`` is non-decreasing and ends at
                ``total`` on full completion.  Pass ``None`` (default) to skip
                progress reporting (existing callers are unaffected).
            is_cancelled: Optional ``() -> bool`` checked at the top of each
                batch iteration.  When it returns True the loop exits early;
                already-committed batches are durable but the task is not marked
                complete (version not bumped by the manager).  Pass ``None``
                (default) to run without cancellation support.
            config: Optional live ``Config`` instance — supplies the filter groups
                the category→region extraction consults.  Loaded lazily (default
                ``Config()``) when ``None`` so existing callers are unaffected.
        """
        _BATCH = 2000

        # The category→region fallback (step 2) needs the filter groups; load a
        # default Config once when the caller didn't pass one.
        if config is None:
            from metatv.core.config import Config
            config = Config()

        id_query = self.session.query(ChannelDB.id)
        if provider_id:
            id_query = id_query.filter(ChannelDB.provider_id == provider_id)
        all_ids = [row[0] for row in id_query.all()]
        total = len(all_ids)

        updated = 0
        processed = 0

        for batch_start in range(0, total, _BATCH):
            # Check for cancellation before starting each batch
            if is_cancelled is not None and is_cancelled():
                logger.info(
                    "update_detected_prefixes: cancelled at batch_start={}/{}",
                    batch_start,
                    total,
                )
                break

            chunk_ids = all_ids[batch_start : batch_start + _BATCH]
            batch_updated, batch_processed = self._commit_prefix_batch_with_retry(
                chunk_ids, separators, config,
            )
            updated += batch_updated
            processed += batch_processed

            # Expunge between batches to release ORM objects from memory before
            # loading the next chunk.  After the last batch there is nothing to
            # free, so we skip the expunge to leave any caller-held references
            # in a usable state (expunge_all would detach them).
            if batch_start + _BATCH < total:
                self.session.expunge_all()

            # Report progress after each committed batch
            if progress_cb is not None:
                progress_cb(min(batch_start + _BATCH, total), total)

        # Step 3: cross-source sibling propagation — fill any still-empty
        # detected_region from a row sharing the same content_key. Skipped after a
        # cancellation (partial per-row state — don't propagate from it).
        sib_filled = 0
        tmdb_adopted = 0
        if not (is_cancelled is not None and is_cancelled()):
            # Both propagation phases below are bulk writers just like the batch
            # loop above and hit the identical lock-contention hazard (owner log
            # 2026-08-01 18:48: propagate_tmdb_from_title_siblings crashed on
            # `database is locked` at its bulk UPDATE, uncovered by #367's
            # batch-only retry). Both methods retry internally via the same
            # shared `_retry_on_lock` helper the batch loop uses, so every
            # write phase of this method gets identical lock-contention
            # coverage — including their OTHER caller, the standalone
            # tmdb_sibling_propagation migration task.
            sib_filled = self._propagate_region_from_siblings(provider_id)
            # Free (no-network) tmdb propagation: an idless row self-heals by adopting
            # a confident same-title sibling's detected_tmdb_id so new content collapses
            # without waiting for a background provider-detail fetch. Same shared helper
            # the one-time migration uses.
            tmdb_adopted = self.propagate_tmdb_from_title_siblings(provider_id)

        logger.info(
            f"Updated parsed name fields for {updated} of {processed} channels "
            f"(+{sib_filled} regions filled from content_key siblings, "
            f"+{tmdb_adopted} tmdb ids from title siblings)"
        )
        return updated

    def _commit_prefix_batch_with_retry(
        self,
        chunk_ids: list[str],
        separators: list[str] | None,
        config,
    ) -> tuple[int, int]:
        """Run one ``update_detected_prefixes`` batch, retrying on a transient lock.

        Delegates the actual query/compute/commit to :meth:`_process_prefix_batch`
        via the shared :meth:`_retry_on_lock` helper, which retries the *whole*
        batch (query included) — a failed commit leaves the session's in-memory
        changes expired after rollback, so re-running just ``session.commit()``
        would flush nothing; the batch must be recomputed from a fresh query.

        Args:
            chunk_ids: Channel ids in this batch.
            separators: Prefix separators passed through to per-channel parsing.
            config: Live ``Config`` instance for the category→region fallback.

        Returns:
            ``(batch_updated, batch_processed)`` from the successful attempt.
        """
        return self._retry_on_lock(
            "update_detected_prefixes: batch",
            self._process_prefix_batch,
            chunk_ids,
            separators,
            config,
        )

    def _process_prefix_batch(
        self,
        chunk_ids: list[str],
        separators: list[str] | None,
        config,
    ) -> tuple[int, int]:
        """Query, parse, and commit one ``update_detected_prefixes`` batch.

        Extracted from ``update_detected_prefixes`` so a lock retry
        (:meth:`_commit_prefix_batch_with_retry`) can re-run the whole batch —
        query, per-channel parse, and commit — from scratch, since a failed
        commit's rollback expires the session's pending in-memory changes and a
        bare retried ``commit()`` would have nothing left to flush.

        Args:
            chunk_ids: Channel ids in this batch.
            separators: Prefix separators passed through to per-channel parsing.
            config: Live ``Config`` instance for the category→region fallback.

        Returns:
            ``(batch_updated, batch_processed)`` — channels actually changed vs.
            total channels queried in this batch.
        """
        channels = self.session.query(ChannelDB).filter(
            ChannelDB.id.in_(chunk_ids)
        ).all()

        batch_updated = 0
        for channel in channels:
            raw_prefix = extract_prefix(channel.name, separators=separators)
            # Normalize full country/language names to standard codes:
            # "NIGERIA" → "NGA", "ENGLISH" → "EN", "TELUGU" → "TE", etc.
            prefix = normalize_region_code(raw_prefix) if raw_prefix else raw_prefix
            # Reject digit-only codes — these are provider-internal category numbers
            # (e.g. "300" from "300  - 2007"), not valid display prefixes.
            if prefix and re.match(r'^\d+$', prefix):
                prefix = None
                raw_prefix = None

            parsed = parse_channel_name(channel.name)

            # ── Compound prefix decomposition ────────────────────────────────── #
            # Handles "4K-DE - Title" (quality+lang), "SE-4K - Title" (lang+quality),
            # "PL 4K - Title" (lang+space+quality), and "[US] 4K-DE - Title" (bracket
            # before compound). When a compound is found the lang part overrides the
            # extracted prefix and the bracket (if any) moves to detected_region.
            compound_quality: str | None = None
            bracket_as_region: str | None = None

            cm = _COMPOUND_PREFIX_RE.match(channel.name)
            if cm:
                bracket    = cm.group("bracket")
                compound_lang = (
                    cm.group("lang_a") or cm.group("lang_b") or cm.group("lang_c") or ""
                ).upper()
                compound_q = (
                    cm.group("qual_a") or cm.group("qual_b") or cm.group("qual_c") or ""
                ).upper()

                # Guard: skip if the "lang" slot is itself a quality token (e.g. 4K-HD)
                if compound_lang and compound_lang not in QUALITY_TOKENS:
                    prefix = normalize_region_code(compound_lang)
                    compound_quality = compound_q or None
                    if bracket:
                        bracket_as_region = normalize_region_code(bracket)

            # Paren prefix: (QFR) Title — parenthetical code at start, not caught by extract_prefix
            if not cm:
                pm = _PAREN_PREFIX_RE.match(channel.name)
                if pm:
                    paren_code = pm.group(1).upper()
                    if paren_code not in QUALITY_TOKENS:
                        prefix = normalize_region_code(paren_code)

            # detected_quality priority:
            #   1. Name suffix  ("CNN HD" → "HD")
            #   2. Compound prefix quality  ("4K" from "4K-DE - Title")
            #   3. Quality-as-prefix  ("HD - Movie" → "HD")
            #   4. API quality field  (channel.quality = "hd" → "HD")
            quality: str | None = None
            if parsed.quality:
                quality = parsed.quality[0].upper()
            elif compound_quality:
                quality = compound_quality
            elif prefix and prefix.upper() in QUALITY_TOKENS:
                quality = prefix.upper()
                prefix = None  # quality token must not display as a category prefix
            elif channel.quality and channel.quality.upper() not in ("UNKNOWN", ""):
                api_q = channel.quality.upper()
                if api_q in QUALITY_TOKENS:
                    quality = api_q

            # Safety net: Guard #3 only fires when Guards 1 and 2 didn't. If Guard 1
            # (parsed.quality) fired first, prefix is still "4K". Clear it here regardless.
            if prefix and prefix.upper() in QUALITY_TOKENS:
                prefix = None

            # If prefix was cleared (quality token) or rejected (numeric guard), fall back to
            # what parse_channel_name extracted in step 1. This lets "[4K] [US] Title" store
            # detected_prefix = "US" rather than None after Guard #3 cleared "4K".
            if prefix is None and parsed.region:
                prefix = parsed.region

            # detected_region: bracket secondary (from compound decomposition) takes
            # priority, then parenthetical lang/region suffix (e.g. "(US)" → "US")
            region: str | None = bracket_as_region or parsed.lang or None

            # AI-provenance marker (single source of truth: detect_ai_provenance).
            # A trailing "(AI)" voiceover marker is TWO uppercase letters, so
            # parse_channel_name reads it as a bogus lang/region qualifier ("AI",
            # which is also the ISO code for Anguilla) and leaks it into region.
            # Clear it here — the marker is an AI dub, not a locale — so the
            # category/sibling fallbacks below can still fill a real region and no
            # bogus region facet is ever produced.  The content_type:ai_voiceover
            # tag carries the real signal.
            _ai_raw = detect_ai_provenance(channel.name)
            if (_ai_raw is not None and _ai_raw.value == AI_VOICEOVER_VALUE
                    and region and region.upper() == "AI"):
                region = None

            # Fill-empty fallback (step 2): when the NAME carries no region,
            # derive it from the provider category (e.g. "|FR|" → "FR") via the
            # shared tag_decomposer extraction. Never overwrites a name-derived
            # region; only explicit region codes qualify (free text → None).
            if not region and channel.category:
                region = region_code_from_category(channel.category, config=config)

            # ── Category marker (owner report: "|EN| ANIME" style leading
            # marker duplicates channel-name language/subtitle info and
            # crowds the title). Strips the marker into the clean
            # detected_collection text and routes the token by kind — never
            # guessing beyond a plain language code or a recognized SUB/DUB
            # compound (see parse_category_marker):
            #   - plain language code: adopted as detected_prefix ONLY when
            #     the channel has none of its own (mirrors the detected_region
            #     fill-empty-only pattern above); when the channel already has
            #     its own prefix, the marker is kept — UNLESS it merely
            #     repeats that same prefix — as detected_collection_language
            #     so it can render its own "other language" chip. Nothing is
            #     silently dropped on disagreement.
            #   - compound "CODE-SUB"/"CODE-DUB": routed to the EXISTING
            #     detected_audio sub/dub facet (below) AND kept as its own
            #     chip-ready display value (detected_collection_subdub, e.g.
            #     "AR-SUB") — never treated as a language.
            # After the marker is stripped, strip_collection_noise_tokens()
            # (channel_name_utils.py) removes whatever's LEFT that merely
            # repeats a chip/icon the row already paints elsewhere — a
            # quality tier (the quality chip), a media-type word (the media
            # icon), or a multi/sub marker (the subtitle-marker chip), e.g.
            # "MULTISUB SERIES 4K" -> "" (every token redundant) or
            # "|MULTI| APPLE+ KIDS" -> "APPLE+ KIDS". A whole-noise SPAN
            # clears entirely ("SERIES MANIA" survives intact — MANIA isn't
            # noise); a TRAILING quality/sub-dub/multi word also gets peeled
            # off a real name even when the rest is kept ("FILMOVI 4K UHD"
            # -> "FILMOVI"), but a media-type word never is ("TAMIL MOVIES"
            # stays — see strip_collection_noise_tokens()'s docstring).
            new_collection: str | None = None
            new_collection_language: str | None = None
            new_collection_subdub: str | None = None
            _marker_sub_lang: str | None = None
            _marker_dub_lang: str | None = None
            if channel.category:
                clean_category, category_marker = parse_category_marker(channel.category)
                new_collection = clean_category or None
                # Strip tokens already conveyed elsewhere on the row (quality
                # chip / media-type icon / subtitle-marker chip) — see
                # strip_collection_noise_tokens() docstring for the "whole
                # span must be noise" rule that keeps a real collection name
                # like "SERIES MANIA" intact. Normalize a fully-noise result
                # ("") back to None, same as the clean_category line above.
                new_collection = strip_collection_noise_tokens(new_collection) or None
                if category_marker is not None:
                    if category_marker.kind == "language":
                        if prefix is None:
                            prefix = category_marker.code
                        elif category_marker.code != prefix:
                            new_collection_language = category_marker.code
                    else:
                        new_collection_subdub = f"{category_marker.code}-{category_marker.kind.upper()}"
                        _lang_name = AUDIO_LANG_WORD_MAP.get(
                            category_marker.code, category_marker.code
                        )
                        if category_marker.kind == "sub":
                            _marker_sub_lang = _lang_name
                        else:
                            _marker_dub_lang = _lang_name

            new_title = fixture_ingest_title(channel) or parsed.bare_name or None
            new_year  = parsed.year or None

            # If extract_prefix set a prefix that parse_channel_name couldn't strip
            # (_SEPARATOR_RE requires [A-Z] first char, so digit-starting codes like "24/7"
            # are not handled), do the strip manually now.
            if prefix and raw_prefix and new_title:
                _strip_m = re.match(
                    rf'^{re.escape(raw_prefix)}\s*(?:[★|]|-\s+)\s*(.+)$',
                    new_title,
                    re.IGNORECASE,
                )
                if _strip_m:
                    new_title = _strip_m.group(1).strip()

            # AI VOICEOVER title cleanup (safety net).  parse_channel_name almost
            # always strips a trailing "(AI)" already (it reads the two letters as
            # a lang qualifier), but if any voiceover marker survives into the
            # title, strip it here so the display title is clean and collapses onto
            # the base production — the content_type:ai_voiceover tag preserves the
            # distinction.  An "(AI Generated)" content marker is DELIBERATELY LEFT
            # in new_title: it flows into content_key below so a fabricated work
            # never shares a content_key with a real same-title production (keeping
            # content_key_for a single, consistent read of the stored detected_title
            # — no new identity machinery).  Only the recognized marker is touched.
            if new_title:
                _ai_title = detect_ai_provenance(new_title)
                if _ai_title is not None and _ai_title.value == AI_VOICEOVER_VALUE:
                    new_title = _ai_title.cleaned_name or None

            # Compute detected_audio from parsed audio fields, merging in any
            # sub/dub language the category marker above contributed (its own
            # display chip is separate — detected_collection_subdub — but the
            # underlying language must ALSO land in the existing queryable
            # sub/dub facet, never fold in silently as a language).
            # Store None when there is no audio annotation so the column is cheap
            # (no JSON blob for the vast majority of channels with no sub/dub tag).
            new_detected_audio = None
            _audio_langs = list(parsed.audio_langs)
            _dub_langs = list(parsed.dub_langs)
            _sub_langs = list(parsed.sub_langs)
            if _marker_sub_lang and _marker_sub_lang not in _sub_langs:
                _sub_langs.append(_marker_sub_lang)
            if _marker_dub_lang and _marker_dub_lang not in _dub_langs:
                _dub_langs.append(_marker_dub_lang)
            if parsed.audio or _audio_langs or _dub_langs or _sub_langs:
                new_detected_audio = {
                    "form":  parsed.audio or "",
                    "audio": _audio_langs,
                    "dub":   _dub_langs,
                    "sub":   _sub_langs,
                }
                # Normalize: drop all-empty dict to None
                if (not new_detected_audio["form"]
                        and not new_detected_audio["audio"]
                        and not new_detected_audio["dub"]
                        and not new_detected_audio["sub"]):
                    new_detected_audio = None

            # Compute canonical genre(s) from raw_data["genre"] (#genre-perf).
            # genres_from_raw() canonicalises each '/'/',' segment (cross-language
            # alias collapse + HTML-entity unescape). detected_genre = first
            # segment (display); detected_genres = every segment (shelf
            # membership via json_each in get_by_genre).
            _raw_genre_str = (channel.raw_data or {}).get("genre") if channel.raw_data else None
            _genre_list = genres_from_raw(_raw_genre_str)
            new_detected_genre  = _genre_list[0] if _genre_list else None
            new_detected_genres = _genre_list or None

            # Restricted-content detection (owner-reported gap): the provider's
            # is_adult flag is unreliable, so this catches XXX/ADULT/X-prefix naming
            # conventions it misses. Reads the UPDATED prefix (this batch's computed
            # value, not the old ORM one) so a channel whose prefix changes in this
            # same pass is judged on its new prefix. Separate provenance from
            # is_adult — never overwrites it. Detection is the user own "Adult" prefix
            # group + their (empty by default) restricted_keywords list.
            new_restricted = is_restricted(
                prefix, channel.name, config, collection=new_collection
            )

            # Compute the content_key from the UPDATED fields (not the old ORM values)
            # so the key is always in sync with detected_title/year/media_type.
            # Build a lightweight proxy that reflects the new field values without
            # mutating the channel yet — this lets us include content_key in the
            # changed comparison atomically.
            # detected_tmdb_id is a provider fact captured at ingestion (not
            # recomputed here) — read the already-stored value so the recomputed
            # content_key stays tmdb-first when the provider shipped an id.
            class _NewFields:
                __slots__ = (
                    "detected_title", "media_type", "detected_year",
                    "detected_tmdb_id", "id",
                )
                def __init__(self, title, mt, year, tmdb_id, ch_id):
                    self.detected_title = title
                    self.media_type = mt
                    self.detected_year = year
                    self.detected_tmdb_id = tmdb_id
                    self.id = ch_id
            new_content_key = content_key_for(
                _NewFields(
                    new_title, channel.media_type, new_year,
                    channel.detected_tmdb_id, channel.id,
                )
            )

            # Trailing credits the parser identified and used to discard —
            # "NICOLAS CAGE" from "… (2002) NICOLAS CAGE". An inference, stored
            # so render/query code reads a field instead of re-parsing (CLAUDE.md
            # rule); None rather than "" so "no credits" and "not yet parsed"
            # stay distinguishable.
            new_name_cast = (parsed.trailing or "").strip() or None

            # Collection the parser recognised after a mid-name year
            # ("Hallmark").  Only the collection kind is stored: dub/genre/
            # rating/quality trailers are correctly removed from the title, but
            # they already have provider-denoted homes and overwriting those
            # with a name guess would lose better data.
            _meta = parsed.trailing_meta
            new_name_collection = (
                _meta[1] if _meta and _meta[0] == "collection" and _meta[1] else None
            )

            # Episode identity out of the name. Stored so a render never
            # re-parses (compute-once), and so the marker leaves detected_title
            # — which is what lets content_key collapse 414 Konusanlar rows.
            new_season = parsed.season or None
            new_episode = parsed.episode or None

            changed = (
                prefix != channel.detected_prefix
                or quality != channel.detected_quality
                or region != channel.detected_region
                or new_title != channel.detected_title
                or new_year  != channel.detected_year
                or new_content_key != channel.content_key
                or new_name_collection != channel.detected_name_collection
                or new_detected_audio != channel.detected_audio
                or new_detected_genre != channel.detected_genre
                or new_detected_genres != channel.detected_genres
                or new_restricted != bool(channel.detected_restricted)
                or new_collection != channel.detected_collection
                or new_collection_language != channel.detected_collection_language
                or new_collection_subdub != channel.detected_collection_subdub
                or new_name_cast != channel.detected_name_cast
                or new_season != channel.detected_season
                or new_episode != channel.detected_episode
            )
            if changed:
                channel.detected_prefix = prefix
                channel.detected_quality = quality
                channel.detected_region = region
                channel.detected_title  = new_title
                channel.detected_year   = new_year
                channel.content_key     = new_content_key
                channel.detected_audio  = new_detected_audio
                channel.detected_genre  = new_detected_genre
                channel.detected_genres = new_detected_genres
                channel.detected_restricted = new_restricted
                channel.detected_collection = new_collection
                channel.detected_collection_language = new_collection_language
                channel.detected_collection_subdub = new_collection_subdub
                channel.detected_name_cast = new_name_cast
                channel.detected_name_collection = new_name_collection
                channel.detected_season = new_season
                channel.detected_episode = new_episode
                channel.updated_at = datetime.now()
                batch_updated += 1

        self.session.commit()
        return batch_updated, len(channels)

    def _propagate_region_from_siblings(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Fill empty ``detected_region`` from a same-``content_key`` sibling.

        Retries the whole pass on a transient lock via the shared
        :meth:`_retry_on_lock` helper — see :meth:`_propagate_region_from_siblings_impl`
        for the actual logic and docstring.
        """
        return self._retry_on_lock(
            "update_detected_prefixes: region-sibling propagation",
            self._propagate_region_from_siblings_impl,
            provider_id,
        )

    def _propagate_region_from_siblings_impl(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Fill empty ``detected_region`` from a same-``content_key`` sibling.

        Final fill-empty-only pass of :meth:`update_detected_prefixes`.  A row
        whose name AND provider-category yielded no region inherits one from a
        sibling sharing its (non-NULL) ``content_key`` — the cross-source content
        identity (DR-0009).  Synthetic ``id:``-keyed singletons (NULL
        ``content_key``) have no siblings and are skipped.

        Winner selection when siblings disagree: the **most common** region code
        across all siblings; ties broken by the **alphabetically-first** code — a
        stable, deterministic order independent of row/scan order.

        Never overwrites a row that already has a region.  Sibling regions are
        read across **all** providers (content identity is source-independent);
        when *provider_id* is given, only that provider's rows are filled.

        Idempotent / retry-safe: only fills rows that are still empty, so a
        retried run after a partial commit simply re-scans and re-applies
        whatever the last successful commit didn't cover — see
        :meth:`_propagate_region_from_siblings` (the public entry point, which
        wraps this in the shared lock-retry helper).

        Args:
            provider_id: Restrict the rows that get filled to this provider, or
                None to fill across the whole library.

        Returns:
            Number of rows that had ``detected_region`` written.
        """
        from collections import Counter, defaultdict

        _BATCH = 2000

        # NB: do NOT expunge_all() here — update_detected_prefixes intentionally
        # leaves the last batch's ORM objects attached so callers can refresh/read
        # them afterward.  The queries below use column projections and the fills
        # use bulk UPDATEs, neither of which needs a clean identity map.

        # 1. Winner map: content_key -> region. Built from a GROUP BY (one row per
        #    distinct key+region) so memory is bounded by distinct keyed regions.
        counters: dict[str, Counter] = defaultdict(Counter)
        grouped = (
            self.session.query(
                ChannelDB.content_key,
                ChannelDB.detected_region,
                func.count().label("n"),
            )
            .filter(ChannelDB.content_key.isnot(None))
            .filter(ChannelDB.detected_region.isnot(None))
            .filter(ChannelDB.detected_region != "")
            .group_by(ChannelDB.content_key, ChannelDB.detected_region)
            .all()
        )
        for key, region, n in grouped:
            counters[key][region] += n

        winner: dict[str, str] = {}
        for key, counter in counters.items():
            # (-count, region): most common first, alphabetical tie-break.
            winner[key] = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        if not winner:
            return 0

        # 2. Fill empty rows whose content_key has a winner (scoped if asked).
        empty_q = (
            self.session.query(
                ChannelDB.id, ChannelDB.content_key, ChannelDB.detected_prefix
            )
            .filter(ChannelDB.content_key.isnot(None))
            .filter(
                or_(
                    ChannelDB.detected_region.is_(None),
                    ChannelDB.detected_region == "",
                )
            )
        )
        if provider_id:
            empty_q = empty_q.filter(ChannelDB.provider_id == provider_id)
        empty_rows = empty_q.all()

        filled = 0
        for ch_id, key, own_prefix in empty_rows:
            region = winner.get(key)
            if not region:
                continue
            if _contradicts_own_locale(own_prefix, region):
                # The row carries its OWN locale code, so an empty region is a
                # fact about that code (there is no place called "EN"), not a
                # gap to fill from someone else. Inheriting the sibling majority
                # here mislabels the row: a generic content_key like
                # "aladdin|movie|" collapses 15 unrelated releases, and the
                # majority region (DE in the owner's library) was being stamped
                # onto the |EN| and |AR| rows — an Arabic release reported as
                # German. Leave it empty; empty is honest.
                continue
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id == ch_id)
                .values(detected_region=region, updated_at=datetime.now())
            )
            filled += 1
            if filled % _BATCH == 0:
                self.session.commit()

        self.session.commit()
        return filled

    def propagate_tmdb_from_title_siblings(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Adopt a confident same-title sibling's ``detected_tmdb_id`` onto idless rows.

        Whole-library passes are single-flight (see
        :mod:`metatv.core.repositories.sweep_guard` for why, and what it cost).
        A ``provider_id``-scoped call is NOT gated: narrow, cheap, and may not
        overlap the running pass at all.

        Retries the whole pass on a transient lock via the shared
        :meth:`_retry_on_lock` helper — this is the site that crashed
        uncovered on 2026-08-01 (owner log: ``database is locked`` inside this
        method's bulk ``UPDATE``, which #367's batch-only retry didn't reach).
        See :meth:`_propagate_tmdb_from_title_siblings_impl` for the actual
        logic and full docstring.
        """
        if provider_id is not None:
            return self._retry_on_lock(
                "propagate_tmdb_from_title_siblings",
                self._propagate_tmdb_from_title_siblings_impl,
                provider_id,
            )

        with single_flight("propagate_tmdb_from_title_siblings") as mine:
            if not mine:
                return 0
            return self._retry_on_lock(
                "propagate_tmdb_from_title_siblings",
                self._propagate_tmdb_from_title_siblings_impl,
                provider_id,
            )

    def _propagate_tmdb_from_title_siblings_impl(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Adopt a confident same-title sibling's ``detected_tmdb_id`` onto idless rows.

        Free (no-network) Phase-2 pass.  For each idless VOD row
        (``detected_tmdb_id IS NULL``), if a sibling shares the **same normalized
        ``detected_title``** (via :func:`content_identity.normalize_title_for_key`
        — the SAME normaliser that computes ``content_key``, never a look-alike)
        **and the same ``media_type``** and is **year-compatible**, adopt that
        sibling's id:
        store ``detected_tmdb_id``, recompute ``content_key`` through the
        :func:`~metatv.core.content_identity.content_key_for` chokepoint (tmdb-first
        → ``"tmdb:{id}|{media_type}"``), and mark ``tmdb_enrich_state='propagated'``.

        Year-compat / remake guard: a sibling is *year-compatible* when either row
        lacks a ``detected_year`` or their start years differ by ≤ 1.  Among the
        year-compatible id-bearing siblings a row adopts an id **only when exactly
        one distinct id remains** — multiple distinct ids (a genuine remake split)
        are ambiguous and skipped (never guess between remakes).

        **The bucket normaliser is load-bearing for that guard (#284).**  This pass
        used ``content_dedup.normalize_title`` — a *raw channel name* cleaner — on
        ``detected_title``, which ingestion has already prefix/year/quality-stripped.
        Double-stripping merged unrelated productions into one bucket
        ("Blade Runner 2049" → ``blade runner``, joining the 1982 film; "WWE: Unreal"
        → ``unreal``, its show name eaten as a provider prefix).  The bucket then held
        several ids, and the guard above refused to guess — so the pass skipped rows
        whose evidence was actually unambiguous.  Measured on the owner's library,
        grouping by the key's own normaliser unlocked 498 adoptions and lost zero.

        Sibling ids are read across **all** providers (content identity is
        source-independent); when *provider_id* is given only that provider's idless
        rows are filled (the ingestion-hook path — new content self-heals against the
        whole library).  Only the generated ``detected_tmdb_id`` / ``content_key`` /
        ``tmdb_enrich_state`` columns are written — user tags/ratings/favorites are
        never touched (mirror-not-cage).  Shared by the one-time migration
        (``tmdb_sibling_propagation``) and ``update_detected_prefixes`` so both paths
        use one definition.

        Idempotent / retry-safe: only touches rows still idless
        (``detected_tmdb_id IS NULL``), so a retried run after a partial commit
        (see :meth:`propagate_tmdb_from_title_siblings`, the public entry point
        wrapping this in the shared lock-retry helper) simply re-scans and
        adopts only what the last successful commit didn't cover.

        Args:
            provider_id: Restrict the idless rows filled to this provider, or None
                to fill across the whole library (the migration path).

        Returns:
            Number of idless rows that adopted a sibling id.
        """
        from metatv.core.content_identity import normalize_title_for_key

        _BATCH = 2000
        _VOD = ("movie", "series")

        # 1. Winner map from id-bearing VOD rows: (norm_title, media_type) ->
        #    {tmdb_id: start_year_or_None}.  Dedup collapses variants; >1 distinct
        #    id in a group flags a remake split resolved per-row (year-compat) below.
        groups: Dict[Tuple[str, str], Dict[str, Optional[int]]] = {}
        id_rows = (
            self.session.query(
                ChannelDB.detected_title,
                ChannelDB.media_type,
                ChannelDB.detected_year,
                ChannelDB.detected_tmdb_id,
            )
            .filter(ChannelDB.detected_tmdb_id.isnot(None))
            .filter(ChannelDB.media_type.in_(_VOD))
            .yield_per(_BATCH)
        )
        for det_title, mt, det_year, det_tmdb in id_rows:
            tmdb = valid_tmdb_id(det_tmdb)
            if not tmdb:
                continue
            norm = normalize_title_for_key(det_title or "")
            if not norm:
                continue
            year = _start_year_int(det_year)
            bucket = groups.setdefault((norm, mt or ""), {})
            # Keep the first year seen for an id, upgrading None → a real year when
            # a later row for the same id carries one (helps the compat check).
            if tmdb not in bucket or (bucket[tmdb] is None and year is not None):
                bucket[tmdb] = year

        if not groups:
            return 0

        # 2. Scan idless rows (scoped) and adopt where a single year-compatible id wins.
        idless_q = (
            self.session.query(
                ChannelDB.id,
                ChannelDB.detected_title,
                ChannelDB.media_type,
                ChannelDB.detected_year,
            )
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.media_type.in_(_VOD))
        )
        if provider_id:
            idless_q = idless_q.filter(ChannelDB.provider_id == provider_id)

        # Paged with a keyset cursor, NOT streamed with yield_per. This loop
        # commits, and a commit hands the connection back to the pool — which
        # CLOSES it when it was an overflow connection. The pass runs on a
        # worker thread beside the EPG fetch, the series monitor and the UI, so
        # it usually IS one. The cursor yield_per left open then raises
        # ``sqlite3.ProgrammingError: Cannot operate on a closed database``,
        # _propagate_after_drain logs it and abandons the pass, and adoption
        # stops after a single batch — six times in the owner's log, against a
        # library with 237,490 idless rows to work through.
        #
        # Paging closes the cursor before any write, so a commit has nothing
        # left to invalidate. A keyset cursor rather than OFFSET because this
        # loop writes the very column the filter tests: rows leave the result
        # set as it runs, and OFFSET would step over their neighbours.
        adopted = 0
        pending = 0
        committed = False
        after = ""
        while True:
            page = (
                idless_q.filter(ChannelDB.id > after)
                .order_by(ChannelDB.id)
                .limit(_BATCH)
                .all()
            )
            if not page:
                break
            after = page[-1][0]
            for cid, det_title, mt, det_year in page:
                norm = normalize_title_for_key(det_title or "")
                if not norm:
                    continue
                bucket = groups.get((norm, mt or ""))
                if not bucket:
                    continue
                my_year = _start_year_int(det_year)
                # Tier 1 — EXACT year. When this row and a sibling both carry a
                # real year and those years are equal, that sibling identifies the
                # same production by the system's own axiom (movie identity is
                # title+year: it is what the fallback key itself keys on). A remake
                # elsewhere in the catalogue is irrelevant to a match this precise,
                # so it must not veto — and under the coarse tier below it does,
                # because that bucket spans every year and a ±1 window treats a
                # stored None as compatible with everything.
                #
                # Measured on the owner's library: 109 idless rows across 88 groups
                # sit beside exactly one id-bearing sibling at their own explicit
                # year and are refused today. It is deliberately not more. Grouping
                # "same title, NEITHER has a year" as a year match would reach 6,297
                # rows — and that is the coarse merge this system refuses on
                # purpose, the one that put a Disney animation, an anime and a
                # documentary under one `aladdin|movie|` key. A missing year is not
                # a matching year.
                exact_ids = (
                    {tid for tid, syear in bucket.items() if syear == my_year}
                    if my_year is not None
                    else set()
                )
                if len(exact_ids) == 1:
                    compat_ids = exact_ids
                else:
                    # Tier 2 — the coarse year-compatible bucket, unchanged. Carries
                    # the yearless rows, where a ±1 window over an unknown year is
                    # the only evidence available.
                    compat_ids = {
                        tid
                        for tid, syear in bucket.items()
                        if my_year is None or syear is None or abs(my_year - syear) <= 1
                    }
                if len(compat_ids) != 1:
                    continue  # no candidate, or ambiguous remake split → don't guess
                tmdb = next(iter(compat_ids))
                proxy = _TmdbKeyProxy(detected_tmdb_id=tmdb, media_type=mt or "", id=cid)
                self.session.execute(
                    update(ChannelDB)
                    .where(ChannelDB.id == cid)
                    .values(
                        detected_tmdb_id=tmdb,
                        content_key=content_key_for(proxy),
                        tmdb_enrich_state="propagated",
                    )
                )
                adopted += 1
                pending += 1
            # One commit per page — outside the row loop, where this page's
            # cursor is already exhausted.
            if pending:
                self.session.commit()
                committed = True
                pending = 0

        # Every pass still ends on exactly ONE commit per unit of work, and on
        # at least one commit even having adopted nothing: it closes the read
        # transaction this pass opened, and TestBackfillTaskSurvivesPropagationLock
        # counts on each propagation phase reaching a commit it can fail so the
        # lock retry is exercised. What changed is that a page-committing pass
        # no longer ALSO commits at the end — that made it commit twice, which
        # TestPropagationLockRetry caught as a fourth attempt where it expects
        # three.
        if not committed:
            self.session.commit()

        if adopted:
            logger.info(
                "tmdb_sibling_propagation: adopted {} idless row(s) from title siblings",
                adopted,
            )
        return adopted

    def _process_tmdb_backfill_batch(self, chunk_ids: list[str]) -> int:
        """Fill one batch of tmdb ids + content keys, committing at the end.

        Split out of :meth:`backfill_tmdb_ids` so the batch can be retried as a
        UNIT through :meth:`_retry_on_lock`. Retrying only the ``commit()``
        would be wrong: a failed commit's rollback expires the session's
        in-memory changes, so a bare re-commit flushes nothing — the batch has
        to be recomputed from a fresh query. That is the same reasoning as
        :meth:`_commit_prefix_batch_with_retry`, and this method exists for the
        same reason.

        Args:
            chunk_ids: Channel ids in this batch.

        Returns:
            Number of rows written in this batch.
        """
        filled = 0
        # raw_data IS needed here (that's where tmdb lives), so load it for
        # this batch only, then expunge below.
        rows = (
            self.session.query(
                ChannelDB.id, ChannelDB.raw_data, ChannelDB.media_type
            )
            .filter(ChannelDB.id.in_(chunk_ids))
            .all()
        )

        for (ch_id, raw, media_type) in rows:
            tmdb = valid_tmdb_id((raw or {}).get("tmdb")) if raw else None
            if tmdb is None:
                continue  # leave NULL — no real id shipped for this row
            key = content_key_for(_TmdbKeyProxy(tmdb, media_type or "", ch_id))
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id == ch_id)
                .values(detected_tmdb_id=tmdb, content_key=key)
            )
            filled += 1

        self.session.commit()
        self.session.expunge_all()
        return filled

    def backfill_tmdb_ids(
        self,
        progress_cb=None,
        is_cancelled=None,
    ) -> int:
        """Populate ``detected_tmdb_id`` from each row's ``raw_data["tmdb"]``.

        Content-identity Slice 3.  Rows ingested before the provider tmdb id was
        captured have a NULL ``detected_tmdb_id``; this one-time pass reads the
        ``raw_data`` blob, validates via the shared ``valid_tmdb_id``, and
        stores it.  **The key is recomputed in the same UPDATE** (via
        ``content_key_for``), so it no longer depends on running before
        ``ContentKeyBackfillTask``: both are independently version-gated and
        this one leaves its version unbumped when cancelled, so a resumed run
        met an already-current key task that sat out, filling ids under stale
        keys that silently orphaned rows from their own variants.  Only
        generated columns are written (mirror-not-cage).

        Processes rows in 2000-row batches, loading ``raw_data`` for at most one
        batch at a time (then commit + ``expunge_all``) to stay memory-safe on
        large tables.  Idempotent: only rows whose ``detected_tmdb_id`` is still
        NULL are scanned, so an interrupted run resumes cheaply.

        Args:
            progress_cb: Optional ``(done: int, total: int) -> None`` called
                after each batch commit.
            is_cancelled: Optional ``() -> bool`` checked at the top of each
                batch.  Early exit leaves committed batches durable; the task
                version is not bumped so it restarts next launch.

        Returns:
            Number of rows that had a non-NULL ``detected_tmdb_id`` written.
        """
        _BATCH = 2000

        # Only rows that don't yet have an id — NULL covers both "never scanned"
        # and "scanned, no id".  We narrow to VOD media types because live
        # channels never carry a tmdb id; this skips the bulk of most libraries.
        q = (
            self.session.query(ChannelDB.id)
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.media_type.in_(("movie", "series")))
        )
        all_ids = [row[0] for row in q.all()]
        total = len(all_ids)

        if total == 0:
            logger.debug("backfill_tmdb_ids: nothing to do (no NULL-id VOD rows)")
            return 0

        logger.info("backfill_tmdb_ids: scanning {} VOD rows for provider tmdb ids", total)
        filled = 0

        for batch_start in range(0, total, _BATCH):
            if is_cancelled is not None and is_cancelled():
                logger.info("backfill_tmdb_ids: cancelled at {}/{}", batch_start, total)
                break

            chunk_ids = all_ids[batch_start : batch_start + _BATCH]
            filled += self._retry_on_lock(
                "backfill_tmdb_ids: batch",
                self._process_tmdb_backfill_batch,
                chunk_ids,
            )

            if progress_cb is not None:
                progress_cb(min(batch_start + _BATCH, total), total)

        logger.info("backfill_tmdb_ids: wrote {} tmdb ids across {} scanned rows", filled, total)
        return filled

    def _process_content_key_backfill_batch(self, chunk_ids: list[str]) -> int:
        """Recompute one batch of ``content_key``, committing at the end.

        Split out of :meth:`backfill_content_keys` so the batch is retried as a
        UNIT through :meth:`_retry_on_lock` — see
        :meth:`_process_tmdb_backfill_batch` for why retrying the commit alone
        would flush nothing.

        Args:
            chunk_ids: Channel ids in this batch.

        Returns:
            Number of rows rewritten in this batch.
        """
        filled = 0
        # Project only the columns we need to stay memory-safe.  detected_tmdb_id
        # is included so content_key_for can pick the tmdb-first key on recompute
        # (else it would fall back to the title/year key and never key on tmdb).
        rows = (
            self.session.query(
                ChannelDB.id,
                ChannelDB.detected_title,
                ChannelDB.media_type,
                ChannelDB.detected_year,
                ChannelDB.detected_tmdb_id,
            )
            .filter(ChannelDB.id.in_(chunk_ids))
            .all()
        )

        for (ch_id, det_title, media_type, det_year, det_tmdb_id) in rows:
            key = content_key_for(
                _FullKeyProxy(det_title, media_type, det_year, det_tmdb_id, ch_id)
            )
            # Bulk UPDATE avoids loading the full ORM object (raw_data JSON blob).
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id == ch_id)
                .values(content_key=key)
            )
            filled += 1

        self.session.commit()
        self.session.expunge_all()
        return filled

    def backfill_content_keys(
        self,
        progress_cb=None,
        is_cancelled=None,
        recompute_all: bool = False,
    ) -> int:
        """Compute and store ``content_key`` for channel rows.

        Reads only ``detected_title``, ``media_type``, ``detected_year``, and
        ``id`` — no raw name re-parsing.  Processes rows in 2000-row batches
        with a commit + expunge_all between batches to stay memory-safe on
        million-row tables.

        Args:
            progress_cb: Optional ``(done: int, total: int) -> None`` called
                after each batch commit.
            is_cancelled: Optional ``() -> bool`` checked at the top of each
                batch.  Early exit leaves all previously committed batches
                durable; the task version is not bumped so it restarts next
                launch.
            recompute_all: When ``False`` (default), only rows with a NULL
                ``content_key`` are processed (the initial-population path,
                idempotent: a no-op once all rows are filled).  When ``True``,
                EVERY row is recomputed — used when the key formula changes so
                that existing non-NULL keys are updated to the new formula.

        Returns:
            Number of rows that had their ``content_key`` written.
        """
        _BATCH = 2000

        # Fetch row ids to process: NULL-only by default, all rows on formula change.
        q = self.session.query(ChannelDB.id)
        if not recompute_all:
            q = q.filter(ChannelDB.content_key.is_(None))
        all_ids = [row[0] for row in q.all()]
        total = len(all_ids)

        if total == 0:
            logger.debug(
                "backfill_content_keys: nothing to do "
                "(recompute_all={}, all rows already keyed)", recompute_all
            )
            return 0

        logger.info(
            "backfill_content_keys: processing {} rows (recompute_all={})",
            total, recompute_all,
        )
        filled = 0

        for batch_start in range(0, total, _BATCH):
            if is_cancelled is not None and is_cancelled():
                logger.info(
                    "backfill_content_keys: cancelled at {}/{}", batch_start, total
                )
                break

            chunk_ids = all_ids[batch_start : batch_start + _BATCH]
            filled += self._retry_on_lock(
                "backfill_content_keys: batch",
                self._process_content_key_backfill_batch,
                chunk_ids,
            )

            if progress_cb is not None:
                progress_cb(min(batch_start + _BATCH, total), total)

        logger.info(f"backfill_content_keys: filled {filled} of {total} rows")
        return filled

    def select_genre_backfill_candidates(
        self,
        limit: int,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, str]]:
        """Return MOVIE rows whose linked metadata row has **empty genres**.

        The list ``raw_data`` for movies is sparse (no genre), so a movie that has
        already been given a MetadataDB row (viewed at least once) still shows empty
        ``genres`` — which makes it invisible to the genre-driven recommendation
        scorer.  This selects those movies so the enrichment sweep can fetch their
        ``get_vod_info`` detail blob and harvest the real genres.

        Candidate predicate: ``media_type == 'movie'``, has a linked ``MetadataDB``
        row whose ``genres`` is NULL or ``[]``, is visible, on a non-excluded
        provider, and has **not** been attempted (``genre_enrich_state IS NULL``) —
        the persistent marker that makes the pass resumable and hits each row once.

        Args:
            limit: Hard cap on rows returned (a bounded drain batch).
            excluded_provider_ids: Hidden providers (inactive ∪ expired) from
                ``ProviderRepository.get_hidden_provider_ids()`` — never enriched.

        Returns:
            List of ``{"id", "provider_id", "source_id", "media_type"}`` dicts (plain
            dicts — no ORM objects escape the session).
        """
        # ``MetadataDB.genres == []`` binds through JSONEncoded to the stored TEXT
        # '[]' (the empty-list form), matching how empty genres are persisted.
        q = (
            self.session.query(
                ChannelDB.id,
                ChannelDB.provider_id,
                ChannelDB.source_id,
                ChannelDB.media_type,
            )
            .join(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
            .filter(ChannelDB.media_type == "movie")
            .filter(ChannelDB.is_hidden.is_(False))
            .filter(ChannelDB.genre_enrich_state.is_(None))
            .filter(or_(MetadataDB.genres.is_(None), MetadataDB.genres == []))
        )
        if excluded_provider_ids:
            q = q.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        q = q.order_by(ChannelDB.provider_id).limit(limit)
        return [
            {"id": cid, "provider_id": pid, "source_id": sid, "media_type": mt}
            for (cid, pid, sid, mt) in q.all()
        ]
