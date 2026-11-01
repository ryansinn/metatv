"""Global-Exclusion actions taken from menus: prefixes and collections.

The details pane's chip menus and the channel-row menu end here. Each action
writes one Global Exclusion field, refreshes what it hides, and offers Undo;
the Exclusions dialog lists the same fields, so every exclusion made here can
be found and reversed there.
"""

from __future__ import annotations

from metatv.gui import deferred_config_save as _cfgsave


class _ExclusionActionsMixin:
    """Prefix and collection exclude/include, mixed into :class:`MainWindow`."""

    def _on_prefix_block(self, prefix: str) -> None:
        if prefix and prefix not in self.config.global_filter_excluded_prefixes:
            self.config.global_filter_excluded_prefixes.append(prefix)
            self._after_exclusion_change()
            self.notification_manager.show(
                title=f'"{prefix}" content excluded',
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
        self._after_exclusion_change()
        self.notification_manager.show(
            title=f'"{prefix}" content included again',
            type="info",
            auto_dismiss_ms=4000,
        )

    # ── Collections (keyed by source) ────────────────────────────────────────

    def is_collection_excluded(self, provider_id: str, value: str) -> bool:
        return [provider_id, value] in [list(p) for p in self.config.global_filter_excluded_collections or []]

    def _after_exclusion_change(self) -> None:
        _cfgsave.save_soon(self)
        self._update_filter_btn_state()
        self.load_channels()
        if self.details_pane.current_channel:
            self._fetch_channel_versions(self.details_pane.current_channel.id)

    def _on_collection_exclude(self, provider_id: str, value: str) -> None:
        if not provider_id or not value or self.is_collection_excluded(provider_id, value):
            return
        self.config.global_filter_excluded_collections = [
            *map(list, self.config.global_filter_excluded_collections or []), [provider_id, value]]
        self._after_exclusion_change()
        self.notification_manager.show(
            title=f'Collection "{value}" excluded',
            type="info",
            auto_dismiss_ms=6000,
            actions=[("Undo", lambda: self._on_collection_include(provider_id, value))],
        )

    def _on_collection_include(self, provider_id: str, value: str) -> None:
        kept = [list(p) for p in self.config.global_filter_excluded_collections or []
                if list(p) != [provider_id, value]]
        if len(kept) == len(self.config.global_filter_excluded_collections or []):
            return
        self.config.global_filter_excluded_collections = kept
        self._after_exclusion_change()
        self.notification_manager.show(
            title=f'Collection "{value}" included again', type="info", auto_dismiss_ms=4000)

    def _exclude_collection_from_menu(self, ctx, gx: int, gy: int) -> None:
        """The row menu's "Exclude collection": one collection → exclude it;
        several (a title whose copies sit in different collections) → a picker
        at the same spot, as "Show N versions" does."""
        if len(ctx.collections) == 1:
            pid, _name, value, _n = ctx.collections[0]
            self._on_collection_exclude(pid, value)
            return
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        for pid, name, value, n in ctx.collections:
            act = menu.addAction(f"{value} · {name} ({n:,} channels)" if name else f"{value} ({n:,} channels)")
            act.triggered.connect(lambda _c=False, p=pid, v=value: self._on_collection_exclude(p, v))
        menu.exec(QPoint(gx, gy))
