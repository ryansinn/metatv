"""Metadata mixin — channel details loading, versions, similar titles, action states.

Extracted from MainWindow; mixed in via:
    class MainWindow(_MetadataMixin, ..., QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

import asyncio
import sys
import time

from loguru import logger
from PyQt6.QtCore import QTimer

from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import parse_provider_urls
from metatv.gui.details_actions import ChannelActionState
from metatv.gui.details_versions import ChannelVersion
from metatv.gui import deferred_config_save as _cfgsave

# Owner's log (2026-09-02): one selection produced two full render+fetch
# cycles for the same channel 185ms apart. #680 fixed the LIST's own
# click/selection double; this debounce covers every OTHER path into
# update_details_pane_for_channel (sidebar sections, version_selected,
# programmatic calls) that had no dedupe of its own. 300ms, not id-gating:
# gating on the id alone breaks click-again-to-refresh, the deliberate escape
# hatch #680's record relies on — a human re-click is seconds apart, the
# measured accidental double was 185ms, so 300ms catches the double without
# touching the escape hatch.
#
# UI-11 (owner's log 2026-09-05 06:39-06:41): the SAME channel id re-rendered
# twelve times in 100s — the pairs landed 350-500ms apart (two surfaces
# firing for one gesture), past the 300ms window. Raised to 2.0s. This is
# now reachable only while metadata for the shown id is STILL LOADING: once
# metadata lands, the _details_shown same-title no-op below short-circuits a
# repeat outright with no timer involved, so widening this constant does not
# reopen the click-again-to-refresh escape hatch on an already-settled title
# — a human re-click is comfortably "seconds", not 2.
_RERENDER_DEBOUNCE_S = 2.0


class _MetadataMixin:
    """Mixin: details pane data loading, versions, similar titles, action states."""

    # ── Channel tags (provenance + confidence display — DR-0006) ────────────

    def _on_channel_tags_requested(self, channel_id: str) -> None:
        """Kick off an off-thread tag load for the given channel_id."""
        self._run_query(
            lambda repos: repos.tags.get_channel_tags_dto(channel_id),
            lambda tags: self._on_channel_tags_loaded(channel_id, tags),
            token_ref=self._channel_tags_token,
        )

    def _on_channel_tags_loaded(self, channel_id: str, tags: list) -> None:
        """Main-thread slot: deliver loaded tags to the details pane."""
        self.details_pane.apply_channel_tags(channel_id, tags or [])

    # ── Action state (is_queued / rating / suppressed / hidden) ────────────

    def _on_action_state_requested(self, channel_id: str) -> None:
        self.executor.submit(self._bg_fetch_action_state, channel_id)

    def _bg_fetch_action_state(self, channel_id: str) -> None:
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                state = ChannelActionState(
                    channel_id=channel_id,
                    in_queue=repos.queue.is_queued(channel_id),
                    rating=repos.ratings.get(channel_id) or 0,
                )
                ch = repos.channels.get_by_id(channel_id)
                if ch:
                    state.is_suppressed = bool(ch.is_rec_suppressed)
                    state.is_hidden = bool(ch.is_hidden)
                    state.is_favorite = bool(ch.is_favorite)
                state.epg_link_blocked = channel_id in (self.config.epg_link_blocklist or [])
        except Exception:
            logger.exception("Failed to fetch action state for %s", channel_id)
            return
        self._action_state_loaded.emit(state)

    def _on_action_state_loaded(self, state) -> None:
        self.details_pane.apply_action_state(state)

    # ── Episode action state (Wave 2 Slice 2B — episode-mode queue/favorite) ──

    def _on_episode_action_state_requested(self, episode_id: str) -> None:
        self.executor.submit(self._bg_fetch_episode_action_state, episode_id)

    def _bg_fetch_episode_action_state(self, episode_id: str) -> None:
        from metatv.core.database import EpisodeDB
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                in_queue = repos.queue.is_episode_queued(episode_id)
                ep = session.get(EpisodeDB, episode_id)
                is_favorite = bool(ep.is_favorite) if ep else False
        except Exception:
            logger.exception(f"Failed to fetch episode action state for {episode_id}")
            return
        self._episode_action_state_loaded.emit(episode_id, in_queue, is_favorite)

    def _on_episode_action_state_loaded(
        self, episode_id: str, in_queue: bool, is_favorite: bool
    ) -> None:
        self.details_pane.apply_episode_action_state(episode_id, in_queue, is_favorite)

    # ── Other Versions / Other Sources ─────────────────────────────────────

    def _fetch_channel_versions(self, channel_id: str) -> None:
        self.executor.submit(self._bg_fetch_versions, channel_id)

    def _bg_fetch_versions(self, channel_id: str) -> None:
        from metatv.core.database import ChannelDB, ProviderDB
        from metatv.core.content_dedup import normalize_title
        from metatv.core.preference_engine import version_score as _version_score
        from metatv.gui.main_window import _version_years_compatible

        versions = []
        try:
            with self.db.session_scope() as session:
                channel = session.get(ChannelDB, channel_id)
                if not channel:
                    return

                repos = RepositoryFactory(session)
                queue_ids = repos.queue.get_queued_ids()
                provider_names = {p.id: p.name for p in session.query(ProviderDB).all()}
                hidden_provider_ids = set(repos.providers.get_hidden_provider_ids())
                from metatv.core.filter_utils import (
                    global_exclusion_set, is_channel_excluded, excluded_tag_content_types,
                )
                _filter_paused = self.config.global_filter_paused
                # Canonical Global-Exclusion set (paused-aware, group→leaf-expanded).
                all_excluded = global_exclusion_set(self.config)
                blocked_prefixes = set() if _filter_paused else set(self.config.global_filter_excluded_prefixes)
                # Content-provenance layer (paused-aware): channel-id set carrying a
                # globally-excluded content_type tag (AI Generated / AI Voiceover).  A
                # matching variant is greyed out here too, matching the channel list.
                _ct_slugs = excluded_tag_content_types(self.config)
                excluded_ct_ids = (
                    repos.tags.channel_ids_for_content_types(_ct_slugs) if _ct_slugs else set()
                )

                def _is_filtered(ch: ChannelDB) -> bool:
                    # Shared predicate: prefix wins, region is the no-prefix fallback —
                    # so a prefix-less variant filed under an excluded region is greyed
                    # out here too, matching the channel list exactly (P1-6).  The
                    # content_type layer (id-set membership) greys out AI variants too.
                    if is_channel_excluded(ch.detected_prefix, ch.detected_region, all_excluded):
                        return True
                    return ch.id in excluded_ct_ids

                def _is_hidden_category(ch: ChannelDB) -> bool:
                    return bool(ch.detected_prefix and ch.detected_prefix in blocked_prefixes)

                def _first_significant_word(text: str) -> str:
                    for w in text.split():
                        if len(w) >= 3:
                            return w
                    return text.split()[0] if text.split() else ""

                is_live = channel.media_type == "live"
                ck = channel.content_key if not is_live else None  # content_key not used for live

                if is_live:
                    # Live channels: always use normalize_title matching (no content_key path).
                    # Include ALL providers (active and inactive) — inactive are marked so
                    # the source-picker chip can display them dimmed with a reactivate affordance.
                    norm = normalize_title(channel.name, channel.detected_prefix)
                    if not norm:
                        self._versions_loaded.emit(channel_id, [])
                        return
                    first_word = _first_significant_word(norm)
                    candidates = (
                        session.query(ChannelDB)
                        .filter(
                            ChannelDB.media_type == "live",
                            ChannelDB.id != channel_id,
                            ChannelDB.name.ilike(f"%{first_word}%"),
                        )
                        .all()
                    )
                    versions_raw = [
                        ch for ch in candidates
                        if normalize_title(ch.name, ch.detected_prefix) == norm
                    ]
                elif ck:
                    # VOD/series — primary path: group by stored content_key (indexed).
                    # Include ALL providers (active and inactive) for the source-picker chips;
                    # inactive ones are marked is_inactive so the chip renders them dimmed.
                    versions_raw = (
                        session.query(ChannelDB)
                        .filter(
                            ChannelDB.content_key == ck,
                            ChannelDB.id != channel_id,
                        )
                        .all()
                    )
                else:
                    # VOD/series fallback: content_key not yet populated (pre-backfill row);
                    # fall back to normalize_title matching with _version_years_compatible guard.
                    current_norm = normalize_title(channel.name, channel.detected_prefix)
                    if not current_norm:
                        self._versions_loaded.emit(channel_id, [])
                        return
                    first_word = _first_significant_word(current_norm)
                    if not first_word:
                        self._versions_loaded.emit(channel_id, [])
                        return
                    candidates = (
                        session.query(ChannelDB)
                        .filter(
                            ChannelDB.media_type == channel.media_type,
                            ChannelDB.id != channel_id,
                            ChannelDB.name.ilike(f"%{first_word}%"),
                        )
                        .all()
                    )
                    versions_raw = [
                        ch for ch in candidates
                        if normalize_title(ch.name, ch.detected_prefix) == current_norm
                        and _version_years_compatible(ch.name, channel.name)
                    ]

                # Score only active-source versions for preferred selection (inactive
                # sources can't be "preferred" — they're off by user choice)
                current_score = _version_score(channel, self.config)
                best_score = current_score
                best_ch = None
                for ch in versions_raw:
                    if ch.provider_id in hidden_provider_ids:
                        continue
                    s = _version_score(ch, self.config)
                    if s > best_score:
                        best_score = s
                        best_ch = ch

                versions = [
                    ChannelVersion(
                        channel_id=ch.id,
                        name=ch.name,
                        in_queue=ch.id in queue_ids,
                        detected_prefix=ch.detected_prefix,
                        detected_title=ch.detected_title,
                        detected_year=ch.detected_year,
                        detected_quality=ch.detected_quality,
                        detected_region=ch.detected_region,
                        is_preferred=(ch is best_ch),
                        is_filtered=_is_filtered(ch) if not ch.is_hidden else False,
                        is_hidden=bool(ch.is_hidden),
                        is_hidden_category=_is_hidden_category(ch),
                        is_favorite=bool(ch.is_favorite),
                        in_history=bool(ch.play_count),
                        provider_name=provider_names.get(ch.provider_id),
                        provider_id=ch.provider_id,
                        is_inactive=ch.provider_id in hidden_provider_ids,
                    )
                    for ch in versions_raw
                ]
                versions.sort(key=lambda v: (
                    v.is_inactive,          # active providers first
                    v.is_hidden,
                    v.is_filtered,
                    -_version_score(
                        next(c for c in versions_raw if c.id == v.channel_id), self.config
                    ),
                    v.name,
                ))
                versions = versions[:20]

        except Exception:
            logger.exception("Error fetching channel versions for %s", channel_id)
            versions = []

        self._versions_loaded.emit(channel_id, versions)

    def _on_versions_loaded(self, channel_id: str, versions: list) -> None:
        if (self.details_pane.current_channel
                and self.details_pane.current_channel.id == channel_id):
            self.details_pane.set_versions(versions)
        # Feed the anchor + any sibling variants to lazy TMDb enrichment — an idless
        # row a user is looking at is exactly one whose id a provider detail lookup
        # could resolve so it collapses onto the rest.  The anchor is ALWAYS enqueued,
        # even when the row is a content_key singleton with no "Other Versions": a
        # corrupted/idless title (e.g. the mojibake "|ES| Alita: …ngel de combate",
        # whose content_key groups with nothing) would otherwise never be attempted
        # by viewing its details, so it stays unmarked and never surfaces in the
        # "Missing TMDb" diagnostic.  enqueue() is idempotent and filters
        # non-candidates off-thread, so a redundant id here is harmless.
        self._enqueue_tmdb_enrichment(
            [channel_id] + [v.channel_id for v in versions]
        )

    def _on_prefix_block(self, prefix: str) -> None:
        if prefix and prefix not in self.config.global_filter_excluded_prefixes:
            self.config.global_filter_excluded_prefixes.append(prefix)
            _cfgsave.save_soon(self)
            self._update_filter_btn_state()
            self.load_channels()
            if self.details_pane.current_channel:
                self._fetch_channel_versions(self.details_pane.current_channel.id)
            self.notification_manager.show(
                title=f"{prefix} channels hidden",
                type="info",
                auto_dismiss_ms=6000,
                actions=[("Undo", lambda p=prefix: self._on_prefix_unblock(p))],
            )

    def _on_prefix_unblock(self, prefix: str) -> None:
        """Un-filter *prefix* across EVERY exclusion axis that can hide a version.

        A version is flagged *filtered* when its ``detected_prefix`` is in
        ``global_filter_excluded_categories`` **OR** ``global_filter_excluded_prefixes``
        (see ``_is_filtered`` in ``_fetch_channel_versions``).  The unblock must clear
        BOTH — clearing only the prefix axis silently no-ops when the token was excluded
        via Content Categories (e.g. an FR locale filter), which was the
        "Remove filter on FR content did nothing" bug: no removal, no refresh, no toast,
        and the variant stayed in FILTERED VARIANTS across reopen.
        """
        removed = False
        if prefix in self.config.global_filter_excluded_prefixes:
            self.config.global_filter_excluded_prefixes.remove(prefix)
            removed = True
        if prefix in self.config.global_filter_excluded_categories:
            self.config.global_filter_excluded_categories.remove(prefix)
            removed = True
        if not removed:
            return
        _cfgsave.save_soon(self)
        self._update_filter_btn_state()
        self.load_channels()
        if self.details_pane.current_channel:
            self._fetch_channel_versions(self.details_pane.current_channel.id)
        self.notification_manager.show(
            title=f"{prefix} content visible again",
            type="info",
            auto_dismiss_ms=4000,
        )

    def _on_prefix_name_saved(self, prefix: str, name: str) -> None:
        if name:
            self.config.category_name_overrides[prefix] = name
        else:
            self.config.category_name_overrides.pop(prefix, None)
        _cfgsave.save_soon(self)
        if self.details_pane.current_channel:
            self._fetch_channel_versions(self.details_pane.current_channel.id)

    # ── Similar Titles ──────────────────────────────────────────────────────

    def _fetch_similar_titles(self, channel_id: str) -> None:
        self.executor.submit(self._bg_fetch_similar_titles, channel_id)

    def _bg_fetch_similar_titles(self, channel_id: str) -> None:
        from metatv.core.database import UserRatingDB

        similar = []
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                # Canonical similar-titles chokepoint: owns the candidate selection,
                # content_key dedup, AND the visibility gate (is_hidden + inactive/
                # expired/orphaned provider exclusion). We shape best-per-group
                # ChannelVersion DTOs (queue/ratings/favorite/history) from its rows.
                excluded = set(repos.providers.get_hidden_provider_ids())
                rows = repos.channels.get_similar_channels(
                    channel_id,
                    excluded_provider_ids=excluded,
                    limit=20,
                    config=self.config,
                )
                if not rows:
                    self._similar_titles_loaded.emit(channel_id, [])
                    return

                queue_ids = repos.queue.get_queued_ids()
                ratings = {r.channel_id: r.rating for r in session.query(UserRatingDB).all()}
                similar = [
                    ChannelVersion(
                        channel_id=ch.id,
                        name=ch.name,
                        in_queue=ch.id in queue_ids,
                        detected_prefix=ch.detected_prefix,
                        detected_title=ch.detected_title,
                        detected_year=ch.detected_year,
                        is_favorite=bool(ch.is_favorite),
                        in_history=bool(ch.play_count),
                        media_type=ch.media_type or "",
                        user_rating=ratings.get(ch.id, 0),
                    )
                    for ch in rows
                ]
        except Exception:
            logger.exception("Error fetching similar titles for %s", channel_id)
            similar = []

        self._similar_titles_loaded.emit(channel_id, similar)

    def _on_similar_titles_loaded(self, channel_id: str, titles: list) -> None:
        if (self.details_pane.current_channel
                and self.details_pane.current_channel.id == channel_id):
            self.details_pane.set_similar_titles(titles)

    # ── Recommendations suppression ─────────────────────────────────────────

    def _hide_channel_from_recommendations(self, channel_id: str) -> None:
        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.set_hidden(channel_id, True)
        self.preferences_view.refresh()
        self._refresh_recommended_section()
        self.load_channels()
        self.channel_state_bus.publish(channel_id, is_hidden=True)

    def _bulk_hide_channels(self, channel_ids: list[str]) -> None:
        """Hide multiple channels from the channel list in one pass then refresh.

        Args:
            channel_ids: IDs of the channels to hide.
        """
        with self.db.session_scope() as session:
            repos = RepositoryFactory(session)
            for cid in channel_ids:
                repos.channels.set_hidden(cid, True)
        self.preferences_view.refresh()
        self._refresh_recommended_section()
        self.load_channels()

    def _unhide_channel(self, channel_id: str) -> None:
        def _bg() -> None:
            with self.db.session_scope() as session:
                RepositoryFactory(session).channels.set_hidden(channel_id, False)
        self.executor.submit(_bg)

        def _after() -> None:
            self.load_channels()
            self.channel_state_bus.publish(channel_id, is_hidden=False)

        QTimer.singleShot(150, _after)

    def _on_rec_sidebar_selected(self, channel_id: str, reason: str) -> None:
        # UI-11: show_channel_details_by_id is now async (the DTO read runs
        # off the main thread) — set_recommendation_reason must land AFTER
        # show_channel actually renders, since show_channel clears the same
        # meta section the reason label lives in. on_shown fires in the
        # main-thread result slot, right after the render, preserving the
        # old synchronous ordering.
        self.show_channel_details_by_id(
            channel_id,
            on_shown=lambda: self.details_pane.set_recommendation_reason(reason),
        )

    def _refresh_recommended_section(self) -> None:
        section = self.sidebar_sections.get("recommended")
        if section:
            section.refresh()

    # ── Channel details pane ────────────────────────────────────────────────

    def show_channel_details_by_id(self, channel_id: str, on_shown=None) -> None:
        """Show channel details in details pane (for sidebar selections).

        UI-11: the DTO read (previously a synchronous session_scope() +
        get_playable_dto() on the main thread) now runs off-thread through
        the ``_run_query`` seam — this call is fire-and-forget; the pane
        updates whenever the result lands, not before this returns.

        Args:
            channel_id: Channel to display.
            on_shown: Optional callback invoked on the main thread right
                after ``update_details_pane_for_channel`` returns for this
                id — for state that must land AFTER the render (e.g. the
                recommendation-reason label, which ``show_channel`` would
                otherwise clear if set beforehand). Not called when the
                channel no longer exists.
        """
        self._run_query(
            lambda repos: repos.channels.get_playable_dto(channel_id),
            lambda channel: self._on_details_channel_loaded(channel, on_shown),
            token_ref=self._details_channel_token,
        )

    def _on_details_channel_loaded(self, channel, on_shown=None) -> None:
        """Main-thread slot: render the DTO loaded by show_channel_details_by_id
        / on_channel_selection_changed, then fire any deferred on_shown callback."""
        if channel:
            self.update_details_pane_for_channel(channel)
            if on_shown:
                on_shown()

    def on_channel_selection_changed(self, current, previous):
        """Handle channel selection change — update details pane."""
        if not current:
            return
        from PyQt6.QtCore import Qt
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if not channel_id or channel_id == self._last_shown_channel_id:
            return
        self._last_shown_channel_id = channel_id

        # UI-11: DTO read moved off the main thread (see show_channel_details_by_id).
        self._run_query(
            lambda repos: repos.channels.get_playable_dto(channel_id),
            self._on_details_channel_loaded,
            token_ref=self._details_channel_token,
        )

    def update_details_pane_for_channel(self, channel, force: bool = False) -> None:
        """Update details pane with channel metadata (async).

        Args:
            channel: A PlayableChannelDTO (or channel-shaped test double).
            force: Bypass the same-title no-op AND the time debounce below —
                for a caller that explicitly wants a hard refresh of a title
                already shown. Grepped for an existing "refresh metadata"/
                force-refresh caller at UI-11 time: none exists, so nothing
                currently passes this — the kwarg is here so one can be
                wired later without touching this chokepoint again.
        """
        from metatv.core.models import MediaType

        # Deliberate diagnostics (2026-09-02; extended UI-11 2026-09-05): names
        # the caller AND the surface that reached IT, so the owner's next
        # "double render" log can name which pair of surfaces fired it without
        # another round of instrumentation.
        caller = sys._getframe(1).f_code.co_name
        try:
            surface = sys._getframe(2).f_code.co_name
        except ValueError:
            surface = "<top>"
        logger.debug(
            "details pane: render request for {} via {} <- {}",
            channel.id, caller, surface,
        )

        if not force:
            # UI-11 same-title no-op: the pane already shows this exact id
            # WITH its metadata applied — a repeat request (two surfaces
            # firing for one gesture, 350-500ms apart per the owner's log)
            # renders nothing and fetches nothing. Read via self.__dict__.get,
            # never getattr/hasattr — a skeleton test double built with
            # QObject.__new__ raises RuntimeError, not AttributeError, on an
            # attribute probe.
            shown = self.__dict__.get("_details_shown")
            if shown is not None and shown[0] == channel.id and shown[1]:
                logger.debug(
                    "details pane: already showing {id} with metadata — skipped",
                    id=channel.id,
                )
                return

            # Debounce: this is the ONE chokepoint every path funnels through
            # (show_channel_details_by_id, on_channel_selection_changed,
            # version_selected, programmatic sidebar calls). Reachable here
            # only while metadata for this id is STILL LOADING — the no-op
            # above already caught the "metadata applied" case — so this stays
            # time-gated rather than id-gated (see _RERENDER_DEBOUNCE_S above).
            now = time.monotonic()
            last = self.__dict__.get("_details_last_render")
            if (
                last is not None
                and last[0] == channel.id
                and (now - last[1]) < _RERENDER_DEBOUNCE_S
            ):
                logger.debug(
                    "details pane: suppressed duplicate render of {id} ({ms:.0f}ms after the last)",
                    id=channel.id, ms=(now - last[1]) * 1000,
                )
                return
            self._details_last_render = (channel.id, now)
        else:
            self._details_last_render = (channel.id, time.monotonic())

        if getattr(channel, "media_type", None) == MediaType.LIVE:
            self.details_pane.set_provider_urls([])
            self.details_pane.show_channel(channel, metadata=None)
            self._details_shown = (channel.id, False)
            return

        # UI-11: render basic info immediately; the provider-URL failover list
        # — previously a synchronous session_scope() + get_by_id() on the MAIN
        # thread here (2,259ms in the owner's 2026-09-03 sample) — now loads
        # off the executor through the _run_query seam and lands whenever
        # it's ready. The basic-info render never waits for it.
        self.details_pane.show_channel(channel, metadata=None)
        self._details_shown = (channel.id, False)
        logger.debug(f"Showing basic info for: {channel.name}")

        channel_id = channel.id
        provider_id = channel.provider_id

        def _fetch_provider_urls(repos):
            provider_db = repos.providers.get_by_id(provider_id)
            if not provider_db or not provider_db.urls:
                return []
            urls_data = parse_provider_urls(provider_db.urls)
            return [
                u.get('url') for u in urls_data
                if u.get('is_active', True) and u.get('url')
            ]

        def _apply_provider_urls(urls) -> None:
            cur = self.details_pane.current_channel
            if cur and cur.id == channel_id:
                self.details_pane.set_provider_urls(urls)
            logger.debug(f"Provider URLs for failover: {urls}")

        def _on_provider_urls_failed(exc: Exception) -> None:
            logger.warning(f"Could not fetch provider URLs: {exc}")
            cur = self.details_pane.current_channel
            if cur and cur.id == channel_id:
                self.details_pane.set_provider_urls([])

        self._run_query(
            _fetch_provider_urls,
            _apply_provider_urls,
            token_ref=self._details_urls_token,
            on_error=_on_provider_urls_failed,
        )

        # metadata_auto_fetch (Settings → Metadata & API Keys) gates ONLY this
        # automatic on-select fetch — basic info from the channel row above always
        # shows. A manual "Refresh metadata" action is unaffected by this switch.
        if not getattr(self.config, "metadata_auto_fetch", True):
            logger.debug(f"metadata_auto_fetch=False — skipping fetch for {channel.name}")
            return

        def fetch_metadata():
            logger.debug(f"=== fetch_metadata() thread started for {channel.name}")
            try:
                logger.debug("Creating event loop...")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                logger.debug(f"Fetching metadata for: {channel.name} (id={channel.id})")
                logger.debug(f"Calling metadata_manager.get_metadata({channel.id})...")
                metadata = loop.run_until_complete(
                    self.metadata_manager.get_metadata(channel.id)
                )
                logger.debug(f"get_metadata returned: {metadata}")
                loop.close()
                if metadata:
                    logger.info(f"Metadata fetched for {channel.name}: plot={bool(metadata.plot)}, cast={len(metadata.cast)}, poster={bool(metadata.poster_url)}")
                else:
                    logger.warning(f"No metadata returned for {channel.name}")
                return metadata
            except Exception as e:
                logger.error(f"Failed to load metadata for {channel.name}: {e}", exc_info=True)
                return None

        def on_metadata_loaded(future):
            if self._shutting_down:
                logger.debug("Metadata fetch completed after shutdown — discarding result")
                return
            try:
                metadata = future.result()
                logger.debug(f"on_metadata_loaded called, metadata={metadata is not None}")
                if metadata:
                    logger.debug(f"Emitting metadata_loaded signal for {channel.name}")
                    self.metadata_loaded.emit(channel, metadata)
                else:
                    logger.warning(f"on_metadata_loaded: No metadata returned for {channel.name}")
            except Exception as e:
                logger.error(f"Error in on_metadata_loaded: {e}", exc_info=True)

        future = self.executor.submit(fetch_metadata)
        future.add_done_callback(on_metadata_loaded)

    def _update_details_with_metadata(self, channel, metadata):
        """Update details pane with metadata (called on main thread via signal)."""
        try:
            logger.debug(f"_update_details_with_metadata called for {channel.name}")
            # Guard against a stale metadata fetch: if the pane has since moved to
            # a different channel, dropping this update prevents a slow fetch for
            # channel A from flipping the pane back from B to A (mirrors the
            # current-channel guard in _on_versions_loaded).
            cur = self.details_pane.current_channel
            if not (cur and cur.id == channel.id):
                logger.debug(
                    f"Ignoring stale metadata for superseded channel {channel.name}"
                )
                return
            logger.debug(f"Metadata has plot: {bool(metadata.plot)}, cast: {len(metadata.cast) if metadata.cast else 0}")
            self.details_pane.show_channel(channel, metadata=metadata)
            # UI-11: marks this id "fully shown" for the same-title no-op gate
            # in update_details_pane_for_channel — a repeat request for this
            # id now short-circuits instead of re-rendering + re-fetching.
            self._details_shown = (channel.id, True)
            logger.debug(f"Details pane updated with metadata for {channel.name}")
        except Exception as e:
            logger.error(f"Error updating details pane: {e}", exc_info=True)
