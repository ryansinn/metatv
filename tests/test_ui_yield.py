"""yield_to_ui hands the GIL over periodically, and only off the main thread."""
import threading
import time

from metatv.core import ui_yield


def test_it_sleeps_every_n_items_off_the_main_thread(monkeypatch):
    slept = []
    monkeypatch.setattr(ui_yield.time, "sleep", lambda s: slept.append(s))
    t = threading.Thread(target=lambda: [ui_yield.yield_to_ui(i, every=10) for i in range(35)])
    t.start()
    t.join()
    assert len(slept) == 3, "at 10, 20 and 30 — never at 0"


def test_it_never_sleeps_on_the_main_thread(monkeypatch):
    monkeypatch.setattr(ui_yield.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError))
    for i in range(3000):
        ui_yield.yield_to_ui(i)
    assert time is ui_yield.time
