"""A source can be active AND expiring — they are different questions.

The owner, on a working install with two enabled sources: *"why does Sources
say 'No Active Sources'? there are two active sources"*.

``summarize_providers`` counted with mutually exclusive branches::

    if concerning:      expiring += 1
    elif p.is_active:   active += 1

so an enabled source whose subscription was near renewal was counted ONLY as
expiring. Two working sources that both happened to be close to renewal
therefore reported ``active=0``. The strip had been showing that as
"● 0 active · ⚠ 2 expiring" — confusing — and once it started leading with its
most urgent fact it became "No active sources", which is a false alarm about an
app that was working fine.

"Active" answers *is this source enabled and serving?* "Expiring" answers *is
its subscription running out?* Orthogonal, so they are counted independently.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

NOW = datetime(2026, 8, 25)


def _provider(*, active: bool, expires_in_days: int | None):
    return SimpleNamespace(
        is_active=active,
        account_exp_date=(
            NOW + timedelta(days=expires_in_days)
            if expires_in_days is not None else None
        ),
        account_created_at=NOW - timedelta(days=365),
    )


def test_an_active_source_near_renewal_counts_as_BOTH(qapp):
    """The owner's install, and the regression itself."""
    from metatv.gui.sidebar.sources_strip import summarize_providers

    active, expiring, _expired = summarize_providers(
        [_provider(active=True, expires_in_days=5),
         _provider(active=True, expires_in_days=9)],
        NOW,
    )
    assert active == 2, (
        "two enabled sources reported as inactive because their subscriptions "
        "are near renewal — those are different questions"
    )
    assert expiring == 2


def test_healthy_active_sources_are_not_expiring(qapp):
    from metatv.gui.sidebar.sources_strip import summarize_providers

    assert summarize_providers(
        [_provider(active=True, expires_in_days=300)], NOW
    ) == (1, 0, 0)


def test_a_disabled_source_is_not_active_even_if_healthy(qapp):
    from metatv.gui.sidebar.sources_strip import summarize_providers

    assert summarize_providers(
        [_provider(active=False, expires_in_days=300)], NOW
    ) == (0, 0, 0)


def test_an_expired_source_still_counts_as_active_when_enabled(qapp):
    """Expired is a subscription fact; enabled is a user choice.

    An expired-but-enabled source is exactly the case the owner runs — the
    provider often keeps serving past the date it advertised.
    """
    from metatv.gui.sidebar.sources_strip import summarize_providers

    summary = summarize_providers(
        [_provider(active=True, expires_in_days=-5)], NOW
    )
    assert summary.active == 1
    assert summary.expired == 1
    assert summary.expiring == 0, "a lapsed subscription is expired, not expiring"


def test_a_disabled_source_that_already_expired_says_nothing(qapp):
    """The owner's install on 2026-10-20: two sources lapsed a month earlier and
    turned off, one live source with 8 days left. The strip said "2 expiring"."""
    from metatv.gui.sidebar.sources_strip import _summary_text, summarize_providers

    providers = [_provider(active=True, expires_in_days=300),
                 _provider(active=False, expires_in_days=-21),
                 _provider(active=False, expires_in_days=-23)]
    summary = summarize_providers(providers, NOW)
    assert summary == (1, 0, 0)
    assert _summary_text(summary, len(providers)).endswith("1 active")


def test_a_disabled_source_still_running_down_is_still_expiring(qapp):
    from metatv.gui.sidebar.sources_strip import summarize_providers

    assert summarize_providers(
        [_provider(active=False, expires_in_days=3)], NOW) == (0, 1, 0)


def test_the_alarm_only_fires_when_nothing_is_enabled(qapp):
    """"No active sources" must mean the app genuinely has nothing to show."""
    from metatv.gui.sidebar.sources_strip import _summary_text

    from metatv.gui.sidebar.sources_strip import SourceSummary as S

    assert _summary_text(S(2, 2, 0), 2).endswith(" 2 expiring")
    assert "Material Design Icons" in _summary_text(S(2, 2, 0), 2)   # the warning icon, inline
    assert _summary_text(S(2, 0, 1), 2).endswith(" 1 expired")
    assert _summary_text(S(2, 1, 1), 2).endswith(" 1 expired"), "overdue outranks running low"
    assert _summary_text(S(2, 0, 0), 2).endswith("2 active")
    assert "No active sources" in _summary_text(S(0, 0, 0), 2)
    assert "No active sources" in _summary_text(S(0, 1, 0), 2)
    assert _summary_text(S(0, 0, 0), 0) == "No sources yet"
