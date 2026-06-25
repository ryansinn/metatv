"""Metadata mixin — channel details loading, versions, similar titles, action states.

Extracted from MainWindow; mixed in via:
    class MainWindow(_MetadataMixin, ..., QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

import asyncio
import re

from loguru import logger
from PyQt6.QtCore import QTimer

from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import parse_provider_urls
from metatv.gui.details_actions import ChannelActionState
from metatv.gui.details_versions import ChannelVersion


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
        except Exception:
            logger.exception("Failed to fetch action state for %s", channel_id)
            return
        self._action_state_loaded.emit(state)

    def _on_action_state_loaded(self, state) -> None:
        self.details_pane.apply_action_state(state)

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
                _filter_paused = self.config.global_filter_paused
                excluded_cats = set() if _filter_paused else set(self.config.global_filter_excluded_categories)
                blocked_prefixes = set() if _filter_paused else set(self.config.global_filter_excluded_prefixes)
                all_excluded = excluded_cats | blocked_prefixes

                def _is_filtered(ch: ChannelDB) -> bool:
                    p = ch.detected_prefix
                    return bool(p and p in all_excluded)

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

    def _on_prefix_block(self, prefix: str) -> None:
        if prefix and prefix not in self.config.global_filter_excluded_prefixes:
            self.config.global_filter_excluded_prefixes.append(prefix)
            self.config.save()
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
        if prefix in self.config.global_filter_excluded_prefixes:
            self.config.global_filter_excluded_prefixes.remove(prefix)
            self.config.save()
            self._update_filter_btn_state()
            self.load_channels()
            if self.details_pane.current_channel:
                self._fetch_channel_versions(self.details_pane.current_channel.id)
            self.notification_manager.show(
                title=f"{prefix} channels visible again",
                type="info",
                auto_dismiss_ms=4000,
            )

    def _on_prefix_name_saved(self, prefix: str, name: str) -> None:
        if name:
            self.config.category_name_overrides[prefix] = name
        else:
            self.config.category_name_overrides.pop(prefix, None)
        self.config.save()
        if self.details_pane.current_channel:
            self._fetch_channel_versions(self.details_pane.current_channel.id)

    # ── Similar Titles ──────────────────────────────────────────────────────

    def _fetch_similar_titles(self, channel_id: str) -> None:
        self.executor.submit(self._bg_fetch_similar_titles, channel_id)

    def _bg_fetch_similar_titles(self, channel_id: str) -> None:
        from metatv.core.database import ChannelDB, MetadataDB, UserRatingDB
        from metatv.core.content_dedup import normalize_title, build_dedup_key
        from metatv.core.preference_engine import version_score as _version_score
        _non_ascii = re.compile(r'[^\x00-\x7F]+')

        similar = []
        try:
            with self.db.session_scope() as session:
                channel = session.get(ChannelDB, channel_id)
                if not channel:
                    self._similar_titles_loaded.emit(channel_id, [])
                    return

                norm = normalize_title(channel.name, channel.detected_prefix)
                words = [w for w in norm.split() if len(w) >= 4]
                if not words:
                    self._similar_titles_loaded.emit(channel_id, [])
                    return

                candidates = (
                    session.query(ChannelDB)
                    .filter(
                        ChannelDB.media_type == channel.media_type,
                        ChannelDB.id != channel_id,
                        ChannelDB.is_hidden == False,
                        ChannelDB.name.ilike(f"%{words[0]}%"),
                    )
                    .limit(200)
                    .all()
                )

                threshold = max(1, len(words) // 2)
                current_meta = session.get(MetadataDB, channel.metadata_id) if channel.metadata_id else None
                current_key = build_dedup_key(channel, current_meta)

                # Group by normalized title, keeping the best-scored version per title so
                # that users who have a preferred prefix (e.g. "EN") see that version when
                # they click a similar title rather than landing on a non-preferred version.
                best_per_title: dict[str, tuple[ChannelDB, int]] = {}
                for ch in candidates:
                    ch_norm = normalize_title(ch.name, ch.detected_prefix)
                    ch_norm_ascii = _non_ascii.sub(" ", ch_norm).strip()
                    ch_words = {w for w in ch_norm_ascii.split() if len(w) >= 4}
                    overlap = sum(1 for w in words if w in ch_words)
                    if overlap < threshold or ch_norm == norm:
                        continue
                    if current_key:
                        ch_meta = session.get(MetadataDB, ch.metadata_id) if ch.metadata_id else None
                        if build_dedup_key(ch, ch_meta) == current_key:
                            continue
                    score = _version_score(ch, self.config)
                    existing = best_per_title.get(ch_norm)
                    if existing is None or score > existing[1]:
                        best_per_title[ch_norm] = (ch, score)

                results = [ch for ch, _ in list(best_per_title.values())[:20]]

                repos = RepositoryFactory(session)
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
                    for ch in results[:20]
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

    def _unhide_channel(self, channel_id: str) -> None:
        def _bg() -> None:
            with self.db.session_scope() as session:
                RepositoryFactory(session).channels.set_hidden(channel_id, False)
        self.executor.submit(_bg)
        QTimer.singleShot(150, self.load_channels)

    def _on_rec_sidebar_selected(self, channel_id: str, reason: str) -> None:
        self.show_channel_details_by_id(channel_id)
        self.details_pane.set_recommendation_reason(reason)

    def _refresh_recommended_section(self) -> None:
        section = self.sidebar_sections.get("recommended")
        if section:
            section.refresh()

    # ── Channel details pane ────────────────────────────────────────────────

    def show_channel_details_by_id(self, channel_id: str):
        """Show channel details in details pane (for sidebar selections)."""
        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if channel:
            self.update_details_pane_for_channel(channel)

    def on_channel_selection_changed(self, current, previous):
        """Handle channel selection change — update details pane."""
        if not current:
            return
        from PyQt6.QtCore import Qt
        channel_id = current.data(Qt.ItemDataRole.UserRole)
        if not channel_id or channel_id == self._last_shown_channel_id:
            return
        self._last_shown_channel_id = channel_id

        channel = None
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if channel:
            self.update_details_pane_for_channel(channel)

    def update_details_pane_for_channel(self, channel):
        """Update details pane with channel metadata (async)."""
        from metatv.core.models import MediaType

        if getattr(channel, "media_type", None) == MediaType.LIVE:
            self.details_pane.set_provider_urls([])
            self.details_pane.show_channel(channel, metadata=None)
            return

        provider_urls = []
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                provider_db = repos.providers.get_by_id(channel.provider_id)
                if provider_db and provider_db.urls:
                    urls_data = parse_provider_urls(provider_db.urls)
                    provider_urls = [
                        u.get('url') for u in urls_data
                        if u.get('is_active', True) and u.get('url')
                    ]
            logger.debug(f"Provider URLs for failover: {provider_urls}")
        except Exception as e:
            logger.warning(f"Could not fetch provider URLs: {e}")

        self.details_pane.set_provider_urls(provider_urls)
        self.details_pane.show_channel(channel, metadata=None)
        logger.debug(f"Showing basic info for: {channel.name}")

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
            logger.debug(f"Metadata has plot: {bool(metadata.plot)}, cast: {len(metadata.cast) if metadata.cast else 0}")
            self.details_pane.show_channel(channel, metadata=metadata)
            logger.debug(f"Details pane updated with metadata for {channel.name}")
        except Exception as e:
            logger.error(f"Error updating details pane: {e}", exc_info=True)
