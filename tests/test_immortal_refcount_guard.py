"""None/True/False stay immortal however long the app runs.

On 2026-09-29 the app aborted after days of uptime: PyQt6's abi3 modules add
one to None's refcount per call that returns None, the interpreter never takes
it back, and after ~1.07 billion calls the low word wrapped and None turned
mortal (core dump: ``ob_refcnt=6928, ob_overflow=1``). Every ``__init__`` then
failed with "should return None, not 'NoneType'".

These tests drive the guard against the REAL objects' refcount words, and one
drives the drift through real PyQt6 calls rather than a hand-written value.
"""

import ctypes
from contextlib import contextmanager

import pytest
from PyQt6.QtCore import QObject

from metatv.core import immortal_refcount_guard as irg

pytestmark = pytest.mark.skipif(
    not irg._layout_supported(), reason="immortal refcount layout is 3.14+ only"
)


def _word(obj: object) -> ctypes.c_uint32:
    return ctypes.c_uint32.from_address(id(obj))


@contextmanager
def _restored(obj: object):
    """Put the object's refcount back to the immortal start whatever happens."""
    try:
        yield _word(obj)
    finally:
        _word(obj).value = irg.IMMORTAL_INITIAL


def test_a_drifted_none_is_reset_before_it_wraps() -> None:
    guard = irg.ImmortalRefcountGuard()
    assert guard.active
    with _restored(None) as word:
        word.value = irg.IMMORTAL_INITIAL + irg.DRIFT_LIMIT + 5
        guard.check()
        assert word.value == irg.IMMORTAL_INITIAL
        assert guard.resets == {"None": 1}


def test_a_downward_drift_is_reset_too() -> None:
    """PyAV's abi3 wheels drain True/False instead of inflating them."""
    guard = irg.ImmortalRefcountGuard()
    with _restored(True) as word:
        word.value = irg.IMMORTAL_INITIAL - irg.DRIFT_LIMIT - 5
        guard.check()
        assert word.value == irg.IMMORTAL_INITIAL
        assert guard.resets == {"True": 1}


def test_a_small_drift_is_left_alone() -> None:
    """Writing on every tick would be a needless store into a live object."""
    guard = irg.ImmortalRefcountGuard()
    with _restored(False) as word:
        word.value = irg.IMMORTAL_INITIAL + 1_000
        guard.check()
        assert word.value == irg.IMMORTAL_INITIAL + 1_000
        assert guard.resets == {}


def test_drift_from_real_pyqt_calls_is_reset(qapp, monkeypatch) -> None:
    """The actual leak path: PyQt methods returning None, then the guard."""
    monkeypatch.setattr(irg, "DRIFT_LIMIT", 10_000)
    guard = irg.ImmortalRefcountGuard()
    obj = QObject()
    with _restored(None) as word:
        word.value = irg.IMMORTAL_INITIAL
        for _ in range(50_000):
            obj.setObjectName("x")
        guard.check()
        assert abs(word.value - irg.IMMORTAL_INITIAL) < irg.DRIFT_LIMIT


def test_an_object_that_does_not_read_immortal_is_never_written(monkeypatch) -> None:
    """If the layout reads wrong, the guard must refuse rather than guess."""
    monkeypatch.setattr(irg, "_is_immortal", lambda low: False)
    guard = irg.ImmortalRefcountGuard()
    assert not guard.active
