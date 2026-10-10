"""A country NAME leading a provider group label is a region, like its code.

"SWEDEN SOCCER PPV" carried Sweden only in words, so 3,075 prefix-less live
channels had no region and Global Exclusions could not see them.
"""
from metatv.core.channel_name_utils import REGION_FULL_NAMES, leading_country
from metatv.core.config import Config
from metatv.core.tag_decomposer import decompose, region_code_from_category


def test_a_leading_country_name_is_peeled_off_the_label():
    assert leading_country("SWEDEN SOCCER PPV") == ("SWE", "SOCCER PPV")
    assert leading_country("Kuwait +6H NA") == ("KW", "+6H NA")
    assert leading_country("SOCCER SWEDEN") is None, "only at the start"


def test_the_label_yields_the_region_and_keeps_the_rest():
    cfg = Config()
    assert region_code_from_category("NORWAY TV2 PLAY PPV VIP", config=cfg) == "NOR"
    tags = decompose("provider_category", "FINLAND VIAPLAY PPV", config=cfg)
    assert ("region", "FIN") in [(t, v) for t, v, _c in tags]
    assert not any(v.upper().startswith("FINLAND") for t, v, _c in tags if t == "collection")


def test_new_country_codes_have_display_names():
    assert REGION_FULL_NAMES["KW"] == "Kuwait"


def test_the_v14_backfill_fills_the_region_of_country_labelled_channels(db):
    from metatv.core.database import ChannelDB
    from metatv.core.migrations.tag_backfill import TagBackfillTask
    with db.session_scope() as s:
        s.add(ChannelDB(id="se", source_id="1", provider_id="p", name="TV4 SPORT",
                        media_type="live", category="SWEDEN SOCCER PPV"))
        s.add(ChannelDB(id="plain", source_id="2", provider_id="p", name="X",
                        media_type="live", category="SOCCER PPV"))
    task = TagBackfillTask(db)
    assert task._collect_channel_ids_country_label(Config()) == ["se"]
    with db.session_scope() as s:
        assert s.get(ChannelDB, "se").detected_region == "SWE"
        assert s.get(ChannelDB, "plain").detected_region in (None, "")
