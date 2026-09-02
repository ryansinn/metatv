"""Clicking OK in Settings must not re-filter 785,551 rows twice.

Measured 2026-09-02: the main-thread watchdog reported **27,050 ms** and
subtracting it lands exactly on "Settings saved" — the OK click starts it.
Eleven handlers fire on ``settings_applied``, synchronously, on the main thread,
and TWO of them independently called ``load_channels()``. One OK therefore re-ran
the whole channel filter twice, whether or not anything relevant had changed.

The eleven were eleven separate Qt connections with a comment warning that a
hand-written tail had once repeated three of five and silently dropped the rest.
They are now one ordered list in one place — which is the same single
enumeration, but one that can be timed, guarded, and reloaded once.

The negative test matters most here: a handler that raises must not take the
remaining handlers with it. As separate connections it could not; as a single
slot it would, and that would be a regression bought with a performance fix.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from metatv.gui import settings_apply


# ── the list is the list ─────────────────────────────────────────────────────

def test_every_handler_name_resolves_on_mainwindow():
    """The connect lines checked this by crashing at startup; a list of strings
    has to be checked on purpose, or a rename becomes a silent no-op."""
    from metatv.gui.main_window import MainWindow

    missing = [n for n in settings_apply.HANDLERS if not hasattr(MainWindow, n)]
    assert not missing, f"settings_apply.HANDLERS names nothing: {missing}"


def test_the_list_has_no_duplicates():
    """A duplicate is a handler run twice — the shape of the bug being fixed."""
    assert len(settings_apply.HANDLERS) == len(set(settings_apply.HANDLERS))


def test_the_list_still_covers_all_eleven():
    """A guard against silently losing one while editing the tuple. If a
    handler is deliberately added or removed, change this number in the same
    commit — that is the point."""
    assert len(settings_apply.HANDLERS) == 11


# ── running them ─────────────────────────────────────────────────────────────

def _host(handlers=None, reloads=None):
    """A host that records the order it was called in."""
    calls = reloads if reloads is not None else []
    host = SimpleNamespace(load_channels=lambda: calls.append("load_channels"))
    for name in (handlers if handlers is not None else settings_apply.HANDLERS):
        setattr(host, name, (lambda n: lambda: calls.append(n))(name))
    host._calls = calls
    return host


def _requesting(host, name):
    """A handler that records itself and then asks for a reload."""
    def handler():
        host._calls.append(name)
        settings_apply.request_channel_reload(host)
    return handler


def test_every_handler_runs_once_and_in_order():
    host = _host()
    settings_apply.run(host)
    assert host._calls == list(settings_apply.HANDLERS)


def test_the_result_reports_a_time_for_each():
    """Returned rather than only logged, so a test can see the list ran."""
    host = _host()
    timings = settings_apply.run(host)
    assert set(timings) >= set(settings_apply.HANDLERS)
    assert all(ms >= 0 for ms in timings.values())


def test_a_missing_handler_is_loud_and_the_rest_still_run():
    """A partially-built host, or a rename. Neither should silently skip nine
    other handlers."""
    host = _host()
    delattr(host, settings_apply.HANDLERS[0])
    settings_apply.run(host)
    assert host._calls == list(settings_apply.HANDLERS[1:])


def test_one_raising_handler_does_not_take_out_the_others():
    """As eleven Qt connections a raise could not stop the rest. As one slot it
    would — so isolation is what makes the collapse safe."""
    host = _host()
    boom = settings_apply.HANDLERS[3]

    def explode():
        host._calls.append(boom)
        raise RuntimeError("boom")

    setattr(host, boom, explode)
    settings_apply.run(host)
    assert host._calls == list(settings_apply.HANDLERS)


# ── the reload, which is the 27 seconds ──────────────────────────────────────

def test_two_handlers_asking_for_a_reload_produce_exactly_one():
    """The bug, stated as an invariant."""
    host = _host()
    for name in ("_apply_adult_mode_setting", "_apply_collapse_variants_setting"):
        setattr(host, name, _requesting(host, name))
    settings_apply.run(host)
    assert host._calls.count("load_channels") == 1


def test_the_single_reload_happens_after_every_handler():
    """Reloading mid-pass would read half-applied settings — the adult-mode
    handler writes into the filter bar that the reload then reads."""
    host = _host()
    setattr(host, settings_apply.HANDLERS[0],
            _requesting(host, settings_apply.HANDLERS[0]))
    settings_apply.run(host)
    assert host._calls[-1] == "load_channels"


def test_no_reload_at_all_when_nobody_asks():
    """Most settings do not change the row SET. They should cost no requery."""
    host = _host()
    settings_apply.run(host)
    assert "load_channels" not in host._calls


def test_outside_a_settings_pass_the_request_is_immediate():
    """Both requesting handlers are also reachable from ordinary UI actions,
    where there is no pass to coalesce into and deferring would just lose it."""
    host = _host()
    assert settings_apply.request_channel_reload(host) is True
    assert host._calls == ["load_channels"]


def test_the_latch_is_cleared_even_if_a_handler_explodes():
    """A stuck latch would swallow every later reload in the app's lifetime."""
    host = _host()

    def explode():
        raise RuntimeError("boom")

    setattr(host, settings_apply.HANDLERS[0], explode)
    settings_apply.run(host)
    assert settings_apply.request_channel_reload(host) is True


# ── the wiring ───────────────────────────────────────────────────────────────

SRC = (pathlib.Path(__file__).resolve().parent.parent
       / "metatv" / "gui" / "main_window.py").read_text()


def test_the_dialog_connects_one_slot_rather_than_eleven():
    assert SRC.count("dialog.settings_applied.connect") == 1, (
        "the eleven separate connections are back — they cannot be ordered, "
        "timed, or coalesced")
    assert "_settings_apply.run(self)" in SRC


@pytest.mark.parametrize("handler", [
    "_apply_adult_mode_setting", "_apply_collapse_variants_setting",
])
def test_the_reloading_handlers_ask_rather_than_force(handler):
    body = SRC[SRC.index(f"def {handler}"):]
    body = body[:body.index("\n    def ", 1)]
    assert "self.load_channels()" not in body, (
        f"{handler} forces a reload again — two of these in one OK is the "
        "double requery this replaced")
    assert "_settings_apply.request_channel_reload(self)" in body
