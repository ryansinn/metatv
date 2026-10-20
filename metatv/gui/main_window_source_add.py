"""Adding sources: the one Add path, the first-run guide, and re-adding after a fresh start.

Mixed into :class:`~metatv.gui.main_window.MainWindow`. Split out of
``main_window_providers`` (which edits, refreshes and deletes sources) because
adding is its own job: every Add Source button, the launch with no sources and
the Fresh-start-keep-sources restore all end in ``_on_provider_added``.
"""
from __future__ import annotations


class _SourceAddMixin:
    """Add Source, the first-run guide, and the fresh-start restore."""

    def add_provider(self):
        """Open the Sources screen on a new, blank source — the ONE Add path.

        Every Add Source button lands here (sidebar, menu, Sources header,
        empty states), so a source is added on the same form it is edited on
        and the user sees where sources live (docs/UI_UX_GUIDELINES.md, "One
        process, never a parallel flow").
        """
        self.switch_to_sources_manager()
        self.sources_manager_view.start_new_source()

    def _on_provider_added(self, provider_id: str, epg_enabled: bool) -> None:
        """A new source was added in the editor: show it, then load it."""
        if epg_enabled:
            # Fetch the guide once its first channel load finishes
            # (consumed by on_provider_refresh_finished).
            self._epg_fetch_after_add.add(provider_id)
        self._refresh_provider_dependent_views()
        self.sources_manager_view.refresh()
        self.sources_manager_view.select_provider(provider_id)
        self.refresh_provider(provider_id)
        self.status("Source added — loading its channels.", ms=5000)

    def restore_sources(self, sources: list[dict]) -> None:
        """After a fresh start that kept sources: add each one back, as if just added.

        Same path as Add Source (``_on_provider_added``): the row is written,
        the views refresh, the channels load and the guide is fetched. URL
        statistics start empty, like a new source.
        """
        from metatv.core.database import ProviderDB
        from metatv.core.models import ProviderURL
        from metatv.core.repositories.provider import provider_url_to_raw

        self._guided_to_first_source = True     # sources are on their way
        with self.db.session_scope() as session:
            for src in sources:
                fields = dict(src)
                urls = [u.get("url") if isinstance(u, dict) else u
                        for u in (fields.pop("urls", None) or [])] or [fields["url"]]
                fields["urls"] = [provider_url_to_raw(ProviderURL(url=u), priority=i)
                                  for i, u in enumerate(urls)]
                session.add(ProviderDB(**fields))
        for src in sources:
            self._on_provider_added(src["id"], bool(src.get("epg_enabled", True)))

    def _guide_to_first_source(self) -> None:
        """At launch with no sources: open the Sources screen on a blank source.

        Once per session, so deleting the last source later does not yank the
        user away from wherever they are.
        """
        if self.__dict__.get("_guided_to_first_source"):
            return
        self._guided_to_first_source = True
        self.add_provider()
