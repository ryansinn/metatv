"""Leading-pipe prefix parsing (ProSat/ottcst format).

ProSat (Ottcst) names wrap the prefix in pipes: "|WC| BEIN SPORTS 1 HD FR",
"|EN| Breaking Bad". The standard separator patterns expect the prefix *before*
the separator, so they missed this entirely — ~190k ottcst channels parsed to no
prefix and an unstripped title. Both `extract_prefix` (detected_prefix / filter
axis) and `parse_channel_name` (detected_region / detected_title) must handle it.
"""

from metatv.core.filter_utils import extract_prefix
from metatv.core.channel_name_utils import parse_channel_name


def test_extract_prefix_pipe_wrapped():
    assert extract_prefix("|WC| BEIN SPORTS 1 HD FR") == "WC"
    assert extract_prefix("|EN| Breaking Bad") == "EN"


def test_extract_prefix_pipe_inner_space():
    # "|MULTI | Title" — trailing space inside the pipes is tolerated.
    assert extract_prefix("|MULTI | Foo Bar") == "MULTI"


def test_extract_prefix_no_closing_pipe_is_none():
    # PPV/event rows start with "|" but have no closing pipe before a spaced run.
    assert extract_prefix("|PPV MAIN EVENT 01: Usyk vs Dubois") is None


def test_parse_strips_pipe_prefix_to_region():
    p = parse_channel_name("|EN| Breaking Bad")
    assert p.region == "EN"
    assert p.bare_name == "Breaking Bad"


def test_parse_pipe_prefix_keeps_trailing_metadata():
    # Region from pipe; year still stripped from the trailing parens.
    p = parse_channel_name("|AR-4K| Some Movie (2024)")
    assert p.bare_name == "Some Movie"
    assert p.year == "2024"


def test_parse_pipe_no_closing_pipe_left_intact():
    p = parse_channel_name("|PPV MAIN EVENT 01: Usyk vs Dubois")
    assert p.region == ""
    assert p.bare_name == "|PPV MAIN EVENT 01: Usyk vs Dubois"


def test_parse_non_pipe_unaffected():
    # Regression guard: the standard dash form still parses as before.
    p = parse_channel_name("EN - Breaking Bad")
    assert p.region == "EN"
    assert p.bare_name == "Breaking Bad"


# ── Region + parenthetical platform: "US (P+) Title" ──────────────────────────── #
# TREX/Ninja sports feeds lead with a region code then a platform tag in parens.
# The standard separators miss it (no separator right after the code). Accepted only
# for a known region with a non-year paren, so "FBI (2024)" stays a title.

def test_region_paren_platform_known_region():
    p = parse_channel_name("US (P+) AFC Champions League 1")
    assert p.region == "US"
    assert p.bare_name == "AFC Champions League 1"
    # detected_prefix flows from parsed.region via the existing fallback in the ETL.


def test_region_paren_platform_other_regions():
    assert parse_channel_name("CA (SN) Hockey Night").region == "CA"
    assert parse_channel_name("AU (STAN) Drama").region == "AU"


def test_region_paren_rejects_unknown_code():
    # "NCIS"/"FBI" are titles, not regions — must not be mistaken for a prefix.
    p = parse_channel_name("NCIS (CBS) Episode")
    assert p.region == ""
    assert p.bare_name == "NCIS (CBS) Episode"


def test_region_paren_rejects_bare_year():
    # "FBI (2024) Reboot" — paren is a year → it's a title, not region+platform.
    p = parse_channel_name("FBI (2024) Reboot")
    assert p.region == ""
    assert p.bare_name == "FBI (2024) Reboot"
