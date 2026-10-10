"""Other copies of a series, and which seasons each one holds.

A provider's series listing can name seasons it carries no episodes for — the
"4K-SC - Invasion" copy lists Seasons 1-3 but ships only Season 3. The series
tree says so ("Season 1 · not in this copy") and lists the other copies the
user could open instead, each with what is known about that season there.
It never switches on its own: this module only reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from metatv.core.database import ChannelDB, EpisodeDB, SeasonDB


@dataclass(frozen=True)
class SeriesCopy:
    """One other copy of the series on screen.

    Attributes:
        channel_id: The copy's ``ChannelDB.id`` (what opening it drills into).
        prefix: Its ``detected_prefix`` ("EN", "SE"…), for the label.
        provider_id: The source it comes from.
        episodes_by_season: ``{season_num: episode count}`` for seasons whose
            episodes are already stored. Empty when that copy has never been
            opened — its seasons are simply unknown, not missing.
    """

    channel_id: str
    prefix: str | None
    provider_id: str
    episodes_by_season: dict[int, int] = field(default_factory=dict)


def other_copies(session, channel_id: str, hidden_provider_ids) -> list[SeriesCopy]:
    """Every other visible copy of a series (same stored ``content_key``).

    Args:
        session: An open session.
        channel_id: The series copy on screen.
        hidden_provider_ids: Inactive/expired sources — never offered.
    """
    me = session.get(ChannelDB, channel_id)
    if me is None or not me.content_key:
        return []
    rows = (session.query(ChannelDB)
            .filter(ChannelDB.content_key == me.content_key,
                    ChannelDB.id != channel_id,
                    ChannelDB.media_type == "series",
                    ChannelDB.is_hidden == False,  # noqa: E712
                    ChannelDB.provider_id.notin_(list(hidden_provider_ids or [])))
            .all())
    copies = []
    for ch in rows:
        counts: dict[int, int] = {}
        for season in (session.query(SeasonDB)
                       .filter(SeasonDB.series_id == ch.source_id,
                               SeasonDB.provider_id == ch.provider_id).all()):
            n = session.query(EpisodeDB).filter(EpisodeDB.season_id == season.id).count()
            if n:
                counts[season.season_number] = n
        copies.append(SeriesCopy(ch.id, ch.detected_prefix, ch.provider_id, counts))
    return copies
