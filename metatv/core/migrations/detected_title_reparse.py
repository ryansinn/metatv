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
CURRENT_VERSION: int = 4


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
