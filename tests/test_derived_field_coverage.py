"""W-0: derived-field coverage guard — catches the CLASS, not the instance.

The failure this closes
------------------------
Four fields shipped reading a raw-payload key that does not exist for one
whole ``media_type`` population, and nothing measured coverage after the
write:

* ``ChannelDB.detected_added`` — NULL for 0 of 127,679 series (100% of
  movies/live populated). The series payload sends ``last_modified``;
  ``XtreamAPI.convert_to_channel`` reads only ``added``.
* ``MetadataDB.runtime`` — non-null on 48,281 rows, all series, 0 of 525,616
  movies. The movie LIST payload carries no ``duration``/``episode_run_time``
  key at all (confirmed against the owner's live library, read-only: 0 of
  529,280 movie rows have an ``"info"`` or ``"duration"`` key in ``raw_data``
  — that data literally does not reach ingestion for movies).
* ``MetadataDB.tmdb_id`` — 0 of 653,306 rows. ``metadata_from_raw`` reads
  ``info.get("tmdb_id")``; every provider payload (live/movie/series alike)
  ships the id under the key ``"tmdb"``, so this is not media-type-conditional
  at all — it fails identically for every population, which the census below
  still catches (every entry gets its own baseline row).
* ``ChannelDB.detected_year`` — a different root cause from the three above
  (see "detected_year is not a payload-key bug" below), included because the
  worklog names it as one of the four flagship instances.

``runtime_from_raw``'s own docstring already recorded this lesson once
("0 of 652,216 rows") and the next fields repeated it anyway — a fix at one
call site does not stop the NEXT field from making the same mistake. This
guard measures *coverage after the write*, per field, per ``media_type``, so
a new field with the same shape fails CI instead of shipping silently.

Why a single representative row per media_type, not a live-DB query
---------------------------------------------------------------------
CI has no real library, so a non-null-RATE assertion proves nothing here —
that is what ``scripts/derived_field_coverage.py`` is for, run by hand (or in
a future CI step) against a real database. This guard instead runs the REAL
ingestion + metadata-backfill code — ``XtreamAPI.convert_to_channel``,
``ProviderLoadThread._store_channels``,
``ChannelRepository.update_detected_prefixes``,
``OfflineMetadataBackfillTask.run``, ``RawFieldBackfillTask.run``, all
unmodified production code — against one hand-built, VERIFIED-REAL fixture
payload per ``media_type`` (live/movie/series), and asserts every derived
field the run touches is either populated or explicitly allowlisted with a
reason. A field that is structurally IMPOSSIBLE to populate for a whole
``media_type`` (the key is not in that type's payload) comes out empty on
every run, deterministically — no live library needed to prove it.

The three fixture payloads use the EXACT key sets shipped by the owner's
providers, confirmed read-only against ``~/.local/share/metatv/metatv.db``
(never written, never copied) — the movie key set matches the brief's given
list verbatim: ``num, name, stream_type, stream_id, stream_icon, rating,
rating_5based, tmdb, trailer, added, is_adult, category_id, category_ids,
container_extension, custom_sid, direct_source``.

Population scope — which fields are censused, and why NOT every detected_*
----------------------------------------------------------------------------
``ChannelDB`` gets >30 columns written by ingestion; most of them
(``detected_prefix/quality/region/title``, ``detected_audio``,
``detected_collection*``, ``detected_name_cast``, ``detected_season/episode``)
are parsed from the free-text ``name`` string by the SAME code path
regardless of ``media_type`` — a bug there cannot take the "reads a key that
doesn't exist for one population" shape this guard targets, and censusing
them with one synthetic name per type would only measure "did this
particular string happen to contain a sub/dub marker", not a real coverage
gap. This census is deliberately scoped to fields that are either (a) read
from a raw-payload key whose PRESENCE differs by media_type
(``detected_tmdb_id``/``detected_rating``/``detected_added`` from
``convert_to_channel``; ``detected_genre``/``detected_genres`` from
``genres_from_raw``/``genres_from_category``, which read different sources
per type by an explicit ``GENRE_MEDIA_TYPES`` branch), (b) the identity
computation every collapse surface depends on (``content_key``), or (c) named
explicitly as a flagship instance in the audit (``detected_year`` — see
below). Extending the population is a deliberate edit to ``CHANNEL_FIELDS``/
``METADATA_FIELDS`` below, the same shape GUARD-4's ``PLUMBING_FILES`` is
hand-maintained and documented rather than derived.

``MetadataDB``'s population is the full set ``metadata_from_raw`` computes
from raw payload data (excludes ``imdb_id`` — see below) and is tested for
``movie``/``series`` only: ``OfflineMetadataBackfillTask`` itself restricts
its candidate query to ``media_type IN ('movie', 'series')`` — live channels
never get a ``MetadataDB`` row from this path, by design, so "live" is not a
meaningful population for these fields at all (not merely empty).

``imdb_id`` is out of scope. ``metadata_from_raw``'s ``MetadataResult(...)``
call never assigns it — there is no raw-payload key mapped to it anywhere in
the offline path; it is populated only by the network TMDb/OMDb providers.
That is a different failure class (network/API-key/rate-limit) from the one
this guard targets (a payload-key read bug), so it is not censused here.

``detected_year`` is not a payload-key bug
--------------------------------------------
Unlike the other three flagship fields, ``detected_year`` is parsed from
``channel.name`` by the exact same ``parse_channel_name()`` call regardless
of ``media_type`` — there is no type-conditional code branch to get wrong.
Measured on the owner's library: movies are 58.6% populated (310,002 /
529,280), series 30.8% (39,302 / 127,679) — both well short of 100% but
neither anywhere near the guard's own >95%-empty failure floor either. The
real gap is a NAMING CONVENTION difference (movies conventionally carry
"(YYYY)"; many long-running series titles simply do not) with no fallback to
``MetadataDB.year`` once that exists — an enrichment gap W-1 owns fixing,
not a key that doesn't exist. The representative fixture rows below reflect
that convention honestly: the movie fixture's name carries a year (the
common case for movies), live never carries a release year at all (not
applicable to that media_type), and the series fixture's name does not (the
common case for long-running series) — so the guard surfaces the real,
named gap without pretending it shares a fix with the other three.

The baseline
------------
``tests/derived_field_coverage_allowlist.json`` — shrink-only (same shape as
``tests/unwired_stored_fields_allowlist.json``): a NEW empty combo fails the
suite; a combo that starts populating and is left listed fails
``test_the_allowlist_only_shrinks``. Unlike the top-level-widget-leak
allowlist's freshness check (QT-2, #816 — order-dependent, so a single run
can prove an entry still needed but never that it is stale), this census has
NO order dependency: one deterministic pipeline run computes the WHOLE
combo->populated matrix, so "not empty this run" is proof positive the entry
is stale, not merely a candidate. A plain shrink-only check is correct here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metatv.core.derived_field_coverage import (
    CHANNEL_FIELDS,
    CHANNEL_MEDIA_TYPES as _MEDIA_TYPES,
    METADATA_FIELDS,
    METADATA_MEDIA_TYPES,
    is_empty as _is_empty,
)

ALLOWLIST_PATH = Path(__file__).resolve().parent / "derived_field_coverage_allowlist.json"

#: Minimum number of (field, media_type) combos the census must produce — a
#: resolver that silently returns nothing would read as a spotless codebase.
#: See CLAUDE.md "a runner that ran nothing exits 0".
_MIN_COMBOS = 20

# ---------------------------------------------------------------------------
# Fixture payloads — VERIFIED real key sets (read-only query against the
# owner's live library; never written, never copied). See module docstring.
# ---------------------------------------------------------------------------

LIVE_RAW = {
    "num": 451,
    "name": "EN| Christmas Channel 4K",
    "stream_type": "live",
    "stream_id": "900001",
    "stream_icon": "http://example.com/900001.png",
    "epg_channel_id": "channel.one",
    "added": "1658587387",
    "is_adult": 0,
    "category_id": "10",
    "category_ids": [10],
    "custom_sid": None,
    "tv_archive": 0,
    "direct_source": "",
    "tv_archive_duration": 0,
}

#: Exact key set given in the W-0 brief, verified byte-for-byte against a
#: real movie row's raw_data.
MOVIE_RAW = {
    "num": 3,
    "name": "EN - Inception (2010)",
    "stream_type": "movie",
    "stream_id": "900002",
    "stream_icon": "https://image.tmdb.org/t/p/original/poster.jpg",
    "rating": "7.8",
    "rating_5based": 3.9,
    "tmdb": "27205",
    "trailer": "YoHD9XEInc0",
    "added": "1773530100",
    "is_adult": "0",
    "category_id": "1109",
    "category_ids": [1109],
    "container_extension": "mkv",
    "custom_sid": None,
    "direct_source": "",
}

#: Series payload — carries genre/last_modified, NOT added; no year in the
#: name (see "detected_year is not a payload-key bug" above).
SERIES_RAW = {
    "num": 3085,
    "name": "EN - Breaking Bad",
    "series_id": 900003,
    "cover": "https://image.tmdb.org/t/p/original/cover.jpg",
    "plot": "A high school chemistry teacher turned methamphetamine manufacturer.",
    "cast": "Bryan Cranston, Aaron Paul, Anna Gunn",
    "director": "Vince Gilligan",
    "genre": "Drama / Crime",
    "releaseDate": "2008-01-20",
    "release_date": "2008-01-20",
    "last_modified": "1759675302",
    "rating": "9.5",
    "rating_5based": "4.7",
    "backdrop_path": ["https://image.tmdb.org/t/p/w1280/backdrop.jpg"],
    "youtube_trailer": "HhesaQXLuRY",
    "tmdb": "1396",
    "episode_run_time": "47",
    "category_id": "1403",
    "category_ids": [1403],
}

#: Category name mapped for the movie fixture — a plausible, common real-world
#: category ("US Movies") that does NOT cross-walk to a genre via
#: genres_from_category's strict recognized_genre() allowlist, matching the
#: real library's majority case (84.6% of movies get no detected_genre this
#: way — most provider categories are not genre-shaped).
_MOVIE_CATEGORY_MAP = {"1109": "US Movies"}

def _run_ingestion(tmp_path) -> dict:
    """Run the REAL ingestion + metadata-backfill pipeline against the three
    fixture payloads and return a plain-dict snapshot (never an ORM object —
    the session this reads from is closed before returning; CLAUDE.md "ORM
    objects must not outlive their session").

    Returns:
        ``{media_type: {"channel": {field: value, ...},
                          "metadata": {field: value, ...} | None}}``.
    """
    from metatv.core.database import ChannelDB, Database, MetadataDB
    from metatv.core.migrations.offline_metadata_backfill import (
        OfflineMetadataBackfillTask,
    )
    from metatv.core.migrations.raw_field_backfill import RawFieldBackfillTask
    from metatv.core.models import Provider
    from metatv.core.provider_loader import ProviderLoadThread
    from metatv.core.repositories import RepositoryFactory
    from metatv.providers.xtream import XtreamAPI

    db = Database(f"sqlite:///{tmp_path / 'derived_field_coverage.db'}")
    db.create_tables()

    api = XtreamAPI("http://host:8080", "user", "pass")
    channels = {
        "live": api.convert_to_channel(LIVE_RAW, provider_id="p1", media_type="live"),
        "movie": api.convert_to_channel(
            MOVIE_RAW, provider_id="p1", media_type="movie",
            category_map=_MOVIE_CATEGORY_MAP,
        ),
        "series": api.convert_to_channel(SERIES_RAW, provider_id="p1", media_type="series"),
    }

    provider = Provider.__new__(Provider)
    provider.id = "p1"
    provider.name = "Test Provider"
    provider.type = "xtream"
    provider.url = "http://host:8080"
    provider.username = "user"
    provider.password = "pass"
    provider.urls = []

    thread = ProviderLoadThread(provider, db)
    session = db.get_session()
    try:
        thread._store_channels(session, list(channels.values()), len(channels))
    finally:
        session.close()

    # Real ingestion: compute detected_* + content_key for the stored rows.
    with db.session_scope() as session:
        RepositoryFactory(session).channels.update_detected_prefixes(provider_id="p1")

    # Real metadata backfills, in the same order main_window.py registers
    # them: offline first (creates the MetadataDB row from raw_data), then
    # the per-field raw_field_backfill pass (runtime/trailer_url/etc — only
    # touches rows a metadata row already exists for).
    OfflineMetadataBackfillTask(db).run(lambda *a: None, lambda: False)
    RawFieldBackfillTask(db).run(lambda *a: None, lambda: False)

    snapshot: dict = {}
    with db.session_scope(commit=False) as session:
        for media_type, ch in channels.items():
            row = session.query(ChannelDB).filter_by(id=ch.id).one()
            channel_snapshot = {f: getattr(row, f, None) for f in CHANNEL_FIELDS}
            metadata_snapshot = None
            if row.metadata_id:
                meta = session.get(MetadataDB, row.metadata_id)
                if meta is not None:
                    metadata_snapshot = {f: getattr(meta, f, None) for f in METADATA_FIELDS}
            snapshot[media_type] = {"channel": channel_snapshot, "metadata": metadata_snapshot}

    db.close()
    return snapshot


@pytest.fixture(scope="module")
def coverage(tmp_path_factory) -> dict:
    """One real pipeline run, shared by every test in this module."""
    tmp_path = tmp_path_factory.mktemp("derived_field_coverage")
    return _run_ingestion(tmp_path)


def _combos(coverage: dict) -> list[tuple[str, str, bool]]:
    """``[(label, media_type, populated), ...]`` for the whole census population."""
    out: list[tuple[str, str, bool]] = []
    for field in CHANNEL_FIELDS:
        for media_type in _MEDIA_TYPES:
            value = coverage[media_type]["channel"][field]
            out.append((f"ChannelDB.{field}", media_type, not _is_empty(value)))
    for field in METADATA_FIELDS:
        for media_type in METADATA_MEDIA_TYPES:
            meta = coverage[media_type]["metadata"]
            value = None if meta is None else meta[field]
            out.append((f"MetadataDB.{field}", media_type, not _is_empty(value)))
    return out


def load_allowlist() -> set[str]:
    """``{"Model.field|media_type", ...}`` — keys of the combo->reason map.

    Unlike GUARD-4's flat list (whose reasons live in the PR body), each
    entry here carries its own one-line reason as the dict value — the brief
    asks for the reason to live IN the baseline, not only in the PR that
    seeded it.
    """
    data = json.loads(ALLOWLIST_PATH.read_text())
    return set(data.get("combos", {}).keys())


# ---------------------------------------------------------------------------
# Unit tests: _is_empty, against synthetic input
# ---------------------------------------------------------------------------


def test_is_empty_treats_none_blank_and_falsy_containers_as_empty():
    assert _is_empty(None)
    assert _is_empty("")
    assert _is_empty([])
    assert _is_empty({})


def test_is_empty_treats_real_values_as_populated():
    assert not _is_empty("Breaking Bad")
    assert not _is_empty(0.0)
    assert not _is_empty(1773530100)
    assert not _is_empty(["Drama"])
    assert not _is_empty([{"name": "Bryan Cranston"}])


# ---------------------------------------------------------------------------
# Integration tests: the real pipeline against the real, checked-in fixtures
# ---------------------------------------------------------------------------


def test_every_derived_field_is_populated_or_allowlisted(coverage):
    """Every (field, media_type) combo is populated, or is allowlisted.

    A failure here means a NEW field was added that reads a raw-payload key
    absent for a whole media_type — exactly the ``detected_added`` shape.
    Either fix the reader (a separate slice — W-1 owns the four known
    instances) or add ``"Model.field|media_type"`` to
    ``tests/derived_field_coverage_allowlist.json`` with a one-line reason.
    """
    allowlist = load_allowlist()
    unpopulated = sorted(
        f"{label}|{media_type}"
        for label, media_type, populated in _combos(coverage)
        if not populated and f"{label}|{media_type}" not in allowlist
    )
    assert not unpopulated, (
        f"{len(unpopulated)} derived field/media_type combo(s) came out empty "
        "and are not in tests/derived_field_coverage_allowlist.json:\n  "
        + "\n  ".join(unpopulated)
    )


def test_the_allowlist_only_shrinks(coverage):
    """A listed combo that now populates must be REMOVED, never left behind.

    No order dependency here (unlike the top-level-widget-leak allowlist,
    QT-2/#816): one pipeline run computes the WHOLE matrix deterministically,
    so "populated this run" is proof the entry is stale, not merely a
    candidate. See the module docstring for why that check does not apply
    the same caution #816 added for the leak allowlist.
    """
    populated = {
        f"{label}|{media_type}"
        for label, media_type, is_populated in _combos(coverage)
        if is_populated
    }
    allowlist = load_allowlist()
    stale = sorted(combo for combo in allowlist if combo in populated)
    assert not stale, (
        "these are allowlisted but now populate — remove them from "
        "tests/derived_field_coverage_allowlist.json:\n  " + "\n  ".join(stale)
    )


def test_every_allowlist_entry_has_a_reason(coverage):
    """Each baseline entry's VALUE is its one-line reason, not just its key.

    An empty/whitespace reason would defeat "the seed list IS the audit" —
    a combo with no stated reason is indistinguishable from one nobody has
    looked at yet.
    """
    data = json.loads(ALLOWLIST_PATH.read_text())
    combos = data.get("combos", {})
    blank = sorted(combo for combo, reason in combos.items() if not str(reason).strip())
    assert not blank, f"allowlist entries with no reason: {blank}"


def test_the_allowlist_has_no_unknown_combos(coverage):
    """Every allowlisted key must name a combo the current census population
    actually produces — otherwise a renamed/removed field's entry sits here
    forever, unable to ever fail ``test_the_allowlist_only_shrinks`` because
    nothing in ``_combos()`` matches it any more.
    """
    known = {f"{label}|{media_type}" for label, media_type, _ in _combos(coverage)}
    allowlist = load_allowlist()
    unknown = sorted(allowlist - known)
    assert not unknown, (
        "allowlist entries that don't match any current census combo "
        f"(stale/renamed field?): {unknown}"
    )


def test_the_census_actually_reaches_real_fields(coverage):
    """A resolver that silently returns nothing would read as a clean codebase.

    Pins that the census still produces a substantial population AND that it
    is a genuine mix of populated/empty results — a pipeline that silently
    stopped running (e.g. an import failure swallowed somewhere) would show
    every combo empty; a population that shrank to nothing would show zero
    combos. Either failure mode must fail this test, not read as "nothing
    wrong". Same role as GUARD-4's
    ``test_the_census_actually_reaches_the_tree``.
    """
    combos = _combos(coverage)
    assert len(combos) >= _MIN_COMBOS, (
        f"only {len(combos)} combos censused — CHANNEL_FIELDS/METADATA_FIELDS "
        "or the pipeline probably broke"
    )
    assert any(populated for _label, _mt, populated in combos), (
        "every combo came out empty — the ingestion pipeline probably isn't "
        "running at all"
    )
    assert any(not populated for _label, _mt, populated in combos), (
        "every combo came out populated — either the class of bug this guard "
        "exists to catch has genuinely been fixed everywhere (update the "
        "allowlist to empty and this assertion) or the census stopped "
        "reading real values"
    )


def test_offline_metadata_backfill_creates_no_row_for_live(coverage):
    """Live channels never get a MetadataDB row from this path — by design
    (``OfflineMetadataBackfillTask``'s own candidate query is scoped to
    ``media_type IN ('movie', 'series')``), not because of a coverage gap.
    Pinned so METADATA_FIELDS is never mistakenly extended to census "live"
    as if it were an empty population rather than a nonexistent one.
    """
    assert coverage["live"]["metadata"] is None
