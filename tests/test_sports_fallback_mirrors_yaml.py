"""The in-memory sports keyword fallback must equal the bundled YAML (ledger D34).

``special_content`` keeps ``_DEFAULT_SPORT_KEYWORDS``/``_DEFAULT_LEAGUE_KEYWORDS``
for when ``metatv/data/sports_definitions.yaml`` cannot be read. Two hand-kept
copies drift; this makes the mirror enforced instead of promised in a comment.
ORDER is compared too — the first matching sport/league wins.
"""

from metatv.core import special_content


def _bundled():
    return special_content._load_definitions_file(special_content._BUNDLED_DEFINITIONS)


def test_sport_fallback_equals_the_bundled_yaml_in_order():
    sport_kw, _ = _bundled()
    assert list(special_content._DEFAULT_SPORT_KEYWORDS.items()) == list(sport_kw.items())


def test_league_fallback_equals_the_bundled_yaml_in_order():
    _, league_kw = _bundled()
    assert list(special_content._DEFAULT_LEAGUE_KEYWORDS.items()) == list(league_kw.items())
