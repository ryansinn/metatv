"""The Sports view — the channel list with a sport/league filter on it.

``sports_filter_bar.py`` and ``ChannelRepository.get_sports_channels`` were both
complete and both unreachable. What was missing was never the widget: the
queries behind it showed every channel from every source, including the 16,715
sports rows belonging to a provider the owner had switched off (fixed in
``_special_content_query``).

**Rows are VIRTUALIZED.** They come from the shared ``ChannelResultsList`` —
``ChannelListModel`` + ``ChannelRowDelegate`` — the same pair the main channel
list paints 785,163 rows with. The first version of this view built one live
``QWidget`` per row via ``chip_row.build_chip_row``, which is correct for a
bounded sidebar section and catastrophic here: at 28,018 sports rows it froze
the UI for ~11 s measured offscreen, and minutes on the owner's machine. Hence
``test_the_widget_count_does_not_scale_with_the_row_count`` at the bottom — the
one test that would have caught it, and the only shape of test that can, since
a per-row widget list passes every assertion about content and order.

The geometry test is the other one that matters. A test asserting the list
"contains" a row passes for any rendering, including a zero-height one — so it
asserts the painted QRect instead.
"""

from datetime import datetime, timedelta

import pytest

from metatv.core.config import Config
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_model import TITLE_ROLE
from metatv.gui.sports_view import SportsView


def _index(view, row: int = 0):
    """The model index for one row."""
    return view.channel_list.model.index(row, 0)


def _row_texts(view, row: int = 0) -> set:
    """Every piece of text the delegate would PAINT in one row.

    There is no per-row widget to interrogate any more — that is the point of
    the change this file guards. The row's content is the set of cells the
    delegate builds from the model's roles, which is what actually reaches the
    screen, plus the title it paints against them.
    """
    idx = _index(view, row)
    cells = view.channel_list.delegate._cells_by_slot(idx)
    texts = {c.text.strip() for group in cells.values() for c in group}
    texts.add((idx.data(TITLE_ROLE) or "").strip())
    return {t for t in texts if t}


def _dto(**over) -> ChannelListDTO:
    base = {
        "id": "c1", "name": "NHL-TEAM| CALGARY FLAMES HD", "provider_id": "p",
        "media_type": "live", "is_favorite": False, "category": "Sports",
        "quality": None, "detected_prefix": "", "detected_region": "",
        "detected_year": "", "sport_type": "hockey", "league_name": "NHL",
        "detected_title": "Calgary Flames", "detected_quality": "HD",
    }
    base.update(over)
    return ChannelListDTO(**base)


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
    # Four: the taxonomy, the channel list, the lane counts, and the catalog
    # staleness banner (SPORT-7). The counts are a separate GROUP BY because
    # they describe every lane, not the open one; the staleness read is
    # independent of both — it asks how fresh the SOURCES are, not the rows.
    assert len(view._runner.calls) == 4


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
    # Two: the list and the counts, because a facet change moves both.
    assert len(view._runner.calls) == before + 2


def test_switching_lanes_does_not_re_run_the_counts(view):
    """The counts describe the whole facet-filtered set.

    They cannot change because a different lane is open, so paying for a
    GROUP BY on every lane click buys nothing.
    """
    _activate(view)
    before = len(view._runner.calls)
    view._on_lane_clicked("finished")
    assert len(view._runner.calls) == before + 1, (
        "a lane switch should re-query the LIST only"
    )


def test_channel_queries_carry_a_stale_token(view):
    """A fast sport→league→sport sequence issues several queries and only the
    newest may render. The taxonomy load needs no token — it happens once.

    This used to assert that every token-carrying call shared ONE counter,
    which was the bug written down as a requirement: ``_run_query`` bumps the
    counter before each submit and drops any result tagged with an older value,
    so two concurrent reads on one counter means the second cancels the first.
    The rows read was discarded on every open of the view.
    """
    _activate(view)
    channel_calls = [c for c in view._runner.calls if c["token"] is not None]
    assert channel_calls, "the channel query must pass token_ref"

    tokens = {id(c["token"]) for c in channel_calls}
    assert len(tokens) == len(channel_calls), (
        "two concurrent reads shared one token counter — the earlier one is "
        "cancelled by the later one and can never render")


def test_deactivate_invalidates_every_in_flight_result(view):
    """Symmetric with on_activate (CLAUDE.md), and the bump IS the cancel.

    BOTH counters, or the un-bumped read still paints over whatever view the
    user switched to.
    """
    _activate(view)
    before = (view._rows_token[0], view._counts_token[0])
    view.on_deactivate()
    assert view._rows_token[0] > before[0], "an in-flight rows read survived"
    assert view._counts_token[0] > before[1], "an in-flight counts read survived"


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

def test_the_title_is_the_clean_title_not_the_provider_string(view):
    """"Calgary Flames" is what the owner is looking for. The raw name is
    "NHL-TEAM| CALGARY FLAMES HD", which repeats the league and the quality
    that sit beside it as chips.

    The title is ``detected_title`` — the ingestion-computed field every other
    view in the app shows — not ``team_name``, which the old renderer preferred.
    team_name was present on only 2,740 of 28,018 sports rows (9.8%) and where
    it differed it was often worse: "4K| V SPORT+ UHD" produced team_name
    "4K| vs SPORT+ UHD", keeping the provider prefix the title exists to strip
    and turning "V" into "vs", while detected_title gave "V SPORT+". One title
    field for every surface is the point.
    """
    _activate(view, [_dto()])
    texts = _row_texts(view)
    assert "Calgary Flames" in texts, texts
    assert not any("NHL-TEAM|" in t for t in texts), (
        "the provider's raw string reached the row")


def test_the_raw_name_survives_as_the_tooltip(view):
    """The title deliberately replaced it, so it must remain reachable — and on
    the ITEM, because the chip row is mouse-transparent."""
    from PyQt6.QtCore import Qt

    _activate(view, [_dto()])
    assert _index(view).data(Qt.ItemDataRole.ToolTipRole) == (
        "NHL-TEAM| CALGARY FLAMES HD")


def test_a_channel_with_no_team_falls_back_to_its_title(view):
    _activate(view, [_dto(detected_title="ESPN2")])
    assert "ESPN2" in _row_texts(view)


def test_the_counts_land_on_the_lane_chips(view):
    """The standalone count line is gone; each lane chip carries its own."""
    _activate(view, [_dto(id="a"), _dto(id="b")])
    view._on_lane_counts_loaded(
        {"live": 2, "upcoming": 7, "channels": 3, "finished": 9, "placeholders": 5})
    assert "(2)" in view._lane_chips["live"].text()
    assert "(7)" in view._lane_chips["upcoming"].text()
    assert "(5)" in view._lane_chips["placeholders"].text()


# --------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------

def test_a_failed_load_shows_a_visible_row(view):
    """CLAUDE.md: never ``clear(); return`` — an empty list and a failed load
    must not look the same."""
    view.on_activate()
    view._runner.calls[1]["err"](RuntimeError("boom"))
    assert view.channel_list.count() == 0, "no phantom row"
    assert view.channel_list._error.isVisible() or view.channel_list._error.text()
    assert "Couldn't load" in view.channel_list._error.text()
    assert not view.channel_list.view.isVisible() or view.channel_list.count() == 0


def test_a_none_result_is_also_an_error(view):
    """_run_query delivers None on failure when no on_error fires."""
    view.on_activate()
    view._runner.calls[1]["ok"](None)
    assert "Couldn't load" in view.channel_list._error.text()


# --------------------------------------------------------------------------
# Interaction
# --------------------------------------------------------------------------

def test_click_selects_and_double_click_plays(view):
    _activate(view, [_dto()])
    seen = []
    view.channelSelected.connect(lambda cid: seen.append(("select", cid)))
    view.playRequested.connect(lambda cid: seen.append(("play", cid)))
    view.channel_list.view.setCurrentIndex(_index(view))
    view.channel_list._on_activated(_index(view))
    assert seen == [("select", "c1"), ("play", "c1")]


def test_the_error_row_emits_nothing(view):
    """It carries no channel id; a click on it must not select a phantom."""
    view.on_activate()
    view._runner.calls[1]["err"](RuntimeError("boom"))
    seen = []
    view.channelSelected.connect(seen.append)
    # There is no row to click: the failure is a label, never a model row, so a
    # click cannot resolve a phantom id in the first place.
    view.channel_list._on_activated(_index(view))
    assert seen == []


# --------------------------------------------------------------------------
# Rendered appearance
# --------------------------------------------------------------------------

def test_the_row_is_painted_with_real_height(view, qapp):
    """Membership passes for a zero-height row; geometry does not.

    The delegate owns the height now, so this asserts the rect the VIEW will
    actually paint into — which is the thing a user sees either way.
    """
    _activate(view, [_dto()])
    view.channel_list.resize(600, 300)
    view.channel_list.show()
    qapp.processEvents()

    idx = _index(view)
    rect = view.channel_list.view.visualRect(idx)
    assert rect.height() >= 16, (
        f"row height {rect.height()}px — the row is not painted")
    assert rect.width() > 100, (
        f"painted rect is {rect.width()}x{rect.height()} — the row does not "
        "span the viewport")


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
    view.channel_list.show()
    view.channel_list.view.customContextMenuRequested.emit(
        view.channel_list.view.visualRect(_index(view)).center())
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
    rect = view.channel_list.view.visualRect(_index(view))
    qapp.sendEvent(view.channel_list.view.viewport(), QMouseEvent(
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
    rect = view.channel_list.view.visualRect(_index(view))
    qapp.sendEvent(view.channel_list.view.viewport(), QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(rect.center()),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    assert seen == []


def test_every_declared_signal_is_actually_emitted():
    """Guards the general shape of the bug above.

    A signal the view never emits is wiring that looks connected and does
    nothing. Source-level, because emitting each one from a test would need a
    scenario per signal and the point is the ABSENCE of an emit.

    Two things this test got wrong the first time, both worth keeping fixed:

    1. It HAND-LISTED the four signals, so a fifth one added later would not be
       checked — the guard had the exact blind spot it exists to close. The list
       is now derived from the class.
    2. It only accepted ``self.X.emit(``. Connecting a source signal straight to
       a destination signal is Qt's own forwarding idiom and emits just as
       really; the view now forwards the harness's signals that way, and the
       test failed on working code.
    """
    from pathlib import Path

    from PyQt6.QtCore import pyqtSignal

    import metatv.gui.sports_view as mod
    from metatv.gui.sports_view import SportsView

    declared = [name for name, value in vars(SportsView).items()
                if isinstance(value, pyqtSignal)]
    assert declared, "no signals found — the introspection broke, not the view"

    source = Path(mod.__file__).read_text()
    for signal in declared:
        emitted = f"self.{signal}.emit(" in source
        forwarded = f"connect(self.{signal})" in source
        assert emitted or forwarded, (
            f"{signal} is declared and never emitted — neither "
            f"self.{signal}.emit(...) nor connect(self.{signal})")


def test_a_failed_taxonomy_load_is_retried_next_activation(view):
    """The dropdowns must not stay empty for the rest of the session.

    The flag is set when the query is SUBMITTED (so two rapid activations do
    not both issue the whole-corpus scan) and cleared on failure (so the next
    activation tries again).
    """
    view.on_activate()
    view._runner.calls[0]["err"](RuntimeError("boom"))
    assert "Couldn't load" in view.channel_list._error.text()

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


def test_the_widget_count_does_not_scale_with_the_row_count(view, qapp):
    """The one test that would have caught the freeze — and the only shape that can.

    Every other test in this file passes just as happily against a list that
    builds one live ``QWidget`` per row: the content is right, the order is
    right, the geometry is right. What is wrong is invisible to all of them, and
    only shows up as time.

    So this asserts the structural property instead. A virtualized list creates
    a fixed number of widgets no matter how many rows it holds — the delegate
    paints the rest. A per-row-widget list creates one (plus its four children)
    per row, which at the owner's 28,018 sports rows meant ~11 s of frozen main
    thread measured offscreen, and minutes on a real display competing with a
    migration.

    250x is a deliberately loose bound: it does not care how many chrome widgets
    the harness has, only that the number does not TRACK the rows. The old
    implementation produced ~5 widgets per row, so it fails this by three orders
    of magnitude, not by a hair.
    """
    from PyQt6.QtWidgets import QWidget

    def widget_count(n: int) -> int:
        _activate(view, [_dto(id=f"c{i}", name=f"Channel {i}") for i in range(n)])
        view.channel_list.resize(600, 400)
        view.channel_list.show()
        qapp.processEvents()
        return len(view.channel_list.findChildren(QWidget))

    few = widget_count(20)
    many = widget_count(5000)

    assert view.channel_list.count() == 5000, "the rows really are all there"
    assert many <= few + 250, (
        f"{few} widgets for 20 rows but {many} for 5000 — the list is building "
        f"a widget per row again. Use the virtualized model+delegate "
        f"(ChannelResultsList); see channel_results_list.py for why."
    )


# --------------------------------------------------------------------------
# Catalog staleness banner (SPORT-7)
#
# On origin/main SportsView has no `_catalog_banner` attribute at all — every
# test below fails at construction/attribute-access against the pre-fix code,
# which is the "proven to fail pre-fix" the UI-slice rule asks for.
# --------------------------------------------------------------------------

def _resolve_catalog(view, value=None, *, failed: bool = False) -> None:
    """Deliver a result to the catalog-freshness query — always the 4th
    _run_query call issued by on_activate() (taxonomy, rows, counts, catalog)."""
    call = view._runner.calls[3]
    if failed:
        call["err"](RuntimeError("boom"))
    else:
        call["ok"](value)


def test_stale_catalog_shows_the_banner_with_its_age(view):
    view.on_activate()
    old = datetime.now() - timedelta(hours=7)
    _resolve_catalog(view, old)

    assert not view._catalog_banner.isHidden()
    assert "7 hours ago" in view._catalog_banner.text(), view._catalog_banner.text()
    assert "Refresh sources" in view._catalog_banner.text()


def test_fresh_catalog_hides_the_banner(view):
    view.on_activate()
    recent = datetime.now() - timedelta(hours=1)
    _resolve_catalog(view, recent)

    assert view._catalog_banner.isHidden()


def test_a_source_that_never_refreshed_reads_as_never(view):
    """None means no active provider has ever ingested a channel — the
    banner must still speak up (never = maximally stale), not stay silent."""
    view.on_activate()
    _resolve_catalog(view, None)

    assert not view._catalog_banner.isHidden()
    assert "never" in view._catalog_banner.text()


def test_a_failed_freshness_query_hides_the_banner(view):
    """The banner is advisory, not content — a failed read must not paint a
    visible error (unlike _on_channels_loaded, which must)."""
    view.on_activate()
    _resolve_catalog(view, failed=True)

    assert view._catalog_banner.isHidden()


def test_refresh_pending_hides_the_banner_even_when_stale(view):
    view.on_activate()
    _resolve_catalog(view, datetime.now() - timedelta(hours=27))
    assert not view._catalog_banner.isHidden()

    view.set_refresh_pending(True)
    assert view._catalog_banner.isHidden()


def test_the_queue_draining_re_checks_freshness(view):
    """Covers the all-failed-refreshes case: reload() only fires on SUCCESS,
    so without this the banner would stay optimistically hidden forever after
    a refresh that enqueued and then failed."""
    view.on_activate()
    _resolve_catalog(view, datetime.now() - timedelta(hours=27))
    view.set_refresh_pending(True)
    before = len(view._runner.calls)

    view.set_refresh_pending(False)
    assert len(view._runner.calls) == before + 1, (
        "the queue draining must re-query freshness, not just flip a flag")


def test_clicking_the_banner_emits_refresh_sources_requested(view):
    """The view never reaches into refresh_queue_manager itself — it asks the
    host via this signal (engine <- control <- view, DR-0007)."""
    view.on_activate()
    _resolve_catalog(view, datetime.now() - timedelta(hours=27))

    seen = []
    view.refreshSourcesRequested.connect(lambda: seen.append(True))
    view._catalog_banner.click()
    assert seen == [True]


def test_deactivate_bumps_the_catalog_token_too(view):
    """Symmetric with the rows/counts tokens — an in-flight freshness read
    must not paint a banner over whatever view the user switched to."""
    view.on_activate()
    before = view._catalog_token[0]
    view.on_deactivate()
    assert view._catalog_token[0] > before
