"""The three things the chip line needs from the filter panel, and nothing else.

The chip bar has to resolve a stored value to a label, count a facet's values,
and lift one constraint. Everything else about the panel — nine ``_Section``
attributes, grouped versus flat rows, the untagged footers — stays the panel's
own business, and this narrow surface is what keeps it that way.

Its own module because ``filter_panel.py`` sits on a shrink-only ratchet, and a
seam is exactly the kind of thing that reads better named than buried at line
700 of the class it serves.
"""

from __future__ import annotations

from loguru import logger


class _ChipSeamMixin:
    """Mixed into ``FilterPanel``. Assumes its ``_Section`` attributes."""


    def label_for(self, facet: str, key: str) -> str:
        """Resolve a stored facet value to its display label.

        Falls back to the key itself when the section has no such row — which
        happens legitimately: a persisted filter can name a value that this
        library no longer contains, and a chip reading the raw key is far
        better than a chip that is missing.
        """
        section = self._facet_sections().get(facet)
        if section is None:
            return key
        return section.label_for(key) or key

    def facet_totals(self) -> dict[str, int]:
        """How many values each facet holds — ``{"language": 41, …}``.

        Lets the chip bar tell "every value ticked but untagged hidden" apart
        from a genuine value constraint. ``tag_includes`` carries a full value
        set in both cases, so the count is the only thing that separates them.
        """
        return {facet: len(sec.get_all_keys())
                for facet, sec in self._facet_sections().items()}

    def clear_facet(self, facet: str) -> None:
        """Lift one constraint — the × on a chip.

        ``facet`` is either a panel section key, ``"media:<kind>"`` for a single
        media kind, or ``"hide_watched"``.

        Dropping the last media kind re-selects all three rather than leaving
        none. Zero kinds selected is an empty result list, and a × that empties
        the screen is not a remove button, it is a trap.
        """
        if facet == "hide_watched":
            self._hide_watched_cb.setChecked(False)
            return

        if facet.startswith("media:"):
            kind = facet.split(":", 1)[1]
            remaining = [k for k in self._media_sec.get_selected_keys() if k != kind]
            if remaining:
                self._media_sec.restore_selection(set(remaining))
                self._on_changed()
            else:
                self._media_sec.select_all()
                self._on_changed()
            return

        section = self._facet_sections().get(facet)
        if section is None:
            logger.debug(f"clear_facet: no section for facet {facet!r}")
            return
        section.select_all()
        self._on_changed()
