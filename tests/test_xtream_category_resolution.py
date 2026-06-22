"""Provider category-name resolution at ingestion.

Xtream stream objects carry only a numeric ``category_id``; the human category
*name* (e.g. "USA | NETFLIX") lives in the separate get_*_categories endpoint.
The loader must JOIN them so every channel stores the provider's own category —
the richest, 100%-coverage attribute source — instead of a bare number.

These drive ``XtreamAPI.convert_to_channel`` directly (no network: __init__ only
stores credentials; convert_to_channel is sync and uses no session).
"""

from __future__ import annotations

from metatv.providers.xtream import XtreamAPI
from metatv.core.models import MediaType


def _api() -> XtreamAPI:
    return XtreamAPI("http://x.example.com", "user", "pass")


def test_category_id_resolves_to_name():
    """A channel's category is the NAME its category_id points to, not the id."""
    api = _api()
    cat_map = {"865": "USA | NETFLIX", "343": "UK | SPORTS"}
    ch = api.convert_to_channel(
        {"stream_id": 1, "name": "Some Show", "category_id": "865"},
        "prov1", MediaType.LIVE, cat_map,
    )
    assert ch.category == "USA | NETFLIX", "category_id must resolve to the category name"
    assert ch.category_id == "865", "the raw id is still preserved"


def test_numeric_category_id_resolves():
    """category_id arriving as an int still matches the (stringified) map key."""
    api = _api()
    ch = api.convert_to_channel(
        {"stream_id": 2, "name": "Film", "category_id": 343},
        "prov1", MediaType.MOVIE, {"343": "UK | SPORTS"},
    )
    assert ch.category == "UK | SPORTS"
    assert ch.category_id == "343"


def test_falls_back_to_inline_name_then_empty():
    """Unknown id → inline category_name if present; no map + no inline → empty."""
    api = _api()
    # id not in map → fall back to an inline name when the provider supplied one
    ch = api.convert_to_channel(
        {"stream_id": 3, "name": "X", "category_id": "999", "category_name": "Inline"},
        "prov1", MediaType.LIVE, {"865": "USA | NETFLIX"},
    )
    assert ch.category == "Inline"

    # no map at all and no inline name → empty (the pre-fix behaviour; no crash)
    ch2 = api.convert_to_channel(
        {"stream_id": 4, "name": "Y", "category_id": "5"}, "prov1", MediaType.LIVE,
    )
    assert ch2.category == ""
    assert ch2.category_id == "5"
