"""EPGF-1: the guide line says WHOSE fault it is.

Before this, every bad EPG state rendered as "⚠ Stale — guide ends 4 Aug 2026
(source out of date)" — a sentence that blames the provider. In the owner's
2026-08-16 case that was flatly wrong: the guide was dead because our own
cached ``epg_url`` carried a *previous subscription's* credentials, and a user
who supplies a broken URL override got the same sentence forever, with no way
to learn that the thing they typed was the thing failing.

Two halves, both executed against real code:

1. ``epg_fetch`` stores the condensed cause of a failed attempt on the provider
   row (``epg_last_fetch_error`` / ``epg_last_fetch_error_at``) and clears both
   on the next success — driven through the REAL ``_run_fetch`` against a
   file-backed ``Database``, with only the network parse doubled.
2. ``epg_utils.guide_freshness`` — the one computation both status lines share
   — returns the right state, wording and tooltip for each case, and the two
   labels actually RENDER it (glyph + colour + tooltip), not merely define it.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import (
    GUIDE_FRESHNESS_STATES,
    guide_freshness,
    now_utc,
)
from metatv.core.xmltv_parser import XmltvChannel, XmltvProgramme


@pytest.fixture(scope="module")
def qapp():
    """One QApplication for the render assertions below."""
    QApplication = pytest.importorskip("PyQt6.QtWidgets").QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _manager(db) -> EpgManager:
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = "auto"
    # Real numbers: the post-fetch prune_expired() sweep does arithmetic with
    # this, and a MagicMock there fails the STORE phase, not the fetch — which
    # would let these tests pass for the wrong reason.
    config.epg_retention_hours = 24
    return EpgManager(db, config, notifications=None)


def _seed(db, pid="p", **kwargs) -> None:
    """A provider row with a derivable EPG URL (urls + credentials)."""
    fields = {
        "id": pid, "name": pid, "type": "xtream", "url": "http://e.com",
        "username": "u", "password": "pw", "is_active": True,
        "urls": [{"url": "http://e.com", "priority": 0}],
        "epg_enabled": True,
    }
    fields.update(kwargs)
    with db.session_scope() as session:
        session.add(ProviderDB(**fields))


def _guide(n: int = 2):
    """A small, entirely-in-the-future XMLTV guide."""
    now = now_utc()
    channels = [XmltvChannel(epg_id="c1", display_name="Chan One")]
    programmes = [
        XmltvProgramme(
            channel_id="c1", title=f"Show {i}", description="",
            start_time=now + timedelta(hours=i),
            stop_time=now + timedelta(hours=i + 1),
        )
        for i in range(n)
    ]
    return channels, programmes


def _labels():
    """A bare host carrying only the two labels ``_set_epg_status_label`` writes.

    ``_ProviderEditorTabsMixin`` is a plain mixin — no ``__init__``, no Qt base
    — so ``__new__`` here copies nothing that could go stale (CLAUDE.md's
    "a test double that COPIES ``__init__``"); the two QLabels are the whole of
    the state the method under test touches.
    """
    from PyQt6.QtWidgets import QLabel

    from metatv.gui.provider_editor_tabs import _ProviderEditorTabsMixin

    host = _ProviderEditorTabsMixin.__new__(_ProviderEditorTabsMixin)
    host._acct_epg_lbl = QLabel()
    host._epg_freshness_lbl = QLabel()
    return host


# ---------------------------------------------------------------------------
# 1. The stored last-fetch error — written by the real fetch path
# ---------------------------------------------------------------------------

def test_a_failed_fetch_stores_a_condensed_cause_and_a_timestamp(db, monkeypatch):
    """Every host failing must leave WHY on the row, not just an empty guide."""
    _seed(db)
    mgr = _manager(db)
    before = now_utc()

    def _boom(url, **kwargs):
        raise OSError(
            "HTTP 403 Forbidden\n[SQL: irrelevant]\n[parameters: (1, 2, 3)]"
        )

    monkeypatch.setattr("metatv.core.epg_fetch.parse_xmltv_url", _boom)
    mgr._run_fetch("p", "p")

    with db.session_scope(commit=False) as s:
        row = s.query(ProviderDB).filter_by(id="p").first()
        assert row.epg_last_fetch_error, "the failure left no cause on the row"
        assert "403" in row.epg_last_fetch_error
        # condense_error keeps ONE actionable line — the SQL tail must not survive.
        assert "[SQL:" not in row.epg_last_fetch_error
        assert "\n" not in row.epg_last_fetch_error
        assert row.epg_last_fetch_error_at is not None
        assert row.epg_last_fetch_error_at >= before

    mgr._executor.shutdown(wait=False)


def test_a_successful_fetch_clears_the_stored_error(db, monkeypatch):
    """A guide that lands makes the previous failure no longer true."""
    _seed(
        db,
        epg_last_fetch_error="host unreachable",
        epg_last_fetch_error_at=now_utc() - timedelta(hours=3),
    )
    mgr = _manager(db)
    monkeypatch.setattr(
        "metatv.core.epg_fetch.parse_xmltv_url",
        lambda url, **kwargs: _guide(),
    )
    mgr._run_fetch("p", "p")

    with db.session_scope(commit=False) as s:
        row = s.query(ProviderDB).filter_by(id="p").first()
        assert row.epg_last_fetch_error is None, (
            "a successful fetch left the old failure standing — the line would "
            "keep blaming a fetch that now works"
        )
        assert row.epg_last_fetch_error_at is None
        assert row.epg_last_fetched is not None

    mgr._executor.shutdown(wait=False)


def test_a_broken_override_is_recorded_even_though_it_is_never_cycled(db, monkeypatch):
    """The override is fetched verbatim with no host cycling — it must still record."""
    _seed(db, epg_url_override="http://typo.example/xmltv.php")
    mgr = _manager(db)
    seen: list[str] = []

    def _boom(url, **kwargs):
        seen.append(url)
        raise ConnectionError("Name or service not known")

    monkeypatch.setattr("metatv.core.epg_fetch.parse_xmltv_url", _boom)
    mgr._run_fetch("p", "p")

    assert seen == ["http://typo.example/xmltv.php"], (
        "the override must be used verbatim, once, with no host cycling"
    )
    with db.session_scope(commit=False) as s:
        row = s.query(ProviderDB).filter_by(id="p").first()
        assert "Name or service not known" in (row.epg_last_fetch_error or "")

    mgr._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# 2. The three-state computation
# ---------------------------------------------------------------------------

def test_source_lagging_names_the_source_not_us():
    """State 1: we fetched fine; the feed simply stops where it stops."""
    now = now_utc()
    fresh = guide_freshness(
        "http://e/xmltv.php", now - timedelta(hours=2),
        epg_data_start=now - timedelta(days=2),
    )
    assert fresh.state == "source_lagging"
    assert "the source has not published further" in fresh.text
    assert "out of date" not in fresh.text, (
        "the old wording blamed the provider for a state that may be ours"
    )
    assert "succeeded" in fresh.detail


def test_fetch_failed_says_we_could_not_fetch_and_offers_refresh():
    """State 2: every host failed — the guide's dates say nothing about that."""
    now = now_utc()
    fresh = guide_freshness(
        "http://e/xmltv.php", now + timedelta(days=3),   # dates still look FINE
        last_fetch_error="HTTP 403 Forbidden",
        last_fetch_error_at=now - timedelta(hours=6),
    )
    assert fresh.state == "fetch_failed"
    assert fresh.text.startswith("Could not fetch since ")
    assert "HTTP 403 Forbidden" in fresh.text
    assert "Refresh" in fresh.text
    assert "Every configured host" in fresh.detail


def test_a_broken_override_is_its_own_state_and_says_so():
    """State 3: the user's own URL is the failing thing — name it."""
    now = now_utc()
    fresh = guide_freshness(
        "http://typo.example/xmltv.php", now - timedelta(days=1),
        last_fetch_error="Name or service not known",
        last_fetch_error_at=now - timedelta(minutes=5),
        has_url_override=True,
    )
    assert fresh.state == "override_failed"
    assert fresh.text.startswith("Your EPG URL override failed since ")
    assert "Name or service not known" in fresh.text
    assert "never cycled" in fresh.detail


def test_a_live_error_outranks_a_healthy_looking_guide_date():
    """The same row, with and without a stored error, must not read the same."""
    now = now_utc()
    end = now + timedelta(days=3)
    healthy = guide_freshness("http://e/xmltv.php", end)
    broken = guide_freshness(
        "http://e/xmltv.php", end,
        last_fetch_error="connection timed out",
        last_fetch_error_at=now,
    )
    assert healthy.state == "current"
    assert broken.state == "fetch_failed"
    assert healthy.text != broken.text


def test_unconfigured_and_never_fetched_stay_distinct():
    assert guide_freshness("", None).state == "not_configured"
    assert guide_freshness("http://e/xmltv.php", None).state == "no_data"


def test_the_healthy_line_still_carries_the_auto_annotation():
    """Regression: the Auto depth note is what makes the resolved interval visible."""
    now = now_utc()
    fresh = guide_freshness(
        "http://e/xmltv.php", now + timedelta(days=6),
        epg_data_start=now - timedelta(days=1),
    )
    assert fresh.state == "current"
    assert "Auto: ~7-day feed" in fresh.text
    assert "refreshing ~every" in fresh.text


def test_every_declared_state_is_reachable_and_named():
    """Non-degeneracy: the state tuple must describe the function, not a wish."""
    now = now_utc()
    produced = {
        guide_freshness("", None).state,
        guide_freshness("u", None).state,
        guide_freshness("u", now + timedelta(days=2)).state,
        guide_freshness("u", now - timedelta(hours=1)).state,
        guide_freshness("u", now, last_fetch_error="x", last_fetch_error_at=now).state,
        guide_freshness("u", now, last_fetch_error="x", last_fetch_error_at=now,
                        has_url_override=True).state,
    }
    assert produced == set(GUIDE_FRESHNESS_STATES)


# ---------------------------------------------------------------------------
# 3. Rendering — glyph + colour, never colour alone
# ---------------------------------------------------------------------------

def test_every_state_has_a_look_and_the_bad_ones_carry_a_glyph(qapp):
    """Colour never travels alone, and no state may fall off the render table."""
    from metatv.gui import theme as _theme
    from metatv.gui.provider_editor_tabs import _EPG_FRESHNESS_LOOK

    assert set(_EPG_FRESHNESS_LOOK) == set(GUIDE_FRESHNESS_STATES)
    for state, (glyph, token) in _EPG_FRESHNESS_LOOK.items():
        assert getattr(_theme, token, None), f"{state}: {token} is not a theme token"
        if state in ("source_lagging", "fetch_failed", "override_failed"):
            assert glyph, f"{state} is announced by colour alone"


def test_the_two_status_labels_show_the_failure_and_carry_the_full_cause(qapp):
    """Rendered: BOTH labels say the override broke, in the error colour, with
    the long explanation on the tooltip.

    Against the pre-EPGF-1 code this label read "⚠ Stale — guide ends <date>
    (source out of date)" in COLOR_WARN, with no tooltip and no mention of the
    override at all.
    """
    from metatv.gui import theme as _theme
    from metatv.gui.provider_editor_tabs import _ProviderEditorTabsMixin

    host = _labels()
    now = now_utc()
    _ProviderEditorTabsMixin._set_epg_status_label(
        host, "http://typo.example/xmltv.php", now - timedelta(days=1),
        last_fetch_error="Name or service not known",
        last_fetch_error_at=now - timedelta(minutes=5),
        has_url_override=True,
    )

    for lbl in (host._acct_epg_lbl, host._epg_freshness_lbl):
        assert "override failed" in lbl.text()
        assert "Name or service not known" in lbl.text()
        assert "out of date" not in lbl.text()
        assert _theme.COLOR_ERR in lbl.styleSheet(), (
            f"expected the error colour, got {lbl.styleSheet()!r}"
        )
        assert "never cycled" in lbl.toolTip()


def test_a_plain_source_lag_still_reads_as_a_warning_not_an_error(qapp):
    """The state that IS the provider's fault keeps the warning colour + glyph."""
    from metatv.gui import icons as _icons
    from metatv.gui import theme as _theme
    from metatv.gui.provider_editor_tabs import _ProviderEditorTabsMixin

    host = _labels()
    _ProviderEditorTabsMixin._set_epg_status_label(
        host, "http://e/xmltv.php", now_utc() - timedelta(hours=3),
    )
    lbl = host._epg_freshness_lbl
    assert lbl.text().startswith(_icons.notification_warning_icon)
    assert "the source has not published further" in lbl.text()
    assert _theme.COLOR_WARN in lbl.styleSheet()


def test_the_healthy_state_reads_green_with_no_warning_glyph(qapp):
    from metatv.gui import icons as _icons
    from metatv.gui import theme as _theme
    from metatv.gui.provider_editor_tabs import _ProviderEditorTabsMixin

    host = _labels()
    _ProviderEditorTabsMixin._set_epg_status_label(
        host, "http://e/xmltv.php", now_utc() + timedelta(days=3),
    )
    lbl = host._epg_freshness_lbl
    assert lbl.text().startswith("Current — guide through ")
    assert _icons.notification_warning_icon not in lbl.text()
    assert _theme.COLOR_OK in lbl.styleSheet()


def test_the_freshness_label_restyles_on_a_theme_switch(qapp):
    """It goes through ``theme.style_fn``, so a palette change re-renders it."""
    from metatv.gui import theme as _theme
    from metatv.gui.provider_editor_tabs import _ProviderEditorTabsMixin

    original = _theme.current_theme()
    try:
        _theme.apply_theme("Midnight")
        host = _labels()
        _ProviderEditorTabsMixin._set_epg_status_label(
            host, "http://e/xmltv.php", now_utc() - timedelta(hours=3),
        )
        midnight = host._epg_freshness_lbl.styleSheet()
        _theme.apply_theme("Daylight")
        daylight = host._epg_freshness_lbl.styleSheet()
    finally:
        _theme.apply_theme(original)

    assert midnight != daylight, (
        "the freshness colour was rendered once and went stale on a theme switch"
    )
