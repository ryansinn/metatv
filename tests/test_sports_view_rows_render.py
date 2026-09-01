"""The Sports view opened permanently empty while its chips filled in.

Cause: ``_run_query`` increments ``token_ref`` before EVERY submit and
``_on_query_result`` drops any result whose tag no longer matches. The view
fired its rows read and its lane-count read back to back through ONE shared
counter, so submitting the counts cancelled the rows — every time, by
construction. The chips and lane counts painted; the list stayed black.

Reproducing it needs the REAL token arithmetic, not a stub that delivers
everything: a double which always calls ``on_result`` passes against the broken
code and proves nothing. ``_FakeAsyncHost`` below therefore copies the seam's
two rules exactly — increment before submit, compare at delivery — and is
asserted against the real ``_AsyncMixin`` so it cannot drift into agreeing with
a bug.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class _Row:
    """A row-shaped sentinel.

    These were plain strings until ``_on_channels_loaded`` began reading the
    result set to decide the leading discriminator slot (SPORT-3). The strings
    then stopped modelling a row at all and the view raised ``AttributeError``
    — repaired HERE, at the double, rather than with a ``getattr`` in the view,
    which would have masked a real shape mismatch in production.

    Deliberately still opaque: this file's subject is the TOKEN ARITHMETIC —
    that a rows read survives the counts read — so the fields carry no meaning
    and identity is what every assertion below compares.
    """

    name: str
    sport_type: str = ""
    detected_region: str = ""


class _FakeAsyncHost:
    """A ``_run_query`` that defers delivery and honours the token contract."""

    def __init__(self):
        self.pending = []          # (on_result, token, token_ref, query_fn)

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
        if token_ref is not None:
            token_ref[0] += 1
        token = token_ref[0] if token_ref is not None else None
        self.pending.append((on_result, token, token_ref, query_fn))

    def deliver_all(self, data_for):
        """Deliver every queued result in submission order, dropping stale ones.

        Returns the on_result callables that actually ran.
        """
        ran = []
        for on_result, token, token_ref, query_fn in self.pending:
            if token_ref is not None and token_ref[0] != token:
                continue           # stale — exactly what the real slot does
            on_result(data_for(query_fn))
            ran.append(on_result)
        self.pending.clear()
        return ran


def test_the_fake_host_matches_the_real_async_seam():
    """Guard the guard: if the seam's rule changes, this test must not keep passing.

    Asserts the two behaviours the fake copies — increment-before-submit, and
    drop-on-mismatch — against the real source.
    """
    import inspect

    from metatv.gui.main_window_async import _AsyncMixin

    run_src = inspect.getsource(_AsyncMixin._run_query)
    assert "token_ref[0] += 1" in run_src, "the seam no longer bumps before submit"

    slot_src = inspect.getsource(_AsyncMixin._on_query_result)
    assert "token_ref[0] != result.token" in slot_src, (
        "the seam no longer drops on token mismatch")


@pytest.fixture
def view(qapp, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.sports_view import SportsView

    from metatv.core.database import Database

    host = _FakeAsyncHost()
    config = Config(config_dir=tmp_path)
    # A real Database on a real file — the view holds it for symmetry only and
    # every read goes through run_query, but :memory: is forbidden for
    # session-backed work and a None would be a different object than ships.
    db = Database(f"sqlite:///{tmp_path / 'sports.db'}")
    db.create_tables()
    v = SportsView(db=db, config=config, run_query=host._run_query)
    return v, host


def test_opening_the_view_renders_rows_not_just_the_counts(view, monkeypatch):
    """The defect, stated as behaviour: rows must survive the counts query.

    FAILS pre-fix — the rows result is discarded because submitting the lane
    counts bumped the shared counter past it.
    """
    v, host = view
    rendered = []
    monkeypatch.setattr(v.channel_list, "set_rows", lambda rows, **k: rendered.append(rows))
    monkeypatch.setattr(v, "_on_lane_counts_loaded", lambda data: None)

    v._reload_channels(refresh_counts=True)
    assert len(host.pending) == 2, "expected a rows read and a counts read"

    host.deliver_all(lambda fn: [_Row("row-a"), _Row("row-b")])

    assert rendered == [[_Row("row-a"), _Row("row-b")]], (
        "the rows never reached the list — the counts query cancelled them")


def test_the_two_reads_do_not_share_a_counter(view):
    """The mechanism, guarded directly so a future merge cannot re-share it."""
    v, _host = view
    assert v._rows_token is not v._counts_token


def test_deactivate_cancels_both_reads(view, monkeypatch):
    """Bumping only one counter would leave the other read free to paint.

    Switching away from a view must drop everything in flight, or a slow read
    lands on top of whatever the user opened instead.
    """
    v, host = view
    rendered = []
    monkeypatch.setattr(v.channel_list, "set_rows", lambda rows, **k: rendered.append(rows))
    counts = []
    monkeypatch.setattr(v, "_on_lane_counts_loaded", lambda data: counts.append(data))

    v._reload_channels(refresh_counts=True)
    v.on_deactivate()
    host.deliver_all(lambda fn: [_Row("late")])

    assert rendered == [], "a stale rows read painted after the view was left"
    assert counts == [], "a stale counts read landed after the view was left"


def test_a_lane_switch_still_renders(view, monkeypatch):
    """The one path that accidentally worked must keep working.

    ``refresh_counts=False`` fires a single read, which is why clicking a
    DIFFERENT lane populated the list while opening the view did not — and why
    the empty state looked unescapable, since clicking the already-active lane
    returns early.
    """
    v, host = view
    rendered = []
    monkeypatch.setattr(v.channel_list, "set_rows", lambda rows, **k: rendered.append(rows))

    v._reload_channels(refresh_counts=False)
    host.deliver_all(lambda fn: [_Row("only-rows")])

    assert rendered == [[_Row("only-rows")]]


# ── the restored filter must reach the QUERY, not just the chips ────────────

def test_a_restored_sport_filter_actually_reloads(view, monkeypatch):
    """The chips remembered the sport; the query did not.

    ``restore_filter_state`` sets the chips under ``blockSignals(True)`` — right,
    or sixteen chips would fire sixteen reloads — so nothing downstream hears
    about it, and nothing reloaded afterwards. The result the owner saw: Baseball
    rendered as the selected chip above a list of hockey fixtures, with
    "Channels (6524)" where the real filtered count is 142. Unselecting and
    reselecting the chip fixed it, which is the tell — the toggle emits the
    signal the restore suppressed.

    Asserts the RELOAD, not the chip state: a test that checked
    ``chip.isChecked()`` passes against the broken code, because the chips were
    never the part that was wrong.
    """
    v, _host = view
    v.config.sports_filter_state = {"sport_types": ["baseball"],
                                    "league_names": [], "search": ""}
    reloads = []
    monkeypatch.setattr(v, "_reload_channels",
                        lambda **kw: reloads.append(kw))
    monkeypatch.setattr(v.filter_bar, "load_taxonomy", lambda *a, **k: None)

    v._on_taxonomy_loaded({"taxonomy": {"baseball": {}}, "counts": {"baseball": 174}})

    assert reloads, (
        "the saved sport was restored onto the chips but never re-queried — "
        "the rows and lane counts stay unfiltered")


def test_an_empty_saved_filter_does_not_re_query(view, monkeypatch):
    """Non-degeneracy, and #626's rule: only reload when it narrows something.

    A saved state with nothing in it describes exactly what the first load
    already did. Re-running it over 6,500 rows to reach an identical answer is
    pure cost — and a version of the fix that reloads unconditionally would pass
    the test above while doing that on every single launch.
    """
    v, _host = view
    v.config.sports_filter_state = {"sport_types": [], "league_names": [],
                                    "search": ""}
    reloads = []
    monkeypatch.setattr(v, "_reload_channels", lambda **kw: reloads.append(kw))
    monkeypatch.setattr(v.filter_bar, "load_taxonomy", lambda *a, **k: None)

    v._on_taxonomy_loaded({"taxonomy": {"baseball": {}}, "counts": {}})

    assert reloads == [], "an empty saved filter re-queried for the same answer"


def test_the_restore_happens_once(view, monkeypatch):
    """A second taxonomy load must not stamp the saved filter back over the
    user's current selection — they may have changed it since."""
    v, _host = view
    v.config.sports_filter_state = {"sport_types": ["baseball"],
                                    "league_names": [], "search": ""}
    restores = []
    monkeypatch.setattr(v.filter_bar, "restore_filter_state",
                        lambda s: restores.append(s))
    monkeypatch.setattr(v, "_reload_channels", lambda **kw: None)
    monkeypatch.setattr(v.filter_bar, "load_taxonomy", lambda *a, **k: None)

    payload = {"taxonomy": {"baseball": {}}, "counts": {}}
    v._on_taxonomy_loaded(payload)
    v._on_taxonomy_loaded(payload)

    assert len(restores) == 1, "the saved filter was re-applied on a later load"


def test_the_startup_reload_does_not_overwrite_the_saved_filter(view, monkeypatch):
    """The bug my first draft of the reload actually had.

    ``_reload_channels`` writes the live filter state back to config, gated on
    ``_filters_restored``. Setting that flag BEFORE the restore-triggered reload
    makes the startup pass save the CHIPS' state over the saved one — and
    ``restore_filter_state`` silently drops a saved sport the taxonomy no longer
    carries, so one source hiccup would erase the user's selection permanently.

    Caught by ``test_nothing_is_saved_before_the_restore_has_run``, which
    documents the flag as the guard for exactly this. Asserted here too, from
    the restore direction, because that test approaches it from the other side
    and neither covers this ordering on its own.
    """
    v, _host = view
    saved = {"sport_types": ["baseball"], "league_names": [], "search": ""}
    v.config.sports_filter_state = dict(saved)
    # The taxonomy no longer carries baseball, so the chips come back empty —
    # the realistic shape of the hazard, not a contrived one.
    monkeypatch.setattr(v.filter_bar, "load_taxonomy", lambda *a, **k: None)
    monkeypatch.setattr(v.filter_bar, "restore_filter_state", lambda s: None)
    monkeypatch.setattr(v.filter_bar, "get_filter_state",
                        lambda: {"sport_types": [], "league_names": [], "search": ""})

    v._on_taxonomy_loaded({"taxonomy": {"hockey": {}}, "counts": {}})

    assert v.config.sports_filter_state == saved, (
        "the startup reload wrote the empty chip state over the saved filter")
