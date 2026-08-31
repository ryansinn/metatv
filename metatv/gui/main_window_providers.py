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
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from loguru import logger

from metatv.core.notifications import StepStatus
from metatv.core.repositories import RepositoryFactory
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
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

    def _sources_status_target(self):
        """Resolve the current per-provider "Sources" UI surface.

        Wave 6: Sources no longer lives in the sidebar section stack — the
        per-row busy/EPG-spinner state now lives on
        :class:`~metatv.gui.sources_manager_view.SourcesManagerView`'s provider
        rows (built once, always present after ``setup_ui()``). Falls back to
        the legacy ``sidebar_sections["sources"]`` entry when the manager view
        isn't present in ``__dict__`` (transitional/test doubles that still
        stub the old sidebar section) — ONE chokepoint, never a parallel
        lookup per call site.

        ``__dict__.get`` (not ``hasattr``/``getattr``): on a bare-host test
        double built via ``MainWindow.__new__``, PyQt can raise
        ``RuntimeError`` on attribute access before ``setup_ui()`` runs, and
        ``hasattr`` only swallows ``AttributeError`` (see #351 / sidebar/alerts.py).
        """
        mgr = self.__dict__.get("sources_manager_view")
        if mgr is not None:
            return mgr
        sections = self.__dict__.get("sidebar_sections")
        return sections.get("sources") if sections else None

    def add_provider(self):
        """Show add provider dialog"""
        dialog = AddProviderDialog(self, self.config, self.db, self.notification_manager)
        if dialog.exec():
            self.load_providers()

    def _build_no_sources_banner(self) -> None:
        """Build the zero-sources empty-state banner and add it to ``_list_layout``.

        Shown above the (empty) channel list ONLY when the user has configured
        no source at all — see ``_show_no_sources_state``/``_on_channels_loaded``
        in ``main_window_channels.py``. A first-time user previously saw "No
        channels match — try a different search or check filter settings",
        which blames search/filters for a cause that is actually "there is no
        source yet" — misleading, and gives no next step. This banner states
        the real cause plainly and offers a discoverable "Add Source" button
        that calls :meth:`add_provider` directly — the SAME handler the
        sidebar '+' (``sidebar/sources.py``) and Sources-manager '+'
        (``sources_manager_view.py``) buttons already use, so there is still
        exactly one path that creates a source.

        Extracted into its own method (called once from ``setup_ui()``) so a
        test can build + wire it directly against a bare host, asserting the
        REAL construction/click-wiring code without booting the whole window.
        """
        self._no_sources_banner = QWidget()
        _nsb_layout = QHBoxLayout(self._no_sources_banner)
        _nsb_layout.setContentsMargins(8, 4, 8, 4)
        _nsb_layout.setSpacing(8)
        self._no_sources_lbl = QLabel(
            "No sources configured yet — add one to start browsing channels."
        )
        _theme.style_fn(self._no_sources_lbl, lambda: f"color: {_theme.COLOR_ACCENT_BLUE}; font-size: {_theme.FONT_MD};")
        self._no_sources_lbl.setWordWrap(True)
        _nsb_layout.addWidget(self._no_sources_lbl)
        _nsb_layout.addStretch()
        self._no_sources_add_btn = QPushButton(f"{_icons.provider_icon} Add Source")
        self._no_sources_add_btn.setToolTip("Add Source…")
        _theme.style_fn(self._no_sources_add_btn, lambda: f"QPushButton {{ border: 1px solid {_theme.COLOR_ACCENT_BLUE}; border-radius: 4px;"
            f" padding: 4px 12px; font-size: {_theme.FONT_MD}; font-weight: 600;"
            f" background: {_theme.OVERLAY_BLUE_20}; color: {_theme.COLOR_ACCENT_BLUE}; }}"
            f"QPushButton:hover {{ background: {_theme.OVERLAY_BLUE_40}; color: {_theme.COLOR_TEXT_HI}; }}")
        self._no_sources_add_btn.clicked.connect(self.add_provider)
        _nsb_layout.addWidget(self._no_sources_add_btn)
        _theme.style_fn(self._no_sources_banner, lambda: f"background: {_theme.OVERLAY_BLUE_10}; border-radius: 4px;")
        self._no_sources_banner.hide()
        self._list_layout.addWidget(self._no_sources_banner)

    def enter_provider_edit_mode(self, provider_id: str):
        """Switch center panel to provider editor for the given provider."""
        self._hide_all_content_views()
        self.provider_editor.setVisible(True)
        self.provider_editor.load_provider(provider_id)
        self.stats_label.setText("Editing source — click another to switch")
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
        self.source_analytics_view.setVisible(True)
        self.source_analytics_view.on_activate(provider_id)
        self.stats_label.setText("Analyzing source — click a source to switch")
        self._deactivate_view_chips()

    def exit_provider_analytics_mode(self):
        """Return to the normal channel list view."""
        self.source_analytics_view.on_deactivate()
        self.switch_to_list_view()

    def enter_missing_tmdb_mode(self):
        """Switch center panel to the Missing TMDb data diagnostic view.

        Opening it drives lazy enrichment (the view feeds the sampled ids through
        the enqueue chokepoint), so the idless counts fill in + shrink as ids land.
        """
        self._hide_all_content_views()
        self.missing_tmdb_view.setVisible(True)
        self.missing_tmdb_view.on_activate()
        self.stats_label.setText("Diagnosing TMDb coverage")
        self._deactivate_view_chips()

    def exit_missing_tmdb_mode(self):
        """Return to the normal channel list view."""
        self.missing_tmdb_view.on_deactivate()
        self.switch_to_list_view()

    def enter_reconnect_engaged_mode(self):
        """Switch center panel to the Reconnect Engaged Content view.

        Lists orphaned favorite/history/queue rows (their source was removed)
        alongside a proposed live replacement, so the user can explicitly move
        the engagement back onto an active source.
        """
        self._hide_all_content_views()
        self.reconnect_engaged_view.setVisible(True)
        self.reconnect_engaged_view.on_activate()
        self.stats_label.setText("Reconnecting engaged content")
        self._deactivate_view_chips()

    def exit_reconnect_engaged_mode(self):
        """Return to the normal channel list view."""
        self.reconnect_engaged_view.on_deactivate()
    def enter_metadata_enrichment_mode(self):
        """Switch center panel to the background metadata enrichment progress view."""
        self._hide_all_content_views()
        self.metadata_enrichment_view.setVisible(True)
        self.metadata_enrichment_view.on_activate()
        self.stats_label.setText("Background metadata enrichment")
        self._deactivate_view_chips()

    def exit_metadata_enrichment_mode(self):
        """Return to the normal channel list view."""
        self.metadata_enrichment_view.on_deactivate()
        self.switch_to_list_view()

    def toggle_provider_active(self, provider_id: str):
        """Flip the is_active flag for a provider and refresh all affected views."""
        sources = self._sources_status_target()
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
        sources = self._sources_status_target()
        had_busy = sources is not None and sources.has_busy()
        if sources is not None:
            sources.clear_busy()
        if had_busy:
            self.status_bar.clearMessage()

    def _on_provider_epg_refresh(self, provider_id: str) -> None:
        """Sidebar EPG indicator clicked — refresh that source's EPG feed."""
        sources = self._sources_status_target()
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
        sources = self._sources_status_target()
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
        sources = self._sources_status_target()
        if sources is not None:
            sources.refresh()

    def _on_provider_saved(self, provider_id: str):
        """Refresh dependent views after a provider is saved in the editor.

        Goes through the canonical refresh so an icon/name/credential edit
        reflects everywhere (sidebar AND the main list's provider badges), not
        just the sidebar.
        """
        self._refresh_provider_dependent_views()
        self.status_bar.showMessage("Source saved.", 3000)

    def _on_provider_deleted(self, provider_id: str):
        """Clean up after a provider is deleted from the editor."""
        self.exit_provider_edit_mode()
        self._refresh_provider_dependent_views()
        self.status_bar.showMessage("Source deleted.", 3000)

    def _on_provider_delete_requested(self, provider_id: str) -> None:
        """User confirmed a source delete — run the purge OFF the UI thread.

        The purge (:meth:`ChannelRepository.prune_provider_content`) sweeps hundreds
        of thousands of rows; running it on the Qt main thread froze the app ("Not
        Responding") for minutes on a large DB.  We submit it to the shared executor
        (mirrors the ``_on_all_refreshes_finished`` write-worker template) and marshal
        the outcome back via ``_provider_delete_finished`` so the editor reset + the
        canonical view refresh run on the main thread — never touching a widget from
        the worker.
        """
        if not provider_id:
            return

        # Disable the editor + mark the source row busy while the purge is in flight
        # (main thread — safe to touch widgets here).
        editor = getattr(self, "provider_editor", None)
        if editor is not None:
            editor.setEnabled(False)
        sources = self._sources_status_target()
        if sources is not None:
            sources.set_provider_busy(provider_id, True)

        # Indeterminate work — suppress the bar so it doesn't sit frozen at 0%
        # (the toast title is the progress indicator).
        notif_id = self.notification_manager.show_progress(
            title="Deleting source…", show_bar=False,
        )
        self._provider_delete_notifs[provider_id] = notif_id

        def _worker() -> None:
            try:
                with self.db.session_scope() as session:
                    deleted = RepositoryFactory(session).providers.delete(provider_id)
                self._provider_delete_finished.emit(provider_id, bool(deleted), "")
            except Exception as exc:  # noqa: BLE001 — reported to the main thread
                logger.exception("Provider delete failed")
                self._provider_delete_finished.emit(provider_id, False, str(exc))

        self.executor.submit(_worker)

    def _on_provider_delete_finished(
        self, provider_id: str, success: bool, error: str
    ) -> None:
        """Main-thread slot: the off-thread purge finished — reset UI + refresh.

        Clears the "Deleting source…" toast, re-enables the editor / source row, and
        on success routes through the canonical ``_on_provider_deleted`` path (exit
        edit mode + ``_refresh_provider_dependent_views``).  A failure surfaces an
        error toast rather than leaving the spinner running.
        """
        notif_id = self._provider_delete_notifs.pop(provider_id, None)
        if notif_id is not None:
            self.notification_manager.dismiss(notif_id)

        editor = getattr(self, "provider_editor", None)
        if editor is not None:
            editor.setEnabled(True)
        sources = self._sources_status_target()
        if sources is not None:
            sources.set_provider_busy(provider_id, False)

        if success:
            # Reset the editor so it never tries to reload the now-deleted provider,
            # then run the canonical delete-cleanup (exit edit mode + view refresh).
            if editor is not None:
                editor._provider_id = None
            self._on_provider_deleted(provider_id)
        else:
            msg = error or "The source could not be deleted."
            self.notification_manager.show(
                title="Delete Failed", message=msg, type="error",
            )
            logger.error(f"Provider {provider_id} delete failed: {error}")

    def _on_account_info_updated(self, provider_id: str):
        """Refresh the Sources UI when account info is updated.

        Called when account info is refreshed in the provider editor so the
        status strip's summary AND the manager view's row (if built) reflect
        the updated expiration date. Deliberately sources-only — the ONE
        sidebar-only exception to the canonical
        ``_refresh_provider_dependent_views`` chokepoint (unchanged by Wave 6,
        just retargeted from the old sidebar section to the strip + manager).
        """
        target = self._sources_status_target()
        if target is not None:
            target.refresh()
        strip = self.__dict__.get("sources_strip")
        if strip is not None:
            strip.refresh()

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
        # Filter-panel facet counts: a mutation may have added/removed facet values.
        # Re-run the tag-facet stats load (off-thread) so the panel reflects the new
        # corpus; on refresh/import this is what re-invokes FilterPanel.update_data,
        # which applies the opt-out model to newly-seen values and fires the
        # new-values popup. (initialize_filter_stats no-ops safely before the panel
        # exists.)
        if hasattr(self, "filter_panel"):
            self.initialize_filter_stats()
        # Center overlay views — lazily constructed, refresh only if present
        if hasattr(self, "discover_view"):
            self.discover_view.reload()
        if hasattr(self, "preferences_view"):
            self.preferences_view.refresh()
        # Recipe shelves are source-scoped too: reload so a source toggle does not
        # leave hidden-source cards on the shelves (mirrors the global-filter reload
        # path). reload() self-guards before the view has ever been activated.
        if "recipe_view" in self.__dict__:
            self.recipe_view.reload()
        # Missing-TMDb diagnostic: an enrichment batch just collapsed rows, so its
        # idless counts + samples should settle down. reload() self-guards on visible.
        if "missing_tmdb_view" in self.__dict__:
            self.missing_tmdb_view.reload()
        # Reconnect Engaged Content: the orphan set is entirely provider-hidden-state
        # derived, so any provider mutation can change it. reload() self-guards on visible.
        if "reconnect_engaged_view" in self.__dict__:
            self.reconnect_engaged_view.reload()
        # EPG scope (get_epg_active_provider_ids) shifts with source active/hidden
        # state. Re-resolve provider ids + reload live only when EPG is on screen;
        # a hidden EPG view re-resolves its scope on its next on_activate().
        epg_view = self.__dict__.get("epg_view")
        if epg_view is not None and epg_view.isVisible():
            epg_view._load_provider_ids()
            epg_view._reload_all()

    def edit_provider(self):
        """Legacy hook — no longer used (edit triggers from sidebar widget)."""

    def load_providers(self):
        """Refresh the Sources status strip + manager view from the database.

        The single per-mutation refresh step for Sources — reached via the
        canonical ``_refresh_provider_dependent_views`` chokepoint for every
        add/edit/delete/toggle, and directly after ``add_provider``'s dialog.
        """
        target = self._sources_status_target()
        if target is not None:
            target.refresh()
        strip = self.__dict__.get("sources_strip")
        if strip is not None:
            strip.refresh()
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
            # Prefix stats were computed in the worker thread — keep the unmapped
            # list for the "Uncategorized" workflow.  NOTE: we no longer feed these
            # prefix stats to FilterPanel.update_data() — that expected the legacy
            # {language_groups: …} shape while update_data() now takes the tag-facet
            # shape ({facet_type: {value: count}}), so the call silently EMPTIED
            # every facet section.  The filter panel now refreshes through the
            # canonical _refresh_provider_dependent_views() → initialize_filter_stats()
            # path (tag model), which also applies the opt-out / new-values logic.
            stats = getattr(thread, "prefix_stats", None) if thread is not None else None
            if stats:
                self._filter_unmapped_prefixes = stats.get("unmapped_prefixes", [])
                logger.info(
                    f"Filter stats: {stats['channels_with_prefix']:,} channels have prefixes"
                )

            # Refresh every view derived from provider/channel data (canonical).
            # This re-runs initialize_filter_stats() → FilterPanel.update_data().
            self._refresh_provider_dependent_views()
            # Re-check any failed streams now that content is fresh — gated by
            # the recheck_failed_on_refresh toggle (default on). check_all_now()
            # re-probes every pending retry-ledger row (flagged/degraded/dead all
            # keep status="pending" until they resolve), restoring recovered ones
            # to reliability_state="ok" via the mark_checked(ok=True) seam.
            # __dict__.get, not hasattr/getattr: on a MainWindow built via
            # __new__ (the bare-host test idiom) PyQt raises RuntimeError for
            # attribute access, and hasattr only swallows AttributeError — the
            # same trap fixed in #351 and documented in sidebar/alerts.py.
            _retry_mgr = self.__dict__.get("stream_retry_manager")
            _cfg = self.__dict__.get("config")
            if _retry_mgr is not None and getattr(
                _cfg, "recheck_failed_on_refresh", True
            ):
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

    def _on_all_refreshes_finished(self) -> None:
        """Whole-library dedup re-sweep after the whole refresh queue drains.

        Wired to ``refresh_queue_manager.all_refreshes_finished`` (fired once
        when the LAST enqueued source finishes).  Re-runs the FREE, no-network
        title-sibling tmdb propagation across the WHOLE library — decoupled from
        the one-time version-gated migration — so idless rows that only just
        became adoptable finally fold onto their canonical tmdb-first
        ``content_key``.  This covers the rows the one-time pass and the
        per-provider at-ingestion hook miss: a refresh that brings in the
        id-bearing variant *after* the one-time pass already ran, or an
        incremental refresh that skipped an unchanged idless row.  It also picks
        up rows a lazy ``get_vod/series_info`` marked ``tmdb_enrich_state='none'``
        — the propagation filter is ``detected_tmdb_id IS NULL`` (state-agnostic),
        so a previously lazy-failed row becomes eligible again on the next sweep.

        Runs OFF the UI thread (it scans/aggregates the channels table — the
        background-DB rule) on the owner's shared executor; the write commits in
        batches inside :meth:`ChannelRepository.propagate_tmdb_from_title_siblings`.
        The adopted count is marshalled back to the main thread via
        ``_propagation_finished`` so the view refresh happens on the main thread.
        The propagation itself is untouched — same shared helper (same
        media_type-only grouping, year-compat remake guard, fill-empty-only,
        generated-data-only) the migration and the ingestion hook call.
        """
        def _worker() -> None:
            try:
                with self.db.session_scope() as session:
                    adopted = RepositoryFactory(session).channels.\
                        propagate_tmdb_from_title_siblings()
            except Exception:
                logger.exception("post-refresh title-sibling propagation failed")
                return
            # Marshal the result back to the main thread (view refresh is a GUI op).
            self._propagation_finished.emit(adopted)

        self.executor.submit(_worker)

    def _on_propagation_finished(self, adopted: int) -> None:
        """Main-thread slot: refresh corpus-derived views when the re-sweep adopted ids.

        Only a positive adopt count changes ``content_key`` values, so we refresh
        exactly then (avoids a redundant reload when nothing folded).  Routes
        through the single canonical ``_refresh_provider_dependent_views`` so
        Browse, Discover, Recipe, filter-facet counts and the details "Other
        Versions" set all re-collapse together — never a partial per-view refresh.

        Args:
            adopted: Number of idless rows that adopted a sibling's tmdb id.
        """
        logger.info(
            "post-refresh title-sibling propagation: {} idless row(s) adopted a "
            "sibling id",
            adopted,
        )
        if adopted > 0:
            self._refresh_provider_dependent_views()

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
            except (TypeError, RuntimeError):
                pass  # silent: already disconnected — which is the state we wanted

        def _on_epg_error(pid: str, error: str) -> None:
            if pid != provider_id:
                return
            # Complete the toast with a warning rather than leaving it spinning
            self.notification_manager.complete_progress(notif_id, "EPG fetch failed")
            try:
                epg.refresh_started.disconnect(_on_epg_started)
                epg.refresh_finished.disconnect(_on_epg_finished)
                epg.refresh_error.disconnect(_on_epg_error)
            except (TypeError, RuntimeError):
                pass  # silent: already disconnected — which is the state we wanted

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
            src = self._sources_status_target()
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
        """Update provider status indicator in the Sources UI.

        Args:
            provider_id: Provider ID
            status: 'disabled', 'testing', 'online', 'offline'
        """
        target = self._sources_status_target()
        if target is not None:
            target.update_provider_status(provider_id, status)

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
