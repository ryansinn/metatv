"""Which name prefixes the parser knows — and what reaches the screen and the DB.

Source Analytics' "Unrecognized prefixes" tested against quality ∪ region ∪
platform only, so on the owner's library it reported 217 prefixes (17,766 rows)
as unknown — status words, BLURAY, WESTERN, AFR, MULTI and every compound among
them. ``prefix_vocabulary`` asks the tables the parser reads instead.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from metatv.core.database import ChannelDB
from metatv.core.event_datetime import parse_event_window
from metatv.core.prefix_vocabulary import is_known_prefix, prefix_genres, prefix_part_kind


@pytest.mark.parametrize("token, kind", [
    ("LIVE", "status"), ("NEXT", "status"), ("END", "status"), ("ENDED", "status"),
    ("TV", "type"), ("BLURAY", "source"), ("WEB-DL", "source"), ("MULTI", "audio"),
    ("AFR", "region"), ("WESTERN", "genre"), ("4K", "quality"), ("NF", "platform"),
])
def test_each_kind_comes_from_its_own_table(token, kind):
    assert prefix_part_kind(token) == kind


@pytest.mark.parametrize("prefix", ["BLURAY-DE", "WESTERN-DE", "UK-NOWTV", "4K-DE"])
def test_a_compound_is_known_when_every_part_is(prefix):
    assert is_known_prefix(prefix)


@pytest.mark.parametrize("prefix", ["XX", "A3", "DE-XQ", "-DE", "CAR-AMP"])
def test_an_unknown_part_keeps_the_prefix_unknown(prefix):
    assert not is_known_prefix(prefix)


def test_a_genre_part_names_its_genre():
    assert prefix_genres("WESTERN-DE") == ["Western"]
    assert prefix_genres("BLURAY-DE") == []


def test_the_tagger_files_a_genre_prefix_under_that_genre(qapp):
    from metatv.core.config import Config
    from metatv.core.tag_decomposer import decompose_name_parse
    tags = decompose_name_parse(detected_prefix="WESTERN-DE", detected_quality=None,
                                detected_region="DE", detected_year=None, config=Config())
    assert ("genre", "Western") in {(t, v) for t, v, _ in tags}


@pytest.mark.parametrize("zone, utc_hour", [("+03 (SA)", 19), ("-02 (BR)", 0), ("+0530", 16)])
def test_a_numeric_zone_offset_converts(zone, utc_hour):
    window = parse_event_window(f"ENDED | DR7 VS. 3BS | Mon 26 Oct 22:00 {zone} | 8K",
                                reference=date(2026, 10, 31))
    assert window.start is not None and window.start.hour == utc_hour


def _channel(name: str) -> ChannelDB:
    return ChannelDB(id=str(uuid.uuid4()), source_id="s", provider_id="p", name=name,
                     media_type="live", stream_url="http://x/1")


def test_a_day_name_ppv_listing_is_categorised_and_stores_its_time():
    from metatv.core.special_content import update_channel_special_content
    ch = _channel("ENDED | PITCH 10B | DAY 3: MORNING SESSION | Mon 26 Oct 01:00 EDT (US) "
                  "| 8K EXCLUSIVE | US: FIFA+ PPV 1")
    assert update_channel_special_content(ch) is True
    assert ch.special_view == "ppv"
    assert ch.event_start_time is not None
    assert (ch.event_start_time.month, ch.event_start_time.day, ch.event_start_time.hour) == (10, 26, 5)


def test_a_dated_sports_listing_stays_in_sports():
    from metatv.core.special_content import detect_and_categorize_channel
    ch = _channel("Next | Gary Parrish Show | NBA | 2026-10-27 | 15:00 (GMT) | 8K EXCLUSIVE | US: DAZN PPV 2")
    assert detect_and_categorize_channel(ch) == "sports"


def test_an_undated_ppv_listing_is_still_not_a_ppv_event():
    from metatv.core.special_content import detect_and_categorize_channel
    ch = _channel("Live | Center Court Live | all | 8K EXCLUSIVE | US: SOCCER PPV 28")
    assert detect_and_categorize_channel(ch) != "ppv"


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed(db):
    from metatv.core.database import ProviderDB
    with db.session_scope() as s:
        s.add(ProviderDB(id="trex", name="TREX", type="xtream", url="http://t", username="u",
                         password="p", is_active=True))
        rows = [("ENDED", "live", 3), ("BLURAY-DE", "movie", 2), ("WESTERN-DE", "movie", 2),
                ("T2", "live", 4), ("FRQ", "movie", 5), ("MH", "series", 1), ("FRQ", "series", 2)]
        for prefix, media, n in rows:
            for i in range(n):
                s.add(ChannelDB(id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="trex",
                                name=f"{prefix}| {media} {i}", media_type=media, detected_prefix=prefix))


def test_the_repository_lists_only_unknowns_grouped_live_films_series(file_db):
    from metatv.core.repositories import RepositoryFactory
    _seed(file_db)
    with file_db.session_scope() as s:
        stats = RepositoryFactory(s).analytics.unrecognized_prefixes("trex")
        got = [(p.prefix, p.media_type, p.count) for p in stats]
    assert got == [("T2", "live", 4), ("FRQ", "movie", 5), ("FRQ", "series", 2), ("MH", "series", 1)]


def test_the_tab_shows_a_heading_per_type_in_order(qapp, file_db):
    from PyQt6.QtWidgets import QLabel

    from metatv.gui.provider_editor import ProviderEditorView
    from tests.conftest import destroy_widget
    _seed(file_db)
    ed = ProviderEditorView(file_db)
    ed.resize(1300, 1600)
    ed.show()
    ed._tabs.setCurrentWidget(ed._analytics_scroll)
    ed.load_provider("trex")
    qapp.processEvents()
    try:
        section = ed._analytics_tab._prefixes
        assert section.subtitle.text() == "3 the name parser does not know"
        labels = [lbl for lbl in section.findChildren(QLabel) if lbl.isVisible()]
        texts = [lbl.text() for lbl in labels]
        assert "ENDED" not in texts and "BLURAY-DE" not in texts
        headings = [lbl for lbl in labels if " · " in lbl.text()]
        assert [h.text() for h in headings] == ["Live channels · 1", "Films · 1", "Series · 2"]
        # The types sit side by side, live → films → series, each row under its heading.
        pos = {lbl.text(): lbl.mapTo(section, lbl.rect().topLeft()) for lbl in labels}
        pj = sorted((lbl.mapTo(section, lbl.rect().topLeft()) for lbl in labels if lbl.text() == "FRQ"),
                    key=lambda p: p.x())
        assert pos["Live channels · 1"].x() < pos["Films · 1"].x() < pos["Series · 2"].x()
        assert pos["T2"].x() == pos["Live channels · 1"].x() and pos["T2"].y() > pos["Live channels · 1"].y()
        assert pj[0].x() == pos["Films · 1"].x() and pj[1].x() == pos["Series · 2"].x()
    finally:
        destroy_widget(ed)


@pytest.mark.parametrize("code, canonical", [("KA", "KN"), ("PJ", "PB"), ("PU", "PB"), ("QC", "QFR")])
def test_provider_spellings_of_known_languages(code, canonical):
    """TREX's KA/PJ/PU are Kannada/Punjabi and QC is Quebec (owner, 2026-10-31)."""
    from metatv.core.region_codes import normalize_region_code
    assert normalize_region_code(code) == canonical


@pytest.mark.parametrize("prefix", ["IN-KA", "IN-PU", "IN-PREM", "PB-PREM", "PAK-PREM", "QC", "DE-TOP", "AHL-TEAM"])
def test_region_language_and_premium_compounds_are_known(prefix):
    assert is_known_prefix(prefix)


def test_prem_is_a_prefix_word_only_never_a_title_tier():
    """"Prem" is a common word in Hindi film titles; the parser must keep it."""
    from metatv.core.quality_vocab import PREFIX_TIER_TOKENS, TIER_TOKENS
    assert "PREM" in PREFIX_TIER_TOKENS and "PREM" not in TIER_TOKENS


def test_a_camcorder_prefix_is_known_and_tags_cam(qapp):
    """SD/CAM: SD quality AND a camcorder copy (owner: bootlegs, short-lived)."""
    from metatv.core.config import Config
    from metatv.core.tag_decomposer import decompose_name_parse
    assert is_known_prefix("SD/CAM")
    tags = decompose_name_parse(detected_prefix="SD/CAM", detected_quality="SD",
                                detected_region=None, detected_year=None, config=Config())
    assert ("quality", "CAM / Pre-release") in {(t, v) for t, v, _ in tags}
