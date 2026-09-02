"""Projecting a flat list of rows into collapsible sections.

Split out of :mod:`channel_list_model` for the reason ``sidebar/section_cap``
and ``core/db_lock`` were, and with the same test: one cohesive behaviour, one
entry point, and a host file that reads better without it. The model was
1,024 lines and had been re-baselined against the code-health ratchet THREE
TIMES in a single session — every one of them for this concern growing. That is
the ratchet doing its job: it is a place to stop and look, and what it kept
pointing at was a second subject living inside the first.

**What stays behind, deliberately.** The ``if self._grouped:`` branches in
``rowCount``, ``data``, ``set_channels`` and ``append_page`` are not moved.
Grouping is a display transform layered over the model's own row store, so the
model necessarily asks "am I grouped?" at the points where Qt asks IT for rows.
Moving those would mean inverting the model's public interface to satisfy a
line count, which is the arithmetic answer the CLAUDE.md guidance rejects:
"split by isolation, not the line count".

**What moved** is everything that only grouping needs — the section order and
labels, the bucket store and its ordering rules, the display-row arithmetic,
the two public mutators, and the paged-append splice.
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional

from PyQt6.QtCore import QModelIndex, Qt

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.core.repositories.search_ranking import (
    WORD_TIERS,
    SECTION_ORDER as _SEARCH_SECTIONS,
)
from metatv.gui.channel_list_roles import (
    CHANNEL_HTML_ROLE, ROW_KIND_ROLE, SECTION_COLLAPSED_ROLE,
    SECTION_COUNT_ROLE, SECTION_LABEL_ROLE, SECTION_TYPE_ROLE,
    SECTION_WORD_ONLY_ROLE,
)
from metatv.gui import theme as _theme


# Search sections are appended here, not left to the alphabetically-sorted
# "extras" branch, which renders Cast & Crew ABOVE Titles — backwards. Order
# comes from search_ranking so there is one definition, not two that can drift.
SECTION_ORDER: tuple[str, ...] = ("movie", "series", "live") + _SEARCH_SECTIONS
_SECTION_LABELS: dict[str, str] = {
    "movie": "Movies", "series": "Series", "live": "Live",
    # "Cast & Crew" covers cast and director: three headers would be near-empty.
    "title": "Titles", "cast": "Cast & Crew",
}


def _heading_html(label: str, count: int, *, second_level: bool = False) -> str:
    """The settled two-tone heading, as HTML for a delegate-painted row.

    Transcribed from ``GroupHeading`` / ``SIDEBAR_GROUP_HEADING`` rather than
    invented, so the channel list and the sidebar say the same thing the same
    way. Three parts of that grammar this list was breaking:

    * **Two tones.** A label at ``COLOR_TEXT`` / ``FONT_SM`` / bold against a
      count at ``COLOR_TEXT_HI`` / ``FONT_MD`` / bold. The count carries the
      emphasis because it is the VARIABLE half — the label always says the
      same word. Both were one flat bright weight here.
    * **No caret.** *"The heading itself is the control, exactly as the section
      headers have been since #329 — a caret beside a clickable title is a
      second affordance for one action."* This list had one.
    * **Small caps**, which is why the label arrives already uppercased.

    ``second_level`` inverts which half is the constant, and that is the same
    rule rather than an exception to it: a PERSON's name is the variable and
    the film count is incidental, so the name takes the bright ramp. It is also
    why the name may not use ``COLOR_TEXT_LOW`` — measured 4.15:1 there, under
    the 4.5 text floor in four of six palettes, and "quiet" cannot be bought
    with contrast a reader needs.
    """
    if second_level:
        return (
            f'<span style="color:{_theme.COLOR_TEXT_HI};font-size:'
            f'{_theme.FONT_MD};font-weight:bold">{_html.escape(label)}</span>'
            f'<span style="color:{_theme.COLOR_TEXT};font-size:'
            f'{_theme.FONT_SM}">&#160;&#160;{count:,}</span>'
        )
    return (
        f'<span style="color:{_theme.COLOR_TEXT};font-size:{_theme.FONT_SM};'
        f'font-weight:bold">{_html.escape(label)}</span>'
        f'<span style="color:{_theme.COLOR_TEXT_HI};font-size:{_theme.FONT_MD};'
        f'font-weight:bold">&#160;&#160;{count:,}</span>'
    )


class ChannelListGroupingMixin:
    """Section projection for :class:`ChannelListModel`.

    Reaches the host through ``self`` and owns none of its widgets — the same
    shape as ``RowBudgetMixin`` and ``SectionContentCapMixin`` in the sidebar.
    """

    # ── Group-by-type: section helpers ───────────────────────────────────────

    def _header_data(self, section: str, role: int) -> Any:
        """Return ``data()`` for a section-header row (grouped mode only)."""
        if role == ROW_KIND_ROLE:
            return "header"
        if role == SECTION_TYPE_ROLE:
            return section
        label = _SECTION_LABELS.get(section, (section or "Other").title())
        if role == SECTION_LABEL_ROLE:
            return label.upper()
        if role == SECTION_COUNT_ROLE:
            return self.section_result_count(section)
        if role == SECTION_COLLAPSED_ROLE:
            return section in self._collapsed_sections
        if role == SECTION_WORD_ONLY_ROLE:
            # None means "draw no slider": narrowing by HOW the term matched is
            # meaningless when there is no term, and Movies/Series/Live are not
            # match rungs. Only the two SEARCH sections offer it.
            if section not in _SEARCH_SECTIONS:
                return None
            return section in self._word_only
        if role in (Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE):
            # Plain text only. The band is painted (see the delegate) because a
            # flex:1 hairline and a segmented control are not expressible in
            # Qt rich text; this stays for size hints, accessibility and tests.
            return f"{label} ({self.section_result_count(section):,})"
        return None

    def toggle_person_collapsed(self, person: str) -> None:
        """Fold or unfold one person's films, leaving their name in place.

        A full reset rather than a splice: a person's run is a contiguous block,
        but folding one changes every display row BELOW it in every later
        section too, and the arithmetic for that is the bug this file keeps
        producing. The list is small by the time anyone reaches for the control.

        **Not persisted**, unlike a section's collapse state. The runs are named
        after whoever the CURRENT search matched, so remembering that "Nicolas
        Cage" was folded would silently fold a later, unrelated search that
        happens to surface him again — the app closing something the user never
        closed, which is the defect ``sidebar/section_cap`` was gutted over.
        """
        self.beginResetModel()
        if person in self._collapsed_people:
            self._collapsed_people.discard(person)
        else:
            self._collapsed_people.add(person)
        self._rebuild_buckets()
        self.endResetModel()

    def is_person_collapsed(self, person: str) -> bool:
        """Whether *person*'s films are currently folded away."""
        return person in self._collapsed_people

    def section_result_count(self, section: str) -> int:
        """Results VISIBLE in a section — what its header should say.

        Not ``len(self._buckets[section])``: with "Whole" active the header
        would name a number the user cannot find on screen, which is the
        specific complaint that made counts worth having. Sub-headings are not
        counted either — a person's name is not a result.
        """
        return sum(1 for kind, _v in self._layout(section) if kind == "channel")

    def set_section_word_only(self, section: str, word_only: bool) -> None:
        """Narrow a section to whole-word matches, or open it back up.

        A full reset rather than fine-grained inserts: the rows this removes are
        scattered through the section's runs, so there is no contiguous block to
        hand Qt. The list is small by the time anyone reaches for this control.
        """
        if bool(word_only) == (section in self._word_only):
            return
        self.beginResetModel()
        if word_only:
            self._word_only.add(section)
        else:
            self._word_only.discard(section)
        self._rebuild_buckets()
        self.endResetModel()

    def is_section_word_only(self, section: str) -> bool:
        """Whether *section* is currently narrowed to whole-word matches."""
        return section in self._word_only

    def _person_data(self, person: str, role: int) -> Any:
        """Return ``data()`` for a matched-person sub-heading row.

        The owner's reason for it, on a page of eighty "cage" results:
        *"that way you don't have 10 Nicolas Cage lines."* Measured on the real
        library, those eighty resolve to 65 Nicolas Cage, 4 Weston Cage, 3 Finn
        McCager Higgins, 2 David Beaucage — where the weak matches become
        self-evidently weak by sitting in a small, NAMED group instead of being
        eighty rows each needing an explanation.

        Quieter than a section header on purpose: this is the second level, and
        two competing headings read as two lists. Muted colour, no count, no
        arrow — a person's run cannot be collapsed independently, and an arrow
        that does nothing is worse than no arrow.
        """
        if role == ROW_KIND_ROLE:
            return "person"
        if role == SECTION_TYPE_ROLE:
            return person
        if role in (Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE):
            count = self._person_counts.get(person, 0)
            if role == Qt.ItemDataRole.DisplayRole:
                return f"{person} ({count:,})"
            return _heading_html(person, count, second_level=True)
        return None

    def _ordered_sections(self) -> list[str]:
        """Sections that currently hold ≥1 loaded row, in fixed display order."""
        return [s for s in self._final_section_order() if self._buckets.get(s)]

    def _final_section_order(self, extra_keys=()) -> list[str]:
        """Display order over current buckets plus any soon-to-be-created sections.

        The single ordering rule; ``_ordered_sections`` is this filtered to the
        non-empty ones. They were two implementations of the same sort until
        adding a section to one and not the other became possible.
        """
        keys = set(self._buckets.keys()) | set(extra_keys)
        known = [s for s in SECTION_ORDER if s in keys]
        others = sorted(k for k in keys if k not in SECTION_ORDER)
        return known + others

    def _section_size(self, section: str) -> int:
        """Number of *display rows* a section occupies (0 if empty)."""
        if not self._buckets.get(section):
            return 0
        # Sub-headings are display rows, so the count is the LAYOUT's length,
        # not the bucket's. Reading the bucket here put every section after
        # Cast & Crew at the wrong offset by exactly the number of people in it.
        return 1 + (0 if section in self._collapsed_sections
                    else len(self._layout(section)))

    def _section_display_start(self, section: str, order=None) -> int:
        """Display-row index where ``section``'s header sits."""
        order = order if order is not None else self._final_section_order([section])
        total = 0
        for s in order:
            if s == section:
                return total
            total += self._section_size(s)
        return total

    def _resolve_row(self, row: int) -> Optional[tuple[str, Any]]:
        """Map a grouped display row → ``("header", section)`` or ``("channel", idx)``."""
        for section in self._ordered_sections():
            size = self._section_size(section)
            if row < size:
                if row == 0:
                    return ("header", section)
                # Content rows are only reachable when the section is expanded
                # (collapsed → size==1 so only row 0 is in range).
                return self._layout(section)[row - 1]
            row -= size
        return None

    def _extend_bucket(self, section: str, indices: list[int]) -> None:
        """Append channel indices to a section bucket, updating the position map."""
        bucket = self._buckets.setdefault(section, [])
        for ci in indices:
            self._bucket_pos[ci] = len(bucket)
            bucket.append(ci)

    def _rebuild_buckets(self) -> None:
        """Rebuild the section buckets + position map from ``_channels`` order."""
        self._buckets = {}
        self._bucket_pos = {}
        self._layouts = {}
        # From the sub-filter's survivors, not from every loaded row: one
        # definition of "which rows exist right now", shared with flat mode.
        for i in self._visible:
            self._extend_bucket(self._channels[i].section, [i])
        for section in list(self._buckets):
            self._rebuild_layout(section)

    def _rebuild_layout(self, section: str) -> None:
        """Recompute one section's display entries, grouping rows by person.

        A section's rows arrive in relevance order — tier, then title — which
        scatters one actor's films across the whole section. A sub-heading over
        scattered rows would be a lie, so the rows are REORDERED here, by the
        person first seen and then by their original relevance position.

        The result is one entry per display row under the header:
        ``("person", name)`` or ``("channel", index)``. Rows with no matched
        person (every Titles row, and any cast row whose name could not be
        resolved) keep their order and get no sub-heading — mirror-not-cage: a
        row nobody can label still gets a row.

        Run order is first-appearance, which is the only honest choice: the
        persons are not ranked against each other, and ordering them any other
        way would move a group while the user reads it.
        """
        self._commit_layout(section, self._compute_layout(section))

    def _compute_layout(self, section: str) -> list:
        """The section's display entries, computed without mutating anything.

        Separate from the commit because ``beginInsertRows`` has to be told how
        many rows are coming BEFORE ``rowCount()`` reports them; a version that
        stored as it computed made the model report the new count during its own
        insert, which Qt treats as a corrupt model.
        """
        indices = self._buckets.get(section, ())
        if section in self._word_only:
            # "Whole" keeps the rungs where the TERM IS A WORD — exact, prefix,
            # whole word — and drops the one where it merely appears inside a
            # longer word: Astronaut answering a search for "tron".
            #
            # A section defaults to showing everything and this is the user
            # narrowing it, never the other way round. Hiding weak matches by
            # default is silent pre-filtering, which PRODUCT_VISION principle 8
            # ("mirror, never cage") rules out — and on a 785,000-row library
            # the weird match is often the point. Owner: "with over 700,000
            # rows of content, letting people find weird shit is valuable."
            indices = [ci for ci in indices
                       if getattr(self._channels[ci], "match_tier", 0)
                       in WORD_TIERS]
        people = {}
        for pos, ci in enumerate(indices):
            person = getattr(self._channels[ci], "match_person", None) or ""
            people.setdefault(person, []).append((pos, ci))

        layout = []
        # "" (no person) first and unlabelled, then each named run in the order
        # its first row appeared.
        for person, rows in sorted(
                people.items(), key=lambda kv: (kv[0] != "", kv[1][0][0])):
            if person:
                layout.append(("person", person))
                self._person_counts[person] = len(rows)
                if person in self._collapsed_people:
                    # The name stays; its films fold away under it. Same rule as
                    # a section header — owner: "we need to be able to collapse
                    # every cast and crew subheader as well."
                    continue
            layout.extend(("channel", ci) for _pos, ci in rows)

        return layout

    def _commit_layout(self, section: str, layout: list) -> None:
        """Store a computed layout and re-point the reverse lookup at it.

        ``_bucket_pos`` is the row's offset in the section's DISPLAY entries,
        not in the bucket: it is what ``_display_row_for_channel_index`` adds to
        the header position, and a sub-heading occupies a row like anything
        else. Reading the bucket offset here put every row after the first
        sub-heading one place too high.
        """
        self._layouts[section] = layout
        for entry_pos, (kind, value) in enumerate(layout):
            if kind == "channel":
                self._bucket_pos[value] = entry_pos

    def _layout(self, section: str) -> list:
        """The section's display entries, built on demand for older callers."""
        if section not in self._layouts:
            self._rebuild_layout(section)
        return self._layouts[section]

    def _display_row_for_channel_index(self, ci: int) -> Optional[int]:
        """Grouped display row for a ``_channels`` index, or None if not visible."""
        if not self._grouped:
            return ci
        if not (0 <= ci < len(self._channels)):
            return None
        section = self._channels[ci].section
        if section in self._collapsed_sections:
            return None  # hidden under a collapsed header
        self._layout(section)          # ensure _bucket_pos reflects the layout
        pos = self._bucket_pos.get(ci)
        if pos is None:
            return None
        return self._section_display_start(section) + 1 + pos

    def row_for_channel_id(self, channel_id: str) -> Optional[int]:
        """Public display-row lookup for a loaded channel id.

        Returns ``None`` when the channel isn't loaded, or (grouped mode) its
        section is currently collapsed. Used by the channel-list thumbnail
        hydrator (``channel_list_thumbnails.py``) to map a completed
        ``ImageCache.image_loaded(url, pixmap)`` signal back to the display
        row(s) that requested it, so it can emit a targeted ``dataChanged``.
        """
        idx = self._id_to_index.get(channel_id)
        if idx is None:
            return None
        return self._display_row_for_channel_index(idx)

    # ── Group-by-type: public mutators ───────────────────────────────────────

    def set_grouped(self, grouped: bool, collapsed_sections=None) -> None:
        """Turn grouping on/off (a full reset — deliberate user toggle).

        Args:
            grouped: True → project the loaded rows into Movies/Series/Live sections.
            collapsed_sections: Optional iterable of media_types to start collapsed
                (restored from config); ignored when None.
        """
        self.beginResetModel()
        self._group_by_type = self._grouped = bool(grouped)
        if collapsed_sections is not None:
            self._collapsed_sections = set(collapsed_sections)
        if self._grouped:
            self._rebuild_buckets()
        self.endResetModel()

    def set_section_collapsed(self, section: str, collapsed: bool) -> None:
        """Collapse/expand one section, inserting/removing just its content rows."""
        currently = section in self._collapsed_sections
        if not self._grouped or collapsed == currently:
            # Still record intent so a later set_grouped() restores it.
            if collapsed:
                self._collapsed_sections.add(section)
            else:
                self._collapsed_sections.discard(section)
            return
        n = len(self._buckets.get(section, ()))
        start = self._section_display_start(section)
        if collapsed:
            if n > 0:
                self.beginRemoveRows(QModelIndex(), start + 1, start + n)
                self._collapsed_sections.add(section)
                self.endRemoveRows()
            else:
                self._collapsed_sections.add(section)
        else:
            if n > 0:
                self.beginInsertRows(QModelIndex(), start + 1, start + n)
                self._collapsed_sections.discard(section)
                self.endInsertRows()
            else:
                self._collapsed_sections.discard(section)
        # Repaint the header so its arrow glyph flips.
        hdr = self.createIndex(start, 0)
        self.dataChanged.emit(
            hdr, hdr, [Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE]
        )

    @property
    def is_grouped(self) -> bool:
        """Whether group-by-type display is currently ON."""
        return self._grouped

    def _append_grouped(self, dtos: list[ChannelListDTO]) -> None:
        """Splice a fetched page into the grouped display, section by section.

        Rows arrive in SQL (name) order — interleaving all media types — so each
        type's new rows land at the END of its section's content block.  Sections
        are processed in display order so every insert position is computed against
        the model state AFTER earlier sections in this batch have been inserted.
        """
        start_index = len(self._channels)
        new_by_section: dict[str, list[int]] = {}
        for offset, ch in enumerate(dtos):
            # ``ch.section``, NOT ``ch.media_type``: a searching page carries a
            # section_key, and reading media_type here filed every row appended
            # on scroll under Movies/Series/Live — the same defect the first-page
            # path was fixed for, still live on the second page.
            new_by_section.setdefault(ch.section, []).append(
                start_index + offset
            )
        # Store the DTOs first (buckets reference these indices).
        self._channels.extend(dtos)
        self._rebuild_index()

        final_order = self._final_section_order(new_by_section.keys())
        for section in final_order:
            indices = new_by_section.get(section)
            if not indices:
                continue
            existed = bool(self._buckets.get(section))
            collapsed = section in self._collapsed_sections
            if not existed:
                # Brand-new section: header + (rows when expanded) as one block.
                pos = self._section_display_start(section, final_order)
                self._extend_bucket(section, indices)
                layout = self._compute_layout(section)
                visible = 1 + (0 if collapsed else len(layout))
                self.beginInsertRows(QModelIndex(), pos, pos + visible - 1)
                self._commit_layout(section, layout)
                self.endInsertRows()
            elif collapsed:
                # Hidden under a collapsed header — only the count label changes.
                self._extend_bucket(section, indices)
                self._commit_layout(section, self._compute_layout(section))
                self._emit_header_changed(section, final_order)
            else:
                # The section's content is REPLACED, not appended to. A new row
                # for a person who already has a run belongs inside that run,
                # which is an insert in the middle — so "append at the end" is
                # only correct for a section with no sub-headings, and silently
                # wrong for the one that has them.
                start = self._section_display_start(section, final_order)
                old_n = len(self._layout(section))
                if old_n:
                    self.beginRemoveRows(QModelIndex(), start + 1, start + old_n)
                    self._layouts[section] = []
                    self.endRemoveRows()
                self._extend_bucket(section, indices)
                new_layout = self._compute_layout(section)
                self.beginInsertRows(QModelIndex(), start + 1,
                                     start + len(new_layout))
                self._commit_layout(section, new_layout)
                self.endInsertRows()
                self._emit_header_changed(section, final_order)

    def _emit_header_changed(self, section: str, order=None) -> None:
        """Repaint a section header (its count/arrow changed)."""
        start = self._section_display_start(section, order)
        hdr = self.createIndex(start, 0)
        self.dataChanged.emit(
            hdr, hdr, [Qt.ItemDataRole.DisplayRole, CHANNEL_HTML_ROLE]
        )
