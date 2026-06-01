"""Characterization tests for Database.session_scope() (B3-2).

Verifies: commit on success, rollback on exception, always-close — before any
call-site migration so the helper is proven safe first.
"""

import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_with_mock_session():
    """Return a (Database, mock_session) pair where SessionLocal returns the mock."""
    from metatv.core.database import Database

    db = Database.__new__(Database)
    mock_session = MagicMock()
    db.SessionLocal = MagicMock(return_value=mock_session)
    return db, mock_session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_session_scope_commits_on_success():
    """session_scope() must call commit() when the body completes normally."""
    db, sess = _make_db_with_mock_session()
    with db.session_scope() as s:
        assert s is sess
    sess.commit.assert_called_once()


def test_session_scope_always_closes():
    """session_scope() must call close() even when the body raises."""
    db, sess = _make_db_with_mock_session()
    with pytest.raises(ValueError):
        with db.session_scope():
            raise ValueError("boom")
    sess.close.assert_called_once()


def test_session_scope_rolls_back_on_exception():
    """session_scope() must call rollback() when the body raises, not commit()."""
    db, sess = _make_db_with_mock_session()
    with pytest.raises(RuntimeError):
        with db.session_scope():
            raise RuntimeError("fail")
    sess.rollback.assert_called_once()
    sess.commit.assert_not_called()


def test_session_scope_yields_session():
    """session_scope() must yield the session created by SessionLocal."""
    db, sess = _make_db_with_mock_session()
    captured = []
    with db.session_scope() as s:
        captured.append(s)
    assert captured[0] is sess


def test_session_scope_exception_propagates():
    """session_scope() must re-raise the original exception after cleanup."""
    db, sess = _make_db_with_mock_session()
    with pytest.raises(KeyError, match="missing"):
        with db.session_scope():
            raise KeyError("missing")
