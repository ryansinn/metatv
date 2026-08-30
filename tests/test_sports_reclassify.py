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
    """All six, not just the three the sports view happens to read.

    ``event_start_time`` and ``event_metadata`` are written by the ppv and
    live_event branches; leaving them behind would show a countdown for an
    event the row is no longer classified as.
    """
    assert set(DERIVED_FIELDS) == {
        "special_view", "sport_type", "league_name", "team_name",
        "event_start_time", "event_metadata",
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


def test_a_settings_edit_still_takes_effect(tmp_path):
    """The cache keys on the override file's mtime, so it is not a freeze.

    The Settings UI writes ``sports_definitions.yaml``; a process-lifetime cache
    would mean the user's edit did nothing until they restarted.
    """
    import os
    import yaml

    from metatv.core.special_content import load_sports_definitions

    cfg = _Cfg(config_dir=str(tmp_path))
    path = tmp_path / "sports_definitions.yaml"
    path.write_text(yaml.safe_dump({"league_keywords": {"League A": ["zzqx"]}}))
    before = load_sports_definitions(cfg)[1]
    assert "League A" in before

    path.write_text(yaml.safe_dump({"league_keywords": {"League B": ["zzqx"]}}))
    os.utime(path, (0, 0))          # force a distinct mtime, not a same-second write
    after = load_sports_definitions(cfg)[1]
    assert "League B" in after, "a Settings edit did not reach the classifier"


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
