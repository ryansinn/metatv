"""The Sports view — 430 lines of finished widget that nothing imported.

``sports_filter_bar.py`` and ``ChannelRepository.get_sports_channels`` were both
complete and both unreachable. What was missing was never the widget: the
queries behind it showed every channel from every source, including the 16,715
sports rows belonging to a provider the owner had switched off (fixed in
``_special_content_query``). This view is what finally calls them.

Rows come from ``chip_row.build_chip_row`` — the one row builder — rather than a
second renderer, so a change to row grammar reaches Sports the same day it
reaches History and Favorites.

The geometry test at the bottom is the one that matters. A test asserting the
list "contains" a row passes for any rendering, including a zero-height one — so
it asserts the painted QRect instead.
"""

import pytest

from metatv.core.config import Config
from metatv.core.repositories.dtos import SpecialContentDTO
from metatv.gui.sports_view import SportsView


def _row_texts(view) -> set:
    """Every piece of text drawn in the first row.

    Both widget classes: the title is a ``MiddleElideLabel`` but the CHIPS are
    flat ``QPushButton``s — ``chip_row`` makes all three kinds the same widget
    "so they share one box model and one padding". A QLabel-only search finds
    the title and reports no chips at all, which is exactly what the first draft
    of this file did.
    """
    from PyQt6.QtWidgets import QLabel, QPushButton

    row = view.channel_list.itemWidget(view.channel_list.item(0))
    return {w.text().strip()
            for w in row.findChildren(QLabel) + row.findChildren(QPushButton)}


def _dto(**over) -> SpecialContentDTO:
    base = {
        "id": "c1", "name": "NHL-TEAM| CALGARY FLAMES HD", "provider_id": "p",
        "media_type": "live", "special_view": "sports", "sport_type": "hockey",
        "league_name": "NHL", "team_name": "Calgary Flames",
        "detected_title": "NHL-TEAM Calgary Flames", "detected_quality": "HD",
    }
    base.update(over)
    return SpecialContentDTO(**base)


class _Runner:
    """Captures _run_query calls so a test can deliver a result synchronously."""

    def __init__(self):
        self.calls = []

    def __call__(self, query_fn, on_result, *, token_ref=None, on_error=None):
        self.calls.append({"fn": query_fn, "ok": on_result,
                           "err": on_error, "token": token_ref})


@pytest.fixture
def view(qapp):
    runner = _Runner()
    v = SportsView(None, Config(), runner)
    v._runner = runner
    return v


def _activate(view, rows=(), taxonomy=None, counts=None):
    view.on_activate()
    view._runner.calls[0]["ok"]({
        "taxonomy": taxonomy or {"hockey": {"NHL": ["Calgary Flames"]}},
        "counts": counts or {"hockey": 1180},
    })
    view._runner.calls[1]["ok"](list(rows))


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def test_activation_loads_the_taxonomy_then_the_channels(view):
    view.on_activate()
    assert len(view._runner.calls) == 2


def test_the_taxonomy_is_loaded_once_not_per_activation(view):
    """It is a scan of the whole classified corpus; re-running it on every
    switch back to the view would cost that scan for nothing."""
    _activate(view)
    view.on_activate()
    taxonomy_calls = sum(1 for c in view._runner.calls
                         if c["token"] is None)
    assert taxonomy_calls == 1


def test_changing_the_filter_re_queries(view):
    _activate(view)
    before = len(view._runner.calls)
    view.filter_bar.filter_changed.emit()
    assert len(view._runner.calls) == before + 1


def test_channel_queries_carry_a_stale_token(view):
    """A fast sport→league→sport sequence issues three queries and only the
    newest may render. The taxonomy load needs no token — it happens once."""
    _activate(view)
    channel_calls = [c for c in view._runner.calls if c["token"] is not None]
    assert channel_calls, "the channel query must pass token_ref"
    assert all(c["token"] is view._token for c in channel_calls)


def test_deactivate_invalidates_an_in_flight_result(view):
    """Symmetric with on_activate (CLAUDE.md), and the bump IS the cancel."""
    _activate(view)
    before = view._token[0]
    view.on_deactivate()
    assert view._token[0] > before


# --------------------------------------------------------------------------
# Visibility — the reason this view could not simply be wired up
# --------------------------------------------------------------------------

def test_the_query_asks_for_a_resolved_visibility_scope(view):
    """A disabled source contributes 16,715 of the owner's 35,181 sports rows.

    Executes the view's own query callable against a stub repository and reads
    the scope it passes — rather than asserting on source text, which would pass
    for a scope built and then ignored.
    """
    from unittest.mock import MagicMock

    view.on_activate()
    captured = {}

    repos = MagicMock()
    repos.providers.get_hidden_provider_ids.return_value = ["disabled-provider"]

    def capture(scope, **kw):
        captured["scope"] = scope
        captured["kw"] = kw
        return []

    repos.channels.get_sports_channels.side_effect = capture
    view._runner.calls[1]["fn"](repos)

    assert "disabled-provider" in captured["scope"].excluded_provider_ids, (
        "the Sports view would show channels from a source the owner disabled")


def test_the_taxonomy_query_is_scoped_too(view):
    """It feeds the DROPDOWNS. Scoping the list but not the taxonomy gives a
    filter offering a sport whose channels are all excluded."""
    from unittest.mock import MagicMock

    view.on_activate()
    captured = {}
    repos = MagicMock()
    repos.providers.get_hidden_provider_ids.return_value = ["disabled-provider"]
    repos.channels.get_sports_taxonomy.side_effect = (
        lambda scope: captured.setdefault("scope", scope) or {})
    repos.channels.get_sports_counts.return_value = {}
    view._runner.calls[0]["fn"](repos)

    assert "disabled-provider" in captured["scope"].excluded_provider_ids


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def test_the_title_is_the_team_not_the_provider_string(view):
    """"Calgary Flames" is what the owner is looking for. The raw name is
    "NHL-TEAM| CALGARY FLAMES HD", which repeats the league and the quality
    that sit beside it as chips."""
    from PyQt6.QtWidgets import QLabel

    _activate(view, [_dto()])
    row = view.channel_list.itemWidget(view.channel_list.item(0))
    texts = [w.text() for w in row.findChildren(QLabel)]
    assert any("Calgary Flames" == t for t in texts), texts
    assert not any("NHL-TEAM|" in t for t in texts), (
        "the provider's raw string reached the row")


def test_the_raw_name_survives_as_the_tooltip(view):
    """The title deliberately replaced it, so it must remain reachable — and on
    the ITEM, because the chip row is mouse-transparent."""
    _activate(view, [_dto()])
    assert view.channel_list.item(0).toolTip() == "NHL-TEAM| CALGARY FLAMES HD"


def test_a_channel_with_no_team_falls_back_to_its_title(view):
    from PyQt6.QtWidgets import QLabel

    _activate(view, [_dto(team_name=None, detected_title="ESPN2")])
    row = view.channel_list.itemWidget(view.channel_list.item(0))
    assert any("ESPN2" == w.text() for w in row.findChildren(QLabel))


def test_the_count_reads_back(view):
    _activate(view, [_dto(id="a"), _dto(id="b")])
    assert view.count_label.text() == "2 channels"
    _activate(view, [_dto()])
    assert view.count_label.text() == "1 channel", "singular, not '1 channels'"


# --------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------

def test_a_failed_load_shows_a_visible_row(view):
    """CLAUDE.md: never ``clear(); return`` — an empty list and a failed load
    must not look the same."""
    from PyQt6.QtCore import Qt

    view.on_activate()
    view._runner.calls[1]["err"](RuntimeError("boom"))
    assert view.channel_list.count() == 1
    item = view.channel_list.item(0)
    assert "Couldn't load" in item.text()
    assert item.flags() == Qt.ItemFlag.NoItemFlags, "the error row must not be selectable"


def test_a_none_result_is_also_an_error(view):
    """_run_query delivers None on failure when no on_error fires."""
    view.on_activate()
    view._runner.calls[1]["ok"](None)
    assert "Couldn't load" in view.channel_list.item(0).text()


# --------------------------------------------------------------------------
# Interaction
# --------------------------------------------------------------------------

def test_click_selects_and_double_click_plays(view):
    _activate(view, [_dto()])
    seen = []
    view.channelSelected.connect(lambda cid: seen.append(("select", cid)))
    view.playRequested.connect(lambda cid: seen.append(("play", cid)))
    item = view.channel_list.item(0)
    view._on_item_clicked(item)
    view._on_item_double_clicked(item)
    assert seen == [("select", "c1"), ("play", "c1")]


def test_the_error_row_emits_nothing(view):
    """It carries no channel id; a click on it must not select a phantom."""
    view.on_activate()
    view._runner.calls[1]["err"](RuntimeError("boom"))
    seen = []
    view.channelSelected.connect(seen.append)
    view._on_item_clicked(view.channel_list.item(0))
    assert seen == []


# --------------------------------------------------------------------------
# Rendered appearance
# --------------------------------------------------------------------------

def test_the_row_is_painted_with_real_height(view, qapp):
    """Membership passes for a zero-height row; geometry does not.

    The size hint is ``QSize(0, row.height())`` — width 0 so the item spans the
    viewport instead of forcing a horizontal scrollbar, height from the row.
    Both halves are asserted because getting the width wrong is invisible until
    someone resizes the pane.
    """
    _activate(view, [_dto()])
    view.channel_list.resize(600, 300)
    view.channel_list.show()
    qapp.processEvents()

    item = view.channel_list.item(0)
    row = view.channel_list.itemWidget(item)
    assert item.sizeHint().width() == 0, (
        "a non-zero width hint forces a horizontal scrollbar")
    assert item.sizeHint().height() >= 16, (
        f"row height {item.sizeHint().height()}px — the row is not painted")
    rect = view.channel_list.visualItemRect(item)
    assert rect.height() >= 16 and rect.width() > 100, (
        f"painted rect is {rect.width()}x{rect.height()}")
    assert row.geometry().height() > 0


def test_the_switcher_and_the_chip_deactivator_read_one_list():
    """They had two copies, and a chip missing from the second stays LIT while
    another view is showing — nothing fails, it just looks broken."""
    from pathlib import Path

    import metatv.gui.main_window_nav as nav
    from metatv.gui.app_header import NAV_CHIP_SPECS

    assert any(attr == "sports_chip" for attr, *_ in NAV_CHIP_SPECS)
    source = Path(nav.__file__).read_text()
    assert "NAV_CHIP_SPECS" in source, (
        "_deactivate_view_chips must derive from the same list that builds the "
        "switcher, not keep its own copy")
    assert "self.discover_chip]" not in source, "the hand-written copy is back"


def test_the_view_is_registered_and_deactivated_by_the_host():
    """An unregistered view never appears; one missing from
    _hide_all_content_views keeps consuming async loads behind whatever the user
    switched to."""
    from pathlib import Path

    import metatv.gui.main_window as mw
    import metatv.gui.main_window_nav as nav

    main = Path(mw.__file__).read_text()
    assert "self.sports_view = SportsView(" in main
    assert "self._list_layout.addWidget(self.sports_view)" in main

    navsrc = Path(nav.__file__).read_text()
    assert "def switch_to_sports_view" in navsrc
    assert "def on_sports_view_toggle" in navsrc
    # Deactivation and hiding are one loop over one list now — membership in it
    # IS the registration, which is the point of collapsing the two.
    assert "sports_view" in nav.CONTENT_VIEW_ATTRS


# --------------------------------------------------------------------------
# The host connections — shapes, not just names
# --------------------------------------------------------------------------

def test_the_context_menu_signal_matches_the_host_handler(view):
    """A signal whose SHAPE is wrong fails only when someone right-clicks.

    ``_on_rec_channel_context_menu(channel_id, gx, gy)`` takes three arguments,
    not a channel id and a QPoint. The first draft emitted ``(str, object)``,
    connected cleanly, and would have raised on the first right-click — which a
    "the signal exists" test would never have caught.
    """
    import inspect

    from metatv.gui.main_window_favorites import _FavoritesMixin

    handler = _FavoritesMixin._on_rec_channel_context_menu
    params = list(inspect.signature(handler).parameters)[1:]  # drop self
    assert len(params) == 3, params

    seen = []
    view.channelContextMenuRequested.connect(
        lambda cid, gx, gy: seen.append((cid, gx, gy)))
    _activate(view, [_dto()])
    view.channel_list.resize(400, 200)
    view._on_context_menu(view.channel_list.visualItemRect(
        view.channel_list.item(0)).center())
    assert len(seen) == 1
    cid, gx, gy = seen[0]
    assert cid == "c1" and isinstance(gx, int) and isinstance(gy, int)


def test_middle_click_plays(view, qapp):
    """Declared-and-never-emitted is dead wiring.

    The first draft declared ``channelMiddleClicked``, connected it in the host
    and never emitted it — the row is mouse-transparent and QListWidget has no
    middle-click signal, so the affordance every other list has was silently
    absent here.
    """
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    _activate(view, [_dto()])
    view.channel_list.resize(400, 200)
    view.channel_list.show()
    qapp.processEvents()

    seen = []
    view.channelMiddleClicked.connect(seen.append)
    rect = view.channel_list.visualItemRect(view.channel_list.item(0))
    qapp.sendEvent(view.channel_list.viewport(), QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(rect.center()),
        Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier))
    assert seen == ["c1"]


def test_a_left_click_is_not_a_middle_click(view, qapp):
    """The filter observes; it must not fire on every press."""
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent

    _activate(view, [_dto()])
    view.channel_list.resize(400, 200)
    view.channel_list.show()
    qapp.processEvents()

    seen = []
    view.channelMiddleClicked.connect(seen.append)
    rect = view.channel_list.visualItemRect(view.channel_list.item(0))
    qapp.sendEvent(view.channel_list.viewport(), QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(rect.center()),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    assert seen == []


def test_every_declared_signal_is_actually_emitted():
    """Guards the general shape of the bug above.

    A signal the view never emits is wiring that looks connected and does
    nothing. Source-level, because emitting each one from a test would need a
    scenario per signal and the point is the ABSENCE of an emit.
    """
    from pathlib import Path

    import metatv.gui.sports_view as mod

    source = Path(mod.__file__).read_text()
    for signal in ("channelSelected", "playRequested", "channelMiddleClicked",
                   "channelContextMenuRequested"):
        assert f"self.{signal}.emit(" in source, (
            f"{signal} is declared and never emitted")


def test_a_failed_taxonomy_load_is_retried_next_activation(view):
    """The dropdowns must not stay empty for the rest of the session.

    The flag is set when the query is SUBMITTED (so two rapid activations do
    not both issue the whole-corpus scan) and cleared on failure (so the next
    activation tries again).
    """
    view.on_activate()
    view._runner.calls[0]["err"](RuntimeError("boom"))
    assert "Couldn't load" in view.channel_list.item(0).text()

    before = len(view._runner.calls)
    view.on_activate()
    assert len(view._runner.calls) > before, "the taxonomy was never retried"


def test_two_rapid_activations_scan_the_corpus_once(view):
    """It is a scan of every classified row; issuing it twice costs that twice."""
    view.on_activate()
    view.on_activate()
    taxonomy_calls = [c for c in view._runner.calls if c["token"] is None]
    assert len(taxonomy_calls) == 1


def test_the_hide_loop_survives_a_skeleton_host():
    """``MainWindow.__new__`` — the double several lifecycle tests use.

    On a skeleton host, attribute access goes through Qt and raises
    ``RuntimeError``, which a ``getattr(..., None)`` default does NOT absorb
    because it is not ``AttributeError``. The first draft of the collapsed loop
    used ``getattr`` and took three lifecycle tests down with it; CLAUDE.md
    names this exact trap, and the fix is ``self.__dict__.get`` — the lookup the
    per-view ``if "x" in self.__dict__`` guards were already using.
    """
    from pathlib import Path

    import metatv.gui.main_window_nav as nav

    source = Path(nav.__file__).read_text()
    method = source[source.index("def _hide_all_content_views"):]
    method = method[:method.index("\n    def ", 1)]
    # Comments only — the prose below the loop names getattr to say NOT to use
    # it, and a naive substring check reads that as the code itself.
    code = "\n".join(line for line in method.split("\n")
                     if not line.strip().startswith("#"))

    assert "self.__dict__.get(attr)" in code
    assert "getattr(self, attr" not in code, (
        "getattr on a skeleton host raises RuntimeError, not AttributeError")


def test_no_chip_pretends_to_be_a_control(view):
    """``CHIP_LANG`` is accent-blue because blue means interactive everywhere.

    ``chip_roles`` documents it as "the only chip in the family that is a
    CONTROL". Neither the league nor the sport is clickable, so neither may
    borrow that role — the first draft gave the sport chip exactly that look.
    """
    from pathlib import Path

    import metatv.gui.sports_view as mod

    source = Path(mod.__file__).read_text()
    code = "\n".join(line for line in source.split("\n")
                     if not line.strip().startswith("#"))
    assert "(CHIP_LANG," not in code, (
        "a non-clickable chip is using the control role")


def test_the_row_shows_league_sport_and_quality(view):
    """All three, and each only when the classifier actually found it."""
    _activate(view, [_dto()])
    assert {"NHL", "Hockey", "HD"} <= _row_texts(view), _row_texts(view)

    _activate(view, [_dto(league_name=None, sport_type=None,
                          detected_quality=None)])
    texts = _row_texts(view)
    assert "NHL" not in texts and "Hockey" not in texts and "HD" not in texts
