"""PPV is a content type, and an exclusion covers every code of its country."""
from types import SimpleNamespace

from metatv.core.region_codes import code_family
from metatv.core.config import Config
from metatv.core.filter_utils import get_active_category_filter, get_excluded_prefixes
from metatv.core.tag_decomposer import decompose


def _tags(label):
    return [(t, v) for t, v, _c in decompose("provider_category", label, config=Config())]


def test_ppv_is_a_content_type_not_part_of_a_collection():
    tags = _tags("SWEDEN SOCCER PPV")
    assert ("content_type", "ppv") in tags
    assert ("collection", "Soccer") in tags
    assert not any("ppv" in v.lower() for t, v in tags if t == "collection")
    assert ("content_type", "ppv") in _tags("PAY PER VIEW")


def test_excluding_one_code_hides_the_country_s_other_codes():
    assert code_family(["DK"]) >= {"DK", "DNK", "DEN"}
    assert code_family(["SWE"]) >= {"SE", "SW", "SWE"}
    assert code_family(["NF"]) == {"NF"}, "a platform has no country family"
    cfg = SimpleNamespace(global_filter_paused=False, global_filter_excluded_categories=["DK"],
                          global_filter_include_uncategorized=True,
                          global_filter_excluded_prefixes=["NO"])
    assert "DEN" in get_active_category_filter(cfg)[0]
    assert "NOR" in get_excluded_prefixes(cfg)


def test_the_v15_backfill_picks_ppv_labelled_channels(db):
    from metatv.core.database import ChannelDB
    from metatv.core.migrations.tag_backfill import TagBackfillTask
    with db.session_scope() as s:
        s.add(ChannelDB(id="ppv", source_id="1", provider_id="p", name="A", media_type="live",
                        category="SWEDEN SOCCER PPV"))
        s.add(ChannelDB(id="no", source_id="2", provider_id="p", name="B", media_type="live",
                        category="SWEDEN SPORT"))
    assert TagBackfillTask(db)._collect_channel_ids_ppv_label() == ["ppv"]
