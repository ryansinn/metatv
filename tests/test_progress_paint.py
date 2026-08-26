"""One progress bar across three surfaces, and what it can say that words cannot.

Owner: "30 minutes left on a 30 minute show is different than 30 minutes left on
a 3 hour show." A duration cannot express that; a proportion can.

Before this there were TWO painters that did not match each other — the EPG
delegate's grey-plus-HSV-ramp and the agenda strip's different grey plus a flat
amber — and four hardcoded colour literals between them, invisible to the theme
layer.
"""

from datetime import datetime, timedelta

import pytest

from metatv.core.config import Config
from metatv.gui import theme as _theme
from metatv.gui.progress_paint import NEARLY_OVER_PCT, elapsed_pct
from metatv.gui.sidebar.alerts_rows import _AlertRow, _ProgressBar

NOW = datetime(2026, 8, 26, 12, 0, 0)


# ── the arithmetic ──────────────────────────────────────────────────────
def test_elapsed_pct_measures_the_share_not_the_remainder():
    start, stop = NOW - timedelta(minutes=10), NOW + timedelta(minutes=20)
    # approx, not ==: 10/30 is not exactly representable in binary floating
    # point, and pinning an exact float is a test that fails for arithmetic
    # reasons rather than behavioural ones.
    assert elapsed_pct(start, stop, NOW) == pytest.approx(100 / 3)  # 10 of 30 min

    # Same 20 minutes remaining, a three-hour programme: nearly done.
    start = NOW - timedelta(minutes=160)
    assert elapsed_pct(start, stop, NOW) > NEARLY_OVER_PCT


def test_elapsed_pct_never_divides_by_a_bad_duration():
    """Provider EPG really does carry zero- and negative-length rows, and a
    crash in a paint path takes the whole list down."""
    assert elapsed_pct(NOW, NOW, NOW) == 0.0
    assert elapsed_pct(NOW + timedelta(hours=1), NOW, NOW) == 0.0
    assert elapsed_pct(None, NOW, NOW) == 0.0
    assert elapsed_pct(NOW, None, NOW) == 0.0


def test_elapsed_pct_clamps_a_programme_that_ran_over():
    start, stop = NOW - timedelta(hours=2), NOW - timedelta(minutes=5)
    assert elapsed_pct(start, stop, NOW) == 100.0


# ── the bar is token-coloured, not literal-coloured ─────────────────────
def test_the_bar_takes_its_colours_from_tokens(qapp):
    """The drift this replaced: four QColor literals across two painters.

    Reads the module source rather than a rendered pixel because the defect is
    structural — a literal is invisible to the theme layer whatever it renders
    as on the palette that happened to be active.
    """
    import inspect

    from metatv.gui import progress_paint

    body = inspect.getsource(progress_paint.paint_progress)
    assert "QColor(" not in body, "a raw QColor literal is back in the paint path"
    assert "_theme.COLOR_LINE" in body
    assert "_theme.COLOR_WARN" in body and "_theme.COLOR_ACCENT" in body


def test_both_epg_surfaces_use_the_shared_painter(qapp):
    """Neither may quietly grow its own bar again."""
    import inspect

    from metatv.gui import epg_agenda_widget, epg_widgets

    for mod in (epg_widgets, epg_agenda_widget):
        src = inspect.getsource(mod)
        assert "paint_progress" in src, f"{mod.__name__} paints its own bar"
        for literal in ("QColor(55, 55, 55)", "QColor(60, 60, 60)",
                        "QColor(255, 200, 0"):
            assert literal not in src, f"{mod.__name__} still has {literal}"


# ── the row ─────────────────────────────────────────────────────────────
def _row(qapp, tmp_path, *, start, stop, live=True):
    from metatv.gui.relative_time import humanize_remaining
    row = _AlertRow("ORF 2 WIEN", humanize_remaining(stop, NOW),
                    Config(config_dir=tmp_path), when=stop, live=live,
                    started_at=start)
    row.refresh_time(NOW)
    return row


def test_same_words_different_bars(qapp, tmp_path):
    """The owner's case, asserted: identical remaining, different fills."""
    stop = NOW + timedelta(minutes=20)
    short = _row(qapp, tmp_path, start=NOW - timedelta(minutes=10), stop=stop)
    long_ = _row(qapp, tmp_path, start=NOW - timedelta(minutes=160), stop=stop)

    assert short.progress is not None and long_.progress is not None
    assert short.progress.toolTip() == long_.progress.toolTip() == "20m left"
    assert short.progress._pct < long_.progress._pct, (
        "two programmes with the same time left rendered the same bar — which is "
        "the whole thing the bar exists to distinguish"
    )
    assert long_.progress._pct >= NEARLY_OVER_PCT > short.progress._pct


def test_an_upcoming_row_keeps_its_words(qapp, tmp_path):
    """Nothing has elapsed, so there is no share to draw."""
    row = _AlertRow("Mexico 86", "in 13m", Config(config_dir=tmp_path),
                    when=NOW + timedelta(minutes=13), live=False)
    assert row.progress is None
    assert row.time_lbl.isVisibleTo(row)
    assert row.time_lbl.text() == "in 13m"


def test_a_live_row_without_a_start_time_keeps_its_words(qapp, tmp_path):
    """No denominator, no proportion — the words still say something true."""
    row = _AlertRow("KANAL 4", "8m left", Config(config_dir=tmp_path),
                    when=NOW + timedelta(minutes=8), live=True)
    assert row.progress is None
    assert row.time_lbl.isVisibleTo(row)


def test_the_tick_advances_the_bar_and_its_tooltip_together(qapp, tmp_path):
    """One instant drives both, so the fill and the tooltip cannot disagree."""
    row = _row(qapp, tmp_path, start=NOW, stop=NOW + timedelta(minutes=60))
    first = row.progress._pct
    assert row.progress.toolTip() == "60m left"

    row.refresh_time(NOW + timedelta(minutes=45))
    assert row.progress._pct > first
    assert row.progress.toolTip() == "15m left"


def test_the_bar_ignores_a_move_too_small_to_see(qapp, tmp_path):
    """A 30s tick over a three-hour show moves the fill by a fraction of a
    pixel; repainting every row for that is work nobody can see."""
    bar = _ProgressBar(50.0)
    bar.set_pct(50.2)
    assert bar._pct == 50.0
    bar.set_pct(56.0)
    assert bar._pct == 56.0
