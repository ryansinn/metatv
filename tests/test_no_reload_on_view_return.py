"""Coming back to the list must not re-run a search the user never changed.

Owner, 2026-09-02: *"search should [not] reload the results if the search hasn't
changed just because the view is changed. Seems like search is reloading the
search results every time the search view regains focus even on the same
search."*

``on_search_view_toggle`` called ``load_channels()`` unconditionally, so a trip
to Discover and back re-ran the whole 785,551-row filter for a query, a filter
set and a corpus that were all identical.

Skipping is safe rather than optimistic, and the reason is that nothing which
invalidates the rows can happen unnoticed:

* every corpus mutation goes through ``_refresh_provider_dependent_views``,
  which reloads the list ITSELF — visible view or not;
* every path that changes the search state already calls ``load_channels`` at
  the moment it changes it;
* per-channel state is pushed into the rows in place by ``channel_state_bus``.

That leaves exactly two things the chokepoints cannot tell us, and both are
tested here: are there rows at all, and do they answer the query in the box.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.main_window_nav import _NavMixin
from tests.conftest import make_bare_channel_list_model, set_model_channels


def _dto(cid: str) -> ChannelListDTO:
    return ChannelListDTO(
        id=cid, name=f"Channel {cid}", media_type="live", provider_id="p",
        is_favorite=False, category=None, quality=None, detected_prefix=None,
        detected_region=None, detected_quality=None, detected_year=None,
        detected_title=None,
    )


@pytest.fixture()
def model():
    yield from make_bare_channel_list_model()


def _host(model=None, text=""):
    box = MagicMock()
    box.text.return_value = text
    host = SimpleNamespace(search_input=box)
    if model is not None:
        host.channel_model = model
    return host


# ── loaded_search_query ──────────────────────────────────────────────────────

def test_the_model_reports_the_query_its_rows_answer(model):
    set_model_channels(model, [_dto("a")])
    assert model.loaded_search_query() == ""

    model.set_channels(
        [_dto("a")], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={"search_query": "  tron  "}, next_offset=1)
    assert model.loaded_search_query() == "tron", "must be stripped to compare"


def test_an_unloaded_model_reports_an_empty_query(model):
    assert model.loaded_search_query() == ""


# ── the decision ─────────────────────────────────────────────────────────────

def test_returning_to_an_unchanged_search_does_not_requery(model):
    """The report, as an invariant."""
    model.set_channels(
        [_dto("a"), _dto("b")], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={"search_query": "tron"}, next_offset=2)
    host = _host(model, text="tron")
    assert _NavMixin._returning_list_is_stale(host) is False


def test_an_empty_list_is_always_reloaded(model):
    """First visit, or something cleared the rows. Nothing to keep."""
    host = _host(model, text="tron")
    assert _NavMixin._returning_list_is_stale(host) is True


def test_an_empty_list_with_an_empty_box_is_still_reloaded(model):
    """The case the query comparison alone cannot see.

    With no rows and no search term, "the rows answer the query in the box" is
    vacuously true — both are empty — so a check that only compares queries
    says "not stale" and the user is shown an empty list forever. That is the
    ordinary first visit with no search typed, i.e. the common path.

    Found by mutation-checking: deleting the ``loaded_count()`` clause left the
    whole file green, because every other empty-list case here also happened to
    have text in the box.
    """
    host = _host(model, text="")
    assert _NavMixin._returning_list_is_stale(host) is True


def test_a_changed_query_is_reloaded(model):
    """The rows on screen answer a question the user is no longer asking."""
    model.set_channels(
        [_dto("a")], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={"search_query": "tron"}, next_offset=1)
    host = _host(model, text="blade runner")
    assert _NavMixin._returning_list_is_stale(host) is True


def test_clearing_the_box_is_a_changed_query(model):
    """Emptying the search is a different result set, not "no change"."""
    model.set_channels(
        [_dto("a")], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={"search_query": "tron"}, next_offset=1)
    host = _host(model, text="")
    assert _NavMixin._returning_list_is_stale(host) is True


def test_whitespace_is_not_a_change(model):
    """Trailing space in the box must not cost a 785k-row requery."""
    model.set_channels(
        [_dto("a")], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={"search_query": "tron"}, next_offset=1)
    host = _host(model, text="  tron ")
    assert _NavMixin._returning_list_is_stale(host) is False


def test_a_host_without_a_model_yet_reloads(model):
    """Construction order: the nav can be asked before the model exists."""
    host = _host(None, text="")
    assert _NavMixin._returning_list_is_stale(host) is True


def test_the_reads_survive_a_half_built_qobject_host(model):
    """``__dict__.get``, not ``getattr(host, name, default)``.

    A missing attribute on a ``MainWindow.__new__`` double raises RuntimeError
    rather than AttributeError, so the default is never reached — the trap this
    codebase has now hit in four separate batches.
    """
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    assert _NavMixin._returning_list_is_stale(host) is True


# ── the wiring ───────────────────────────────────────────────────────────────

SRC = (pathlib.Path(__file__).resolve().parent.parent
       / "metatv" / "gui" / "main_window_nav.py").read_text()


def test_the_toggle_no_longer_reloads_unconditionally():
    body = SRC[SRC.index("def on_search_view_toggle"):]
    body = body[:body.index("\n    def ", 1)]
    lines = [ln for ln in body.splitlines() if ln.strip()]
    guard = [i for i, ln in enumerate(lines)
             if "self._returning_list_is_stale()" in ln]
    assert guard, "returning to the list requeries whatever the state — the report"

    reload_lines = [i for i, ln in enumerate(lines)
                    if ln.strip() == "self.load_channels()"]
    assert reload_lines, "the toggle can no longer reload at all"
    for i in reload_lines:
        preceding = [g for g in guard if g < i]
        assert preceding, f"load_channels at line {i} is not behind the guard"
        # Behind it means nested UNDER it, not merely after it: a dedented call
        # following the if would run every time and still pass a "comes after"
        # check, which is the shape this test exists to reject.
        indent = len(lines[i]) - len(lines[i].lstrip())
        guard_indent = len(lines[preceding[-1]]) - len(lines[preceding[-1]].lstrip())
        assert indent > guard_indent, (
            "load_channels sits at or outside the guard's indent — it still "
            "runs on every return to the list")
