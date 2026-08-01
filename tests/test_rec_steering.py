"""Recommendation steering (0.15.0) — proportional media mix + scoring dials.

What this proves:

1. √-damped proportional mix — the share follows engagement but never crushes the
   minority type (100 movies : 15 series → 72 : 28 → 7 / 3 in a 10-slot list), an
   even history stays even, an all-one-type history stays all-one-type, and a
   brand-new library cold-starts at 50 : 50. See ``test_damped_*`` / ``test_mix_*``.

2. The engine reads the user's dials — actor support gate, cast weight, impression
   decay, people-diversity decay and the already-liked cap all change the actual
   returned list when the corresponding setting moves, and the *bare* engine call
   (no settings, no mix) still behaves exactly as before. See ``test_dial_*``.

3. The one shared config key round-trips: both the dashboard slider and the
   settings panel read and write ``rec_media_mix``. See ``test_config_*`` /
   ``test_settings_panel_*`` / ``test_dashboard_*``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.database import ChannelDB, MetadataDB, UserRatingDB, WatchQueueDB


@pytest.fixture(scope="module")
def qapp():
    """Process-wide QApplication for headless Qt widget tests."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# --------------------------------------------------------------------------- #
# Helpers (file-backed DB per the tests rule — never :memory:)
# --------------------------------------------------------------------------- #

def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _channel(session, name, *, media_type="movie", metadata_id=None,
             last_played=None, is_favorite=False, rec_shown_count=0) -> ChannelDB:
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id="p1",
        name=name,
        media_type=media_type,
        metadata_id=metadata_id,
        last_played=last_played,
        is_favorite=is_favorite,
        rec_shown_count=rec_shown_count,
    )
    session.add(ch)
    session.flush()
    return ch


def _metadata(session, title, *, genres=None, cast=None, director=None) -> MetadataDB:
    meta = MetadataDB(
        id=str(uuid.uuid4()),
        title=title,
        genres=genres or [],
        cast=cast or [],
        director=director,
    )
    session.add(meta)
    session.flush()
    return meta


def _rate(session, channel_id, rating):
    session.add(UserRatingDB(channel_id=channel_id, rating=rating))
    session.flush()


def _sc(score, media_type):
    """Minimal stand-in for ScoredChannel — the mixer reads only these two."""
    return SimpleNamespace(score=score, media_type=media_type)


def _scp(score, people):
    """Stand-in for the people-diversity re-rank (reads .score + .score_people)."""
    return SimpleNamespace(score=score, media_type="movie", score_people=tuple(people))


# --------------------------------------------------------------------------- #
# 1. Damped share math
# --------------------------------------------------------------------------- #

def test_damped_share_hits_the_target_case():
    """100 movies : 15 series → ~72 : 28 → 7 movie / 3 series in a 10-slot list."""
    from metatv.core.media_mix import damped_media_share, format_media_share, split_slots

    share = damped_media_share(100, 15)
    assert 0.71 < share < 0.73, share                 # √100 : √15 = 10 : 3.87
    assert format_media_share(share) == "72 : 28"
    assert split_slots(10, share, movies_available=50, series_available=50) == (7, 3)


def test_damped_share_keeps_even_and_extreme_histories_intact():
    from metatv.core.media_mix import damped_media_share

    assert damped_media_share(50, 50) == 0.5      # balanced stays balanced
    assert damped_media_share(7, 7) == 0.5
    assert damped_media_share(100, 0) == 1.0      # one-sided stays one-sided
    assert damped_media_share(0, 40) == 0.0


def test_damped_share_cold_starts_at_even():
    """No engagement at all → 50/50, not a divide-by-zero or an all-movies list."""
    from metatv.core.media_mix import damped_media_share
    assert damped_media_share(0, 0) == 0.5


def test_damping_narrows_the_gap_versus_raw_proportion():
    """The whole point of the √: a 10:1 engagement gap must not become a 10:1 list."""
    from metatv.core.media_mix import damped_media_share

    raw = 100 / (100 + 10)             # 0.909 — what a plain proportion would give
    damped = damped_media_share(100, 10)
    assert damped < raw
    assert damped > 0.5                # …but still leans the way the user leans


# --------------------------------------------------------------------------- #
# 2. Slot allocation + interleave
# --------------------------------------------------------------------------- #

def test_mix_allocates_by_share_and_spreads_the_minority():
    from metatv.core.media_mix import mix_media_types

    movies = [_sc(100 - i, "movie") for i in range(20)]
    series = [_sc(50 - i, "series") for i in range(20)]
    out = mix_media_types(movies + series, slots=10, movie_share=0.72)

    kinds = [s.media_type for s in out]
    assert kinds.count("movie") == 7 and kinds.count("series") == 3
    # The three series are spread through the list, not dumped at the end.
    assert kinds[-1] == "series" or kinds.index("series") <= 3
    assert max(_run_length(kinds)) <= 3


def _run_length(kinds: list[str]) -> list[int]:
    runs, current = [], 1
    for prev, cur in zip(kinds, kinds[1:]):
        current = current + 1 if cur == prev else 1
        runs.append(current)
    return runs or [1]


def test_mix_refills_when_one_type_runs_short():
    """A short candidate pool must not shrink the list below the cap."""
    from metatv.core.media_mix import mix_media_types

    movies = [_sc(100 - i, "movie") for i in range(9)]
    series = [_sc(50, "series")]
    out = mix_media_types(movies + series, slots=6, movie_share=0.3)
    assert len(out) == 6
    assert [s.media_type for s in out].count("series") == 1  # only one existed


def test_mix_single_type_returns_top_slots_unchanged():
    from metatv.core.media_mix import mix_media_types
    movies = [_sc(10, "movie"), _sc(8, "movie"), _sc(6, "movie")]
    assert [s.score for s in mix_media_types(movies, 2, 0.5)] == [10, 8]


# --------------------------------------------------------------------------- #
# 3. Engagement counts + resolution against a real DB
# --------------------------------------------------------------------------- #

def _engagement_fixture(session):
    """3 movie signals (like, favorite, play) and 1 series signal (queued)."""
    liked = _channel(session, "EN - Liked Movie")
    _rate(session, liked.id, 1)
    _channel(session, "EN - Fav Movie", is_favorite=True)
    _channel(session, "EN - Played Movie", last_played=datetime(2024, 1, 1))
    queued = _channel(session, "EN - Queued Series", media_type="series")
    session.add(WatchQueueDB(channel_id=queued.id, channel_name=queued.name,
                             media_type="series"))
    # A disliked movie and an untouched series are NOT positive signals.
    disliked = _channel(session, "EN - Disliked Movie")
    _rate(session, disliked.id, -1)
    _channel(session, "EN - Untouched Series", media_type="series")
    session.commit()


def test_media_engagement_counts_sums_positive_signals(tmp_path):
    from metatv.core.media_mix import media_engagement_counts

    db = _make_db(tmp_path / "engagement.db")
    session = db.get_session()
    try:
        _engagement_fixture(session)
        assert media_engagement_counts(session) == (3, 1)
    finally:
        session.close()
        db.close()


def test_resolve_media_share_automatic_uses_engagement(tmp_path):
    from metatv.core.media_mix import MEDIA_MIX_AUTOMATIC, resolve_media_share

    db = _make_db(tmp_path / "resolve_auto.db")
    session = db.get_session()
    try:
        _engagement_fixture(session)                       # 3 movie : 1 series
        share = resolve_media_share(session, MEDIA_MIX_AUTOMATIC)
        assert abs(share - (3 ** 0.5) / (3 ** 0.5 + 1)) < 1e-9
        assert 0.6 < share < 0.65                          # damped, not 0.75
    finally:
        session.close()
        db.close()


def test_resolve_media_share_honors_explicit_override_and_none(tmp_path):
    from metatv.core.media_mix import resolve_media_share

    db = _make_db(tmp_path / "resolve_explicit.db")
    session = db.get_session()
    try:
        _engagement_fixture(session)
        assert resolve_media_share(session, 0.25) == 0.25   # user's number wins
        assert resolve_media_share(session, 4.0) == 1.0     # clamped
        assert resolve_media_share(session, None) is None   # "don't mix"
    finally:
        session.close()
        db.close()


def test_resolve_media_share_cold_start_is_even(tmp_path):
    """A library with no engagement at all resolves to 50/50."""
    from metatv.core.media_mix import MEDIA_MIX_AUTOMATIC, resolve_media_share

    db = _make_db(tmp_path / "resolve_cold.db")
    session = db.get_session()
    try:
        _channel(session, "EN - Never Touched")
        session.commit()
        assert resolve_media_share(session, MEDIA_MIX_AUTOMATIC) == 0.5
    finally:
        session.close()
        db.close()


# --------------------------------------------------------------------------- #
# 4. score_candidates end-to-end with a media mix
# --------------------------------------------------------------------------- #

def _mix_fixture(session, *, series_signals: int = 0):
    """Liked Action movies (so movies out-score series) plus plenty of both types.

    ``series_signals`` queues that many series, giving the automatic mix a series
    engagement count to work with.
    """
    for tag in ("A", "B"):
        m = _metadata(session, f"Liked {tag}", genres=["Action"], cast=[{"name": "Star"}])
        ch = _channel(session, f"EN - Liked {tag}", metadata_id=m.id,
                      last_played=datetime(2024, 1, 1))
        _rate(session, ch.id, 1)
    for i in range(12):
        m = _metadata(session, f"Cand Movie {i}", genres=["Action"], cast=[{"name": "Star"}])
        _channel(session, f"EN - Cand Movie {i}", metadata_id=m.id)
    for i in range(12):
        m = _metadata(session, f"Cand Series {i}", genres=["Action"])
        _channel(session, f"EN - Cand Series {i}", media_type="series", metadata_id=m.id)
    for i in range(series_signals):
        q = _channel(session, f"EN - Queued Series {i}", media_type="series")
        session.add(WatchQueueDB(channel_id=q.id, channel_name=q.name, media_type="series"))
    session.commit()


def test_automatic_mix_reflects_engagement_without_starving_series(tmp_path):
    """4 movie signals : 1 series signal → 2:1 damped → series still get slots."""
    from metatv.core.media_mix import MEDIA_MIX_AUTOMATIC
    from metatv.core.preference_engine import compute_weights, score_candidates

    db = _make_db(tmp_path / "mix_auto.db")
    session = db.get_session()
    try:
        # _mix_fixture watches 2 liked movies (2 like + 2 play = 4 movie signals).
        _mix_fixture(session, series_signals=1)
        weights = compute_weights(session)
        recs = score_candidates(session, weights, limit=9,
                                media_mix=MEDIA_MIX_AUTOMATIC)
        kinds = [r.media_type for r in recs]
        assert len(recs) == 9
        # √4 : √1 = 2 : 1 → 6 movies / 3 series.
        assert kinds.count("movie") == 6 and kinds.count("series") == 3
    finally:
        session.close()
        db.close()


def test_explicit_mix_overrides_the_automatic_share(tmp_path):
    """The user's slider wins over engagement, even against the score order."""
    from metatv.core.preference_engine import compute_weights, score_candidates

    db = _make_db(tmp_path / "mix_explicit.db")
    session = db.get_session()
    try:
        _mix_fixture(session)                      # engagement is all-movies
        weights = compute_weights(session)
        recs = score_candidates(session, weights, limit=10, media_mix=0.2)
        kinds = [r.media_type for r in recs]
        assert kinds.count("movie") == 2 and kinds.count("series") == 8
    finally:
        session.close()
        db.close()


def test_bare_engine_call_is_unchanged_by_the_new_parameters(tmp_path):
    """No settings, no mix → the raw ranking, exactly as before this feature."""
    from metatv.core.preference_engine import (
        DEFAULT_REC_SETTINGS, compute_weights, score_candidates,
    )

    db = _make_db(tmp_path / "mix_default.db")
    session = db.get_session()
    try:
        _mix_fixture(session)
        weights = compute_weights(session)
        bare = score_candidates(session, weights, limit=6)
        assert [r.media_type for r in bare] == ["movie"] * 6    # movies out-score series
        # Passing the shipped defaults explicitly must be indistinguishable.
        assert DEFAULT_REC_SETTINGS.media_mix is None
        with_defaults = score_candidates(session, weights, limit=6,
                                         settings=DEFAULT_REC_SETTINGS)
        assert [r.channel_id for r in with_defaults] == [r.channel_id for r in bare]
    finally:
        session.close()
        db.close()


def test_settings_media_mix_applies_without_an_explicit_parameter(tmp_path):
    """Call sites can steer purely through RecScoringSettings.from_config()."""
    from metatv.core.preference_engine import (
        RecScoringSettings, compute_weights, score_candidates,
    )

    db = _make_db(tmp_path / "mix_via_settings.db")
    session = db.get_session()
    try:
        _mix_fixture(session)
        weights = compute_weights(session)
        settings = RecScoringSettings(media_mix=0.5)
        recs = score_candidates(session, weights, limit=8, settings=settings)
        kinds = [r.media_type for r in recs]
        assert kinds.count("movie") == 4 and kinds.count("series") == 4
    finally:
        session.close()
        db.close()


# --------------------------------------------------------------------------- #
# 5. The engine reads the scoring dials
# --------------------------------------------------------------------------- #

def test_dial_actor_min_support_lets_a_single_title_actor_count(tmp_path):
    from metatv.core.preference_engine import RecScoringSettings, compute_weights

    db = _make_db(tmp_path / "dial_support.db")
    session = db.get_session()
    try:
        m = _metadata(session, "Liked", genres=["Action"], cast=[{"name": "One Off"}])
        ch = _channel(session, "EN - Liked", metadata_id=m.id)
        _rate(session, ch.id, 1)
        session.commit()

        assert "One Off" not in compute_weights(session).actors          # gate at 2
        loosened = compute_weights(session, settings=RecScoringSettings(actor_min_support=1))
        assert loosened.actors["One Off"] > 0                            # gate at 1
    finally:
        session.close()
        db.close()


def test_dial_cast_weight_zero_removes_cast_affinity(tmp_path):
    from metatv.core.preference_engine import RecScoringSettings, compute_weights

    db = _make_db(tmp_path / "dial_actor_weight.db")
    session = db.get_session()
    try:
        for tag in ("A", "B"):
            m = _metadata(session, f"Liked {tag}", genres=["Action"],
                          cast=[{"name": "Star"}])
            ch = _channel(session, f"EN - Liked {tag}", metadata_id=m.id)
            _rate(session, ch.id, 1)
        session.commit()

        assert compute_weights(session).actors["Star"] > 0
        muted = compute_weights(session, settings=RecScoringSettings(actor_weight=0.0))
        assert muted.actors["Star"] == 0.0
    finally:
        session.close()
        db.close()


def test_dial_impression_decay_changes_the_score(tmp_path):
    """A shown item is penalized by the configured rate — 0 disables the fade."""
    from metatv.core.preference_engine import (
        RecScoringSettings, compute_weights, score_candidates,
    )

    db = _make_db(tmp_path / "dial_impression.db")
    session = db.get_session()
    try:
        m = _metadata(session, "Liked", genres=["Action"])
        liked = _channel(session, "EN - Liked", metadata_id=m.id,
                         last_played=datetime(2024, 1, 1))
        _rate(session, liked.id, 1)
        cm = _metadata(session, "Cand", genres=["Action"])
        _channel(session, "EN - Cand", metadata_id=cm.id, rec_shown_count=5)
        session.commit()

        weights = compute_weights(session)
        default = score_candidates(session, weights, limit=5)[0].score
        undecayed = score_candidates(
            session, weights, limit=5, settings=RecScoringSettings(impression_decay=0.0)
        )[0].score
        harsh = score_candidates(
            session, weights, limit=5, settings=RecScoringSettings(impression_decay=0.1)
        )[0].score
        assert harsh < default < undecayed
        assert abs(default - undecayed * 0.8) < 1e-9   # 5 impressions × 4%
    finally:
        session.close()
        db.close()


def test_dial_liked_cap_limits_already_liked_slots(tmp_path):
    from metatv.core.preference_engine import (
        RecScoringSettings, compute_weights, score_candidates,
    )

    db = _make_db(tmp_path / "dial_liked_cap.db")
    session = db.get_session()
    try:
        # Five liked-but-unwatched Action titles. A liked title is normally
        # suppressed by its own engagement fingerprint; the user's "show this
        # separately" override (dedupe_overrides) is what puts liked items back in
        # the candidate pool — which is exactly where the liked cap applies.
        liked_ids = []
        for i in range(5):
            m = _metadata(session, f"Liked {i}", genres=["Action"])
            ch = _channel(session, f"EN - Liked {i}", metadata_id=m.id)
            _rate(session, ch.id, 1)
            liked_ids.append(ch.id)
        for i in range(5):
            m = _metadata(session, f"Fresh {i}", genres=["Action"])
            _channel(session, f"EN - Fresh {i}", metadata_id=m.id)
        session.commit()

        weights = compute_weights(session)
        overrides = set(liked_ids)
        default = score_candidates(session, weights, limit=6, dedupe_overrides=overrides)
        assert sum(1 for r in default if r.already_liked) == 3       # shipped cap
        tightened = score_candidates(session, weights, limit=6, dedupe_overrides=overrides,
                                     settings=RecScoringSettings(liked_cap=1))
        assert sum(1 for r in tightened if r.already_liked) == 1
    finally:
        session.close()
        db.close()


def test_dial_people_diversity_decay_off_preserves_score_order():
    from metatv.core.preference_engine import _diversify_people

    ranked = [_scp(10, ["Star"]), _scp(9, ["Star"]), _scp(8, [])]
    spread = _diversify_people(ranked)                       # default 0.5 → re-ranks
    assert spread[1] is ranked[2]
    off = _diversify_people(ranked, decay=1.0)                # 1.0 → no knock-down
    assert [s.score for s in off] == [10, 9, 8]


# --------------------------------------------------------------------------- #
# 6. Config — one shared key, defaults tracked, round-trips to disk
# --------------------------------------------------------------------------- #

def test_config_defaults_resolve_to_shipped_dials_and_automatic_mix():
    from metatv.core.config import Config
    from metatv.core.media_mix import MEDIA_MIX_AUTOMATIC
    from metatv.core.preference_engine import RecScoringSettings

    resolved = RecScoringSettings.from_config(Config())
    defaults = RecScoringSettings()
    assert resolved.genre_weight == defaults.genre_weight
    assert resolved.actor_min_support == defaults.actor_min_support
    assert resolved.impression_decay == defaults.impression_decay
    assert resolved.liked_cap == defaults.liked_cap
    # The one inversion: an untouched rec_media_mix means Automatic for the app,
    # while the bare engine default is "don't mix".
    assert resolved.media_mix == MEDIA_MIX_AUTOMATIC
    assert defaults.media_mix is None


def test_config_overrides_reach_the_engine():
    from metatv.core.config import Config
    from metatv.core.preference_engine import RecScoringSettings

    config = Config()
    config.rec_media_mix = 0.8
    config.rec_weight_actor = 0.9
    config.rec_actor_min_support = 4
    config.rec_impression_decay = 0.1

    resolved = RecScoringSettings.from_config(config)
    assert resolved.media_mix == 0.8
    assert resolved.actor_weight == 0.9
    assert resolved.actor_min_support == 4
    assert resolved.impression_decay == 0.1
    assert resolved.genre_weight == RecScoringSettings().genre_weight   # untouched


def test_config_round_trips_the_steering_keys_through_yaml():
    """Save → load from the (isolated) user config dir keeps every dial."""
    from metatv.core.config import Config
    from metatv.core.preference_engine import RecScoringSettings

    config = Config()
    config.rec_media_mix = 0.35
    config.rec_weight_director = 2.25
    config.rec_liked_cap = 0
    config.rec_people_diversity_decay = 0.75
    config.save()

    loaded, _ = Config.load()
    assert loaded.rec_media_mix == 0.35
    assert loaded.rec_weight_director == 2.25
    assert loaded.rec_liked_cap == 0
    assert loaded.rec_people_diversity_decay == 0.75
    assert RecScoringSettings.from_config(loaded).media_mix == 0.35

    # Back to Automatic → the key is cleared, not frozen at the old number.
    loaded.rec_media_mix = None
    loaded.save()
    reloaded, _ = Config.load()
    assert reloaded.rec_media_mix is None


# --------------------------------------------------------------------------- #
# 7. Settings panel — the dials persist, defaults stay unfrozen
# --------------------------------------------------------------------------- #

def test_settings_panel_saves_dials_and_shared_mix_key(qapp):
    from metatv.core.config import Config
    from metatv.gui.settings_dialog import SettingsDialog

    config = Config()
    dialog = SettingsDialog(config)
    try:
        # Defaults on open: Automatic ticked, percentage control inert.
        assert dialog._rec_mix_auto_check.isChecked()
        assert not dialog._rec_mix_spin.isEnabled()
        assert dialog._rec_genre_spin.value() == 1.0
        assert dialog._rec_impression_spin.value() == 4

        dialog._rec_mix_auto_check.setChecked(False)
        dialog._rec_mix_spin.setValue(80)
        dialog._rec_actor_spin.setValue(0.0)
        dialog._rec_actor_support_spin.setValue(4)
        dialog._save_values()

        assert config.rec_media_mix == 0.8          # the ONE shared key
        assert config.rec_weight_actor == 0.0
        assert config.rec_actor_min_support == 4
        # Untouched dials stay None so they keep tracking the shipped default.
        assert config.rec_weight_genre is None
        assert config.rec_liked_cap is None
    finally:
        dialog.deleteLater()


def test_settings_panel_reset_restores_defaults(qapp):
    from metatv.core.config import Config
    from metatv.core.preference_engine import RecScoringSettings
    from metatv.gui.settings_dialog import SettingsDialog

    config = Config()
    config.rec_media_mix = 0.9
    config.rec_weight_actor = 1.2
    dialog = SettingsDialog(config)
    try:
        assert not dialog._rec_mix_auto_check.isChecked()   # restored the override
        assert dialog._rec_mix_spin.value() == 90
        assert dialog._rec_actor_spin.value() == 1.2

        dialog._reset_recommendation_defaults()
        dialog._save_values()

        assert config.rec_media_mix is None                 # back to Automatic
        assert config.rec_weight_actor is None
        assert RecScoringSettings.from_config(config).actor_weight == \
            RecScoringSettings().actor_weight
    finally:
        dialog.deleteLater()


# --------------------------------------------------------------------------- #
# 8. Dashboard slider — the main-thread half
# --------------------------------------------------------------------------- #

def _make_mix_view(qapp, config):
    """A PreferencesView with only its mix controls built (no DB, no layout)."""
    from PyQt6.QtWidgets import QHBoxLayout, QWidget
    from metatv.gui.preferences_view import PreferencesView

    view = PreferencesView.__new__(PreferencesView)
    QWidget.__init__(view)
    view.config = config
    view.refresh = lambda: None          # the re-score is exercised elsewhere
    view._build_mix_controls(QHBoxLayout(view))
    return view


def test_dashboard_slider_shows_the_automatic_ratio(qapp):
    from metatv.core.config import Config

    view = _make_mix_view(qapp, Config())
    try:
        assert view._mix_label.text() == "Automatic"       # no share known yet
        view._update_mix_controls(0.7208)                   # engine reports 72 : 28
        assert view._mix_label.text() == "Automatic (72 : 28)"
        assert view._mix_slider.value() == 72               # handle parks on it
        assert not view._mix_auto_btn.isEnabled()           # already automatic
    finally:
        view.deleteLater()


def test_dashboard_slider_override_persists_and_restores(qapp):
    from metatv.core.config import Config

    config = Config()
    view = _make_mix_view(qapp, config)
    try:
        view._mix_slider.setValue(30)                       # user drags the slider
        assert view._mix_label.text() == "30 : 70"          # live preview, no "Automatic"
        view._apply_mix_override()                          # debounce fires
        assert config.rec_media_mix == 0.3
        assert view._mix_auto_btn.isEnabled()
    finally:
        view.deleteLater()

    # A fresh view restores the override rather than defaulting to Automatic.
    restored = _make_mix_view(qapp, config)
    try:
        assert restored._mix_slider.value() == 30
        assert restored._mix_label.text() == "30 : 70"
        restored._on_mix_automatic()                        # "Automatic" pressed
        assert config.rec_media_mix is None
        assert not restored._mix_auto_btn.isEnabled()
    finally:
        restored.deleteLater()
