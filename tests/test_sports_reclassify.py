"""#587 fixed the classifier and the owner could not see a single change.

``parse_sports_channel`` matched league keywords with ``if keyword in name``, so
``co-NFL-ict`` was an NFL channel, ``GREE-NBA-Y`` an NBA one and ``T-F1``
Formula 1. #587 made the match word-bounded. Nothing moved, because
**the classifier only ever runs on a row that has never been classified** —
``ProviderLoader`` filters ``special_view IS NULL``, deliberately, since
re-deriving 300k rows on every refresh is not free and the classification does
not change between refreshes.

It changes when the CLASSIFIER changes, and nothing was watching for that.

Measured over all 785,163 of the owner's rows with the current classifier:
7,804 change, of which 3,025 change ``special_view`` (35,181 → 32,237 sports,
408 → 510 ppv), 2,795 change ``league_name`` and 2,700 change ``team_name``.
The largest single correction removes 729 channels from Premier League.

The reset-then-recompute order is the load-bearing part, and
``test_a_false_positive_loses_its_label`` is the test that proves it:
``update_channel_special_content`` returns early and writes NOTHING when a row
no longer matches anything, so recomputing in place leaves every false positive
exactly where it was — and those 2,944 rows are the entire point of the pass.
"""

import pytest
from sqlalchemy import text

from metatv.core.database import ChannelDB, Database
from metatv.core.migrations.sports_reclassify import (
    CURRENT_VERSION, DERIVED_FIELDS, SportsReclassifyTask,
)


@pytest.fixture
def db(tmp_path):
    """A real file-backed database — the task pages over real ORM rows."""
    database = Database(f"sqlite:///{tmp_path / 'sports.db'}")
    database.create_tables()
    return database


class _Cfg:
    """Config double.

    ``config_dir`` is not decoration: the task threads config through to the
    classifier so a user's ``sports_definitions.yaml`` override is honoured,
    and ``get_user_definitions_path`` reads ``config.config_dir`` off it. A
    double without it raises AttributeError on the path production always
    takes — which is how ``test_runs_with_a_real_config_object`` came to exist.
    """

    def __init__(self, config_dir="/nonexistent-for-tests"):
        self.sports_reclassify_version = 0
        self.config_dir = config_dir
        self.saved = 0

    def save(self):
        self.saved += 1


def _seed(db, rows):
    """rows: (name, category, special_view, sport_type, league_name, team_name)."""
    with db.session_scope() as session:
        for i, (name, category, sv, st, ln, tn) in enumerate(rows):
            session.add(ChannelDB(
                id=f"c{i:04d}", source_id=f"s{i}", provider_id="p",
                name=name, category=category, stream_url=f"http://x/{i}",
                media_type="live", special_view=sv, sport_type=st,
                league_name=ln, team_name=tn,
            ))


def _labels(db):
    with db.session_scope() as session:
        return {
            r[0]: (r[1], r[2], r[3])
            for r in session.execute(text(
                "SELECT name, special_view, league_name, sport_type FROM channels"
            )).all()
        }


def _run(db, cfg=None, is_cancelled=lambda: False):
    task = SportsReclassifyTask(db)
    calls = []
    task.run(lambda done, total: calls.append((done, total)), is_cancelled, cfg)
    if cfg is not None:
        task.on_completed(cfg)
    return calls


# --------------------------------------------------------------------------
# The defect: a stale label survives a recompute
# --------------------------------------------------------------------------

def test_a_false_positive_loses_its_label(db):
    """The reason the six fields are RESET before the recompute.

    "4K - Conflict (2024)" was labelled NFL because "nfl" is inside "conflict".
    The fixed classifier declines to label it at all — and declining writes
    nothing, so without the reset the row keeps every wrong value it had.
    """
    _seed(db, [("4K - Conflict (2024)", "Movies", "sports", "football",
                "NFL", None)])
    _run(db)
    assert _labels(db)["4K - Conflict (2024)"] == (None, None, None)


def _row(name, category):
    class _Row:
        pass
    row = _Row()
    row.name, row.category, row.stream_url = name, category, "http://x"
    row.media_type, row.detected_prefix, row.epg_channel_id = "live", None, None
    return row


@pytest.mark.parametrize("name, category", [
    # "sport" must reach every compound. This is the case that nearly shipped
    # a regression: whole-token matching removed 11,451 real sports channels
    # from the view, because "sport" does not match "sports" or "sportsnet".
    ("4K| SPORTSNET 360 UHD", "4K UHD 3840P"),
    ("US| SPECTRUM SPORTS 1", "US| SPECTRUM NETWORK"),
    # Broadcaster brands that take a numeric or letter suffix. These are why
    # the brands are NOT all whole-token: ESPN2 and TSN1 are ESPN and TSN.
    ("GO| ESPN2", "GO| GENERAL"),
    ("CAR-HUB| ESPNU (CARIBBEAN)", "CAR-HUB| GENERAL"),
    ("CA| TSN1 FHD", "CA| GENERAL"),
    # Other stems that compound.
    ("##### MOTOGP #####", "TREX| HEADERS"),
    ("ES - Formula1 2024 - Miami", "ES| VOD"),
    ("F1TV PRO", "US| GENERAL"),
    ("PRIME| RUGBYPASS TV", "PRIME| GENERAL"),
    ("PRIME| GLORY KICKBOXING", "PRIME| GENERAL"),
    ("BEIN SPORTS 1", "TR| GENERAL"),
])
def test_a_stem_still_reaches_the_words_it_compounds_into(name, category):
    """The gate is a RECALL question, and a stem earns its keep by compounding.

    A one-line "make it consistent with the league matcher" change would take
    11,451 channels out of the sports view — an error an order of magnitude
    larger than the false positives whole-token matching was added to remove.
    Stems guard their LEFT edge only; acronyms guard both.
    """
    from metatv.core.special_content import detect_sports_channel
    assert detect_sports_channel(_row(name, category)) is True


@pytest.mark.parametrize("name, category", [
    ("4K - Conflict (2024)", "Movies"),          # "nfl" inside "conflict"
    ("CITY| ABC WBAY GREENBAY", "US Locals"),    # "nba" inside "GREENBAY"
    ("4k| TF1 HDR/UHD/4K", "France"),            # "f1" inside "TF1"
    ("EN - Being There (1979)", "Movies"),       # "bein" inside "Being"
    ("24/7 BEING MARY JANE", "TV"),              # 137 rows, measured
    ("EN - Freedom Fighters (2003)", "Movies"),  # 300 rows, measured
    ("US| FIREFIGHTERS", "Reality"),             # "fight" inside "firefighter"
    ("NL - HOCKEYVADERS", "Movies"),             # "hockey" starting a real word
    ("[MV] The Baseballs - Umbrella", "Music"),  # a band, not a sport
    ("EN - The Godfather (1972)", "Movies"),
])
def test_an_acronym_inside_a_word_is_not_a_sports_channel(name, category):
    """The other half — and the reason the left-edge guard is on stems too."""
    from metatv.core.special_content import detect_sports_channel
    assert detect_sports_channel(_row(name, category)) is False


def test_every_gate_keyword_is_in_exactly_one_set():
    """Each keyword's treatment is DECLARED, not inferred from its length.

    A rule like "five letters or more gets prefix matching" would put `moto`
    (which must reach MOTOGP) and `bein` (which must not reach "being") on the
    same side of the line — and a rule of "brands are whole tokens" drops ESPN2
    and TSN1, which is how the first draft of this lost them. Every membership
    was measured against the owner's 467,373 distinct names before it was
    written down.
    """
    from metatv.core.special_content import (
        SPORTS_GATE_STEMS, SPORTS_GATE_TOKENS,
    )
    overlap = set(SPORTS_GATE_STEMS) & set(SPORTS_GATE_TOKENS)
    assert not overlap, f"keyword in both sets: {overlap}"
    # Each membership below is a measured decision, not a convention:
    #   sport  prefix adds SPORTS(2300) SPORTSNET(113) SPORT1 — all real
    #   espn   prefix adds ESPN2 ESPNU ESPN3 ESPN8 ESPNEWS
    #   f1     prefix adds F1TV(35); TF1 is still blocked by the LEFT guard
    #   bein   prefix would add "BEING MARY JANE" and "Being Flynn" (137 rows)
    #   fight  prefix would add "Freedom Fighters" (300 rows)
    for kw in ("sport", "moto", "formula", "f1", "rugby", "espn", "tsn"):
        assert kw in SPORTS_GATE_STEMS, kw
    for kw in ("nba", "nfl", "bein", "fight", "hockey", "baseball"):
        assert kw in SPORTS_GATE_TOKENS, kw



@pytest.mark.parametrize("name, category", [
    ("CITY| ABC WBAY GREENBAY", "US Locals"),   # "nba" inside "GREENBAY"
    ("US| FANDUEL TV", "US Sports"),            # "uel" inside "FANDUEL"
    ("4k| TF1 HDR/UHD/4K", "France"),           # "f1" inside "TF1"
])
def test_the_substring_matches_are_gone(name, category):
    """Each of these was a real, shipped league assignment."""
    from metatv.core.special_content import parse_sports_channel

    assert parse_sports_channel(_row(name, category))["league_name"] is None


def test_a_real_league_is_still_labelled(db):
    """The pass must not simply delete everything it touches."""
    _seed(db, [("US| NFL NETWORK HD", "US Sports", None, None, None, None)])
    _run(db)
    _sv, league, _sport = _labels(db)["US| NFL NETWORK HD"]
    assert league == "NFL"


def test_an_unclassified_row_gets_classified(db):
    """A row the old classifier missed is picked up, not just cleaned."""
    _seed(db, [("US| NBA TV", "US Sports", None, None, None, None)])
    _run(db)
    sv, league, _ = _labels(db)["US| NBA TV"]
    assert sv == "sports"
    assert league == "NBA"


def test_untouched_rows_keep_their_nulls(db):
    """An ordinary channel gains no labels at all."""
    _seed(db, [("EN - The Godfather (1972)", "Movies", None, None, None, None)])
    _run(db)
    assert _labels(db)["EN - The Godfather (1972)"] == (None, None, None)


# --------------------------------------------------------------------------
# Mechanics
# --------------------------------------------------------------------------

def test_every_derived_field_is_reset(db):
    """All nine, not just the three the sports view happens to read.

    ``event_start_time``, ``event_stop_time`` and ``event_metadata`` are
    written by the ppv and live_event branches; leaving them behind would show
    a countdown for an event the row is no longer classified as.
    ``event_team_a``/``event_team_b`` (SPORT-4) join the set for the same
    reason — a row that stops being a fixture must not keep its old opponents.

    The exact set is pinned deliberately: a field added to the classifier that
    is NOT reset here keeps a stale value through the sweep, and that failure is
    invisible — the row looks classified, just wrongly. Adding a field is
    therefore a visible edit to this line.
    """
    assert set(DERIVED_FIELDS) == {
        "special_view", "sport_type", "league_name", "team_name",
        "event_start_time", "event_stop_time", "event_metadata",
        "event_team_a", "event_team_b",
    }
    _seed(db, [("4K - Conflict (2024)", "Movies", "ppv", "football", "NFL", "Bears")])
    with db.session_scope() as session:
        row = session.query(ChannelDB).first()
        row.event_start_time = None
        row.event_metadata = {"event_name": "stale"}
    _run(db)
    with db.session_scope() as session:
        row = session.query(ChannelDB).first()
        for field in DERIVED_FIELDS:
            assert getattr(row, field) is None, f"{field} survived the reset"


def test_progress_reaches_the_total(db):
    """Every row is visited exactly once across batches."""
    import metatv.core.migrations.sports_reclassify as mod
    keep, mod._BATCH = mod._BATCH, 7
    try:
        _seed(db, [(f"EN - Film {i}", "Movies", None, None, None, None)
                   for i in range(50)])
        calls = _run(db)
    finally:
        mod._BATCH = keep
    assert calls[-1] == (50, 50)
    assert len(calls) > 1, "the batch override did not take — one call means one batch"


def test_second_run_changes_nothing(db):
    """Idempotent: the classifier is a pure function of the row."""
    _seed(db, [("US| NFL NETWORK HD", "US Sports", None, None, None, None),
               ("4K - Conflict (2024)", "Movies", "sports", "football", "NFL", None)])
    _run(db)
    first = _labels(db)
    _run(db)
    assert _labels(db) == first


def test_cancel_returns_early(db):
    """A cancel stops the pass; committed batches stay committed."""
    import metatv.core.migrations.sports_reclassify as mod
    keep, mod._BATCH = mod._BATCH, 5
    try:
        _seed(db, [(f"EN - Film {i}", "Movies", None, None, None, None)
                   for i in range(60)])
        seen = {"n": 0}

        def cancel_after_two():
            seen["n"] += 1
            return seen["n"] > 2

        calls = _run(db, is_cancelled=cancel_after_two)
    finally:
        mod._BATCH = keep
    assert calls and calls[-1][0] < 60


def test_version_gate(db):
    task = SportsReclassifyTask(db)
    cfg = _Cfg()
    assert task.needs_run(cfg) is True
    task.on_completed(cfg)
    assert cfg.sports_reclassify_version == CURRENT_VERSION
    assert cfg.saved == 1
    assert task.needs_run(cfg) is False


def test_version_gate_survives_a_config_without_the_field(db):
    class _Old:
        pass
    assert SportsReclassifyTask(db).needs_run(_Old()) is True


def test_config_declares_the_version_field():
    """Asserted through model_fields — Config is pydantic v2, so hasattr is
    False for every declared field and would pass for a name that does not
    exist at all."""
    from metatv.core.config import Config
    assert "sports_reclassify_version" in Config.model_fields
    assert Config().sports_reclassify_version == 0


def test_registered_with_the_migration_manager():
    """An unregistered task never runs — which is this whole slice's subject."""
    from pathlib import Path
    import metatv.gui.main_window as mw
    source = Path(mw.__file__).read_text()
    assert "self.migration_manager.register(SportsReclassifyTask(self.db))" in source


def test_the_ingestion_filter_that_made_this_necessary_is_still_there():
    """Documents WHY this task exists, and fails if the premise changes.

    ``ProviderLoader`` classifies only rows with no ``special_view``. If that
    filter is ever removed, a refresh re-derives everything and this migration
    is redundant — and whoever removes it should be told that here rather than
    discovering the redundancy later.
    """
    from pathlib import Path
    import metatv.core.provider_loader as pl
    source = Path(pl.__file__).read_text()
    assert "ChannelDB.special_view.is_(None)" in source


# --------------------------------------------------------------------------
# Drift guard: the half-fix
# --------------------------------------------------------------------------

def test_no_keyword_list_is_matched_by_substring():
    """#587 fixed ONE of the three places that match a sport keyword.

    ``parse_sports_channel`` got whole-token matching. ``detect_sports_channel``
    — the gate deciding whether a channel is in the sports view AT ALL — and
    ``parse_ppv_event``'s sport_type kept ``if kw in name``. So "4K - Conflict
    (2024)" lost its bogus NFL label and stayed in the sports view regardless,
    labelled sport_type "unknown"; the view would still have listed it.

    An AST walk rather than a grep, and it names the bug's SHAPE: a membership
    test whose iterable is a keyword list. Any wording of it fails —
    ``any(kw in name ...)``, ``[k for k in kws if k in hay]``, a bare loop.

    Note what this does NOT forbid. ``_matches_stem`` matches a keyword at the
    START of a word, which is prefix matching and entirely deliberate — "sport"
    has to reach SPORTSNET. The bug is an UNGUARDED substring, where the
    keyword may begin mid-word; both matchers guard the left edge, and the
    token one guards the right as well. ``_matches_keyword`` and
    ``_matches_stem`` are the two matchers, and there is no third.
    """
    import ast
    from pathlib import Path

    import metatv.core.special_content as mod

    tree = ast.parse(Path(mod.__file__).read_text())
    offenders = []
    for node in ast.walk(tree):
        iters = []
        if isinstance(node, (ast.GeneratorExp, ast.ListComp, ast.SetComp)):
            iters = [(g.iter, node.elt) for g in node.generators]
            iters += [(g.iter, cond) for g in node.generators for cond in g.ifs]
        elif isinstance(node, ast.For):
            iters = [(node.iter, stmt) for stmt in node.body]
        for iterable, body in iters:
            name = ast.unparse(iterable).lower()
            if "keyword" not in name and not name.endswith("kws"):
                continue
            for sub in ast.walk(body):
                if isinstance(sub, ast.Compare) and any(
                        isinstance(op, ast.In) for op in sub.ops):
                    offenders.append(ast.unparse(sub))

    assert not offenders, (
        "substring keyword matching is back in special_content.py — call "
        f"_matches_keyword() instead: {offenders}")


def test_runs_with_a_real_config_object(db, tmp_path):
    """The config path production always takes, which no other test covered.

    ``run`` passes config to ``update_channel_special_content`` so a user's
    ``sports_definitions.yaml`` override applies to the backfill as well as to
    ingestion. Every other test here passes ``config=None``, so the first time
    a config actually reached the classifier was in a manual smoke run against
    real rows — and it raised ``AttributeError: 'Cfg' object has no attribute
    'config_dir'``.
    """
    _seed(db, [("US| NFL NETWORK HD", "US Sports", None, None, None, None),
               ("4K - Conflict (2024)", "Movies", "sports", "football", "NFL", None)])
    cfg = _Cfg(config_dir=str(tmp_path))
    _run(db, cfg)
    labels = _labels(db)
    assert labels["US| NFL NETWORK HD"][1] == "NFL"
    assert labels["4K - Conflict (2024)"] == (None, None, None)
    assert cfg.sports_reclassify_version == CURRENT_VERSION


def test_a_user_definitions_override_reaches_the_backfill(db, tmp_path):
    """A custom league keyword must apply when re-classifying, not only at
    ingestion — otherwise the user's own definitions silently do not reach
    the 785k rows they already have."""
    import yaml

    # Both maps are FLAT — sport name -> keywords, league DISPLAY name ->
    # keywords. league_keywords is not nested under a sport.
    (tmp_path / "sports_definitions.yaml").write_text(yaml.safe_dump({
        "sport_keywords": {"hockey": ["hockey"]},
        "league_keywords": {"Fictional League": ["zzqx"]},
    }))
    _seed(db, [("US| ZZQX HOCKEY NIGHT", "US Sports", None, None, None, None)])
    _run(db, _Cfg(config_dir=str(tmp_path)))
    assert _labels(db)["US| ZZQX HOCKEY NIGHT"][1] == "Fictional League"


# --------------------------------------------------------------------------
# The YAML parse that ran once per channel
# --------------------------------------------------------------------------

def test_definitions_are_not_re_read_per_channel(tmp_path):
    """4.34 ms per call, called once per channel.

    ``parse_sports_channel`` calls ``load_sports_definitions``, which read and
    parsed the bundled YAML every time — measured, that was **the entire cost**
    of the function (4.34 ms of 4.34 ms). It made the classification pass 736
    rows/s, so 785,163 rows took 18 minutes, and ProviderLoader's categorize
    step paid the same toll on every refresh.

    Someone already knew: ``channel_name_utils._sports_keywords_flat`` carries
    an lru_cache and a comment saying this function reads a YAML file. The cache
    went on the call site that was noticed, not on the function, so the hot
    caller kept paying.

    Asserting object IDENTITY, not equality — equal dicts would also be
    returned by a re-read, which is precisely the thing being forbidden.
    """
    from metatv.core.special_content import load_sports_definitions

    cfg = _Cfg(config_dir=str(tmp_path))
    first = load_sports_definitions(cfg)
    second = load_sports_definitions(cfg)
    assert first[0] is second[0] and first[1] is second[1]


def test_a_settings_edit_still_takes_effect(tmp_path, monkeypatch):
    """The cache keys on the override file's mtime, so it is not a freeze.

    The Settings UI writes ``sports_definitions.yaml``; a process-lifetime cache
    would mean the user's edit did nothing until they restarted. With the stat()
    TTL, a file edit is picked up after the TTL expires, which is within a second.
    """
    import os
    import yaml
    import metatv.core.special_content as mod
    from metatv.core.special_content import load_sports_definitions

    # Reset TTL tracking and cache so test ordering doesn't leak.
    mod._last_stamp_check.clear()
    mod._last_stamp_check.update(path=None, at=0.0, key=None)
    mod._DEFINITIONS_CACHE.clear()

    # Mock time.monotonic to control the TTL boundary.
    fake_time = {"now": 0.0}

    def mock_monotonic():
        return fake_time["now"]

    monkeypatch.setattr("time.monotonic", mock_monotonic)

    cfg = _Cfg(config_dir=str(tmp_path))
    path = tmp_path / "sports_definitions.yaml"
    path.write_text(yaml.safe_dump({"league_keywords": {"League A": ["zzqx"]}}))
    before = load_sports_definitions(cfg)[1]
    assert "League A" in before

    path.write_text(yaml.safe_dump({"league_keywords": {"League B": ["zzqx"]}}))
    os.utime(path, (0, 0))          # force a distinct mtime, not a same-second write

    # Advance fake clock past TTL boundary so the file change is picked up.
    fake_time["now"] = 1.5
    after = load_sports_definitions(cfg)[1]
    assert "League B" in after, "a Settings edit did not reach the classifier after TTL expiry"


def test_the_cached_maps_are_not_mutated_by_a_caller(tmp_path):
    """One shared object per key is only safe while callers read it.

    ``parse_sports_channel`` iterates the maps and writes nothing. If that ever
    changes, the mutation would leak into every subsequent caller — so pin it.
    """
    from metatv.core.special_content import load_sports_definitions, parse_sports_channel

    cfg = _Cfg(config_dir=str(tmp_path))
    sport_kw, league_kw = load_sports_definitions(cfg)
    snapshot = ({k: list(v) for k, v in sport_kw.items()},
                {k: list(v) for k, v in league_kw.items()})
    for name in ("US| NFL NETWORK HD", "4K - Conflict (2024)", "GO| ESPN2"):
        parse_sports_channel(_row(name, "Sports"), cfg)
    assert (sport_kw, league_kw) == snapshot


# --------------------------------------------------------------------------
# The lock the pass used to hold — see the module note in sports_reclassify.py
# --------------------------------------------------------------------------

class _TxnRecorder:
    """Records what each WRITE transaction did, from SQLAlchemy's own events.

    The observable is the SQL that actually reached the driver, not anything
    the task reports about itself: DML statements are attributed to the
    transaction in flight, and a COMMIT closes it. A transaction with no DML is
    never recorded, because it took no write lock — which is the property the
    98.75%-unchanged rows depend on.

    Deliberately not ``session.dirty``/``session.deleted``: those are empty
    under ``synchronize_session=False``, so an assertion over them is vacuously
    true — which is how a chunking guard can pass on unchunked code.
    """

    def __init__(self, database):
        from sqlalchemy import event

        self.transactions: list[tuple[int, int]] = []   # (rows, statements)
        self.selects: list[str] = []
        self._rows = self._stmts = 0

        @event.listens_for(database.engine, "before_cursor_execute")
        def _dml(conn, cursor, statement, parameters, context, executemany):
            head = statement.lstrip()[:6].upper()
            if head in ("UPDATE", "INSERT", "DELETE"):
                self._rows += len(parameters) if executemany else 1
                self._stmts += 1
            elif head == "SELECT":
                self.selects.append(statement)

        @event.listens_for(database.engine, "commit")
        def _commit(conn):
            if self._stmts:
                self.transactions.append((self._rows, self._stmts))
            self._rows = self._stmts = 0

    @property
    def rows_written(self) -> int:
        return sum(rows for rows, _ in self.transactions)

    @property
    def widest(self) -> int:
        return max((rows for rows, _ in self.transactions), default=0)

    @property
    def most_statements(self) -> int:
        return max((stmts for _, stmts in self.transactions), default=0)


def _stale_sports_rows(n):
    """*n* rows wrongly labelled NFL — every one of them changes on a re-run."""
    return [(f"4K - Conflict {i} (2024)", "Movies", "sports", "football", "NFL", "Bears")
            for i in range(n)]


def test_no_write_transaction_holds_more_rows_than_the_chunk(db):
    """The lock-hold bound, measured on the SQL that reached the driver.

    The old shape put every changed row of a page in ONE transaction, so a page
    that changed 2,000 rows held the write lock for all 2,000. Chunking is the
    same fix ``epg.delete_programmes_chunked`` applies to the other bulk writer
    on this database (#601).
    """
    import metatv.core.migrations.sports_reclassify as mod

    keep, mod._BATCH = mod._BATCH, 1200
    try:
        _seed(db, _stale_sports_rows(1200))
        recorder = _TxnRecorder(db)
        _run(db)
    finally:
        mod._BATCH = keep

    assert recorder.rows_written == 1200, (
        "nothing was written — the bound below would be vacuously true")
    assert recorder.widest <= mod.WRITE_CHUNK, (
        f"a transaction wrote {recorder.widest} rows, over the "
        f"{mod.WRITE_CHUNK}-row chunk")
    assert len(recorder.transactions) >= 3, (
        "1,200 changed rows must span at least three chunks, not one transaction")


def test_a_chunk_is_one_statement_not_one_per_changed_column_set(db):
    """Where the 21x of lock time went.

    A full ORM flush emits one UPDATE per distinct changed-COLUMN combination,
    and each is a round trip taken while holding the write lock — 13 statements
    for 24 rows, measured. The bulk update is a single ``executemany`` however
    many column shapes the chunk contains, so this seeds two shapes on purpose.
    """
    _seed(db, [
        # sport/league/team cleared -> one column shape
        ("4K - Conflict (2024)", "Movies", "sports", "football", "NFL", "Bears"),
        ("4K - Conflict 2 (2024)", "Movies", "sports", "football", "NBA", "Lakers"),
        # gains a label -> a different column shape
        ("US| NFL NETWORK HD", "US Sports", None, None, None, None),
        ("UK: SKY SPORTS 1 FHD", "Sports", None, None, None, None),
    ])
    recorder = _TxnRecorder(db)
    _run(db)

    assert recorder.rows_written == 4, "all four rows must change, or this proves nothing"
    assert recorder.most_statements == 1, (
        f"{recorder.most_statements} statements inside one transaction — the "
        "chunk must be a single executemany")


def test_the_page_query_does_not_load_the_raw_data_blob(db):
    """The read half: three strings per row, not a ~45-column row with its JSON.

    ``raw_data`` averages 2 KB across the owner's 785k rows, and the classifier
    never looks at it.
    """
    _seed(db, [("US| NFL NETWORK HD", "US Sports", None, None, None, None)])
    recorder = _TxnRecorder(db)
    _run(db)

    pages = [s for s in recorder.selects if "channels.name" in s]
    assert pages, "no page query was recorded — the assertion below is vacuous"
    assert not any("raw_data" in s for s in pages), (
        "the page query still loads raw_data")
    assert any("channels.special_view" in s for s in pages), (
        "the page query must load the derived fields, or nothing can be compared")


def test_a_run_that_changes_nothing_takes_no_write_transaction_at_all(db):
    """98.75% of the catalog must never reach a write lock.

    A second pass over already-correct rows is the common case — every launch
    after a bumped CURRENT_VERSION re-reads all 785k of them.
    """
    _seed(db, [("US| NFL NETWORK HD", "US Sports", None, None, None, None),
               ("EN | Discovery Channel HD", "Docs", None, None, None, None)])
    _run(db)                       # first pass: settles the labels

    recorder = _TxnRecorder(db)
    _run(db)                       # second pass: nothing to do
    assert recorder.transactions == [], (
        f"an unchanged pass still took the write lock: {recorder.transactions}")


def test_a_concurrent_writer_gets_through_while_the_pass_runs(db, tmp_path):
    """The four writers that failed in the owner's log were all small ones.

    A second connection doing the ``UPDATE channels SET rec_shown_count=…`` from
    the crash report must keep landing throughout, and the pass must still
    finish — that is the shape that broke, so it is the shape that is pinned.
    """
    import threading
    import time

    _seed(db, _stale_sports_rows(600) +
          [("EN | Marker", "Docs", None, None, None, None)])

    other = Database(f"sqlite:///{tmp_path / 'sports.db'}")
    stop = threading.Event()
    landed, failures = [], []

    def _hammer():
        while not stop.is_set():
            try:
                with other.session_scope() as session:
                    row = session.get(ChannelDB, "c0600")
                    row.rec_shown_count = (row.rec_shown_count or 0) + 1
                landed.append(1)
            except Exception as exc:                     # noqa: BLE001
                failures.append(str(exc).split("\n")[0])

    hammer = threading.Thread(target=_hammer, daemon=True)
    hammer.start()
    try:
        # Wait for the probe to be demonstrably alive and committing BEFORE
        # the pass starts, instead of hoping it gets scheduled twice inside
        # it. The pass takes ~0.2s on a 16-core laptop and the probe is a
        # Python thread contending for the GIL, so on a 2-core CI runner it
        # could land once and no more — which failed the suite as
        # "the probe never ran; this proves nothing" (assert 1 > 1) while
        # passing 11/11 locally, clean AND under 16-way load.
        #
        # That guard was right to fire: the run HAD proved nothing. The bug
        # was pinning a concurrency claim to thread scheduling. Waiting makes
        # the "> 1" below true by construction, and the probe keeps hammering
        # across _run either way — so what this test actually pins, that a
        # small concurrent writer is never locked out, is unchanged.
        deadline = time.monotonic() + 30
        while len(landed) < 2 and not failures and time.monotonic() < deadline:
            time.sleep(0.005)
        assert landed, "the probe thread never committed once; it is broken"
        _run(db)
    finally:
        stop.set()
        hammer.join(timeout=10)

    assert not failures, f"a concurrent writer was locked out: {failures[:2]}"
    assert len(landed) > 1, "the probe never ran; this proves nothing"
    with db.session_scope(commit=False) as session:
        assert session.get(ChannelDB, "c0600").rec_shown_count == len(landed)
        assert session.get(ChannelDB, "c0000").special_view is None, (
            "the pass did not finish its work")


# --------------------------------------------------------------------------
# A partial run must not record itself complete, and must resume
# --------------------------------------------------------------------------

def _task_that_dies_on_the_second_chunk(db):
    """A real task whose second write chunk raises 'database is locked'."""
    task = SportsReclassifyTask(db)
    original = task._write_changes
    calls = {"n": 0}

    def _die(updates):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("database is locked")
        return original(updates)

    task._write_changes = _die
    return task, calls


def test_a_crash_partway_leaves_the_version_unbumped(db, qapp):
    """Driven through the REAL MigrationManager, because that is who decides.

    ``_run_all`` skips ``on_completed`` when ``run`` raises, so the version
    stays behind and the task retries next launch. A task that recorded itself
    complete after a partial pass would burn the version permanently — which is
    what happened to detected_title_reparse v8 (#364).
    """
    import threading
    from unittest.mock import MagicMock

    import metatv.core.migrations.sports_reclassify as mod
    from metatv.core.migration_manager import MigrationManager

    _seed(db, _stale_sports_rows(30))
    task, calls = _task_that_dies_on_the_second_chunk(db)

    mgr = MigrationManager.__new__(MigrationManager)
    cfg = _Cfg()
    mgr.config = cfg
    mgr._cancel_event = threading.Event()
    for name in ("_task_started", "_task_progress", "_task_finished", "_all_finished"):
        setattr(mgr, name, MagicMock(emit=lambda *a: None))

    keep, mod._BATCH = mod._BATCH, 10
    try:
        mgr._run_all([task])
    finally:
        mod._BATCH = keep

    assert calls["n"] > 1, "the injected failure never fired"
    assert cfg.sports_reclassify_version == 0, (
        "a crashed pass recorded itself complete — it will never retry")
    assert cfg.saved == 0
    assert task.needs_run(cfg) is True


def test_the_rerun_finishes_the_job_and_rewrites_nothing_it_already_fixed(db):
    """Resumability, at the grain the migration framework defines it.

    ``migrations/base.py``: "interrupting it mid-way leaves it in an
    un-completed state so it will re-run on next launch". What makes that cheap
    rather than merely correct is that the retry writes ONLY the rows the first
    attempt did not reach — the ones it did now compare equal.
    """
    import metatv.core.migrations.sports_reclassify as mod

    _seed(db, _stale_sports_rows(30))
    task, _calls = _task_that_dies_on_the_second_chunk(db)

    keep, mod._BATCH = mod._BATCH, 10
    try:
        with pytest.raises(RuntimeError):
            task.run(lambda d, t: None, lambda: False, None)

        with db.session_scope(commit=False) as session:
            fixed = session.query(ChannelDB).filter(
                ChannelDB.special_view.is_(None)).count()
        assert fixed == 10, "the first chunk should have committed before the crash"

        recorder = _TxnRecorder(db)
        _run(db)                                     # the resumed run
    finally:
        mod._BATCH = keep

    assert recorder.rows_written == 20, (
        f"the retry rewrote {recorder.rows_written} rows; the 10 the first "
        "attempt already fixed must compare equal and cost no write")
    with db.session_scope(commit=False) as session:
        assert session.query(ChannelDB).filter(
            ChannelDB.special_view.isnot(None)).count() == 0


def test_the_classifier_reads_no_column_the_page_query_omits():
    """The drift guard that makes the narrowed SELECT safe to keep.

    ``CLASSIFIER_INPUTS`` is the reason the page query can skip ``raw_data``,
    and it is a hand-written tuple — so the day someone makes
    ``special_content`` read another column, this fails and names it, instead
    of the migration silently classifying every row against ``None``.
    """
    import ast
    from pathlib import Path

    import metatv.core.special_content as mod
    from metatv.core.migrations.sports_reclassify import CLASSIFIER_INPUTS

    tree = ast.parse(Path(mod.__file__).read_text())
    touched = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "channel"
    }
    assert touched, "the AST walk found nothing — this guard is not looking at the code"
    stray = touched - set(CLASSIFIER_INPUTS) - set(DERIVED_FIELDS)
    assert not stray, (
        f"special_content reads {sorted(stray)} off a channel, which the page "
        "query in sports_reclassify.py does not load — add it to CLASSIFIER_INPUTS")


def test_the_bulk_write_round_trips_json_and_datetime_columns(db):
    """``event_metadata`` is JSONEncoded and ``event_start_time`` a DateTime.

    The write moved from the ORM unit of work to a bulk UPDATE, and a bulk
    UPDATE that bypassed the column types would store a repr instead of JSON.
    """
    from datetime import datetime

    _seed(db, [
        ("End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | US: SOCCER PPV 1",
         "PPV", None, None, None, None),
    ])
    _run(db)

    with db.session_scope(commit=False) as session:
        row = session.query(ChannelDB).one()
        assert row.special_view == "ppv"
        assert isinstance(row.event_metadata, dict), (
            f"event_metadata came back as {type(row.event_metadata).__name__}")
        assert isinstance(row.event_start_time, datetime)
        assert row.updated_at is not None


# --------------------------------------------------------------------------
# PERF-18: Stat() TTL to avoid 785k syscalls per backfill pass
# --------------------------------------------------------------------------

def test_stat_ttl_reuses_cache_key_within_window(tmp_path, monkeypatch):
    """Within the 1s TTL, the cache key is reused without stat()ing again.

    A hot backfill calls load_sports_definitions once per row; statting the
    override file per call is 785k syscalls per pass. The TTL lets a hot
    loop stat once per second instead of once per row.
    """
    import metatv.core.special_content as mod
    from metatv.core.special_content import load_sports_definitions

    cfg = _Cfg(config_dir=str(tmp_path))

    # Mock time.monotonic and Path.stat to count stat calls.
    stat_count = {"n": 0}
    fake_time = {"now": 0.0}

    def mock_stat(self, *args, **kwargs):
        stat_count["n"] += 1
        import os
        return os.stat_result((0, 0, 0, 0, 0, 0, 0, 0, 0, 0))

    def mock_monotonic():
        return fake_time["now"]

    monkeypatch.setattr("pathlib.Path.stat", mock_stat)
    monkeypatch.setattr("time.monotonic", mock_monotonic)

    # Reset the TTL tracking so test ordering doesn't leak.
    mod._last_stamp_check.clear()
    mod._last_stamp_check.update(path=None, at=0.0, key=None)
    mod._DEFINITIONS_CACHE.clear()

    # Call 50 times at the same fake time — should stat only once.
    for _ in range(50):
        load_sports_definitions(cfg)
    assert stat_count["n"] == 1, "multiple stat() calls within the TTL window"

    # Advance fake clock past the 1.0s TTL boundary.
    fake_time["now"] = 1.5
    load_sports_definitions(cfg)
    assert stat_count["n"] == 2, "stat() was not called after TTL expired"

    # At same fake time again — reuse without stat.
    load_sports_definitions(cfg)
    assert stat_count["n"] == 2, "stat() called again within the same second"


def test_stat_ttl_freshness_after_file_change(tmp_path, monkeypatch):
    """After the TTL expires, a file edit is picked up.

    This is the behavior that would break if the TTL logic went stale-forever:
    modifying the override file with a new mtime and advancing past the TTL
    must pick up the new definitions.
    """
    import os
    import yaml
    import metatv.core.special_content as mod
    from metatv.core.special_content import load_sports_definitions

    cfg = _Cfg(config_dir=str(tmp_path))
    fake_time = {"now": 0.0}

    def mock_monotonic():
        return fake_time["now"]

    monkeypatch.setattr("time.monotonic", mock_monotonic)

    # Reset TTL tracking and cache.
    mod._last_stamp_check.clear()
    mod._last_stamp_check.update(path=None, at=0.0, key=None)
    mod._DEFINITIONS_CACHE.clear()

    # Write initial override file with one custom league.
    path = tmp_path / "sports_definitions.yaml"
    path.write_text(yaml.safe_dump({"league_keywords": {"League A": ["zzqx"]}}))

    first = load_sports_definitions(cfg)[1]
    assert "League A" in first

    # Modify the file with new mtime.
    path.write_text(yaml.safe_dump({"league_keywords": {"League B": ["zzqx"]}}))
    os.utime(path, (0, 0))  # force distinct mtime

    # Advance clock past TTL boundary.
    fake_time["now"] = 1.5

    second = load_sports_definitions(cfg)[1]
    assert "League B" in second, "file edit after TTL expiry was not picked up"
    assert "League A" not in second, "old definition persisted after file change"


def test_stat_ttl_mutation_check(tmp_path, monkeypatch):
    """Mutation test: make the TTL always hit and confirm test_freshness breaks.

    This proves the freshness test would actually fail if the TTL logic
    went stale-forever (i.e., if we never expired the cached key).
    """
    import os
    import yaml
    import metatv.core.special_content as mod
    from metatv.core.special_content import load_sports_definitions

    cfg = _Cfg(config_dir=str(tmp_path))
    fake_time = {"now": 0.0}

    def mock_monotonic():
        return fake_time["now"]

    monkeypatch.setattr("time.monotonic", mock_monotonic)

    # Reset TTL tracking and cache.
    mod._last_stamp_check.clear()
    mod._last_stamp_check.update(path=None, at=0.0, key=None)
    mod._DEFINITIONS_CACHE.clear()

    # Temporarily patch _STAMP_TTL_S to an impossibly large value so the
    # TTL never expires, simulating a stale-forever bug.
    original_ttl = mod._STAMP_TTL_S
    mod._STAMP_TTL_S = float('inf')

    try:
        # Write initial override with one league.
        path = tmp_path / "sports_definitions.yaml"
        path.write_text(yaml.safe_dump({"league_keywords": {"League A": ["zzqx"]}}))

        first = load_sports_definitions(cfg)[1]
        assert "League A" in first

        # Modify the file.
        path.write_text(yaml.safe_dump({"league_keywords": {"League B": ["zzqx"]}}))
        os.utime(path, (0, 0))

        # Advance time far past what would be the TTL.
        fake_time["now"] = 100.0

        second = load_sports_definitions(cfg)[1]
        # With the mutation (TTL forever), the old definition persists.
        assert "League A" in second, "mutation was not applied — TTL is working as intended"
        assert "League B" not in second, "mutation check passed: TTL went stale"

    finally:
        # Restore the real TTL constant.
        mod._STAMP_TTL_S = original_ttl
