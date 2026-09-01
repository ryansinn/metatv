"""Migration task: re-parse detected_title to strip trailing quality/region/subtitle qualifiers, and populate detected_audio.

Fix #78 (version 1) and #78 follow-up (version 2).

Version 1 — Before fix, ``parse_channel_name`` left trailing single-token
parenthetical qualifiers in ``detected_title`` when no year was present to anchor
stripping.  Examples:

  "NF - 13 Reasons Why (US) (4K)"  → detected_title = "13 Reasons Why (US) (4K)"  (wrong)
  "FR - 1883 (VOSTFR)"             → detected_title = "1883 (VOSTFR)"              (wrong)

After version 1:

  "NF - 13 Reasons Why (US) (4K)"  → detected_title = "13 Reasons Why"             (correct)
  "FR - 1883 (VOSTFR)"             → detected_title = "1883"                        (correct)

Version 2 — Space-containing parentheticals where EVERY token is a recognized
lang/region/quality/sub/dub marker are now also stripped (recognized-token allowlist).
Examples:

  "Title (ENG DUB)"              → detected_title = "Title"                          (correct)
  "As Linas Descontinuas (2025) (SPANISH ENG-SUB)" → "As Linas Descontinuas"        (correct)
  "Title (Soleil Noir)"          → preserved — "SOLEIL"/"NOIR" unrecognized          (correct)

Multi-word alt-language titles — (30 Monedas), (Soleil Noir) — are preserved because
they contain tokens that are not in the recognized-qualifier vocabulary.

Because ``update_detected_prefixes`` computes BOTH ``detected_title`` AND
``content_key`` in one pass, a single full re-run is sufficient.  There is no need
for a separate ``backfill_content_keys`` call.

Idempotency
-----------
``needs_run`` returns True when ``config.detected_reparse_version`` is behind
``CURRENT_VERSION``.  On completion the version is bumped and saved.
An interrupted run leaves the version unbumped so the task restarts on the next
launch from scratch (already-committed batches are durable).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the full detected_title re-parse for all users on next launch.
# History:
#   1 — initial strip: remove trailing quality/region/subtitle paren qualifiers from
#       detected_title and recompute content_key in one update_detected_prefixes pass.
#   2 — recognized-token allowlist: space-containing parentheticals where EVERY
#       space/dash/slash-split leaf is a lang/region/quality/sub/dub token are now
#       also stripped (e.g. "(ENG DUB)", "(SPANISH ENG-SUB)", "(DUAL AUDIO)").
#       Genuine alt-titles like "(Soleil Noir)" are preserved (unrecognized tokens).
#   3 — marker-anchored rule: strip a trailing parenthetical when it contains an
#       unambiguous sub/dub marker (SUB/SUBS/SUBBED/SUBTITLED/DUB/DUBBED/VOST/
#       VOSTFR/LEG/LEGENDADO/MULTISUB/ENGSUB) AND every leaf token is alphabetic.
#       Catches ~170 language+sub qualifiers whose language word (JAPANESE, KURDISH,
#       PERSIAN, NORWEGIAN, CHINESE, …) is not in the recognized-token vocab.
#       All-alpha guard prevents stripping parentheticals with digits (e.g. "Episode 5 SUB").
#   4 — detected_audio capture: sub/dub/multi parentheticals now populate
#       ChannelDB.detected_audio (form, audio, dub, sub language lists) at the same
#       update_detected_prefixes pass. Full re-run needed to back-fill all rows.
#   5 — AI-provenance markers: a trailing "(AI)" voiceover marker is now stripped
#       from detected_title (clean display; collapses onto the base production),
#       while a trailing "(AI Generated)" content marker is deliberately KEPT in
#       detected_title so its content_key stays distinct from any real same-title
#       work.  Full re-run re-parses all rows and recomputes content_key in the
#       same update_detected_prefixes pass (no separate backfill needed).
#   6 — control-char mojibake strip: parse_channel_name now removes stray C0/C1
#       control characters (e.g. a raw U+0081 corrupting "Á" in
#       "|ES| Alita: <U+0081>ngel de combate") from the name before deriving
#       detected_title, so the stored title displays cleanly and its title-fallback
#       content_key is no longer polluted by the artifact.  Full re-run re-cleans
#       every existing detected_title and recomputes content_key in the same
#       update_detected_prefixes pass (only generated fields are written — user
#       tags/ratings/favorites are never touched).
#   7 — mid-name year pre-cut: parse_channel_name now relocates a "(YYYY)" that has
#       trailing cast/extra credits after it (e.g. "From Dusk Till Dawn 4K (1996)
#       HARVEY KEITEL, TARANTINO") so the existing end-anchored year/quality strip
#       still extracts detected_year and a clean detected_title instead of leaving
#       the whole cast blob in the title and detected_year empty.  Full re-run
#       re-parses every row and recomputes content_key in the same
#       update_detected_prefixes pass.
#   8 — leading-pipe separator residue: "|MULTI|. Title" left ". " at the start of
#       detected_title after the pipe-wrapped prefix was stripped; parse_channel_name
#       now removes a leading punctuation-run-plus-whitespace after the prefix strip
#       (a bare leading dot with no space — ".hack//Sign" — is preserved).  Full
#       re-run re-parses every row and recomputes content_key.
#   9 — re-run of 8. The only v8 run on the owner's machine (2026-07-31) crashed
#       mid-pass on a transient "database is locked", and a MigrationManager bug
#       (fixed alongside this bump) marked the crashed run complete anyway — so
#       stored version 8 is burned without the pipe-residue strip ever applying.
#       No parser change beyond v8; this bump makes the fixed parse actually run
#       to completion.
#  10 — the year always wins. v7 relocated a mid-name "(YYYY)" only when the text
#       AFTER it was ALL-CAPS (provider cast blobs). Title-case trailers defeated
#       it entirely — "Christmas At Castle Hart (2021) Hallmark" parsed with
#       year="" and kept "(2021) Hallmark" inside detected_title, so it keyed to
#       the coarse yearless content_key and could not match its own siblings.
#       Measured on the owner's library: 2,092 rows across 478 distinct trailers,
#       led by "sinhronizirano" (385), "Hallmark" (322) and "Polski" (176).
#       The year is now extracted wherever it appears; the trailing TEXT is only
#       removed from the title when classify_trailing_metadata() can name it
#       (collection / dub / sub / genre / rating / quality), because 383 of those
#       478 trailers are singletons that may be real subtitles ("FBI (2024)
#       Reboot") — those keep their text and still gain the year.
#       Verified against all 466,061 distinct names: 2,038 gain a year, 0 lose
#       one, 0 lose a cast blob.
#
# v11 — Scene-release filenames. 1,268 rows rendered a torrent filename as
#       their title: "Onder.Het.Maaiveld.2023.DUTCH.1080p.WEB.h264-TRIPEL",
#       "Ceu.em.Chamas-Skyfire.2019.1080p.WEB-DL.x264.DUAL-COMANDO.TO". The
#       end-anchored strip could not reach any of them — it walks BACKWARDS and
#       stops at the first unknown token, and a scene name ends in a
#       release-group tag ("-TURG", "XT", "COMANDO.TO") that no vocabulary will
#       ever contain, so one unknown token at the tail hid everything in front
#       of it. channel_name_utils._extract_scene_release is a forward pass that
#       finds where the TITLE stops instead. HDTV also joined the quality
#       vocabulary and normalizes onto HD, which clears it out of "NBA TV HDTV"
#       and "WFOR CBS 4 HDTV".
#       Verified against all 467,373 distinct names: 484 parse differently, 481
#       of those a title change, and the 1,138 assertions in the 48 existing
#       test files that touch the parser all held.
#
# v12 — Episode markers. 960 rows are 48 series whose provider filed every
#       episode as a separate movie, and the "S01E57" in the name is what made
#       them look distinct: 414 Konusanlar rows, 62 Sihirli Annem, 56 Leyla ile
#       Mecnun. The marker now lifts out into stored detected_season /
#       detected_episode, so detected_title is the SHOW and content_key — which
#       is derived from it — collapses 960 rows into 48 cards.
#       Only the SxxExx form. "1x05" was measured across the library and matched
#       14 rows, ALL real film titles ("10x10 (2018)", "8x10 Tasveer", "12x12");
#       "Season N Episode N" matched nothing. Verified: 0 of the other 784,203
#       names gain a season or episode.
# Version 13 — repair rows whose detected_title names a DIFFERENT event than
#       the one the slot now carries. #629 nulls the derived fields when a row is
#       renamed and lets ingestion refill them, which fixes every rename FROM
#       THEN ON — but it has no backfill, and a row that went stale before it
#       shipped never changes name again, so nothing ever nulls it. It stays
#       wrong permanently.
#
#       Measured on the owner's library: 1,077 of 2,940 dated event rows (36.6%)
#       carry a title whose embedded date differs from the name's. The provider
#       rotates event slots daily, so the list showed last week's fixture on a
#       channel carrying tonight's — "(FLSP 154) flovolleyball … (2026-08-28)"
#       on a row whose name, sport_type and event_start_time all said hockey
#       tonight. Render reads detected_title, so the app and mpv disagreed about
#       what was playing, which is how the owner found it.
#
#       A bump is the whole fix: update_detected_prefixes recomputes
#       detected_title from the current name and writes it when it differs — it
#       is fill-empty-only for detected_REGION precedence, not for the title.
CURRENT_VERSION: int = 13


class DetectedTitleReparseTask:
    """Re-parse detected_title to strip trailing qualifiers and recompute content_key.

    ``needs_run`` checks ``config.detected_reparse_version`` against
    ``CURRENT_VERSION``.  On full completion the version is bumped and config is
    saved; on cancellation the version is left unbumped so the next launch
    re-runs from scratch.
    """

    id: str = "detected_title_reparse"
    label: str = "Cleaning channel title qualifiers"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """Return True when the re-parse has not yet completed for this version.

        Args:
            config: The application Config instance.

        Returns:
            True when ``config.detected_reparse_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "detected_reparse_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the full detected_title re-parse.

        Runs on a **worker thread** (called by MigrationManager).  Delegates
        to ``ChannelRepository.update_detected_prefixes(provider_id=None)`` which
        processes all rows in 2000-row batches with commit + expunge between
        batches.  Cancellation is supported: the loop exits early, already-
        committed batches are durable, and the version is not bumped so the task
        restarts on the next launch.

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        logger.info(
            "DetectedTitleReparseTask: starting full re-parse (version={})",
            CURRENT_VERSION,
        )

        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                provider_id=None,
                progress_cb=progress_cb,
                is_cancelled=is_cancelled,
            )

        logger.info("DetectedTitleReparseTask: completed")

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.detected_reparse_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "DetectedTitleReparseTask: bumped detected_reparse_version={}",
            CURRENT_VERSION,
        )
