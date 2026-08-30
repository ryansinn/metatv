"""A function that takes a ``now`` must not reach for the real clock underneath.

``summarize_providers(providers, now)`` looked deterministic: its test pinned
``NOW = datetime(2026, 8, 25)`` and passed it in. But it classified each source
two ways — ``is_expired`` against the injected ``now``, and
``subscription_color(...)`` which hardcoded ``datetime.now()``. Half the answer
followed the test's clock and half followed the wall.

That is invisible until the wall moves past one of the fixture's dates. It did,
at 2026-08-30 00:00 UTC, and the suite went red on **three unrelated open PRs**
at once — none of which touched sources. The tests below fix the date so the
bug is reproducible on any day, in any timezone, rather than for a few hours a
year.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytest.importorskip("PyQt6")

#: The day the real failure happened, and a fixture date that sits exactly on a
#: provider's expiry — the boundary where the two clocks disagree.
ROLLOVER = datetime(2026, 8, 30, 0, 54)
FIXTURE_NOW = datetime(2026, 8, 25)


def test_subscription_color_honours_an_injected_now(qapp):
    from metatv.gui.provider_editor import subscription_color
    from metatv.gui import theme as _theme

    exp = FIXTURE_NOW + timedelta(days=5)          # 2026-08-30
    created = FIXTURE_NOW - timedelta(days=365)

    # Five days out from the injected reference: running low, not expired.
    assert subscription_color(exp, created, FIXTURE_NOW) != _theme.COLOR_MUTED, (
        "a subscription five days from lapsing was reported as already expired "
        "— subscription_color ignored the reference point it was given"
    )
    # Past it: expired, from the same function, decided only by the argument.
    assert subscription_color(exp, created, ROLLOVER) == _theme.COLOR_MUTED


def test_summarize_providers_is_decided_only_by_its_now(qapp):
    """The regression itself: same inputs, same answer, whatever day it is."""
    from types import SimpleNamespace

    from metatv.gui.sidebar.sources_strip import summarize_providers

    def _p(days):
        return SimpleNamespace(
            is_active=True,
            account_exp_date=FIXTURE_NOW + timedelta(days=days),
            account_created_at=FIXTURE_NOW - timedelta(days=365),
        )

    providers = [_p(5), _p(9)]
    assert summarize_providers(providers, FIXTURE_NOW) == (2, 2)


def test_the_answer_does_not_drift_as_the_real_clock_moves(qapp):
    """Called twice with the same ``now``, it must give the same answer.

    A second call is not the point — the point is that nothing inside consults
    a clock the caller cannot see, which is what made this a time bomb rather
    than a bug someone would notice.
    """
    from types import SimpleNamespace

    from metatv.gui.sidebar.sources_strip import summarize_providers

    providers = [
        SimpleNamespace(is_active=True,
                        account_exp_date=FIXTURE_NOW + timedelta(days=d),
                        account_created_at=FIXTURE_NOW - timedelta(days=365))
        for d in (1, 5, 9, 300)
    ]
    for reference in (FIXTURE_NOW, ROLLOVER, datetime(2027, 1, 1)):
        first = summarize_providers(providers, reference)
        second = summarize_providers(providers, reference)
        assert first == second, f"unstable answer at {reference}"

    # And the reference genuinely changes the verdict, so the loop above is not
    # passing merely because `now` is ignored entirely. Far enough out that
    # every subscription has lapsed — 2027-01-01 is NOT such a date (the +300
    # one is still live then, and it happens to give the same pair as the
    # fixture date, which is exactly the sort of coincidence that makes a
    # "different inputs, different answer" check quietly vacuous).
    assert summarize_providers(providers, FIXTURE_NOW) == (4, 3)
    assert summarize_providers(providers, datetime(2028, 1, 1)) == (4, 4)
