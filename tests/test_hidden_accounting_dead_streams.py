"""Behavioral tests for dead-stream accounting in the channel-list hidden-content

audit (wave6/hidden-accounting).

Diagnosed gap: the channel list hides content through five predicates but only
two were counted and revealable (Global Exclusions / search filters). This adds
a third, symmetric layer for the dead-stream gate — channels whose
``StreamRetryDB.reliability_state`` has graduated to "dead" (repeated play
failures) — so it is counted (``hidden_by_dead``) and recoverable
(``include_dead`` on the list-query path, the ⚠ gold-bar segment,
``_show_dead_hidden``) exactly like the existing two layers (mirror-not-cage).

The provider category-header ("##...") junk-row filter stays deliberately
UNcounted/UNrevealable — it drops provider label rows, not content — so this
suite also asserts a junk row never leaks into any of the counts or results.

These tests drive the real query path (``_ChannelListMixin._query_channels``
against a file-backed DB, per CLAUDE.md) and the gold-bar breakdown renderer.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, ProviderDB, StreamRetryDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.main_window_channels import _ChannelListMixin
from tests.conftest import channel_query_params


# ---------------------------------------------------------------------------
# Fixtures — file-backed DB (CLAUDE.md: never :memory:)
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def session(file_db):
    s = file_db.get_session()
    # Active, non-expired provider so channels aren't scoped out by
    # get_hidden_provider_ids (the canonical provider gate _query_channels
    # applies before the dead-stream layer under test here).
    s.add(ProviderDB(
        id="p1", name="Test Source", type="xtream", url="http://example",
        is_active=True, account_status="Active",
    ))
    s.commit()
    yield s
    s.close()


def _ch(session, name: str, *, provider_id: str = "p1", media_type: str = "movie") -> str:
    """Insert a minimal visible ChannelDB and return its id."""
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=False,
        detected_title=name,
    )
    session.add(ch)
    session.flush()
    return ch.id


def _mark_dead(session, channel_id: str) -> None:
    """Graduate a channel to reliability_state='dead' (repeated play failures)."""
    session.add(StreamRetryDB(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        channel_name="dead",
        reliability_state="dead",
        play_fail_count=6,
    ))


# ---------------------------------------------------------------------------
# Layer 3 — dead-stream gate: hidden_by_dead
# ---------------------------------------------------------------------------

class TestHiddenByDead:
    def test_default_query_excludes_dead_and_junk_counts_only_dead(self, session):
        """One normal, one dead, one '##' junk row: default query returns only the
        normal row; hidden_by_dead counts exactly the dead row (never the junk
        row, which is a deliberately-uncounted provider-junk drop)."""
        repos = RepositoryFactory(session)
        normal_id = _ch(session, "Normal Channel")
        dead_id = _ch(session, "Flaky Channel")
        _mark_dead(session, dead_id)
        _ch(session, "##### BEIN SPORTS #####")  # provider category-header junk
        session.commit()

        params = channel_query_params()
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert [d.id for d in dtos] == [normal_id], \
            "only the non-dead, non-junk channel survives the default query"
        assert out["hidden_by_dead"] == 1, "exactly the dead row is counted, not the junk row"
        assert out["hidden_by_exclusions"] == 0
        assert out["hidden_by_search"] == 0

    def test_junk_row_never_appears_in_results_or_counts(self, session):
        """The '##' junk row is dropped unconditionally — it never shows up in the
        surviving set nor inflates ANY of the transparency counts, with or without
        the dead-gate reveal."""
        repos = RepositoryFactory(session)
        normal_id = _ch(session, "Normal Channel")
        junk_id = _ch(session, "##### BEIN SPORTS #####")
        session.commit()

        for bypass in (False, True):
            params = channel_query_params(bypass_dead_gate=bypass)
            dtos, out = _ChannelListMixin._query_channels(repos, params)
            ids = [d.id for d in dtos]
            assert junk_id not in ids, f"junk row must never appear (bypass_dead_gate={bypass})"
            assert normal_id in ids
            assert out["hidden_by_dead"] == 0, "no dead rows in this seed"
            assert out["hidden_by_exclusions"] == 0
            assert out["hidden_by_search"] == 0

    def test_include_dead_bypass_reveals_dead_row_and_zeroes_count(self, session):
        """bypass_dead_gate=True → both rows visible, hidden_by_dead == 0 (nothing
        further hidden by this layer once it's revealed for the view)."""
        repos = RepositoryFactory(session)
        normal_id = _ch(session, "Normal Channel")
        dead_id = _ch(session, "Flaky Channel")
        _mark_dead(session, dead_id)
        session.commit()

        params = channel_query_params(bypass_dead_gate=True)
        dtos, out = _ChannelListMixin._query_channels(repos, params)

        assert {d.id for d in dtos} == {normal_id, dead_id}, \
            "the dead-gate reveal surfaces the dead channel alongside the normal one"
        assert out["hidden_by_dead"] == 0, "layer already revealed — nothing further to report"
        # The revealed dead row keeps its degraded/dim styling via reliability_state.
        dead_dto = next(d for d in dtos if d.id == dead_id)
        assert dead_dto.reliability_state == "dead"


# ---------------------------------------------------------------------------
# Reveal handler — sets the view-scoped bypass flag, never stored settings
# ---------------------------------------------------------------------------

class TestShowDeadHidden:
    def test_sets_flag_and_reloads_without_touching_other_bypasses(self):
        host = _ChannelListMixin()
        host._bypass_tier1_filters = False
        host._bypass_global_exclusions = False
        host._bypass_dead_gate = False
        host.load_channels = MagicMock()

        host._show_dead_hidden()

        assert host._bypass_dead_gate is True
        assert host._bypass_tier1_filters is False
        assert host._bypass_global_exclusions is False
        host.load_channels.assert_called_once()


# ---------------------------------------------------------------------------
# Gold-bar breakdown renderer — three segments, each shown only when > 0
# ---------------------------------------------------------------------------

class TestBreakdownRendererThreeSegments:
    def _host(self, qapp):
        from PyQt6.QtWidgets import QWidget, QPushButton
        host = _ChannelListMixin()
        host._channel_filter_bar = QWidget()
        host._channel_exclusion_btn = QPushButton()
        host._channel_filter_btn = QPushButton()
        host._channel_dead_btn = QPushButton()
        return host

    def test_only_dead_segment_when_only_dead_hidden(self, qapp):
        host = self._host(qapp)
        host._show_channel_filter_breakdown(hidden_by_dead=3)
        assert not host._channel_exclusion_btn.isVisible()
        assert not host._channel_filter_btn.isVisible()
        assert host._channel_dead_btn.isVisible()
        assert host._channel_filter_bar.isVisible()
        assert "3" in host._channel_dead_btn.text()
        assert "unavailable" in host._channel_dead_btn.text()
        assert "repeated play failures" in host._channel_dead_btn.text()

    def test_all_three_segments_shown_with_correct_text_when_all_nonzero(self, qapp):
        host = self._host(qapp)
        host._show_channel_filter_breakdown(
            hidden_by_exclusions=4, hidden_by_search=7, hidden_by_dead=2
        )
        assert host._channel_exclusion_btn.isVisible()
        assert host._channel_filter_btn.isVisible()
        assert host._channel_dead_btn.isVisible()
        assert host._channel_filter_bar.isVisible()

        assert "4" in host._channel_exclusion_btn.text()
        assert "Global Exclusions" in host._channel_exclusion_btn.text()

        assert "7" in host._channel_filter_btn.text()
        assert "search filters" in host._channel_filter_btn.text().lower()

        assert "2" in host._channel_dead_btn.text()
        assert "unavailable" in host._channel_dead_btn.text()
        assert "repeated play failures" in host._channel_dead_btn.text()

    def test_bar_hidden_when_nothing_hidden(self, qapp):
        host = self._host(qapp)
        host._channel_filter_bar.setVisible(True)
        host._show_channel_filter_breakdown()
        assert not host._channel_exclusion_btn.isVisible()
        assert not host._channel_filter_btn.isVisible()
        assert not host._channel_dead_btn.isVisible()
        assert not host._channel_filter_bar.isVisible()
