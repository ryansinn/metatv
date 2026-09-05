"""Column-only recommendation-candidate feed (PERF-21a).

``preference_engine.score_candidates`` used to materialise a full ``ChannelDB``
ORM instance for every movie/series candidate — up to 786k on the owner's
library — via ``candidates_q.options(defer(ChannelDB.raw_data)).all()``, then a
second chunked ``MetadataDB`` ``IN (...)`` query, then read ~10 instrumented
attributes per row both in its own scoring loop and in
``content_dedup.build_dedup_key``. Every one of those reads is a descriptor
call holding the GIL. Worklog PERF-21's worst measured stall was 7,314 ms with
the main thread frozen mid-paint while a worker ran exactly this path; a
launch the next morning sampled the same family — an executor thread inside
``orm/loading.py:_instance`` while the main thread painted.

CLAUDE.md's DTO-boundary rule ("ORM objects must not outlive their session —
cross the boundary with a DTO") was breached inside the scoring path itself.
This module is that crossing: :func:`fetch_candidates` replaces BOTH queries
with ONE column-only statement — ``session.query(<explicit columns>)``, never
``query(ChannelDB)`` — returning plain :class:`Candidate` rows.

The channel→metadata join is 1:1 (``MetadataDB.id`` is a primary key, so a
channel's ``metadata_id`` can match at most one row) — it cannot fan out the
way a one-to-many join would, so folding it into the same statement is safe.
That also removes the entire reason the old metadata lookup needed
``sql_batching.fetch_in_chunks``: there is no longer a per-candidate
``IN (...)`` list to bind past SQLite's compiled bound-parameter ceiling (see
``tests/test_recommendations_scale.py``, which is what caught that bug
originally) — this statement has no such list at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metatv.core.channel_visibility import VisibilityScope


@dataclass(frozen=True, slots=True)
class Candidate:
    """One column-only recommendation candidate: a ChannelDB row joined 1:1 to
    its MetadataDB row.

    Carries EXACTLY the fields ``preference_engine.score_candidates`` (and its
    helpers — ``content_dedup.build_dedup_key``/``director_key``/
    ``extract_year``, and ``preference_engine.version_score`` via the
    ``version_scorer`` callback) read per candidate. Field names mirror the
    source columns on purpose: ``content_dedup.build_dedup_key(channel, meta)``
    reads ``channel.*`` off its first argument and ``meta.*`` off its second
    via plain attribute access with no ORM-specific behavior, and both
    "sides" live on this one flattened object, so ``build_dedup_key(candidate,
    candidate)`` works unmodified — the same function keeps serving the ORM
    callers (``build_engaged_normalized``, the Similar-titles path in
    ``repositories/channel.py``) untouched.

    Built by :func:`fetch_candidates` inside a session — no ORM instance
    crosses the session boundary (CLAUDE.md "ORM objects must not outlive
    their session").
    """

    # ChannelDB fields
    id: str
    name: str
    media_type: str | None
    provider_id: str
    detected_prefix: str | None
    detected_region: str | None
    detected_quality: str | None
    detected_year: str | None
    detected_title: str | None
    content_key: str | None
    last_played: datetime | None
    rec_shown_count: int | None
    # MetadataDB fields — the join partner, 1:1 on metadata_id == MetadataDB.id.
    # genres/cast are JSONEncoded columns: the TypeDecorator's
    # process_result_value already decodes them at the Core level, so these
    # arrive as plain Python list/dict — no different from an ORM read.
    genres: list | None
    cast: list | None
    plot: str | None
    director: str | None
    poster_url: str | None
    rating: float | None
    year: int | None


def fetch_candidates(session, scope: "VisibilityScope") -> list[Candidate]:
    """Column-only feed of movie/series candidates, visibility applied.

    Same filters/joins ``score_candidates``'s old ``candidates_q`` applied —
    moved here verbatim, not paraphrased: movie/series only, not
    rec-suppressed, must carry metadata (now an INNER JOIN rather than an
    ``.isnot(None)`` filter plus a second query — a candidate whose
    ``metadata_id`` has no matching ``MetadataDB`` row is silently dropped by
    the join, the same outcome the old code got from its ``if not meta:
    continue`` guard), every visibility axis in *scope* via the single
    ``channel_visibility.apply()`` chokepoint (provider scoping, is_hidden,
    the prefix/keyword Global-Exclusion axes, user-category, content-type
    provenance, and the adult-content gate — see that module for the
    "Recommendations ignores global exclusions" history). ``raw_data`` is
    simply never in the column list — nothing on the scoring path reads it.

    Args:
        session: Open SQLAlchemy session.
        scope: Resolved ``VisibilityScope`` — the caller (``score_candidates``)
            builds it from ``recommendation_scope()``'s output; this function
            never reads ``Config``.

    Returns:
        One :class:`Candidate` per (channel, metadata) pair, unordered — the
        caller ranks by score.
    """
    query = _build_candidates_query(session, scope)

    candidates: list[Candidate] = []
    for (cid, name, media_type, provider_id, detected_prefix, detected_region,
         detected_quality, detected_year, detected_title, content_key,
         last_played, rec_shown_count, genres, cast, plot, director,
         poster_url, rating, year) in query.all():
        candidates.append(Candidate(
            id=cid, name=name, media_type=media_type, provider_id=provider_id,
            detected_prefix=detected_prefix, detected_region=detected_region,
            detected_quality=detected_quality, detected_year=detected_year,
            detected_title=detected_title, content_key=content_key,
            last_played=last_played, rec_shown_count=rec_shown_count,
            genres=genres, cast=cast, plot=plot, director=director,
            poster_url=poster_url, rating=rating, year=year,
        ))
    return candidates


def _build_candidates_query(session, scope: "VisibilityScope"):
    """The column-only ``Query`` object :func:`fetch_candidates` executes.

    Split out so a test can inspect the REAL statement (``column_descriptions``,
    the compiled SQL) rather than a hand-reconstructed lookalike — the same
    reasoning as the AST-based style/URL-cycling drift guards elsewhere in this
    project: a guard on a reconstruction proves the reconstruction is correct,
    not that the production code is.
    """
    from metatv.core import channel_visibility
    from metatv.core.database import ChannelDB, MetadataDB

    query = (
        session.query(
            ChannelDB.id,
            ChannelDB.name,
            ChannelDB.media_type,
            ChannelDB.provider_id,
            ChannelDB.detected_prefix,
            ChannelDB.detected_region,
            ChannelDB.detected_quality,
            ChannelDB.detected_year,
            ChannelDB.detected_title,
            ChannelDB.content_key,
            ChannelDB.last_played,
            ChannelDB.rec_shown_count,
            MetadataDB.genres,
            MetadataDB.cast,
            MetadataDB.plot,
            MetadataDB.director,
            MetadataDB.poster_url,
            MetadataDB.rating,
            MetadataDB.year,
        )
        .join(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        .filter(
            ChannelDB.media_type.in_(["movie", "series"]),
            ChannelDB.is_rec_suppressed == False,  # noqa: E712
        )
    )
    return channel_visibility.apply(query, scope, channel_cls=ChannelDB)
