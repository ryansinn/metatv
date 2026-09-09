"""One publish point for "this channel's user-state changed".

Writes to a channel's rating/favorite/suppressed/hidden/queued state are
already chokepointed (``_toggle_rating`` / ``_toggle_favorite_by_id`` /
``_apply_favorite_toggle`` / ``_not_interested`` / ``_add_to_queue`` /
``_remove_from_queue`` / ``_hide_channel_from_*`` / ``_unhide_channel`` in
``main_window_favorites.py`` and ``main_window_metadata.py``), but reads were
never invalidated: each mutation handler ended with a hand-picked list of the
views it happened to remember to refresh, and the details pane's action-bar
buttons — written in exactly one place, ``show_channel`` →
``action_state_requested`` → ``apply_action_state`` — were never on any of
those lists. Select a channel, dislike it from the Watch Queue, and the
pane's buttons stayed frozen.

This is the ``theme.style()`` lesson applied to per-channel state: a
hand-maintained enumeration of "views to refresh" can never see what nobody
remembered to add to it. ``theme.py``'s ``apply_theme()`` replaced a
hand-maintained ``refresh_theme()`` sweep (838 call sites against 22 sweep
methods) with widgets registering themselves; #253/#261 both "completed" that
sweep and both still shipped it broken, because an enumeration is only ever as
complete as the last person to remember it. ``ChannelStateBus`` does the same
inversion here: a view that cares about a channel's state subscribes itself
(weakly, so a destroyed widget silently drops out) instead of a mutation
handler trying to know every view that might care.

Every mutation publishes to the bus instead of hand-refreshing views itself.

BUS-2 closed the gap for the three bulk mutations that carry a state axis the
bus tracks: ``_bulk_add_to_favorites``, ``_bulk_add_to_queue``, and
``_bulk_hide_channels`` (``main_window_favorites.py`` / ``main_window_metadata.py``)
now publish one delta per channel, after the whole batch has committed — the
existing list-membership refresh (``load_favorites()`` etc.) stays a single
call, a different grain, per CLAUDE.md.

Measured cost of doing this the straightforward way: :meth:`publish` triggers
one off-thread authoritative re-read per call (``_on_action_state_requested``
→ an executor job doing a tiny ``session_scope()`` read), and
``apply_action_state`` already drops every result whose ``channel_id`` isn't
the one currently shown — so for a 500-item selection, 499 of those re-reads
are pure waste. Measured on a real ``Database``: ~0.7ms/item of off-thread DB
work (~350ms total for 500), against ~0.035ms total for the synchronous tier-1
echo across the same 500. That's real but bounded, off the UI thread, and
consistent with every other publish() call in the app — a bulk-aware seam that
publishes once and re-reads only if the shown channel is in the batch would
remove the waste, but changing the bus's own re-read contract for this one
caller is a separate, larger slice, not a per-call special case.

``_bulk_mark_watched`` is unaffected by BUS-2 and stays out of scope: "watched"
isn't a field ``ChannelActionState`` tracks at all — not even
``_mark_channel_watched``/``_mark_channel_unwatched``, its single-channel
siblings, publish to this bus. The action bar has no watched indicator to
desync, so there's nothing for this bus to fix there.
"""

from __future__ import annotations

import weakref
from typing import Callable

from loguru import logger


class ChannelStateBus:
    """One publish point for "this channel's user-state changed".

    A mutation handler calls :meth:`publish` once; every live subscriber gets
    an instant optimistic echo, and the authoritative off-thread re-read
    (passed in as ``reread``) always runs after, overwriting the echo with
    real DB state. Subscribers register themselves — nothing enumerates them.
    """

    def __init__(self, reread: Callable[[str], None]) -> None:
        """Initialize the bus.

        Args:
            reread: The authoritative off-thread re-read, invoked with a
                ``channel_id`` as tier 2 of every :meth:`publish` call. In
                production this is ``MainWindow._on_action_state_requested``,
                which submits the real DB read to the executor and delivers
                the result back to the details pane via the existing
                ``_action_state_loaded`` signal.
        """
        self._reread = reread
        self._subscribers: list[weakref.WeakMethod] = []

    def subscribe(self, callback: Callable[[str, dict], None]) -> None:
        """Register a bound-method callback, held weakly.

        Args:
            callback: A bound method of the form ``callback(channel_id, delta)``.
                Held via :class:`weakref.WeakMethod` — when the callback's
                owning object is garbage-collected, the subscription silently
                drops out on the next :meth:`publish` rather than raising or
                being resurrected.
        """
        self._subscribers.append(weakref.WeakMethod(callback))

    def publish(self, channel_id: str, **delta) -> None:
        """Announce that ``channel_id``'s user-state changed.

        Two tiers, always in this order:

        1. **Echo (synchronous, zero DB):** every live subscriber is called
           as ``callback(channel_id, delta)`` for an instant optimistic
           update. A subscriber that raises is logged at warning and never
           prevents the remaining subscribers — or tier 2 — from running.
        2. **Authoritative:** ``reread(channel_id)`` — the real off-thread
           DB re-read passed to the constructor — always runs last,
           overwriting the optimistic echo with real state.

        Args:
            channel_id: The channel whose user-state changed.
            **delta: The fields that changed, e.g. ``rating=1`` or
                ``is_favorite=True``. Passed through to subscribers verbatim;
                this method attaches no meaning to any key.
        """
        live: list[Callable[[str, dict], None]] = []
        dead: list[weakref.WeakMethod] = []
        for ref in self._subscribers:
            callback = ref()
            if callback is None:
                dead.append(ref)
            else:
                live.append(callback)
        for ref in dead:
            self._subscribers.remove(ref)

        for callback in live:
            try:
                callback(channel_id, delta)
            except Exception:
                logger.warning(
                    "ChannelStateBus subscriber raised for channel_id={}",
                    channel_id, exc_info=True,
                )

        self._reread(channel_id)
