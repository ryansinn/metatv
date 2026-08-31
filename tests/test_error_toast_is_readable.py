"""An error toast must show the CAUSE, not the statement (owner report).

A provider refresh failed with "database is locked" and the notification
carried the whole SQLAlchemy error — 56,162 characters, most of it
``(?, ?, ?, …)`` — so the toast was a wall of question marks with the reason
scrolled off the top. The full text was already in the log at that moment; what
the toast owed the user was the one line they can act on.
"""

import pytest

from metatv.core.notifications import condense_error

_REAL = (
    "(sqlite3.OperationalError) database is locked\n"
    "[SQL: INSERT INTO channels (id, source_id) VALUES (?, ?)"
    + ", (?, ?)" * 4000 + "]\n"
    "[parameters: ('86634c27_1118063', '1118063', ...)]"
)


def test_the_owners_actual_error_becomes_one_readable_line():
    out = condense_error(_REAL)
    assert out == "(sqlite3.OperationalError) database is locked"
    assert len(_REAL) > 30_000, "the fixture must be a realistically huge error"
    assert len(out) < 60


def test_the_sql_never_survives():
    """The specific thing that made it unreadable."""
    out = condense_error(_REAL)
    assert "(?" not in out
    assert "[SQL:" not in out and "[parameters:" not in out


def test_a_statement_on_the_same_line_is_still_cut():
    """Not every driver puts the SQL on its own line."""
    assert condense_error("boom [SQL: SELECT 1]") == "boom"


@pytest.mark.parametrize("text,expected", [
    ("Connection refused", "Connection refused"),
    ("  padded  ", "padded"),
    ("", "Unknown error"),
    (None, "Unknown error"),
])
def test_ordinary_messages_pass_through(text, expected):
    """Condensing must not damage a message that was already fine."""
    assert condense_error(text) == expected


def test_a_long_single_line_is_cut_and_marked():
    out = condense_error("x" * 900)
    assert len(out) <= 240
    assert out.endswith("…"), "a truncated message must say it was truncated"


def test_the_refresh_failure_path_uses_it():
    """The helper is worthless if the one caller does not call it."""
    import inspect

    from metatv.gui import refresh_queue_manager

    src = inspect.getsource(refresh_queue_manager)
    assert "condense_error(message)" in src, (
        "the Refresh Failed toast must condense its message")
