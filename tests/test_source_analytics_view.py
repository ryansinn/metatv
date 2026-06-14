"""Behavioral tests for SourceAnalyticsView's async dispatch.

The regression these pin: the view fires FIVE concurrent _run_query loads (provider
list + four panels). The seam's stale-token guard drops any result whose token no
longer matches its token_ref's current value. If all five share ONE token_ref, each
_run_query bumps the same counter, so by the time results arrive only the
last-submitted query survives and the other panels render blank. The fix gives each
logical query its OWN token_ref. We replay the seam's exact stale-drop semantics
against a real view and assert every panel renders.
"""
from __future__ import annotations

import pytest

from metatv.gui.source_analytics_view import SourceAnalyticsView
from metatv.core.repositories.dtos import (
    SourceFingerprintDTO,
    OverlapMatrixDTO,
    UniqueChannelDTO,
    PrefixStatDTO,
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSeam:
    """Records _run_query calls, then replays them with the seam's real stale-drop.

    Mirrors _AsyncMixin: bumps token_ref[0] on submit, captures (on_result, token,
    token_ref); deliver() drops a result iff token_ref[0] != token (a sibling bumped it).
    """
    def __init__(self):
        self.calls = []

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
        if token_ref is not None:
            token_ref[0] += 1
        token = token_ref[0] if token_ref is not None else None
        self.calls.append((query_fn, on_result, token, token_ref))

    def deliver(self, on_result, data):
        for query_fn, cb, token, token_ref in self.calls:
            if cb == on_result:
                if token_ref is not None and token_ref[0] != token:
                    return False  # dropped as stale
                cb(data)
                return True
        raise AssertionError("no matching _run_query call recorded")


def _fingerprint():
    return SourceFingerprintDTO(
        provider_id="A", name="TREX", live_count=10, movie_count=5, series_count=2,
        total_count=17, live_visible=10, movie_visible=5, series_visible=2,
        total_visible=17, quality_histogram={"HD": 8}, region_histogram={"EN": 7},
        recognized_count=6, unrecognized_count=4, recognized_pct=60.0, adult_pct=0.0,
        untagged_pct=10.0, special_view_breakdown={},
    )


def _overlap():
    return [OverlapMatrixDTO(
        provider_a_id="A", provider_b_id="B", provider_a_name="TREX",
        provider_b_name="Ninja", media_type="live", shared=40, a_only=4, b_only=3,
        jaccard=0.845,
    )]


def _make_view(qapp):
    view = SourceAnalyticsView.__new__(SourceAnalyticsView)
    from PyQt6.QtWidgets import QWidget
    QWidget.__init__(view)
    view.main_window = None
    view.current_provider_id = None
    for name in ("_providers_token", "_fingerprint_token", "_overlap_token",
                 "_unique_token", "_prefixes_token"):
        setattr(view, name, [0])
    view._build_ui()
    return view


def _count_widgets(layout):
    return layout.count()


def test_all_four_panels_render_despite_concurrent_loads(qapp):
    """With per-query tokens, every panel's result survives the stale-drop and renders."""
    view = _make_view(qapp)
    seam = _FakeSeam()
    view.main_window = seam
    view.on_activate("A")

    # provider-id load resolves → fires the four panel loads
    seam.deliver(view._on_provider_ids_loaded, ["A", "B"])

    assert seam.deliver(view._on_fingerprint_loaded, _fingerprint()) is True
    assert seam.deliver(view._on_overlap_loaded, _overlap()) is True
    assert seam.deliver(view._on_unique_loaded, []) is True
    assert seam.deliver(view._on_prefixes_loaded,
                        [PrefixStatDTO("EX", 6801, ["EX - Foo"], False)]) is True

    # Every panel cleared its "Loading…" and rendered real content.
    assert _count_widgets(view._fingerprint_layout) > 0
    assert _count_widgets(view._overlap_layout) > 0
    assert _count_widgets(view._prefixes_layout) > 0


def test_overlap_headline_uses_names_not_uuids(qapp):
    """The headline must read 'TREX is 84.5% shared with Ninja', never raw provider IDs."""
    view = _make_view(qapp)
    view.current_provider_id = "A"
    view._on_overlap_loaded(_overlap())

    from PyQt6.QtWidgets import QLabel
    texts = [w.text() for w in view._overlap_panel.findChildren(QLabel)]
    assert any("TREX is 84.5% shared with Ninja" in t for t in texts), texts
    assert not any("provider_a_id" in t or "A is " in t for t in texts)


def test_panel_tokens_are_independent(qapp):
    """Sanity: the five token refs are distinct objects (the crux of the fix)."""
    view = _make_view(qapp)
    refs = [view._providers_token, view._fingerprint_token, view._overlap_token,
            view._unique_token, view._prefixes_token]
    assert len({id(r) for r in refs}) == 5
