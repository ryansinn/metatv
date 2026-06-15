"""Behavioral tests for the EPG Events tab (PR-5).

Coverage:
  - ``get_live_events_dto``: repo method against a file-backed DB — fields mapped
    correctly, hidden providers excluded, non-event channels excluded, sentinel →
    always_available=True/start_time=None.
  - ``group_events_timeline`` / ``group_events_by_network``: pure helper functions
    tested directly without any Qt widget.  A fixed ``now`` makes classification
    deterministic.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import LiveEventDTO
from metatv.gui.epg_view import LIVE_EVENT_WINDOW, group_events_timeline, group_events_by_network


# ---------------------------------------------------------------------------
# File-backed DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def file_db():
    """File-backed SQLite Database — required for multi-connection pool correctness."""
    tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmpfile.close()
    db_path = tmpfile.name
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def session(file_db):
    s = file_db.get_session()
    yield s
    s.close()


def _make_provider(session, provider_id: str, *, is_active: bool = True) -> ProviderDB:
    prov = ProviderDB(
        id=provider_id,
        name=f"Provider {provider_id}",
        type="xtream",
        url="http://example.com",
        username="u",
        password="p",
        is_active=is_active,
    )
    session.add(prov)
    session.flush()
    return prov


def _make_live_event_channel(
    session,
    provider_id: str,
    *,
    name: str = "US (Peacock 01) | Some Event (2026-06-15 18:00:00)",
    detected_title: str | None = "Some Event",
    event_start_time: datetime | None = datetime(2026, 6, 15, 18, 0, 0),
    event_metadata: dict | None = None,
    is_hidden: bool = False,
    special_view: str = "live_event",
) -> ChannelDB:
    if event_metadata is None:
        event_metadata = {
            "network": "Peacock",
            "channel_num": "01",
            "region": "US",
            "event_name": "Some Event",
            "availability": "scheduled",
        }
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        detected_title=detected_title,
        media_type="live",
        is_hidden=is_hidden,
        special_view=special_view,
        event_start_time=event_start_time,
        event_metadata=event_metadata,
        stream_url="http://example.com/stream",
    )
    session.add(ch)
    session.flush()
    return ch


# ---------------------------------------------------------------------------
# Tests: get_live_events_dto
# ---------------------------------------------------------------------------

class TestGetLiveEventsDto:
    """Behavioral tests for ChannelRepository.get_live_events_dto."""

    def test_scheduled_event_fields_mapped(self, session):
        """A scheduled live_event channel maps all fields correctly into LiveEventDTO."""
        _make_provider(session, "p1")
        _make_live_event_channel(
            session,
            "p1",
            name="US (Peacock 01) | Some Event (2026-06-15 18:00:00)",
            detected_title="Some Event",
            event_start_time=datetime(2026, 6, 15, 18, 0, 0),
            event_metadata={
                "network": "Peacock",
                "channel_num": "01",
                "region": "US",
                "event_name": "Some Event",
                "availability": "scheduled",
            },
        )
        session.commit()

        repos = RepositoryFactory(session)
        dtos = repos.channels.get_live_events_dto()

        assert len(dtos) == 1
        dto = dtos[0]
        assert isinstance(dto, LiveEventDTO)
        assert dto.network == "Peacock"
        assert dto.channel_num == "01"
        assert dto.region == "US"
        assert dto.detected_title == "Some Event"
        assert dto.start_time == datetime(2026, 6, 15, 18, 0, 0)
        assert dto.always_available is False

    def test_always_available_sentinel_maps_correctly(self, session):
        """A sentinel / always-available channel → always_available=True, start_time=None."""
        _make_provider(session, "p1")
        _make_live_event_channel(
            session,
            "p1",
            name="US (ESPN+ 391) | Some Show (2098-12-31 08:00:01)",
            detected_title="Some Show",
            event_start_time=None,          # parse_platform_event sets None for sentinel
            event_metadata={
                "network": "ESPN+",
                "channel_num": "391",
                "region": "US",
                "event_name": "Some Show",
                "availability": "always",
            },
        )
        session.commit()

        repos = RepositoryFactory(session)
        dtos = repos.channels.get_live_events_dto()

        assert len(dtos) == 1
        assert dtos[0].always_available is True
        assert dtos[0].start_time is None

    def test_hidden_provider_excluded(self, session):
        """Channels on a hidden (inactive) provider must not appear in the DTO list."""
        _make_provider(session, "active_p")
        _make_provider(session, "hidden_p", is_active=False)

        _make_live_event_channel(session, "active_p", name="Active Event")
        _make_live_event_channel(session, "hidden_p", name="Hidden Event")
        session.commit()

        repos = RepositoryFactory(session)
        excluded = set(repos.providers.get_hidden_provider_ids())
        dtos = repos.channels.get_live_events_dto(excluded_provider_ids=excluded)

        channel_names = {d.name for d in dtos}
        assert "Active Event" in channel_names
        assert "Hidden Event" not in channel_names

    def test_non_event_channel_excluded(self, session):
        """Channels with special_view != 'live_event' (or NULL) must not appear."""
        _make_provider(session, "p1")
        _make_live_event_channel(session, "p1", name="Real Event")
        _make_live_event_channel(
            session, "p1",
            name="Regular Channel",
            special_view=None,             # normal live channel, no special_view
            event_start_time=None,
            event_metadata=None,
        )
        session.commit()

        repos = RepositoryFactory(session)
        dtos = repos.channels.get_live_events_dto()

        channel_names = {d.name for d in dtos}
        assert "Real Event" in channel_names
        assert "Regular Channel" not in channel_names

    def test_hidden_channel_excluded(self, session):
        """A live_event channel with is_hidden=True must not appear in results."""
        _make_provider(session, "p1")
        _make_live_event_channel(session, "p1", name="Visible Event", is_hidden=False)
        _make_live_event_channel(session, "p1", name="Hidden Event", is_hidden=True)
        session.commit()

        repos = RepositoryFactory(session)
        dtos = repos.channels.get_live_events_dto()

        channel_names = {d.name for d in dtos}
        assert "Visible Event" in channel_names
        assert "Hidden Event" not in channel_names

    def test_availability_field_drives_always_available(self, session):
        """availability='always' (even with a non-None start_time) → always_available=True."""
        _make_provider(session, "p1")
        # Some rows might have a non-None start_time but availability=='always'
        _make_live_event_channel(
            session,
            "p1",
            event_start_time=datetime(2098, 12, 31, 8, 0, 1),  # sentinel timestamp kept
            event_metadata={
                "network": "BTN+",
                "channel_num": "01",
                "region": "CA",
                "event_name": "Test",
                "availability": "always",
            },
        )
        session.commit()

        repos = RepositoryFactory(session)
        dtos = repos.channels.get_live_events_dto()

        assert len(dtos) == 1
        # availability='always' → always_available regardless of stored start_time
        assert dtos[0].always_available is True


# ---------------------------------------------------------------------------
# Tests: group_events_timeline (pure function)
# ---------------------------------------------------------------------------

class TestGroupEventsTimeline:
    """Timeline grouping logic against a fixed reference time."""

    def _dto(self, start_time, always=False, network="Peacock"):
        return LiveEventDTO(
            channel_id=str(uuid.uuid4()),
            name="Test Event",
            detected_title="Test Event",
            network=network,
            region="US",
            channel_num="01",
            start_time=start_time,
            always_available=always,
        )

    def test_on_now_event_in_active_group(self):
        """An event that started 1 hour ago falls in the on-now/upcoming group."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto = self._dto(now - timedelta(hours=1))
        active, always, passed = group_events_timeline([dto], now)
        assert dto in active
        assert dto not in always
        assert dto not in passed

    def test_upcoming_event_in_active_group(self):
        """An event starting in 2 hours is also in the active (upcoming) group."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto = self._dto(now + timedelta(hours=2))
        active, always, passed = group_events_timeline([dto], now)
        assert dto in active

    def test_passed_event_outside_window(self):
        """An event older than LIVE_EVENT_WINDOW falls in the passed group."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto = self._dto(now - LIVE_EVENT_WINDOW - timedelta(seconds=1))
        active, always, passed = group_events_timeline([dto], now)
        assert dto in passed
        assert dto not in active

    def test_always_available_in_always_group(self):
        """A sentinel/always-available DTO falls in the always group."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto = self._dto(None, always=True)
        active, always_list, passed = group_events_timeline([dto], now)
        assert dto in always_list
        assert dto not in active
        assert dto not in passed

    def test_active_sorted_ascending(self):
        """Active events are sorted ascending by start_time (soonest first)."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto_later = self._dto(now + timedelta(hours=3))
        dto_sooner = self._dto(now - timedelta(hours=1))
        active, _, _ = group_events_timeline([dto_later, dto_sooner], now)
        assert active[0] is dto_sooner
        assert active[1] is dto_later

    def test_passed_sorted_most_recent_first(self):
        """Passed events are sorted most-recent-first."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto_older = self._dto(now - LIVE_EVENT_WINDOW - timedelta(hours=5))
        dto_recent = self._dto(now - LIVE_EVENT_WINDOW - timedelta(seconds=1))
        _, _, passed = group_events_timeline([dto_older, dto_recent], now)
        assert passed[0] is dto_recent   # most-recent first
        assert passed[1] is dto_older

    def test_network_filter_narrows_results(self):
        """network_filter='ESPN+' excludes events on other networks."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto_espn = self._dto(now, network="ESPN+")
        dto_nbc = self._dto(now, network="NBC")
        active, _, _ = group_events_timeline([dto_espn, dto_nbc], now, "ESPN+")
        assert dto_espn in active
        assert dto_nbc not in active

    def test_network_filter_all_includes_everything(self):
        """network_filter='All' includes events from all networks."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto_a = self._dto(now, network="A")
        dto_b = self._dto(now, network="B")
        active, _, _ = group_events_timeline([dto_a, dto_b], now, "All")
        assert len(active) == 2


# ---------------------------------------------------------------------------
# Tests: group_events_by_network (pure function)
# ---------------------------------------------------------------------------

class TestGroupEventsByNetwork:
    """By-Network grouping logic."""

    def _dto(self, network: str, start_time=None, always: bool = False) -> LiveEventDTO:
        return LiveEventDTO(
            channel_id=str(uuid.uuid4()),
            name="Test",
            detected_title="Test",
            network=network,
            region="US",
            channel_num="01",
            start_time=start_time,
            always_available=always,
        )

    def test_events_grouped_by_network(self):
        """Events from two networks appear in separate groups."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto_e = self._dto("ESPN+", now)
        dto_p = self._dto("Peacock", now)
        groups = group_events_by_network([dto_e, dto_p], now)
        assert "ESPN+" in groups
        assert "Peacock" in groups

    def test_network_groups_sorted_alphabetically(self):
        """Network keys are sorted alphabetically."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dtos = [self._dto("Peacock", now), self._dto("BTN+", now), self._dto("ESPN+", now)]
        groups = group_events_by_network(dtos, now)
        assert list(groups.keys()) == ["BTN+", "ESPN+", "Peacock"]

    def test_network_group_order_active_always_passed(self):
        """Within a network, events are ordered: active → always → passed."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        active_dto = self._dto("ESPN+", now - timedelta(hours=1))
        always_dto = self._dto("ESPN+", always=True)
        passed_dto = self._dto("ESPN+", now - LIVE_EVENT_WINDOW - timedelta(hours=1))
        groups = group_events_by_network([passed_dto, always_dto, active_dto], now)
        active, always_list, passed = groups["ESPN+"]
        assert active_dto in active
        assert always_dto in always_list
        assert passed_dto in passed

    def test_network_filter_applied_in_by_network_mode(self):
        """A network filter reduces the result to only the specified network."""
        now = datetime(2026, 6, 15, 18, 0, 0)
        dto_e = self._dto("ESPN+", now)
        dto_p = self._dto("Peacock", now)
        groups = group_events_by_network([dto_e, dto_p], now, "ESPN+")
        assert "ESPN+" in groups
        assert "Peacock" not in groups
