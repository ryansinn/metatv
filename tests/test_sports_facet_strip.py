"""The sport axis is a strip of icon buttons, and search narrows within it.

Mockup Q5/Q6/Q16. The owner's words about the cascade it replaces: "the dropdown
as it is now is clunky, it's the old style".

Two things this pins that are easy to get wrong:

* **All selected and none selected both mean "no filter".** Passing every sport
  name to a ``WHERE IN`` would silently drop rows whose ``sport_type`` is NULL —
  the 16,830 General rows, the largest facet in the library.
* **Search narrows, it does not replace.** It composes with the active lane and
  the active chips rather than jumping to a global result set.

Nothing new was built for the chip itself: ``ToggleChip`` already took a
``vector_role`` and rendered a tinted vector icon from ``icons.VECTOR_KEYS``.
"""

from __future__ import annotations

import datetime

import pytest

from metatv.core.channel_visibility import VisibilityScope
from metatv.core.database import Database, ChannelDB, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.icons import VECTOR_KEYS
from metatv.gui.sports_filter_bar import SportsFilterBar, sport_display_name


NOW = datetime.datetime(2026, 8, 31, 12, 0)
_D = datetime.timedelta

#: Every sport_type the classifier actually stores, measured on the owner's library.
STORED_SPORT_TYPES = [
    "soccer", "mma", "racing", "tennis", "hockey", "boxing", "basketball",
    "wrestling", "american_football", "baseball", "golf", "field_hockey",
    "cricket", "rugby", "cycling",
]


# ── the icon vocabulary ─────────────────────────────────────────────────────

def test_every_stored_sport_type_has_an_icon(qapp):
    """A facet with no glyph would render as a bare word beside fifteen icons."""
    missing = [s for s in STORED_SPORT_TYPES if f"sport_{s}" not in VECTOR_KEYS]
    assert not missing, f"sport_types with no vector role: {missing}"
    assert "sport_general" in VECTOR_KEYS, "the 16,830 multi-sport networks need one too"


def test_every_sport_icon_actually_exists_in_the_bundled_font(qapp):
    """Resolved, not assumed from the name.

    ``mdi6.judo`` and ``mdi6.wrestling`` both read like real keys and neither
    exists. A first probe reported them present because it ran with no
    QApplication, which makes qtawesome answer for a font it has not loaded —
    hence the ``qapp`` fixture here, which is load-bearing rather than habit.
    """
    import qtawesome

    broken = []
    for role, key in VECTOR_KEYS.items():
        if not role.startswith("sport_"):
            continue
        try:
            qtawesome.icon(key)
        except Exception as exc:            # noqa: BLE001 - reporting, not handling
            broken.append(f"{role} -> {key} ({exc})")
    assert not broken, "unresolvable sport icons: " + "; ".join(broken)


def test_no_two_sports_share_a_glyph(qapp):
    """A repeated glyph shows one facet twice and makes the strip unreadable."""
    sports = {r: k for r, k in VECTOR_KEYS.items() if r.startswith("sport_")}
    seen: dict[str, str] = {}
    for role, key in sports.items():
        assert key not in seen, f"{role} and {seen[key]} both use {key}"
        seen[key] = role


@pytest.mark.parametrize("stored,shown", [
    ("american_football", "NFL"),
    ("mma", "MMA"),
    ("field_hockey", "Field hockey"),
    ("unknown", "General"),
    (None, "General"),
    ("tennis", "Tennis"),
])
def test_stored_tokens_render_as_words(stored, shown):
    """"General", not "Unknown" — a multi-sport network has no single sport,
    which is correct rather than a classification failure."""
    assert sport_display_name(stored) == shown


# ── the strip's filter semantics ────────────────────────────────────────────

@pytest.fixture
def bar(qapp):
    widget = SportsFilterBar()
    widget.resize(900, 60)
    widget.load_taxonomy(
        {"soccer": {"Premier League": []}, "tennis": {}, "unknown": {}},
        {"soccer": 5933, "tennis": 968, "unknown": 16830},
    )
    return widget


def test_nothing_selected_means_no_filter(bar):
    assert bar.get_filter_state()["sport_types"] == []


def test_everything_selected_also_means_no_filter(bar):
    """Otherwise a WHERE IN over every sport drops the NULL rows."""
    for chip in bar._sport_chips.values():
        chip.setChecked(True)
    assert bar.get_filter_state()["sport_types"] == []


def test_one_chip_selects_one_sport(bar):
    bar._sport_chips["tennis"].setChecked(True)
    assert bar.get_filter_state()["sport_types"] == ["tennis"]


def test_the_strip_is_ordered_biggest_first(bar):
    """It is read left to right; the sports the library holds should lead."""
    assert list(bar._sport_chips) == ["unknown", "soccer", "tennis"]


def test_clearing_unchecks_rather_than_checking_everything(bar):
    """Both read as "no filter", but only an empty strip LOOKS unfiltered."""
    bar._sport_chips["tennis"].setChecked(True)
    bar.search_input.setText("open")
    bar.clear_filters()
    assert not any(c.isChecked() for c in bar._sport_chips.values())
    assert bar.get_filter_state() == {"sport_types": [], "league_names": [], "search": ""}


def test_a_restored_sport_that_no_longer_exists_is_dropped(bar):
    """A source may simply have stopped carrying it — not an error."""
    bar.restore_filter_state(
        {"sport_types": ["tennis", "quidditch"], "league_names": [], "search": "ufc"})
    assert bar.get_filter_state()["sport_types"] == ["tennis"]
    assert bar.get_filter_state()["search"] == "ufc"


def test_search_is_trimmed(bar):
    bar.search_input.setText("   US Open   ")
    assert bar.get_filter_state()["search"] == "US Open"


# ── search, against the query ───────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 's.db'}")
    database.create_tables()
    with database.session_scope() as session:
        session.add(ProviderDB(id="p", name="P", type="xtream", url="http://x",
                               username="u", password="p", is_active=True))
        rows = [
            ("US Open: Court 5 - Qualifying", NOW + _D(hours=1), "tennis"),
            ("US Open: Court 9 - Qualifying", NOW + _D(hours=2), "tennis"),
            ("Ajax v FC Sion", NOW + _D(hours=3), "soccer"),
            ("FOX SPORTS 1 HD", None, None),
        ]
        for i, (name, start, sport) in enumerate(rows):
            session.add(ChannelDB(
                id=f"c{i}", source_id=str(i), provider_id="p", name=name,
                stream_url="u", media_type="live", special_view="sports",
                sport_type=sport, event_start_time=start))
    return database


def _names(db, **kw):
    with db.session_scope(commit=False) as session:
        return [r.name for r in RepositoryFactory(session).channels.get_sports_channels(
            VisibilityScope(), now=NOW, **kw)]


def test_search_narrows_the_list(db):
    assert len(_names(db, search="US Open")) == 2


def test_search_is_case_insensitive(db):
    assert len(_names(db, search="us open")) == 2


def test_search_composes_with_the_lane_rather_than_replacing_it(db):
    """The whole point of Q6: it narrows WITHIN the active lane.

    "FOX SPORTS 1 HD" matches nothing here, but it is in a different lane
    anyway — a search that ignored the lane would surface it.
    """
    assert _names(db, search="Court", lane="upcoming") == [
        "US Open: Court 5 - Qualifying", "US Open: Court 9 - Qualifying"]
    assert _names(db, search="Court", lane="channels") == []


def test_search_composes_with_the_sport_chips(db):
    assert _names(db, search="a", sport_types=["soccer"]) == ["Ajax v FC Sion"]


def test_the_lane_counts_honour_the_search_too(db):
    """A chip must not promise fixtures the searched list will not show."""
    with db.session_scope(commit=False) as session:
        counts = RepositoryFactory(session).channels.get_sports_lane_counts(
            VisibilityScope(), search="US Open", now=NOW)
    assert counts["upcoming"] == 2
    assert counts["channels"] == 0, "the 24/7 channel does not match the search"
