"""Movie/series mix for recommendation lists — √-damped proportional or explicit.

A capped recommendation list has to decide how many of its slots go to movies and
how many to series.  Two answers live here, behind one resolver:

* **Automatic** (``MEDIA_MIX_AUTOMATIC``) — derive the split from what the user
  actually engages with (liked + favorited + queued + watched), damped by square
  root so a big library-usage gap narrows instead of shutting the smaller type
  out.  100 movies : 15 series → √100 : √15 ≈ 10 : 3.9 → ~72% : 28% → 7 movie /
  3 series in a 10-slot list.  A 50/50 history stays 50/50; a 100/0 history stays
  all-one-type; no history at all falls back to 50/50.
* **Explicit** — a float in 0.0–1.0 (the movie share) set by the user in the
  Recommendations dashboard slider / settings panel; it simply overrides the
  computed share.

Both resolve through :func:`resolve_media_share` to a single number, and
:func:`mix_media_types` is the one place that turns that number into a selected,
interleaved list.  Nothing here scores anything — the caller passes candidates
already ranked by :mod:`metatv.core.preference_engine`.
"""

from __future__ import annotations

import math

from loguru import logger

# Config/engine sentinel: "work the share out from my engagement".
MEDIA_MIX_AUTOMATIC: str = "automatic"

# The only two media types a recommendation list can hold.
_MEDIA_TYPES: tuple[str, ...] = ("movie", "series")

# Nothing engaged with yet → an even split is the least presumptuous start.
_COLD_START_SHARE: float = 0.5


def damped_media_share(movie_signals: float, series_signals: float) -> float:
    """Return the movie share (0.0–1.0) of a list from raw engagement counts.

    Square-root damping keeps the minority type present without pretending the
    user's history is balanced: the share follows the engagement ratio, but a
    10:1 gap in counts becomes a ~3:1 gap in slots.  Ratios at the extremes are
    preserved exactly — an all-movies history returns 1.0, an even one 0.5.

    Args:
        movie_signals: Positive-signal count for movies (never negative).
        series_signals: Positive-signal count for series (never negative).

    Returns:
        The fraction of slots that should go to movies. ``0.5`` when there is no
        engagement at all (cold start).
    """
    m = math.sqrt(max(0.0, float(movie_signals)))
    s = math.sqrt(max(0.0, float(series_signals)))
    if m + s <= 0.0:
        return _COLD_START_SHARE
    return m / (m + s)


def media_engagement_counts(session) -> tuple[int, int]:
    """Count positive engagement signals per media type.

    A "positive signal" is any of: an explicit like, a favorite, a Watch Queue
    entry, or a play (``last_played``).  Signals are summed, not de-duplicated —
    an item the user liked *and* queued *and* watched is three signals, which is
    exactly the strength of preference the mix should reflect.

    Args:
        session: Open SQLAlchemy session.

    Returns:
        ``(movie_count, series_count)``.
    """
    from sqlalchemy import func

    from metatv.core.database import ChannelDB, UserRatingDB, WatchQueueDB

    counts: dict[str, int] = dict.fromkeys(_MEDIA_TYPES, 0)

    def _tally(rows) -> None:
        for media_type, n in rows:
            if media_type in counts:
                counts[media_type] += int(n or 0)

    def _base():
        return (
            session.query(ChannelDB.media_type, func.count(ChannelDB.id))
            .filter(ChannelDB.media_type.in_(_MEDIA_TYPES))
        )

    _tally(
        _base().filter(ChannelDB.is_favorite == True)  # noqa: E712
        .group_by(ChannelDB.media_type).all()
    )
    _tally(
        _base().filter(ChannelDB.last_played.isnot(None))
        .group_by(ChannelDB.media_type).all()
    )
    _tally(
        _base().join(UserRatingDB, UserRatingDB.channel_id == ChannelDB.id)
        .filter(UserRatingDB.rating > 0)
        .group_by(ChannelDB.media_type).all()
    )
    _tally(
        _base().join(WatchQueueDB, WatchQueueDB.channel_id == ChannelDB.id)
        .group_by(ChannelDB.media_type).all()
    )
    return counts["movie"], counts["series"]


def resolve_media_share(session, media_mix) -> float | None:
    """Resolve a media-mix spec to a movie share, or ``None`` for "don't mix".

    Args:
        session: Open SQLAlchemy session (only read for the automatic spec).
        media_mix: ``None`` (no mixing — rank order stands), the string
            ``MEDIA_MIX_AUTOMATIC``, or a float movie share in 0.0–1.0.

    Returns:
        The movie share to use, or ``None`` when no mixing should be applied.
    """
    if media_mix is None:
        return None
    if isinstance(media_mix, str):
        if media_mix.strip().lower() != MEDIA_MIX_AUTOMATIC:
            logger.warning(f"Unknown media_mix spec {media_mix!r} — leaving the mix unchanged")
            return None
        movies, series = media_engagement_counts(session)
        share = damped_media_share(movies, series)
        logger.debug(
            f"Automatic media mix: {movies} movie / {series} series signals → "
            f"{format_media_share(share)}"
        )
        return share
    try:
        return clamp_share(float(media_mix))
    except (TypeError, ValueError):
        logger.warning(f"Invalid media_mix value {media_mix!r} — leaving the mix unchanged")
        return None


def clamp_share(share: float) -> float:
    """Clamp a movie share into the valid 0.0–1.0 range."""
    return min(1.0, max(0.0, float(share)))


def format_media_share(share: float) -> str:
    """Render a movie share as a human ratio label, e.g. ``0.7208`` → ``"72 : 28"``."""
    movie_pct = int(round(clamp_share(share) * 100))
    return f"{movie_pct} : {100 - movie_pct}"


def split_slots(slots: int, movie_share: float, movies_available: int,
                series_available: int) -> tuple[int, int]:
    """Split ``slots`` between movies and series, refilling from what exists.

    The share sets the target; whichever type can't fill its target gives its
    unused slots to the other, so a short candidate pool never shrinks the list.

    Returns:
        ``(movie_slots, series_slots)``.
    """
    if slots <= 0:
        return 0, 0
    n_movie = int(round(slots * clamp_share(movie_share)))
    n_series = slots - n_movie
    if n_movie > movies_available:
        n_series += n_movie - movies_available
        n_movie = movies_available
    if n_series > series_available:
        n_movie = min(movies_available, n_movie + (n_series - series_available))
        n_series = series_available
    return n_movie, n_series


def mix_media_types(scored: list, slots: int, movie_share: float) -> list:
    """Select ``slots`` candidates honoring ``movie_share``, spread through the list.

    Each type keeps its own score order.  Selection takes the top N of each type
    per :func:`split_slots`, then interleaves the two runs by *quota progress* so
    the minority type is spread through the list rather than dumped at the end
    (7 : 3 reads ``M M S M M S M M S M``, not ``M M M M M M M S S S``).  Ties in
    progress are broken by score, so the stronger type leads.

    Args:
        scored: Candidates already sorted by score, descending.
        slots: How many items the caller wants back.
        movie_share: Fraction of slots to give movies (0.0–1.0).

    Returns:
        Up to ``slots`` candidates. When only one media type is present there is
        nothing to mix and the top ``slots`` are returned unchanged.
    """
    if slots <= 0:
        return []
    movies = [s for s in scored if s.media_type == "movie"]
    series = [s for s in scored if s.media_type == "series"]
    if not movies or not series:
        return scored[:slots]

    n_movie, n_series = split_slots(slots, movie_share, len(movies), len(series))
    m_sel, s_sel = movies[:n_movie], series[:n_series]
    if not m_sel or not s_sel:
        return (m_sel or s_sel)[:slots]

    out: list = []
    mi = si = 0
    while mi < len(m_sel) or si < len(s_sel):
        if si >= len(s_sel):
            out.append(m_sel[mi])
            mi += 1
            continue
        if mi >= len(m_sel):
            out.append(s_sel[si])
            si += 1
            continue
        m_progress = (mi + 1) / len(m_sel)
        s_progress = (si + 1) / len(s_sel)
        if m_progress < s_progress:
            take_movie = True
        elif s_progress < m_progress:
            take_movie = False
        else:  # equally far along their quotas — the stronger match leads
            take_movie = m_sel[mi].score >= s_sel[si].score
        if take_movie:
            out.append(m_sel[mi])
            mi += 1
        else:
            out.append(s_sel[si])
            si += 1
    return out
