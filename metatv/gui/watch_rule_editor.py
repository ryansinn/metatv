"""The Option B rule row — one editor, for composing a rule and for editing one.

Settled in "Catch, Keep, Record" (2026-08-30) Q3: *Option B now* — a structured
row where each control is one idea, built on an engine that can express the
smart-text syntax (Option C) later as a parser onto these same fields rather
than a second matcher. And Q4: *one list, two surfaces* — a rule is stored once
and rendered by both Watch Alerts and the EPG watchlist.

**The same widget composes and edits.** The watchlist used to add rules through
a bare text box, which stopped fitting the moment a rule grew a mode, an
exclude list and a scope — owner: *"having just the plain text box does not
work with the complexity of the watchlist rule now."* A "New rule" button now
expands this, so the form you fill in is the form you later come back to.

Match and Look-in are SEGMENTED tracks rather than a dropdown and a checkbox,
per the mockup. A dropdown hides two thirds of the choice behind a click and
makes the current mode read as a setting rather than a decision;
``ToggleChip`` already renders a segmented track (Sports uses it for lanes), so
nothing new was built for it.

It is deliberately dumb about storage and about counting. It renders a
:class:`WatchRule`, emits a new one when the user changes something, and
displays whatever counts it is handed. The host owns the write and owns the
query — "how many programmes does this rule match" scans the guide, and
CLAUDE.md is explicit that an EPG-sized query never runs on the UI thread.

The summary line is not decoration. From the artifact: *"showing the suppressed
count is what makes an exclude list trustworthy — otherwise you can never tell
the difference between 'my exclusions are working' and 'my pattern stopped
matching'."*
"""

from __future__ import annotations

from functools import partial

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from metatv.core.watchlist_matching import (
    ALL_WORDS, ANY_WORD, MATCH_MODES, PHRASE, WatchRule,
)
from metatv.gui import icons
from metatv.gui import theme as _theme
from metatv.gui.filter_bar import ToggleChip

#: Mode value -> the label the user reads. Their own three names for the axis
#: ("Includes, Consecutively" / "Includes, all matched" / 'any, separated by
#: ","'), shortened to what fits a segment.
_MODE_LABELS = {
    PHRASE: "Phrase",
    ALL_WORDS: "All words",
    ANY_WORD: "Any word",
}

_MODE_HELP = {
    PHRASE: "The words must appear together, in this order.",
    ALL_WORDS: "Every term must appear somewhere in the programme.",
    ANY_WORD: "Any one of the terms is enough.",
}


def split_terms(text: str) -> tuple[str, ...]:
    """Comma-separated text -> terms, blanks dropped.

    ``WatchRule.terms`` does the same split on the stored string; this is the
    editor's half of that contract, named so the round trip (edit -> store ->
    match) is testable without a widget.
    """
    return tuple(t.strip() for t in (text or "").split(",") if t.strip())


class WatchRuleEditor(QWidget):
    """The expanded body of a watch-rule row, and the new-rule form.

    Args:
        compose: True for the "New rule" form — adds Cancel/Add buttons and
            emits :attr:`rule_committed` instead of live-editing. The controls
            are identical either way, which is the point.

    Signals:
        rule_changed: A new :class:`WatchRule` whenever the user changes any
            control. Never emitted by :meth:`set_rule`, which is a programmatic
            restore. Not emitted at all in compose mode.
        rule_committed: The finished rule when Add is clicked (compose only).
        cancelled: Cancel was clicked (compose only).
    """

    rule_changed = pyqtSignal(object)
    rule_committed = pyqtSignal(object)
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, *,
                 compose: bool = False) -> None:
        super().__init__(parent)
        self._rule = WatchRule(term="")
        self._compose = compose
        self._matched: int | None = None
        self._suppressed: int | None = None
        self._horizon_days = 7

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        #: Exposed so a caller (and the layout test) can reach a field's label
        #: via ``labelForField`` — the two-column shape is part of the design,
        #: not an accident of the default policy.
        self.form = form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self.mode_chips: "dict[str, ToggleChip]" = {}
        mode_row = QHBoxLayout()
        mode_row.setSpacing(0)
        mode_row.setContentsMargins(0, 0, 0, 0)
        last = len(MATCH_MODES) - 1
        for i, mode in enumerate(MATCH_MODES):
            segment = "first" if i == 0 else ("last" if i == last else "middle")
            chip = ToggleChip(_MODE_LABELS[mode], enabled=(mode == PHRASE),
                              segment=segment)
            chip.setToolTip(_MODE_HELP[mode])
            chip.toggled_changed.connect(partial(self._on_mode_clicked, mode))
            self.mode_chips[mode] = chip
            mode_row.addWidget(chip)

        mode_row.addSpacing(12)
        self.whole_word_chip = ToggleChip(
            "Whole words only", enabled=WatchRule(term="").whole_word)
        self.whole_word_chip.setToolTip(
            'Off means "contains, anywhere" — "NFL" would then also match '
            '"Inflammation".')
        self.whole_word_chip.toggled_changed.connect(self._on_chip_toggled)
        mode_row.addWidget(self.whole_word_chip)
        mode_row.addStretch()
        mode_host = QWidget()
        mode_host.setLayout(mode_row)
        form.addRow(self._label("Match"), mode_host)

        self.include_input = QLineEdit()
        self.include_input.setClearButtonEnabled(True)
        self.include_input.setPlaceholderText("Denver Broncos, Broncos, DEN")
        self.include_input.setToolTip(
            "Separate terms with commas. How they combine is set by Match.")
        self.include_input.editingFinished.connect(self._emit)
        self.include_input.textChanged.connect(self._on_text_changed)
        form.addRow(self._label("Include"), self.include_input)

        self.exclude_input = QLineEdit()
        self.exclude_input.setClearButtonEnabled(True)
        self.exclude_input.setPlaceholderText("news, pregame, highlights")
        self.exclude_input.setToolTip(
            "A programme matching any of these is skipped, even when it also "
            "matches the Include terms.")
        self.exclude_input.editingFinished.connect(self._emit)
        form.addRow(self._label("Exclude"), self.exclude_input)

        # Title is always searched, so its chip shows ON and is not clickable:
        # offering to turn it off would be offering a rule that searches
        # nothing.
        look_row = QHBoxLayout()
        look_row.setSpacing(0)
        look_row.setContentsMargins(0, 0, 0, 0)
        self.title_chip = ToggleChip("Title", enabled=True, segment="first")
        # NOT Qt-disabled: a greyed chip reads as "off", and titles are always
        # searched. Clicking it simply re-asserts itself.
        self.title_chip.setToolTip("Titles are always searched.")
        self.title_chip.toggled_changed.connect(
            lambda _on: self.title_chip.set_enabled(True))
        look_row.addWidget(self.title_chip)
        self.description_chip = ToggleChip("Description", enabled=False,
                                           segment="last")
        self.description_chip.setToolTip(
            "Also search the programme synopsis. Finds more, and more of what "
            "it finds will be loose matches.")
        self.description_chip.toggled_changed.connect(self._on_chip_toggled)
        look_row.addWidget(self.description_chip)
        look_row.addStretch()
        look_host = QWidget()
        look_host.setLayout(look_row)
        form.addRow(self._label("Look in"), look_host)

        outer.addLayout(form)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        _theme.style(self.summary_label, "META_HINT")
        outer.addWidget(self.summary_label)

        if compose:
            footer = QHBoxLayout()
            footer.addStretch()
            self.cancel_btn = QPushButton("Cancel")
            self.cancel_btn.setFlat(True)
            self.cancel_btn.clicked.connect(self.cancelled.emit)
            footer.addWidget(self.cancel_btn)
            self.add_btn = QPushButton("Track it")
            self.add_btn.setDefault(True)
            self.add_btn.setToolTip("Start watching for anything this matches")
            self.add_btn.clicked.connect(self._on_commit)
            footer.addWidget(self.add_btn)
            outer.addLayout(footer)
            self._update_commit_enabled()

        self._refresh_summary()

    # ── state ────────────────────────────────────────────────────────────

    def set_rule(self, rule: WatchRule) -> None:
        """Load *rule* into the controls WITHOUT emitting ``rule_changed``.

        The chips are set directly rather than through their clicked handlers,
        which is what keeps this silent — a handler would emit, and loading a
        list of rules would write every one of them straight back.
        """
        self._rule = rule
        for mode, chip in self.mode_chips.items():
            chip.set_enabled(mode == rule.match_mode)
        self.whole_word_chip.set_enabled(rule.whole_word)
        self.description_chip.set_enabled(rule.search_description)
        # Unknown until the host's next set_counts() — cleared rather than
        # left showing the PREVIOUS rule's would-find number.
        self.description_chip.set_count(0)
        for widget in (self.include_input, self.exclude_input):
            widget.blockSignals(True)
        try:
            self.include_input.setText(rule.term)
            self.exclude_input.setText(", ".join(rule.exclude))
        finally:
            for widget in (self.include_input, self.exclude_input):
                widget.blockSignals(False)
        if self._compose:
            self._update_commit_enabled()
        self._refresh_summary()

    def rule(self) -> WatchRule:
        """The rule the controls currently describe."""
        return WatchRule(
            term=self.include_input.text().strip(),
            whole_word=self.whole_word_chip.is_enabled(),
            exclude=split_terms(self.exclude_input.text()),
            match_mode=self._current_mode(),
            search_description=self.description_chip.is_enabled(),
            live_only=self._rule.live_only,
            action=self._rule.action,
        )

    def set_counts(self, matched: int | None, suppressed: int | None,
                   horizon_days: int = 7,
                   description_gain: int | None = None) -> None:
        """Show what this rule currently finds. ``None`` renders as "counting…".

        ``description_gain`` — how many MORE programmes turning Description on
        would find — lands on the Description chip itself via
        :meth:`ToggleChip.set_count`, the same "(N)" badge the filter bar
        already uses for a chip's match count (Q2, "Catch, Keep, Record": *"the
        count next to it says what turning it on would find"*). ``0``/``None``
        clears the badge; the repository layer already reports ``0`` once the
        toggle is on, so the badge only ever appears while there is something
        to gain.
        """
        self._matched = matched
        self._suppressed = suppressed
        self._horizon_days = horizon_days
        self.description_chip.set_count(description_gain or 0)
        self._refresh_summary()

    # ── internals ────────────────────────────────────────────────────────

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        _theme.style(label, "FIELD_LABEL")
        return label

    def _current_mode(self) -> str:
        for mode, chip in self.mode_chips.items():
            if chip.is_enabled():
                return mode
        return PHRASE

    def _on_mode_clicked(self, mode: str, *_args) -> None:
        """Exclusive selection: one segment on, the rest off.

        The chip has already toggled ITSELF by the time this runs, so clicking
        the active mode would otherwise turn every mode off and leave the rule
        with none. Forcing the clicked one on is what makes the track behave
        like a choice rather than three independent switches.
        """
        for value, chip in self.mode_chips.items():
            chip.set_enabled(value == mode)
        self._emit()

    def _on_chip_toggled(self, *_args) -> None:
        """A plain on/off chip already flipped itself; just publish the rule."""
        self._emit()

    def _on_text_changed(self, *_args) -> None:
        if self._compose:
            self._update_commit_enabled()

    def _update_commit_enabled(self) -> None:
        """Add is dead until there is something to match on."""
        self.add_btn.setEnabled(bool(split_terms(self.include_input.text())))

    def _on_commit(self) -> None:
        rule = self.rule()
        if not rule.terms:
            return
        self.rule_committed.emit(rule)

    def _emit(self, *_args) -> None:
        rule = self.rule()
        self._rule = rule
        # The counts describe the OLD rule the moment anything changes, and a
        # stale number beside a just-edited rule is worse than no number.
        self._matched = self._suppressed = None
        self.description_chip.set_count(0)
        self._refresh_summary()
        if not self._compose:
            self.rule_changed.emit(rule)

    def _refresh_summary(self) -> None:
        parts = ["Whole words only" if self.whole_word_chip.is_enabled()
                 else "Contains anywhere"]
        if self.description_chip.is_enabled():
            parts.append("title and description")

        if self._matched is None:
            parts.append("counting…")
        else:
            parts.append(f"{self._matched} "
                         f"{'match' if self._matched == 1 else 'matches'} "
                         f"in the next {self._horizon_days} days")

        # Shown whenever the rule HAS excludes, including at zero: the whole
        # point is being able to tell "my exclusions are working" from "my
        # pattern stopped matching".
        if split_terms(self.exclude_input.text()) and self._suppressed is not None:
            parts.append(f"{self._suppressed} suppressed by excludes")

        self.summary_label.setText(" · ".join(parts))
        self.summary_label.setToolTip(_MODE_HELP.get(self._current_mode(), ""))


# ---------------------------------------------------------------------------
# Hosting — the assembly a surface needs to show one editable rule
# ---------------------------------------------------------------------------
# Lives here rather than in ``epg_watchlist_mixin`` because it is rule-editor
# work, not watchlist-render work: the mixin was already the largest file in
# the EPG package and this is the "extract" step of the code-health process
# (trim -> dedup -> EXTRACT -> re-baseline) that normally gets skipped. The
# mixin keeps two-line delegates so ``self``-bound call sites and the conftest
# test wiring stay unchanged.


def attach_rule_editor(host, layout, pattern: str, toggle_btn) -> None:
    """Hang the collapsed rule row under a pattern card.

    Collapsed by default: the card's job is "what is on", and the artifact is
    explicit that the list has to stay scannable. Built eagerly rather than on
    first expand — it is five widgets, and building it lazily would put widget
    construction inside a toggle handler, which is where "styled once, then
    stale after a theme switch" bugs come from.

    Args:
        host: The surface showing the card. Must expose ``config``,
            ``_rule_counts`` and ``_on_rule_changed`` — see
            ``tests/conftest.wire_watchlist_card_host``.
    """
    from metatv.core import watchlist

    rule = next((r for r in watchlist.rules(host.config)
                 if r.key.casefold() == pattern.casefold()), None)
    if rule is None:
        return

    editor = WatchRuleEditor()
    editor.set_rule(rule)
    counts = host._rule_counts.get(pattern)
    if counts is not None:
        matched, suppressed, _capped, description_gain = counts
        editor.set_counts(matched, suppressed, description_gain=description_gain)
    editor.setVisible(False)
    editor.rule_changed.connect(
        lambda new_rule, p=pattern: host._on_rule_changed(p, new_rule))
    layout.addWidget(editor)

    def _toggle(_checked=False, ed=editor, btn=toggle_btn):
        showing = not ed.isVisible()
        ed.setVisible(showing)
        btn.setText(f"Edit {icons.collapse_icon if showing else icons.expand_icon}")

    toggle_btn.clicked.connect(_toggle)


def apply_rule_change(host, pattern: str, rule: WatchRule) -> None:
    """Persist an edited rule, then refresh everything that reads rules.

    The term itself can change here — editing Include is how a rule is renamed
    — so a changed term is an add+remove rather than an update:
    ``pattern_value`` is the row's identity and every surface keys off it.
    """
    from metatv.core import watchlist

    if rule.term and rule.term.casefold() != pattern.casefold():
        watchlist.add(host.config, rule.term)
        watchlist.remove(host.config, pattern)
        target = rule.term
    else:
        target = pattern
    watchlist.update(
        host.config, target,
        whole_word=rule.whole_word,
        exclude=rule.exclude,
        match_mode=rule.match_mode,
        search_description=rule.search_description,
    )
    host.watchlist_changed.emit()
    host._reload_watchlist()
