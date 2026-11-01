"""A trailing code is a region only if the region table knows it (ledger F4).

On the owner's library 113 of 259 stored region codes had no name (1,446 rows):
"SUB" 675 and "DUB" 465 led, then "DOC", "(BK)" backup feeds, team codes.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import parse_channel_name


@pytest.mark.parametrize("name, audio", [("|ALB| The Munsters (SUB)", "Sub"),
                                         ("IR - To Cook A Bear (DUB)", "Dub")])
def test_sub_and_dub_in_parentheses_are_audio_not_a_region(name, audio):
    parsed = parse_channel_name(name)
    assert parsed.audio == audio
    assert parsed.lang == ""
    assert "(" not in parsed.bare_name


@pytest.mark.parametrize("name, kept", [("IR - Sarevo (DOC)", "(DOC)"),
                                        ("RS| ARENA SPORT 1 FHD (BK)", "(BK)"),
                                        ("AHL-TEAM| TORONTO MARLIES [TOR]", "[TOR]")])
def test_an_unknown_code_stays_in_the_name_and_is_no_region(name, kept):
    parsed = parse_channel_name(name)
    assert parsed.lang == ""
    assert parsed.bare_name.endswith(kept)


@pytest.mark.parametrize("name, lang", [("ES - Formula 1 2024 Monza [SPA]", "ES"),
                                        ("ZZ - Rang Panjab (PNJ)", "PB"),
                                        ("QFR - Family Guy (VFQ)", "")])   # same as the prefix → no override
def test_language_codes_providers_append_are_known(name, lang):
    assert parse_channel_name(name).lang == lang


def test_a_known_code_in_parentheses_is_still_the_region():
    assert parse_channel_name("EN - Anger Management (US)").lang == "US"


def test_the_cleanup_clears_unnamed_regions_and_keeps_named_ones(db):
    from metatv.core.database import ChannelDB
    from metatv.core.migrations.unknown_region_cleanup import UnknownRegionCleanupTask
    with db.session_scope() as s:
        for cid, region in (("a", "SUB"), ("b", "DOC"), ("c", "FR"), ("d", None)):
            s.add(ChannelDB(id=cid, source_id=cid, provider_id="p", name=cid, detected_region=region))
    UnknownRegionCleanupTask(db).run(lambda *_: None, lambda: False)
    with db.session_scope() as s:
        got = {c.id: c.detected_region for c in s.query(ChannelDB)}
    assert got["c"] == "FR" and got["d"] is None
    assert not got["a"] and not got["b"]


def test_the_cleanup_runs_before_the_reparse():
    from metatv.core.migrations.registry import TASKS
    order = [module for module, _cls, _extra in TASKS]
    assert order.index("unknown_region_cleanup") < order.index("detected_title_reparse")
