"""Provider/source lifecycle mixin for :class:`MainWindow`.

This module holds :class:`_ProviderMixin` — the provider/source lifecycle
methods extracted verbatim from ``main_window.py`` as part of the B10
decomposition. It covers the full add / edit / delete / refresh / toggle /
test surface plus the canonical ``_refresh_provider_dependent_views``
chokepoint that every provider mutation must funnel through.

The methods rely on attributes and sibling methods defined on ``MainWindow``
(e.g. ``self.db``, ``self.load_channels``); they resolve via ``self``/MRO at
runtime, so the split is behaviour-preserving.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from loguru import logger

from metatv.core.notifications import StepStatus
from metatv.core.repositories import RepositoryFactory
from metatv.gui.dialogs import AddProviderDialog


# ── Source-refresh step definitions ──────────────────────────────────────────
#
# Fixed step labels shown in the "Refreshing {source}" toast.  The mapper
# below advances these based on progress messages from ProviderLoadThread.
#
# EPG steps are optional: they are appended only when the source has
# ``epg_enabled`` and a usable EPG URL.

_STEP_FETCH    = "Fetching channels"
_STEP_STORE    = "Storing channels"
_STEP_PARSE    = "Parsing & detecting"
_STEP_EPG_DL   = "Downloading EPG"
_STEP_EPG_PARSE = "Parsing EPG"

# The base step list (without EPG steps).
_BASE_STEPS: list[str] = [_STEP_FETCH, _STEP_STORE, _STEP_PARSE]


def _make_steps(epg: bool) -> list[tuple[str, StepStatus]]:
    """Return the initial step list with all steps pending.

    Args:
        epg: When True, append the two EPG steps.

    Returns:
        list of ``(label, StepStatus.PENDING)`` tuples.
    """
    labels = _BASE_STEPS.copy()
    if epg:
        labels += [_STEP_EPG_DL, _STEP_EPG_PARSE]
    return [(lbl, StepStatus.PENDING) for lbl in labels]


def _advance_steps(
    steps: list[tuple[str, StepStatus]],
    message: str,
    pct: int,
) -> list[tuple[str, StepStatus]]:
    """Return a new step list reflecting the current progress message.

    Maps ProviderLoadThread / XtreamProvider progress messages to the fixed
    step set.  Message content takes priority over percentage because the
    batch-store sub-emits carry a distinctive ``"Storing channels"`` string.

    Progress flow (band constants are defined in provider_loader._BAND_*):
    * pct 0-14, messages "Connecting…" / "Fetching …":
        FETCH active; STORE/PARSE pending.
    * pct 15-22, message "Storing channels (…)" / "Stored N channels":
        FETCH done; STORE active (batch sub-emits + store-complete).
    * pct 22-37, message "Categorizing content (PPV/Events/Sports)…":
        STORE done; PARSE active.
    * pct 38-59, messages "Detecting prefixes (N / M channels)…":
        STORE done; PARSE active (per-batch sub-emits from _update_prefixes_in_thread).
    * pct 60-96, messages "Tagging N / M channels…" / "Computing content tags…":
        STORE done; PARSE active (per-batch sub-emits from _update_tags_in_thread).
    * pct 97, message "Updating filter statistics…":
        all channel steps done.
    * pct 100, message "Loaded N channels":
        all channel steps done.

    EPG steps (if present) are driven separately via ``_advance_epg_steps``.

    Args:
        steps:   Current step list.
        message: Progress message string.
        pct:     Progress percentage (0-100).

    Returns:
        New step list (same length as input).
    """
    labels = [lbl for lbl, _ in steps]

    # Detect phases by message first, then fall back to percentage.
    # _BAND_STORE[1] = 22 is the store-complete boundary emit.
    in_storing = "Storing channels" in message or (pct == 22 and "Stored" in message)
    in_parse   = ("Categorizing" in message or "Detecting" in message
                  or "Computing content tags" in message
                  or "Tagging" in message
                  or "Updating filter" in message)
    all_done   = pct >= 97 or (pct >= 100 and "Loaded" in message)

    def _compute(lbl: str) -> StepStatus:
        if lbl == _STEP_FETCH:
            if in_storing or in_parse or all_done or pct >= 22:
                return StepStatus.DONE
            return StepStatus.ACTIVE
        if lbl == _STEP_STORE:
            if in_parse or all_done:
                return StepStatus.DONE
            if in_storing or pct == 22:
                return StepStatus.ACTIVE
            return StepStatus.PENDING
        if lbl == _STEP_PARSE:
            if all_done:
                return StepStatus.DONE
            if in_parse:
                return StepStatus.ACTIVE
            return StepStatus.PENDING
        # EPG steps — untouched by this mapper; keep current status.
        current_map = dict(steps)
        return current_map.get(lbl, StepStatus.PENDING)

    return [(lbl, _compute(lbl)) for lbl in labels]


def _advance_epg_steps(
    steps: list[tuple[str, StepStatus]],
    stage: str,
) -> list[tuple[str, StepStatus]]:
    """Advance the EPG step pair based on *stage*.

    Args:
        steps: Current step list (must contain EPG step labels).
        stage: One of ``"started"`` (set Downloading→active, Parsing→pending)
               or ``"finished"`` (set both EPG steps→done).

    Returns:
        New step list.
    """
    result = []
    for lbl, status in steps:
        if lbl == _STEP_EPG_DL:
            if stage == "started":
                status = StepStatus.ACTIVE
            elif stage == "finished":
                status = StepStatus.DONE
        elif lbl == _STEP_EPG_PARSE:
            if stage == "started":
                status = StepStatus.PENDING
            elif stage == "finished":
                status = StepStatus.DONE
        result.append((lbl, status))
    return result


def _has_epg_steps(steps: list[tuple[str, StepStatus]]) -> bool:
    """Return True if *steps* includes the EPG step pair."""
    labels = {lbl for lbl, _ in steps}
    return _STEP_EPG_DL in labels


class _ProviderMixin:
    """Provider/source lifecycle methods mixed into :class:`MainWindow`."""

    def add_provider(self):
        """Show add provider dialog"""
        dialog = AddProviderDialog(self, self.config, self.db, self.notification_manager)
        if dialog.exec():
            self.load_providers()

    def enter_provider_edit_mode(self, provider_id: str):
        """Switch center panel to provider editor for the given provider."""
        self._hide_all_content_views()
        self.provider_editor.setVisible(True)
        self.provider_editor.load_provider(provider_id)
        self.stats_label.setText("Editing provider — click a source to switch")
        self._in_provider_edit_mode = True
        self._deactivate_view_chips()

    def exit_provider_edit_mode(self):
        """Return to the normal channel list view."""
        self._in_provider_edit_mode = False
        self.switch_to_list_view()
        self.load_providers()

    def enter_provider_analytics_mode(self, provider_id: str):
        """Switch center panel to source analytics for the given provider."""
        self._hide_all_content_views()
        self.source_analytics.setVisible(True)
        self.source_analytics.on_activate(provider_id)
        self.stats_label.setText("Analyzing source — click a source to switch")
        self._deactivate_view_chips()

    def exit_provider_analytics_mode(self):
        """Return to the normal channel list view."""
        self.source_analytics.on_deactivate()
        self.switch_to_list_view()

    def toggle_provider_active(self, provider_id: str):
        """Flip the is_active flag for a provider and refresh all affected views."""
        sources = self.sidebar_sections.get("sources")
        # Re-entrancy guard: the canonical refresh below can take many seconds
        # (recommendations recompute over the whole library), so ignore repeat
        # clicks while one is in flight rather than stacking them.
        if sources is not None and sources.is_provider_busy(provider_id):
            self.status_bar.showMessage("Source update already in progress…", 2000)
            return
        if sources is not None:
            sources.set_provider_busy(provider_id, True)
        self.status_bar.showMessage("Updating views…")

        session = self.db.get_session()
        try:
            from metatv.core.database import ProviderDB as _PDB
            db_prov = session.query(_PDB).filter_by(id=provider_id).first()
            if db_prov:
                db_prov.is_active = not db_prov.is_active
                session.commit()
                logger.info(f"Provider '{db_prov.name}' is_active → {db_prov.is_active}")
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to toggle provider: {e}")
            self._clear_provider_busy()   # early-return cleanup (CLAUDE.md rule)
            return
        finally:
            session.close()
        # Refresh every view derived from provider/channel data (canonical).
        # Busy state is cleared when the channel reload completes (_on_channels_loaded);
        # the timer is a safety net in case that signal never fires.
        self._refresh_provider_dependent_views()
        QTimer.singleShot(30_000, self._clear_provider_busy)

    def _clear_provider_busy(self) -> None:
        """Clear any in-flight provider busy/spinner state and the status message.

        Called when a provider-triggered refresh completes (via _on_channels_loaded)
        and as a safety timeout from toggle_provider_active."""
        sources = self.sidebar_sections.get("sources")
        had_busy = sources is not None and sources.has_busy()
        if sources is not None:
            sources.clear_busy()
        if had_busy:
            self.status_bar.clearMessage()

    def _on_provider_epg_refresh(self, provider_id: str) -> None:
        """Sidebar EPG indicator clicked — refresh that source's EPG feed."""
        sources = self.sidebar_sections.get("sources")
        if sources is not None:
            sources.set_provider_epg_refreshing(provider_id, True)
            # Safety net: clear the spinner if the fetch never signals back (e.g. the
            # provider has no usable EPG URL, so force_refresh_provider no-ops).
            QTimer.singleShot(
                90_000,
                lambda pid=provider_id: self._epg_refresh_spinner_off(pid),
            )
        self.status_bar.showMessage("Refreshing EPG…", 3000)
        self.epg_manager.force_refresh_provider(provider_id)

    def _epg_refresh_spinner_off(self, provider_id: str) -> None:
        sources = self.sidebar_sections.get("sources")
        if sources is not None:
            sources.set_provider_epg_refreshing(provider_id, False)

    def _maybe_refresh_provider_epg(self, provider_id: str) -> None:
        """Step 2 of a source refresh: pull current EPG — unless EPG is off.

        Gated on the per-provider ``epg_enabled`` flag and a usable EPG URL, so a
        source whose EPG the user turned off is skipped entirely. Reuses the
        canonical EPG-refresh path (sidebar spinner + status + force_refresh), so a
        refreshed source's guide is fresh without a separate manual EPG refresh.
        """
        if getattr(self, "epg_manager", None) is None:
            return
        from metatv.core.database import ProviderDB
        session = self.db.get_session()
        try:
            provider = session.query(ProviderDB).filter_by(id=provider_id).first()
            if provider is None:
                return
            if not getattr(provider, "epg_enabled", True):
                logger.info(f"EPG disabled for {provider_id} — skipping post-refresh EPG fetch")
                return
            if not self.epg_manager.effective_epg_url(provider):
                logger.info(f"No EPG URL for {provider_id} — skipping post-refresh EPG fetch")
                return
        finally:
            session.close()
        logger.info(f"Source refresh complete for {provider_id} — fetching current EPG")
        self._on_provider_epg_refresh(provider_id)

    def _on_provider_epg_refreshed(self, provider_id: str, *_args) -> None:
        """EPG fetch finished/errored — rebuild Sources so the indicator recolors with
        the new date range and the spinner clears."""
        sources = self.sidebar_sections.get("sources")
        if sources is not None:
            sources.refresh()

    def _on_provider_saved(self, provider_id: str):
        """Refresh dependent views after a provider is saved in the editor.

        Goes through the canonical refresh so an icon/name/credential edit
        reflects everywhere (sidebar AND the main list's provider badges), not
        just the sidebar.
        """
        self._refresh_provider_dependent_views()
        self.status_bar.showMessage("Provider saved.", 3000)

    def _on_provider_deleted(self, provider_id: str):
        """Clean up after a provider is deleted from the editor."""
        self.exit_provider_edit_mode()
        self._refresh_provider_dependent_views()
        self.status_bar.showMessage("Provider deleted.", 3000)

    def _on_account_info_updated(self, provider_id: str):
        """Refresh sources sidebar when account info is updated.

        Called when account info is refreshed in the provider editor so the
        sidebar color/display reflects the updated expiration date.
        """
        sources_section = self.sidebar_sections.get("sources")
        if sources_section:
            sources_section.refresh()

    def _refresh_provider_dependent_views(self) -> None:
        """Canonical refresh for everything derived from provider/channel data.

        ALL provider/source mutations — add, edit, delete, refresh-complete,
        toggle active/visibility — must funnel through this one method instead
        of hand-picking a subset of views at each call site. Hand-picking is
        what repeatedly left views stale (e.g. the sidebar icon updated but the
        main list's ``provider_icon_map`` did not, so new sources showed content
        with no icon). Keep this list complete; do not re-implement partial
        refreshes elsewhere.
        """
        # Sidebar sections fed by the channel/provider corpus
        self.load_providers()
        self.load_favorites()
        self.load_history()
        self._refresh_queue_section()
        self._refresh_recommended_section()
        # Main channel list / search results — also rebuilds provider_icon_map
        self.load_channels()
        # Center overlay views — lazily constructed, refresh only if present
        if hasattr(self, "discover_view"):
            self.discover_view.reload()
        if hasattr(self, "preferences_view"):
            self.preferences_view.refresh()

    def edit_provider(self):
        """Legacy hook — no longer used (edit triggers from sidebar widget)."""
        pass

    def load_providers(self):
        """Load providers from database into sidebar"""
        if "sources" in self.sidebar_sections:
            self.sidebar_sections["sources"].refresh()
        self._refresh_details_provider_map()

    def _refresh_details_provider_map(self):
        """Push current provider icon/name map to the details pane."""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all()
            provider_map = {
                p.id: {"icon": getattr(p, "icon", "") or "", "name": p.name}
                for p in providers
            }
            self.details_pane.set_provider_map(provider_map)
        except Exception as e:
            logger.warning(f"Could not refresh provider map: {e}")
        finally:
            session.close()

    def _provider_has_epg(self, provider_id: str) -> bool:
        """Return True when the provider has EPG enabled and a usable URL.

        Used to decide whether to include EPG steps in the refresh toast.
        Reads from the DB so it reflects any config changes made since startup.
        """
        if getattr(self, "epg_manager", None) is None:
            return False
        from metatv.core.database import ProviderDB
        session = self.db.get_session()
        try:
            provider = session.query(ProviderDB).filter_by(id=provider_id).first()
            if provider is None:
                return False
            if not getattr(provider, "epg_enabled", True):
                return False
            return bool(self.epg_manager.effective_epg_url(provider))
        finally:
            session.close()

    def refresh_provider(self, provider_id: str):
        """Enqueue a provider for serial refresh via the queue manager.

        All provider refresh calls — single-source, refresh-all, and startup —
        funnel through :class:`~metatv.gui.refresh_queue_manager.RefreshQueueManager`
        which processes one source at a time and maintains a single consolidated
        overview notification.  Duplicate enqueue calls for the same provider are
        silently ignored by the manager.
        """
        if not hasattr(self, "refresh_queue_manager"):
            # Safety fallback: manager not yet initialised (shouldn't happen in
            # normal startup, but guards against test environments that only
            # partially construct MainWindow).
            logger.warning("RefreshQueueManager not yet available; ignoring refresh_provider call")
            return

        # Look up the provider name for the overview notification label
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(provider_id)
            if not db_provider:
                logger.error(f"Provider not found: {provider_id}")
                return
            provider_name = db_provider.name
        finally:
            session.close()

        self.refresh_queue_manager.enqueue(provider_id, provider_name)

    def on_provider_refresh_finished(
        self,
        notif_id: str,
        success: bool,
        message: str,
        thread,
        current_steps: list | None = None,
    ):
        """Legacy entry point — retained so test code that calls it directly still works.

        New code should wire :meth:`_on_queue_refresh_finished` to
        ``refresh_queue_manager.refresh_finished`` instead.  This method
        reconstructs the minimum context needed to call the canonical handler.
        """
        provider_id = getattr(thread, "provider_id", None)
        self._on_queue_refresh_finished(provider_id, success, message, thread)

    def _on_queue_refresh_finished(
        self,
        provider_id: str,
        success: bool,
        message: str,
        thread,
    ) -> None:
        """Canonical post-refresh handler — wired to ``refresh_queue_manager.refresh_finished``.

        Runs all the side-effects that must happen after a provider's channel
        corpus is freshly loaded: prefix stats, view refresh, EPG relink,
        monitor/alert checks, and the post-refresh EPG pull.

        Called on the main thread (delivered via Qt signal from the manager).
        """
        # Remove thread from legacy active_threads list (threads started by the
        # queue manager are not in this list, but harmless if absent).
        if thread is not None and thread in self.active_threads:
            self.active_threads.remove(thread)

        # Legacy refreshing_providers set — discard to avoid leaving a stale entry
        # (the queue manager already guards duplicates, so this is belt-and-braces).
        if provider_id and provider_id in self.refreshing_providers:
            self.refreshing_providers.discard(provider_id)

        if success:
            # Prefix stats were computed in the worker thread — just apply them.
            stats = getattr(thread, "prefix_stats", None) if thread is not None else None
            if stats:
                self._filter_unmapped_prefixes = stats.get("unmapped_prefixes", [])
                if hasattr(self, "filter_panel"):
                    self.filter_panel.update_data(stats)
                logger.info(
                    f"Filter stats: {stats['channels_with_prefix']:,} channels have prefixes"
                )

            # Refresh every view derived from provider/channel data (canonical)
            self._refresh_provider_dependent_views()
            # Re-check any failed streams now that content is fresh
            if hasattr(self, "stream_retry_manager"):
                self.stream_retry_manager.check_all_now()

            # Relink EPG rows against the freshly-loaded channel corpus.
            # This is a DB-only pass (no network fetch) that fixes the partial-match
            # case: channels whose EPG rows were stored with channel_db_id=NULL
            # because they weren't loaded at XMLTV fetch time get linked now.
            if getattr(self, "epg_manager", None):
                self.epg_manager.relink_all()

            # Check monitored series for new episodes.
            if provider_id and "series_monitor" in self.__dict__:
                self.series_monitor.check_provider(provider_id)

            # Check VOD watch-for rules against this provider's freshly-loaded content.
            if provider_id and "vod_watch_alert_manager" in self.__dict__:
                self.vod_watch_alert_manager.check_provider(provider_id)

            # Post-refresh EPG pull: step 2 of a source refresh.
            if provider_id:
                self._epg_fetch_after_add.discard(provider_id)
                self._maybe_refresh_provider_epg(provider_id)
        else:
            # Channel load failed — drop any pending add-time EPG flag.
            if provider_id:
                self._epg_fetch_after_add.discard(provider_id)

    def _on_queue_epg_wire_requested(
        self,
        active_notif_id: str,
        provider_id: str,
        current_steps: list,
    ) -> None:
        """Connect EPG-manager signals to the active step-checklist toast.

        Called via ``refresh_queue_manager._request_epg_wire`` signal when a
        source refresh finished and its toast has EPG step rows.  Delegates to
        the existing :meth:`_wire_epg_step_signals` helper.
        """
        if _has_epg_steps(current_steps[0]) and provider_id:
            self._wire_epg_step_signals(active_notif_id, provider_id, current_steps)

    def _wire_epg_step_signals(
        self,
        notif_id: str,
        provider_id: str,
        current_steps: list,
    ) -> None:
        """Connect EPG-manager signals to advance the EPG step pair in the toast.

        Uses one-shot lambdas scoped to this notification so signal connections
        don't accumulate across multiple refreshes.  Both handlers disconnect
        themselves after firing so resources are freed even if only one fires
        (e.g. an error fires refresh_error, not refresh_finished).

        Args:
            notif_id:      The notification to update.
            provider_id:   The provider being refreshed.
            current_steps: The mutable step-list container shared with the
                           progress handler.
        """
        epg = self.epg_manager

        def _on_epg_started(pid: str) -> None:
            if pid != provider_id:
                return
            steps = _advance_epg_steps(current_steps[0], "started")
            current_steps[0] = steps
            self.notification_manager.set_steps(notif_id, steps)

        def _on_epg_finished(pid: str, count: int) -> None:
            if pid != provider_id:
                return
            steps = _advance_epg_steps(current_steps[0], "finished")
            current_steps[0] = steps
            self.notification_manager.set_steps(notif_id, steps)
            # Complete the toast once EPG is done
            self.notification_manager.complete_progress(
                notif_id, f"{count:,} programmes loaded"
            )
            # Disconnect to avoid accumulating handlers on long-running sessions
            try:
                epg.refresh_started.disconnect(_on_epg_started)
                epg.refresh_finished.disconnect(_on_epg_finished)
                epg.refresh_error.disconnect(_on_epg_error)
            except Exception:
                pass

        def _on_epg_error(pid: str, error: str) -> None:
            if pid != provider_id:
                return
            # Complete the toast with a warning rather than leaving it spinning
            self.notification_manager.complete_progress(notif_id, "EPG fetch failed")
            try:
                epg.refresh_started.disconnect(_on_epg_started)
                epg.refresh_finished.disconnect(_on_epg_finished)
                epg.refresh_error.disconnect(_on_epg_error)
            except Exception:
                pass

        epg.refresh_started.connect(_on_epg_started)
        epg.refresh_finished.connect(_on_epg_finished)
        epg.refresh_error.connect(_on_epg_error)

    def refresh_all_providers(self) -> None:
        """Enqueue providers for serial refresh via the queue manager.

        When ``config.refresh_all_includes_inactive`` is False (default),
        providers with ``is_active=False`` are silently skipped — the user has
        toggled them off and doesn't want to pay the refresh cost for them (and
        they're already scoped out of every content view).  Set it True to also
        enqueue disabled sources, matching the historical behaviour.

        Note: this setting never affects per-source refresh (the individual
        refresh button) — that is always a deliberate user action and always
        works regardless of ``is_active``.
        """
        skip_inactive = not getattr(self.config, "refresh_all_includes_inactive", False)
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            # Fetch all providers; filter inactive here so we can log the count.
            all_providers = repos.providers.get_all(active_only=False)
            if skip_inactive:
                skipped = [p for p in all_providers if not p.is_active]
                providers = [p for p in all_providers if p.is_active]
                if skipped:
                    logger.info(
                        "Refresh All: skipped %d inactive source(s): %s",
                        len(skipped),
                        ", ".join(p.name for p in skipped),
                    )
            else:
                providers = all_providers
            provider_pairs = [(p.id, p.name) for p in providers]
        finally:
            session.close()
        # Enqueue through the manager so they run serially, not concurrently
        for pid, pname in provider_pairs:
            if hasattr(self, "refresh_queue_manager"):
                self.refresh_queue_manager.enqueue(pid, pname)
            else:
                # Fallback (shouldn't happen in normal usage)
                self.refresh_provider(pid)

    def on_provider_selected(self, item, column):
        """Handle provider selection in tree"""
        provider_id = item.data(0, Qt.ItemDataRole.UserRole)
        if provider_id:
            self.selected_provider_id = provider_id
            logger.info(f"Selected provider: {provider_id}")
            self.load_channels(provider_id)

    def on_provider_selected_new(self, provider_id: str):
        """Handle provider selection from modular sidebar.

        In provider edit mode, clicking a source switches the editor instead of
        filtering the channel list.  Otherwise clicking the already-active source
        toggles the per-source filter OFF; clicking a different source switches to it.
        """
        if self._in_provider_edit_mode:
            self.provider_editor.load_provider(provider_id)
            return
        if provider_id and provider_id == self.selected_provider_id:
            # Toggle OFF — clicking the active source again clears the filter.
            self.selected_provider_id = None
            self._save_search_state()
            self.load_channels(None)
            src = self.sidebar_sections.get("sources")
            if src is not None and hasattr(src, "clear_selection"):
                src.clear_selection()
            logger.info("Cleared source filter (toggled off)")
        else:
            self.selected_provider_id = provider_id
            self._save_search_state()
            logger.info(f"Selected provider: {provider_id}")
            self.load_channels(provider_id)

    def toggle_provider_visibility(self, provider_id: str):
        """Toggle provider visibility (active/disabled)"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider = repos.providers.get_by_id(provider_id)
            if provider:
                # Toggle active state
                provider.is_active = not provider.is_active
                session.commit()

                logger.info(f"Provider {provider.name} is now {'active' if provider.is_active else 'disabled'}")

                # Update status button
                self.update_provider_status(provider_id, "testing" if provider.is_active else "disabled")

                # Refresh every view derived from provider/channel data (canonical)
                self._refresh_provider_dependent_views()

                # Test connection if enabled
                if provider.is_active:
                    self.test_provider_connection(provider_id)
        finally:
            session.close()

    def update_provider_status(self, provider_id: str, status: str):
        """Update provider status indicator in sidebar

        Args:
            provider_id: Provider ID
            status: 'disabled', 'testing', 'online', 'offline'
        """
        if "sources" in self.sidebar_sections:
            self.sidebar_sections["sources"].update_provider_status(provider_id, status)

    def test_all_providers(self):
        """Test connection for all active providers on startup"""
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            providers = repos.providers.get_all(active_only=True)

            for provider in providers:
                self.update_provider_status(provider.id, "testing")
                self.test_provider_connection(provider.id)
        finally:
            session.close()

    def test_provider_connection(self, provider_id: str):
        """Test connection to a specific provider"""
        session = self.db.get_session()
        try:
            from metatv.core.provider_loader import ProviderTestThread

            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(provider_id)
            if not db_provider:
                return

            # Start test in background
            test_thread = ProviderTestThread(
                db_provider.type,
                db_provider.url,
                db_provider.username,
                db_provider.password
            )
            test_thread.result.connect(
                lambda success, msg, pid=provider_id: self.on_connection_test_result(pid, success, msg)
            )

            # Keep thread alive
            self.active_threads.append(test_thread)
            test_thread.finished.connect(
                lambda: self.active_threads.remove(test_thread) if test_thread in self.active_threads else None
            )

            test_thread.start()
        finally:
            session.close()

    def on_connection_test_result(self, provider_id: str, success: bool, message: str):
        """Handle connection test result"""
        logger.info(f"Provider {provider_id} test result: {'online' if success else 'offline'} - {message}")
        self.update_provider_status(provider_id, "online" if success else "offline")
