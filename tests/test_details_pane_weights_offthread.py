"""The details pane must not compute taste weights on the UI thread.

The owner's main-thread watchdog caught a **28,731 ms** freeze (worst of twelve
stalls that session) with this sampled stack::

    gui/main_window_metadata.py:712  _update_details_with_metadata
    gui/details_pane.py:272          show_channel
    gui/details_pane.py:631          _apply_metadata
    gui/details_pane.py:643          _fetch_weights
    core/preference_engine.py:338    compute_weights
    sqlalchemy … query.all() → cursor.fetchall()

``_fetch_weights`` opened its own session and called ``compute_weights()``
synchronously *inside the render path*: every ``UserRatingDB`` row, a batch load
of the rated channels, then every favourite channel WITH its metadata — seconds
of SQL with the paint held.

The fix is render-first/annotate-second: ``_apply_metadata`` paints both people
sections with ``weights=None`` (the already-existing degraded render) and emits
``weights_requested``; the host answers off-thread through the one ``_run_query``
seam and hands the result back via ``apply_taste_weights``, which drops a reply
for a channel the pane has already left — the same guard
``apply_action_state``/``apply_channel_tags`` use.

These tests fail against the pre-fix code: ``show_channel`` called
``compute_weights`` itself, so the first test's exploding patch fired, and there
was no ``weights_requested`` signal to assert on.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from loguru import logger

from metatv.core.models import MediaType
from metatv.metadata_providers.base import MetadataResult
from tests.conftest import destroy_widget, wire_inline_run_query


CHANNEL_A = "prov_a"
CHANNEL_B = "prov_b"

# The two markers _pref_signal paints in front of a liked / disliked person.
LIKED_MARK = "▲"
DISLIKED_MARK = "▼"


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _config(tmp_path):
    from metatv.core.config import Config

    return Config(config_dir=tmp_path)


def _weights(**over):
    """A real AttributeWeights with a liked actor and a disliked director."""
    from metatv.core.preference_engine import AttributeWeights

    return AttributeWeights(
        actors={"Ada Star": 1.0},
        directors={"Bob Helm": -1.0},
        rated_count=over.pop("rated_count", 3),
        **over,
    )


def _metadata():
    return MetadataResult(
        title="A Film",
        plot="Something happens.",
        release_date="2001-02-03",
        cast=[{"name": "Ada Star"}, {"name": "Cid Nobody"}],
        director="Bob Helm",
    )


def _channel(channel_id: str):
    return SimpleNamespace(
        id=channel_id,
        name=f"Channel {channel_id}",
        media_type=MediaType.MOVIE,
        is_favorite=False,
        detected_prefix="",
        watch_progress=0,
        watch_completed=False,
        logo_url=None,
        detected_title=f"Title {channel_id}",
        detected_region="",
        detected_quality="",
        detected_year="2001",
        provider_id=None,
        is_adult=False,
        raw_data={},
    )


@pytest.fixture
def pane(qapp, tmp_path, db):
    """A real pane over a real file-backed DB.

    ``db`` is not decoration: the pre-fix ``_fetch_weights`` bailed out early
    when the pane had none, so a ``db=None`` pane could never prove the render
    path stopped calling ``compute_weights``.
    """
    from metatv.gui.details_pane import DetailsPaneWidget

    widget = DetailsPaneWidget(_config(tmp_path), image_cache=MagicMock(), db=db)
    widget.resize(460, 900)
    yield widget
    # _action_bar is deliberately parentless — the pane reparents its BUTTONS
    # into the tiered slots and keeps the bar itself as a holder (details_pane
    # _setup_ui), so it outlives the pane and trips the top-level leak guard
    # unless it is destroyed by name.
    destroy_widget(widget, widget._action_bar)


# ── 1. the render path never computes weights ───────────────────────────────


def test_the_render_path_never_computes_taste_weights(pane, monkeypatch):
    """show_channel() must paint without touching compute_weights.

    Patched on ``preference_engine`` — the module that DEFINES it — because the
    host resolves the name at call time from there.
    """
    import metatv.core.preference_engine as pe

    def _explode(*a, **kw):  # pragma: no cover - the assertion is that it never runs
        raise AssertionError(
            "compute_weights ran on the UI thread inside the render path"
        )

    monkeypatch.setattr(pe, "compute_weights", _explode)

    asked: list[str] = []
    pane.weights_requested.connect(asked.append)

    pane.show_channel(_channel(CHANNEL_A), metadata=_metadata())

    assert asked == [CHANNEL_A], (
        "the pane must ASK the host for weights, exactly once, carrying the "
        "channel id the reply will be checked against"
    )
    text = pane._cast.cast_label.text()
    assert "Ada Star" in text, "the cast must be painted before any weights arrive"
    assert LIKED_MARK not in text and DISLIKED_MARK not in text, (
        "the first paint is the weights=None render — no preference markers yet"
    )


def test_a_channel_with_no_metadata_never_asks_for_weights(pane):
    """The un-enriched tier-1 render has no cast to annotate."""
    asked: list[str] = []
    pane.weights_requested.connect(asked.append)
    pane.show_channel(_channel(CHANNEL_A), metadata=None)
    assert asked == []


# ── 2. the host answers through the _run_query seam ─────────────────────────


def _host(db, tmp_path):
    """A MainWindow double carrying only what the weights path touches."""
    from metatv.gui.main_window_metadata import _MetadataMixin

    host = SimpleNamespace(
        db=db,
        config=_config(tmp_path),
        details_pane=MagicMock(),
        _details_weights_token=[0],
    )
    wire_inline_run_query(host)
    host._on_weights_requested = _MetadataMixin._on_weights_requested.__get__(host)
    host._on_weights_loaded = _MetadataMixin._on_weights_loaded.__get__(host)

    # Record what reached the seam without replacing it — the real _run_query
    # still runs, inline, so the query_fn executes against a real session.
    calls: list[dict] = []
    inner = host._run_query

    def _recording(query_fn, on_result, **kw):
        calls.append({"query_fn": query_fn, "on_result": on_result, **kw})
        return inner(query_fn, on_result, **kw)

    host._run_query = _recording
    host.calls = calls
    return host


def test_the_host_reads_the_weights_through_the_run_query_seam(db, tmp_path, monkeypatch):
    """One _run_query call, with a query_fn, the pane's token and an on_error."""
    import metatv.core.preference_engine as pe

    computed = _weights()
    seen_sessions: list = []

    def _fake(session, settings=None, **kw):
        seen_sessions.append(session)
        return computed

    monkeypatch.setattr(pe, "compute_weights", _fake)

    host = _host(db, tmp_path)
    host._on_weights_requested(CHANNEL_A)

    assert len(host.calls) == 1, "the read goes through the seam exactly once"
    call = host.calls[0]
    assert callable(call["query_fn"]), "the seam is handed a query_fn, not data"
    assert call["token_ref"] is host._details_weights_token
    assert callable(call["on_error"]), (
        "a failed read must reach the main thread, not vanish in the worker"
    )
    assert call.get("commit") in (None, False), "computing weights is a READ"

    assert seen_sessions, "compute_weights must run inside the seam's session"
    from sqlalchemy.orm import Session

    assert isinstance(seen_sessions[0], Session)

    host.details_pane.apply_taste_weights.assert_called_once_with(CHANNEL_A, computed)


def test_an_empty_taste_profile_reaches_the_pane_as_none(db, tmp_path, monkeypatch):
    """is_empty() weights are None to the pane — the pre-fix contract, kept."""
    import metatv.core.preference_engine as pe

    monkeypatch.setattr(
        pe, "compute_weights", lambda *a, **kw: pe.AttributeWeights()
    )
    host = _host(db, tmp_path)
    host._on_weights_requested(CHANNEL_A)
    host.details_pane.apply_taste_weights.assert_called_once_with(CHANNEL_A, None)


# ── 3. the error branch leaves the un-annotated render, and says so ─────────


def test_a_failed_read_logs_and_leaves_the_render_alone(db, tmp_path, monkeypatch):
    import metatv.core.preference_engine as pe

    def _boom(*a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(pe, "compute_weights", _boom)

    lines: list[str] = []
    sink = logger.add(lines.append, level="WARNING", format="{message}")
    try:
        host = _host(db, tmp_path)
        host._on_weights_requested(CHANNEL_A)
    finally:
        logger.remove(sink)

    host.details_pane.apply_taste_weights.assert_not_called()
    # The seam's own worker log is not enough: loguru's diagnosed traceback
    # mentions the channel id anyway, so the assertion names the message the
    # on_error callback writes — drop that callback and this goes red.
    assert any("Taste weights unavailable" in line and CHANNEL_A in line for line in lines), (
        "a failed taste read must reach the main thread and be logged against "
        "the channel, never swallowed in the worker"
    )


def test_none_weights_leave_the_un_annotated_render_standing(pane):
    """No taste signal is not a reason to blank the cast the pane already painted."""
    pane.show_channel(_channel(CHANNEL_A), metadata=_metadata())
    before = pane._cast.cast_label.text()
    assert "Ada Star" in before

    pane.apply_taste_weights(CHANNEL_A, None)

    assert pane._cast.cast_label.text() == before, (
        "a None reply must leave the render untouched — never clear() it"
    )
    assert not pane._cast.isHidden(), "the Cast section must not be hidden"


# ── 4. a late reply for a channel the pane has left is dropped ──────────────


def test_a_late_reply_for_a_channel_the_pane_has_left_is_dropped(pane):
    pane.show_channel(_channel(CHANNEL_A), metadata=_metadata())
    pane.show_channel(_channel(CHANNEL_B), metadata=_metadata())
    text_on_b = pane._cast.cast_label.text()

    pane.apply_taste_weights(CHANNEL_A, _weights())

    assert pane._cast.cast_label.text() == text_on_b, (
        "channel A's weights must not annotate channel B's pane"
    )
    assert LIKED_MARK not in pane._cast.cast_label.text()


def test_the_reply_for_the_channel_on_screen_is_applied(pane):
    pane.show_channel(_channel(CHANNEL_A), metadata=_metadata())
    assert LIKED_MARK not in pane._cast.cast_label.text()

    pane.apply_taste_weights(CHANNEL_A, _weights())

    text = pane._cast.cast_label.text()
    assert LIKED_MARK in text, "the liked actor must gain its ▲ marker"
    assert DISLIKED_MARK in pane._cast._director_lbl.text(), (
        "the disliked director must gain its ▼ marker"
    )


# ── 5. rendered appearance: the marker is added in place ────────────────────


def test_the_marker_is_added_without_moving_the_cast_row(pane, qapp):
    """Rendered-appearance gate, driven through the real two-pass render.

    Pass one is what the user now sees immediately; pass two is what the
    off-thread reply paints on top of it. The annotated pass must occupy the
    SAME rectangle and add only the marker glyph in the palette's positive
    colour — an annotation that re-flowed the section would shift the pane
    under the reader's cursor a second after they opened it.

    Fails against the pre-fix code: there is no ``apply_taste_weights`` to make
    the second pass with — the only render was the annotated one.
    """
    from metatv.gui import theme as _theme

    def _settle():
        """Run the layout to rest — a half-laid-out row is not a rendering."""
        for _ in range(3):
            pane._cast._content.layout().activate()
            pane._cast.layout().activate()
            qapp.processEvents()

    pane.show()
    _settle()

    pane.show_channel(_channel(CHANNEL_A), metadata=_metadata())
    _settle()
    plain_geom = pane._cast.cast_label.geometry()
    plain_dir_geom = pane._cast._director_lbl.geometry()
    plain_text = pane._cast.cast_label.text()

    assert plain_geom.width() > 0 and plain_geom.height() > 0, (
        "the un-annotated pass must actually paint a row to compare against"
    )
    assert LIKED_MARK not in plain_text and DISLIKED_MARK not in plain_text

    pane.apply_taste_weights(CHANNEL_A, _weights())
    _settle()

    marked_text = pane._cast.cast_label.text()
    assert LIKED_MARK in marked_text, "the liked actor gains ▲"
    assert _theme.COLOR_OK in marked_text, (
        "the ▲ takes the palette's positive colour, never a literal"
    )
    assert DISLIKED_MARK in pane._cast._director_lbl.text()
    assert _theme.COLOR_ERR in pane._cast._director_lbl.text()

    assert pane._cast.cast_label.geometry() == plain_geom, (
        "annotating must not move or resize the cast row — the markers are "
        "inline, so the pane must not jump once the weights land"
    )
    assert pane._cast._director_lbl.geometry() == plain_dir_geom
