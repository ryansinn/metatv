"""The Watch Alerts row's left slot: one column, several markers, no reflow.

The bug: the play affordance was a button at the RIGHT edge, shown on hover, so
it pushed the progress bar sideways every time the pointer crossed a row. Owner:
"the play button on the right on hover bumps the progress bar and fucks with the
layout."

And it appeared on UPCOMING rows, offering to play a programme that has not
aired. Owner: "how can it play anything in future... no time machine."
"""

from datetime import datetime, timedelta

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QEnterEvent, QMouseEvent

from metatv.core.config import Config
from metatv.gui import theme as _theme
from metatv.gui.relative_time import humanize_remaining
from metatv.gui.sidebar.alerts_rows import SLOT_W, _AlertRow

NOW = datetime(2026, 8, 26, 12, 0, 0)


def _live(tmp_path, *, mins_in=10, total=30):
    stop = NOW + timedelta(minutes=total - mins_in)
    row = _AlertRow("Mexico Life", humanize_remaining(stop, NOW),
                    Config(config_dir=tmp_path), when=stop, live=True,
                    started_at=NOW - timedelta(minutes=mins_in))
    row.refresh_time(NOW)
    return row


def _upcoming(tmp_path):
    return _AlertRow("Mexico 86", "in 27m", Config(config_dir=tmp_path),
                     when=NOW + timedelta(minutes=27), live=False)


def _enter(row) -> None:
    """Qt6 types enterEvent as taking a QEnterEvent specifically, not a QEvent."""
    pos = QPointF(4, 4)
    row.enterEvent(QEnterEvent(pos, pos, pos))


def _leave(row) -> None:
    row.leaveEvent(QEvent(QEvent.Type.Leave))


def _has_marker(row) -> bool:
    pixmap = row._slot.pixmap()
    return not pixmap.isNull()


# ── the reflow, which is the whole reason the slot exists ───────────────
def test_hover_does_not_move_anything(qapp, tmp_path):
    """Rendered geometry, before and after hover, must be identical.

    This is the assertion that fails against the pre-fix code: a right-edge
    button appearing on hover took real layout space and shifted the bar left.
    """
    row = _live(tmp_path)
    row.setFixedWidth(280)
    row.show()
    qapp.processEvents()

    title = row.layout().itemAt(1).widget()
    before = (title.geometry(), row.progress.geometry())

    _enter(row)
    qapp.processEvents()
    after = (title.geometry(), row.progress.geometry())

    assert before == after, (
        "hovering moved the row's contents — the play affordance is taking "
        "layout space instead of living in the reserved slot"
    )


def test_the_slot_reserves_its_width_even_when_empty(qapp, tmp_path):
    """An empty slot must still occupy the column, or rows would not align."""
    row = _live(tmp_path)
    assert not _has_marker(row), "an idle row should show no marker"
    assert row._slot.width() == SLOT_W


# ── what the slot shows, and in what order ─────────────────────────────
def test_hovering_a_live_row_offers_play(qapp, tmp_path):
    row = _live(tmp_path)
    _enter(row)
    assert _has_marker(row)
    assert row._slot.toolTip() == "Play"
    _leave(row)
    assert not _has_marker(row)


def test_an_upcoming_row_never_offers_play(qapp, tmp_path):
    """No time machine. Hovering must change nothing."""
    row = _upcoming(tmp_path)
    assert not _has_marker(row)
    _enter(row)
    assert not _has_marker(row), "an upcoming row offered to play a future programme"
    assert row._slot.toolTip() == ""


def test_playing_outranks_hover_and_new(qapp, tmp_path):
    """One column, so the markers need an order; what is ON now wins."""
    row = _live(tmp_path)
    row.set_new(True)
    assert row._slot.toolTip() == "New since you last looked"

    _enter(row)
    assert row._slot.toolTip() == "Play", "hover must outrank the new marker"

    row.set_playing(True)
    assert row._slot.toolTip() == "Playing now", "playing must outrank hover"

    row.set_playing(False)
    assert row._slot.toolTip() == "Play"


def test_a_new_upcoming_row_still_shows_its_dot(qapp, tmp_path):
    """Suppressing PLAY on upcoming rows must not suppress the whole slot."""
    row = _upcoming(tmp_path)
    row.set_new(True)
    assert _has_marker(row)
    assert row._slot.toolTip() == "New since you last looked"


# ── clicking ────────────────────────────────────────────────────────────
def _press(row, x):
    row.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, 8), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))


def test_clicking_the_slot_plays_and_clicking_the_row_selects(qapp, tmp_path):
    row = _live(tmp_path)
    row.setFixedWidth(280)
    row.show()
    qapp.processEvents()
    _enter(row)

    played, selected = [], []
    row.play_clicked.connect(lambda: played.append(1))
    row.row_clicked.connect(lambda: selected.append(1))

    _press(row, row._slot.geometry().center().x())
    assert played and not selected, "clicking the triangle did not play"

    _press(row, 150)
    assert selected, "clicking the row body did not select it"


def test_clicking_the_slot_of_an_upcoming_row_selects_rather_than_plays(qapp, tmp_path):
    """The slot is only a play control while it is offering to play."""
    row = _upcoming(tmp_path)
    row.setFixedWidth(280)
    row.show()
    qapp.processEvents()
    _enter(row)

    played, selected = [], []
    row.play_clicked.connect(lambda: played.append(1))
    row.row_clicked.connect(lambda: selected.append(1))
    _press(row, row._slot.geometry().center().x())
    assert not played and selected
