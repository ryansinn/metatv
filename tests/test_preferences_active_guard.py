"""PreferencesView.refresh() runs only while the view is active.

Before the guard, every provider/enrichment cascade ran the FULL preference
engine (compute_weights + score_candidates over the whole corpus) for a
dashboard nobody had open — its ``_bg_refresh`` appeared in nearly every stall
sample of the owner's 2026-09-03 launches. And because ``on_deactivate`` shuts
the pool down without recreating it, re-opening the view submitted to a dead
executor. Both behaviors are pinned here.

The double is a ``__new__`` shell carrying ONLY the attributes the real
``refresh``/``on_deactivate`` bodies touch, all placed in ``__dict__`` so Qt's
attribute resolution never runs (the repo's skeleton-host rule).
"""

from metatv.gui.preferences_view import PreferencesView


class _Recorder:
    def __init__(self):
        self.submits = []
        self.shutdowns = []

    def submit(self, fn, *a, **k):
        self.submits.append(fn)

    def shutdown(self, **k):
        self.shutdowns.append(k)


class _Label:
    def __init__(self):
        self.texts = []

    def setText(self, t):
        self.texts.append(t)


def _shell(active: bool, executor) -> PreferencesView:
    view = PreferencesView.__new__(PreferencesView)
    view.__dict__["_active"] = active
    view.__dict__["_executor"] = executor
    view.__dict__["_header_label"] = _Label()
    return view


def test_refresh_is_a_no_op_while_inactive():
    ex = _Recorder()
    view = _shell(active=False, executor=ex)

    view.refresh()

    assert ex.submits == [], "a hidden Preferences view must not run the engine"
    assert view._header_label.texts == [], "no loading header on a closed view"


def test_refresh_submits_while_active():
    ex = _Recorder()
    view = _shell(active=True, executor=ex)

    view.refresh()

    assert len(ex.submits) == 1
    assert view._header_label.texts == ["Loading recommendations…"]


def test_reactivation_rebuilds_the_shutdown_pool(monkeypatch):
    """activate → deactivate → activate must not submit to a dead executor."""
    from metatv.gui import preferences_view as mod

    built = []

    class _Factory:
        def __init__(self, max_workers):
            built.append(self)
            self.submits = []

        def submit(self, fn, *a, **k):
            self.submits.append(fn)

    monkeypatch.setattr(mod, "ThreadPoolExecutor", _Factory)

    ex = _Recorder()
    view = _shell(active=True, executor=ex)
    view.on_deactivate()
    assert ex.shutdowns and view._executor is None, (
        "deactivate must shut the pool down AND null it"
    )

    view.__dict__["_active"] = True  # what on_activate sets before refresh()
    view.refresh()

    assert len(built) == 1 and built[0].submits, (
        "reactivation must rebuild the pool and submit — pre-fix this raised "
        "on the shutdown executor"
    )
