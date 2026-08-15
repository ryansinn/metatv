"""The resolved knobs that decide provider-URL ranking order.

Why this module exists
----------------------
``Provider.ordered_urls()`` (``core/models.py``) needs three tunables to rank
hosts.  Reading them straight from ``Config`` there would put application
settings inside a plain data model — the same mistake ``VisibilityScope``
(``core/channel_visibility.py``) exists to avoid: *the control layer resolves
the values, the low-level object holds a frozen bag of already-resolved ones,
never a ``Config``.*

It also cannot be solved by threading a ``Config`` down through the callers.
The six busiest cycling call sites live in ``providers/xtream.py``, which
deliberately has no ``Config`` access at all (provider plugins are constructed
by a registry, ``get_provider(type)``, that takes none) — and giving the plugin
layer config access to fix a ranking knob would be a much worse trade.

So the policy is resolved ONCE at startup from the loaded ``Config`` and stored
here.  ``ordered_urls()`` imports only this leaf module (no cycle: this module
imports nothing from ``metatv``), and tests pass an explicit policy rather than
touching the global.

Without this wiring the three ``Config`` fields are decorative: every call site
falls back to defaults and editing ``config.yaml`` changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UrlRankingPolicy:
    """Already-resolved ranking knobs. Holds no ``Config``.

    Attributes:
        health_decay: EWMA decay per attempt-age step when scoring a URL's
            recent success history. Lower = the newest outcome dominates
            harder.
        cooldown_minutes: A URL whose most recent attempt failed within this
            window is demoted (never removed).
        recent_attempts_kept: How many per-URL attempts are persisted.
    """

    health_decay: float = 0.85
    cooldown_minutes: int = 10
    recent_attempts_kept: int = 20

    @classmethod
    def from_config(cls, config) -> "UrlRankingPolicy":
        """Resolve the policy from an application ``Config``.

        Args:
            config: The loaded application config. Missing attributes fall back
                to this class's defaults, so a partial test double is fine.

        Returns:
            A frozen policy carrying only plain values.
        """
        return cls(
            health_decay=getattr(config, "url_health_decay", cls.health_decay),
            cooldown_minutes=getattr(config, "url_cooldown_minutes", cls.cooldown_minutes),
            recent_attempts_kept=getattr(config, "url_recent_attempts_kept", cls.recent_attempts_kept),
        )


_DEFAULT = UrlRankingPolicy()
_current: UrlRankingPolicy = _DEFAULT


def set_url_ranking_policy(policy: UrlRankingPolicy) -> None:
    """Install the process-wide policy. Called once, at startup, from ``__main__``.

    Args:
        policy: The resolved policy to use for all subsequent ranking.
    """
    global _current
    _current = policy


def get_url_ranking_policy() -> UrlRankingPolicy:
    """Return the process-wide policy (defaults until startup installs one)."""
    return _current


def reset_url_ranking_policy() -> None:
    """Restore the built-in defaults. Test hook — keeps cases order-independent."""
    global _current
    _current = _DEFAULT
