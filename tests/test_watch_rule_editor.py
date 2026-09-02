"""The Option B rule row — what it renders, and where the pieces actually land.

CLAUDE.md: a UI slice must assert RENDERED APPEARANCE, because a test that
checks parsed data or token existence passes for infinitely many wrong-looking
renderings. So this file measures geometry — real ``QRect``s after a layout
pass — not just widget presence.

The summary line gets its own attention. From the artifact: *"showing the
suppressed count is what makes an exclude list trustworthy — otherwise you can
never tell the difference between 'my exclusions are working' and 'my pattern
stopped matching'."* Its exact wording is a spec, not a detail.
"""
from __future__ import annotations

from metatv.core.watchlist_matching import ANY_WORD, PHRASE, WatchRule


def _destroy(host, qapp):
    """Actually free the top-level. ``deleteLater()`` alone is NOT enough.

    A parentless QWidget left alive is repainted by every later
    ``apply_theme()``, and a leaked one per test is what segfaulted a CI shard
    (CLAUDE.md). The posted DeferredDelete has to be pumped for the C++ object
    to go.
    """
    from PyQt6.QtCore import QEvent
    host.hide()
    host.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def _editor(qapp):
    from PyQt6.QtWidgets import QWidget, QVBoxLayout
    from metatv.gui.watch_rule_editor import WatchRuleEditor

    host = QWidget()
    layout = QVBoxLayout(host)
    editor = WatchRuleEditor()
    layout.addWidget(editor)
    host.resize(560, 320)
    host.show()
    qapp.processEvents()
    return host, editor


# ---------------------------------------------------------------------------
# Rendered appearance
# ---------------------------------------------------------------------------

def test_the_row_lays_its_controls_out_top_to_bottom_with_the_summary_last(qapp):
    """Geometry, not order-in-a-list: assert where each control actually sits.

    ``layout.itemAt(i)`` order is satisfied by a layout that renders every row
    on top of every other one. These are painted ``QRect`` positions after a
    real layout pass.
    """
    host, ed = _editor(qapp)
    try:
        rows = [ed.mode_chips[PHRASE], ed.include_input, ed.exclude_input,
                ed.description_chip, ed.summary_label]
        tops = [w.mapTo(host, w.rect().topLeft()).y() for w in rows]

        assert tops == sorted(tops), (
            f"controls are not stacked in reading order: {tops}")
        assert len(set(tops)) == len(tops), (
            "two controls share a Y — they are drawn on top of each other")
        for widget in rows:
            assert widget.height() > 0 and widget.width() > 0, (
                f"{widget} rendered with no area")
        assert ed.summary_label.mapTo(host, ed.summary_label.rect().topLeft()).y() > \
            ed.description_chip.mapTo(host, ed.description_chip.rect().bottomLeft()).y() - 1, \
            "the summary must sit below the controls it describes"
    finally:
        _destroy(host, qapp)


def test_each_field_sits_BESIDE_its_label_in_a_real_two_column_form(qapp):
    """Two columns, measured — not "both widgets exist".

    Mutation-checked: an earlier version of this test asserted only that the
    field's left edge was > 0 and it was wide enough. Switching the form to
    ``WrapAllRows`` — which stacks every label ABOVE its field and doubles the
    row's height — left it green. Comparing the field's left edge against its
    OWN label's right edge is what actually pins the shape.
    """
    host, ed = _editor(qapp)
    try:
        for field in (ed.include_input, ed.exclude_input):
            label = ed.form.labelForField(field)
            assert label is not None, f"{field} has no form label"
            label_right = label.mapTo(host, label.rect().topRight()).x()
            field_left = field.mapTo(host, field.rect().topLeft()).x()
            assert field_left >= label_right, (
                f"{label.text()!r} is not beside its field: label ends at "
                f"{label_right}, field starts at {field_left} — the row wrapped")

            label_mid = label.mapTo(host, label.rect().center()).y()
            field_top = field.mapTo(host, field.rect().topLeft()).y()
            field_bottom = field_top + field.height()
            assert field_top <= label_mid <= field_bottom, (
                f"{label.text()!r} is not vertically aligned with its field")

            assert field.width() > 80, (
                f"{field} is {field.width()}px wide; the value is unreadable")
    finally:
        _destroy(host, qapp)


# ---------------------------------------------------------------------------
# The summary line — its wording is the spec
# ---------------------------------------------------------------------------

def test_the_summary_reads_exactly_as_the_settled_design_says(qapp):
    host, ed = _editor(qapp)
    try:
        ed.set_rule(WatchRule(term="Denver Broncos", exclude=("news", "pregame")))
        ed.set_counts(18, 6)
        assert ed.summary_label.text() == (
            "Whole words only · 18 matches in the next 7 days · "
            "6 suppressed by excludes")
    finally:
        _destroy(host, qapp)


def test_the_suppressed_count_shows_at_zero_when_the_rule_has_excludes(qapp):
    """Zero is the informative case: it is how "my exclusions are working"
    is distinguished from "my pattern stopped matching"."""
    host, ed = _editor(qapp)
    try:
        ed.set_rule(WatchRule(term="Denver", exclude=("news",)))
        ed.set_counts(4, 0)
        assert "0 suppressed by excludes" in ed.summary_label.text()

        ed.set_rule(WatchRule(term="Denver"))
        ed.set_counts(4, 0)
        assert "suppressed" not in ed.summary_label.text(), (
            "a rule with no excludes should not claim anything about them")
    finally:
        _destroy(host, qapp)


def test_counts_read_as_counting_until_they_arrive_never_as_zero(qapp):
    """An unmeasured count must not render as a measured zero."""
    host, ed = _editor(qapp)
    try:
        ed.set_rule(WatchRule(term="Denver"))
        assert "counting…" in ed.summary_label.text()
        assert "0 matches" not in ed.summary_label.text()
    finally:
        _destroy(host, qapp)


def test_editing_clears_a_count_that_now_describes_the_old_rule(qapp):
    host, ed = _editor(qapp)
    try:
        ed.set_rule(WatchRule(term="Denver"))
        ed.set_counts(18, 0)
        assert "18 matches" in ed.summary_label.text()
        ed.whole_word_chip.click()
        assert "18 matches" not in ed.summary_label.text(), (
            "a stale number beside a just-edited rule is worse than no number")
        assert "counting…" in ed.summary_label.text()
    finally:
        _destroy(host, qapp)


def test_the_summary_names_the_matching_mode_in_words(qapp):
    """Never colour or icon alone — the a11y rule, and the only way the
    escape hatch is discoverable at all."""
    host, ed = _editor(qapp)
    try:
        ed.set_rule(WatchRule(term="NFL", whole_word=True))
        assert "Whole words only" in ed.summary_label.text()
        ed.set_rule(WatchRule(term="NFL", whole_word=False))
        assert "Contains anywhere" in ed.summary_label.text()
    finally:
        _destroy(host, qapp)


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def test_set_rule_does_not_emit(qapp):
    """Programmatic restore must be silent, or loading a list of rules writes
    every one of them back — and the mode combo's own handler would read the
    include box before it had been filled, emitting the PREVIOUS row's terms.
    """
    host, ed = _editor(qapp)
    seen = []
    ed.rule_changed.connect(seen.append)
    try:
        ed.set_rule(WatchRule(term="Denver, Broncos", match_mode=ANY_WORD,
                              exclude=("news",), search_description=True))
        assert seen == []
        assert ed._current_mode() == ANY_WORD
        assert ed.include_input.text() == "Denver, Broncos"
        assert ed.exclude_input.text() == "news"
    finally:
        _destroy(host, qapp)


def test_every_control_emits_a_complete_rule(qapp):
    host, ed = _editor(qapp)
    seen = []
    ed.rule_changed.connect(seen.append)
    try:
        ed.set_rule(WatchRule(term="Denver"))
        ed.include_input.setText("Denver, Broncos")
        ed.include_input.editingFinished.emit()
        ed.mode_chips[ANY_WORD].click()
        ed.exclude_input.setText("news, pregame")
        ed.exclude_input.editingFinished.emit()
        ed.description_chip.click()

        assert len(seen) == 4
        final = seen[-1]
        assert final.term == "Denver, Broncos"
        assert final.terms == ("Denver", "Broncos")
        assert final.match_mode == ANY_WORD
        assert final.exclude == ("news", "pregame")
        assert final.search_description is True
    finally:
        _destroy(host, qapp)


def test_a_fresh_editor_describes_the_settled_default_not_a_bare_checkbox(qapp):
    """An unchecked QCheckBox would claim "contains anywhere", which is the
    opposite of what a new rule actually does."""
    host, ed = _editor(qapp)
    try:
        assert ed.whole_word_chip.is_enabled() is True
        assert "Whole words only" in ed.summary_label.text()
        assert ed.rule().match_mode == PHRASE
    finally:
        _destroy(host, qapp)


# ---------------------------------------------------------------------------
# Hosting — the path the card actually takes
# ---------------------------------------------------------------------------

def _card_host(tmp_path, qapp, term="Denver"):
    """A host with a REAL bound watchlist database holding one rule.

    The existing card hosts in ``test_epg_watchlist_ranking`` and
    ``test_b10_2_render_parse_cleanup`` have no stored rules, so
    ``attach_rule_editor`` returns early on all of them — they prove the card
    still builds, not that the editor is ever attached. This one carries a rule.
    """
    from types import SimpleNamespace

    from PyQt6.QtCore import QObject, pyqtSignal

    from metatv.core import watchlist
    from metatv.core.database import Database

    class _Signals(QObject):
        watchlist_changed = pyqtSignal()

    db = Database(f"sqlite:///{tmp_path / 'cards.db'}")
    db.create_tables()
    watchlist.bind(db)

    class _Cfg:
        epg_watchlist_patterns: list[str] = []

    cfg = _Cfg()
    watchlist.add(cfg, term)
    watchlist.flush()

    signals = _Signals()
    host = SimpleNamespace()
    host.config = cfg
    host._rule_counts = {term: (18, 6, False)}
    host.watchlist_changed = signals.watchlist_changed
    host.reloaded = []
    host._reload_watchlist = lambda: host.reloaded.append(True)
    host._on_rule_changed = lambda p, r: __import__(
        "metatv.gui.watch_rule_editor", fromlist=["x"]).apply_rule_change(host, p, r)
    return host, signals


def test_the_card_attaches_a_collapsed_editor_that_the_toggle_opens(qapp, tmp_path):
    from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    from metatv.core import watchlist
    from metatv.gui.watch_rule_editor import WatchRuleEditor, attach_rule_editor

    host, _sig = _card_host(tmp_path, qapp)
    card = QWidget()
    layout = QVBoxLayout(card)
    toggle = QPushButton("Rule >")
    layout.addWidget(toggle)
    try:
        attach_rule_editor(host, layout, "Denver", toggle)
        editors = card.findChildren(WatchRuleEditor)
        assert len(editors) == 1, "no rule editor was attached to the card"
        editor = editors[0]

        assert editor.isVisible() is False, "the row must start collapsed"
        # Exact, with no `or` fallback: an assertion that accepts two answers
        # accepts most wrong ones. The rule has no excludes, so the suppressed
        # clause must be absent rather than present-and-zero.
        assert editor.summary_label.text() == (
            "Whole words only · 18 matches in the next 7 days"), (
            "the host's counts were not handed to the row")

        card.show()
        qapp.processEvents()
        toggle.click()
        qapp.processEvents()
        assert editor.isVisible() is True
        assert editor.height() > 0, "expanded to nothing"
        assert "Edit" in toggle.text()

        toggle.click()
        qapp.processEvents()
        assert editor.isVisible() is False
    finally:
        watchlist.unbind()
        _destroy(card, qapp)


def test_editing_a_rule_on_a_card_persists_and_refreshes(qapp, tmp_path):
    from metatv.core import watchlist
    from metatv.gui.watch_rule_editor import apply_rule_change

    host, signals = _card_host(tmp_path, qapp)
    fired = []
    signals.watchlist_changed.connect(lambda: fired.append(True))
    try:
        apply_rule_change(host, "Denver", WatchRule(
            term="Denver", whole_word=False, exclude=("news",),
            match_mode=ANY_WORD, search_description=True))
        watchlist.flush()

        stored = watchlist.rules(host.config)[0]
        assert stored.whole_word is False
        assert stored.exclude == ("news",)
        assert stored.match_mode == ANY_WORD
        assert stored.search_description is True
        assert fired, "dependent views were never told the rule changed"
        assert host.reloaded, "the card list was never reloaded"
    finally:
        watchlist.unbind()


def test_renaming_via_the_include_field_moves_the_rule(qapp, tmp_path):
    """Editing Include IS the rename path — pattern_value is the row identity."""
    from metatv.core import watchlist
    from metatv.gui.watch_rule_editor import apply_rule_change

    host, _sig = _card_host(tmp_path, qapp)
    try:
        apply_rule_change(host, "Denver",
                          WatchRule(term="Denver, Broncos", match_mode=ANY_WORD))
        watchlist.flush()

        terms = [r.term for r in watchlist.rules(host.config)]
        assert terms == ["Denver, Broncos"], terms
        stored = watchlist.rules(host.config)[0]
        assert stored.match_mode == ANY_WORD, (
            "the renamed rule lost the fields that were saved with it")
    finally:
        watchlist.unbind()


# ---------------------------------------------------------------------------
# Compose mode — "Track Something New"
# ---------------------------------------------------------------------------

def test_compose_mode_will_not_commit_an_empty_entry(qapp):
    """A blank entry would match nothing and clutter the list."""
    from metatv.gui.watch_rule_editor import WatchRuleEditor

    ed = WatchRuleEditor(compose=True)
    got = []
    ed.rule_committed.connect(got.append)
    try:
        assert ed.add_btn.isEnabled() is False
        ed.include_input.setText("   ")
        assert ed.add_btn.isEnabled() is False, "whitespace is not a term"
        ed.include_input.setText("Severance")
        assert ed.add_btn.isEnabled() is True
        ed.add_btn.click()
        assert [r.term for r in got] == ["Severance"]
    finally:
        _destroy(ed, qapp)


def test_compose_mode_does_not_live_edit(qapp):
    """A half-typed new entry must not be written on every keystroke.

    ``rule_changed`` is the live-edit signal for an EXISTING entry. In compose
    mode the commit is the Track It button, so firing it here would create an
    entry called "Sev" on the way to "Severance".
    """
    from metatv.gui.watch_rule_editor import WatchRuleEditor

    ed = WatchRuleEditor(compose=True)
    live = []
    ed.rule_changed.connect(live.append)
    try:
        ed.include_input.setText("Sev")
        ed.include_input.editingFinished.emit()
        ed.description_chip.click()
        assert live == []
    finally:
        _destroy(ed, qapp)


def test_compose_carries_every_control_into_the_committed_entry(qapp):
    """The point of replacing the text box: the extra fields actually arrive."""
    from metatv.core.watchlist_matching import ALL_WORDS
    from metatv.gui.watch_rule_editor import WatchRuleEditor

    ed = WatchRuleEditor(compose=True)
    got = []
    ed.rule_committed.connect(got.append)
    try:
        ed.include_input.setText("Denver, Broncos")
        ed.exclude_input.setText("news, pregame")
        ed.mode_chips[ALL_WORDS].click()
        ed.description_chip.click()
        ed.whole_word_chip.click()
        ed.add_btn.click()

        rule = got[-1]
        assert rule.terms == ("Denver", "Broncos")
        assert rule.exclude == ("news", "pregame")
        assert rule.match_mode == ALL_WORDS
        assert rule.search_description is True
        assert rule.whole_word is False
    finally:
        _destroy(ed, qapp)


def test_the_mode_track_is_a_choice_not_three_switches(qapp):
    """Clicking the ACTIVE segment must not leave the entry with no mode.

    ToggleChip flips itself on click, so without the handler forcing the
    clicked mode back on, a second click on "Phrase" would turn every mode off
    and ``_current_mode`` would silently fall back — a rule quietly changing
    what it matches because you clicked the thing it already was.
    """
    from metatv.core.watchlist_matching import ANY_WORD
    from metatv.gui.watch_rule_editor import WatchRuleEditor

    ed = WatchRuleEditor()
    try:
        ed.mode_chips[ANY_WORD].click()
        assert ed._current_mode() == ANY_WORD
        assert [m for m, c in ed.mode_chips.items() if c.is_enabled()] == [ANY_WORD]

        ed.mode_chips[ANY_WORD].click()
        assert ed._current_mode() == ANY_WORD, "clicking the active mode blanked it"
        assert [m for m, c in ed.mode_chips.items() if c.is_enabled()] == [ANY_WORD]
    finally:
        _destroy(ed, qapp)


def test_title_stays_searched_however_often_it_is_clicked(qapp):
    """Turning Title off would be a rule that searches nothing."""
    from metatv.gui.watch_rule_editor import WatchRuleEditor

    ed = WatchRuleEditor()
    try:
        for _ in range(3):
            ed.title_chip.click()
            assert ed.title_chip.is_enabled() is True
    finally:
        _destroy(ed, qapp)
