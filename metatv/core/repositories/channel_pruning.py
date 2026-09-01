"""Removing channels — and everything that hangs off them.

Split out of ``channel.py`` following the pattern its siblings already set
(``channel_stats``, ``channel_lens``, ``channel_ingestion``, ``channel_history``):
one coherent cluster, here the three methods that delete channel rows.

``channel.py`` is the file whose 1016 -> 4129 growth is the reason the
code-health ratchet exists, so adding a second prune to it was not going to be
the thing that grew it again. Extracting instead took it 3,319 -> 3,035, under
its baseline rather than over.

The two public entry points differ only in WHICH rows are doomed:

* :meth:`prune_provider_content` — the source itself is gone. Also clears
  feed-side EPG and orphaned seasons for the whole provider.
* :meth:`prune_vanished_channels` — the source remains, these particular
  channels do not. The provider-wide steps would be wrong here.

Both go through :meth:`_delete_channel_cascade`, and that is the point of the
shape: SQLite foreign keys are off, so every child table has to be named by
hand, and a second copy of that list is how ``content_tags`` once leaked 1.24M
rows. What a channel drags with it is defined once.

Engagement is never the caller's to decide. Favourited, played and queued rows
survive every path here — the settled rule is flag engaged-unavailable, never
delete it.
"""

from __future__ import annotations

from datetime import datetime  # noqa: F401 - used in type context by callers

from loguru import logger
from sqlalchemy import and_, func, or_

from metatv.core.database import (AlertMatchDB, ChannelDB, ContentTagDB,
                                  EpgProgramDB, EpisodeDB, MetadataDB,
                                  SeasonDB, UserRatingDB)
from metatv.core.repositories.epg import delete_programmes_chunked


class _ChannelPruningMixin:
    """Channel deletion for ChannelRepository (uses ``self.session``)."""

    #: Refuse to prune when more than this share of a source's rows look vanished.
    #:
    #: A truncated fetch is indistinguishable from a shrunken catalog at the point
    #: of the delete: both arrive as "the list no longer mentions these". A source
    #: that answers with a tenth of its channels because of a bad gateway would
    #: otherwise take 90% of the library with it, and the rows are not recoverable
    #: from the app. Half is well above real churn — the owner's event slots turn
    #: over about 980 of 785,552 rows, roughly 0.1% — and well below the shape of
    #: any plausible failure.
    VANISHED_PRUNE_CEILING = 0.5

    def prune_vanished_channels(self, provider_id: str, seen_at) -> dict[str, int]:
        """Delete non-engaged rows *provider_id* has stopped listing.

        The source is still here; these particular channels are not. That makes
        this the sibling of :meth:`prune_provider_content`, not a special case of
        it — the provider-wide steps there (feed-side EPG, orphaned seasons for a
        whole source) would be wrong when the source remains.

        **Why it is needed at all:** ingestion is upsert-only. Nothing has ever
        removed a row the source dropped, so they accumulate for ever. Measured on
        the owner's library: their provider re-issues each event slot with a NEW
        stream id per fixture, leaving 1,960 rows for 980 slots — exactly 2:1 —
        and 1,358 of those carry no event time, which is part of why the Sports
        "Channels" lane read 6,523.

        **Engaged rows are kept**, by the same predicate every other caller uses:
        a favourite, something played, something queued. They stay reachable in
        History and Favourites and are excluded from forward-looking views. That
        is the settled rule — flag engaged-unavailable, never delete it.

        Args:
            provider_id: The source that was just refreshed.
            seen_at: The instant that refresh stamped on every row it saw. Rows
                strictly older than this are the ones it did not.

        Returns:
            Per-table delete counts, or all-zero when nothing was pruned.
        """
        counts: dict[str, int] = {
            "channels": 0, "metadata": 0, "content_tags": 0,
            "epg_by_channel": 0, "epg_by_provider": 0, "seasons": 0,
            "episodes": 0, "ratings": 0, "alerts": 0,
        }
        if not provider_id or seen_at is None:
            return counts

        # NULL is never pruned. It means "no observation under this scheme" —
        # a row the catalog upsert did not write — and deleting on an absence of
        # evidence is the mistake #642 recorded about inferring a first launch
        # from four empty lists.
        #
        # The `isnot(None)` is EXPLICITNESS, not the mechanism: SQL's
        # `NULL < :t` evaluates to NULL, so such a row is already excluded, and
        # removing this line changes no behaviour (mutation-checked — the suite
        # stays green, correctly). It is here so the rule is legible without the
        # reader holding three-valued logic in their head, and so a future
        # rewrite to `COALESCE(last_seen_at, 0) < :t` — which WOULD delete every
        # unobserved row — reads as the deliberate change it would be. That
        # mutation does go red.
        vanished = and_(
            ChannelDB.provider_id == provider_id,
            ChannelDB.last_seen_at.isnot(None),
            ChannelDB.last_seen_at < seen_at,
        )

        total = (self.session.query(func.count(ChannelDB.id))
                 .filter(ChannelDB.provider_id == provider_id).scalar() or 0)
        doomed = (self.session.query(func.count(ChannelDB.id))
                  .filter(vanished).scalar() or 0)
        if not doomed:
            return counts

        if total and doomed / total > self.VANISHED_PRUNE_CEILING:
            logger.warning(
                "prune_vanished_channels: refusing to prune {} of {} rows for "
                "provider {} ({:.0%} — over the {:.0%} ceiling). A truncated "
                "fetch looks exactly like a shrunken catalog here, so nothing is "
                "deleted; the rows stay and the next refresh can try again.",
                doomed, total, provider_id, doomed / total,
                self.VANISHED_PRUNE_CEILING)
            return counts

        logger.info(
            "prune_vanished_channels: provider {} stopped listing {} of {} rows "
            "({:.1%}) — removing the non-engaged ones",
            provider_id, doomed, total, (doomed / total) if total else 0)
        self._delete_channel_cascade(vanished, counts)
        return counts

    def _delete_channel_cascade(self, scope, counts: dict) -> None:
        """Delete non-engaged channels matching *scope*, and everything hanging off them.

        Extracted so ``prune_provider_content`` (the source is gone) and
        ``prune_vanished_channels`` (the source remains, these rows do not) cannot
        drift into two different ideas of what a channel drags with it. They
        differ in WHICH rows are doomed, never in what deleting one means — and a
        second copy of this is how ``content_tags`` came to leak 1.24M rows the
        first time, because SQLite foreign keys are off and every child table has
        to be named here by hand.

        Args:
            scope: A SQLAlchemy filter selecting candidate ``ChannelDB`` rows.
                The engagement test is applied on top and is NOT the caller's to
                supply — favourited, played and queued rows survive every caller.
            counts: Mutated in place with per-table delete counts.
        """
        engaged = self._engaged_channel_predicate()

        # The doomed set as a reusable correlated subquery. Because the channels
        # row is deleted LAST, this resolves the same non-engaged set for every
        # child delete below, so the planner never materialises the id list.
        doomed_channel_ids = (
            self.session.query(ChannelDB.id).filter(scope).filter(~engaged)
        )
        doomed_meta_ids = (
            self.session.query(ChannelDB.metadata_id)
            .filter(scope).filter(~engaged)
            .filter(ChannelDB.metadata_id.isnot(None))
        )

        # content_tags first (no FK cascade — the leak this also fixes).
        counts["content_tags"] += (
            self.session.query(ContentTagDB)
            .filter(ContentTagDB.channel_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        # chunked-delete-exempt: one step of an ATOMIC cascade; per-chunk commits
        # would publish a half-pruned tree (why: docs/REFACTOR_PLAN.md D16).
        counts["epg_by_channel"] += (
            self.session.query(EpgProgramDB)
            .filter(EpgProgramDB.channel_db_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["episodes"] += (
            self.session.query(EpisodeDB)
            .filter(EpisodeDB.series_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["seasons"] += (
            self.session.query(SeasonDB)
            .filter(SeasonDB.series_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["ratings"] += (
            self.session.query(UserRatingDB)
            .filter(UserRatingDB.channel_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["alerts"] += (
            self.session.query(AlertMatchDB)
            .filter(AlertMatchDB.channel_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        # MetadataDB rows referenced by the doomed channels (subquery reads
        # channels.metadata_id — must run before the channels row is deleted).
        counts["metadata"] += (
            self.session.query(MetadataDB)
            .filter(MetadataDB.id.in_(doomed_meta_ids))
            .delete(synchronize_session=False)
        )
        # Finally, the channels themselves — deleted LAST so the correlated
        # doomed-set subquery above still resolved while the child deletes ran.
        counts["channels"] += (
            self.session.query(ChannelDB)
            .filter(scope)
            .filter(~engaged)
            .delete(synchronize_session=False)
        )
        self.session.commit()

    def prune_provider_content(
        self,
        provider_ids: list[str],
    ) -> dict[str, int]:
        """Delete non-engaged channels (and their dependents) for a set of providers.

        "Engaged" means the channel was favorited, played, or queued.  Engaged
        channels are KEPT even when their provider is removed — they remain
        accessible in History / Favorites / Watch Queue and are hidden from
        forward-looking views via ``get_hidden_provider_ids()``.

        Set-based, provider-scoped deletes (not id-batched):  every child delete
        targets ``... WHERE <fk> IN (SELECT id FROM channels WHERE provider_id IN
        (:pids) AND NOT <engaged>)`` and the channels themselves are removed with a
        single ``DELETE ... WHERE provider_id IN (:pids) AND NOT <engaged>`` — the
        doomed set is resolved by SQLite via the indexed ``provider_id`` instead of
        shipping every id to Python and issuing ~150 batches of ~7 ``IN(...)``
        deletes.  The channels row is deleted LAST so the correlated subquery still
        resolves the doomed set for the child deletes, and each step group commits
        once (a few large transactions, not ~150 per-batch commits) — collapsing the
        SQLite single-writer lock-contention points that turned a ~13s purge into a
        2-minute UI freeze.

        ``content_tags`` is pruned here too: it has no FK cascade (SQLite FKs are
        off), so before this fix a deleted channel's ``content_tags`` rows were
        orphaned forever.  Engaged channels' tags are spared by the same doomed-set
        subquery.

        Args:
            provider_ids: Provider IDs whose non-engaged content should be
                purged.  May be an empty list (returns zero counts immediately).

        Returns:
            Dict with counts: ``channels``, ``metadata``, ``content_tags``,
            ``epg_by_channel``, ``epg_by_provider``, ``seasons``, ``episodes``,
            ``ratings``, ``alerts``.
        """
        if not provider_ids:
            return {
                "channels": 0, "metadata": 0, "content_tags": 0,
                "epg_by_channel": 0, "epg_by_provider": 0, "seasons": 0,
                "episodes": 0, "ratings": 0, "alerts": 0,
            }

        counts: dict[str, int] = {
            "channels": 0, "metadata": 0, "content_tags": 0,
            "epg_by_channel": 0, "epg_by_provider": 0, "seasons": 0,
            "episodes": 0, "ratings": 0, "alerts": 0,
        }

        engaged = self._engaged_channel_predicate()

        logger.info(
            f"prune_provider_content: pruning non-engaged channels from "
            f"{len(provider_ids)} provider(s) via set-based provider-scoped deletes"
        )

        # Step 2 — the channel-level cascade, shared with prune_vanished_channels.
        self._delete_channel_cascade(ChannelDB.provider_id.in_(provider_ids), counts)
        # Step 3 — feed-side EPG: programmes whose provider_id is one of the removed
        # providers (these are EPG feed entries, not channel matches).
        counts["epg_by_provider"] += delete_programmes_chunked(
            self.session, EpgProgramDB.provider_id.in_(provider_ids)
        )

        # Step 4 — orphaned SeasonDB / EpisodeDB whose provider_id is in the removed
        # set but whose series channel is NOT one of the KEPT (engaged) channels.
        # After Step 2 the only ChannelDB rows still present for these providers are
        # the engaged (favorited/played/queued) series we deliberately preserve, so a
        # season/episode whose series_id still resolves to an existing channel belongs
        # to a kept series — leave it intact so per-episode resume/watched history
        # survives a provider delete (history is sacrosanct).  Only truly orphaned
        # catalog rows (series channel already gone) are pruned, and even those are
        # spared when the episode itself still carries user watch-state.
        kept_series_subq = (
            self.session.query(ChannelDB.id)
            .filter(ChannelDB.provider_id.in_(provider_ids))
        )
        counts["episodes"] += (
            self.session.query(EpisodeDB)
            .filter(EpisodeDB.provider_id.in_(provider_ids))
            .filter(~EpisodeDB.series_id.in_(kept_series_subq))
            # Floor: never delete an episode carrying user watch-state, even if its
            # series channel is already gone (pre-fix orphans).
            .filter(
                ~or_(
                    EpisodeDB.is_watched == True,       # noqa: E712
                    EpisodeDB.watch_completed == True,  # noqa: E712
                    EpisodeDB.watch_progress > 0,
                    EpisodeDB.last_played.isnot(None),
                    EpisodeDB.play_count > 0,
                )
            )
            .delete(synchronize_session=False)
        )
        counts["seasons"] += (
            self.session.query(SeasonDB)
            .filter(SeasonDB.provider_id.in_(provider_ids))
            .filter(~SeasonDB.series_id.in_(kept_series_subq))
            .delete(synchronize_session=False)
        )
        self.session.commit()

        logger.info(
            f"prune_provider_content complete: {counts['channels']} channels, "
            f"{counts['metadata']} metadata, {counts['content_tags']} content_tags, "
            f"{counts['epg_by_channel'] + counts['epg_by_provider']} EPG rows, "
            f"{counts['seasons']} seasons, {counts['episodes']} episodes pruned; "
            f"engaged channels preserved."
        )
        return counts


