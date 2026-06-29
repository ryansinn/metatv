"""Single source of truth for the configurable channel-row middle-click action.

A middle-click on a channel row performs a user-chosen play action, selected in
Settings → Interaction and persisted to ``config.middle_click_action``.  This
registry maps each stable action key to a human label (shown in the Settings
combo) and the name of the ``MainWindow`` play method that performs it.

Adding a new middle-click behaviour is one entry here: the Settings combo is
populated from :data:`MIDDLE_CLICK_ACTIONS`, and ``_on_channel_middle_clicked``
dispatches through it — so a new entry surfaces in both places automatically
(the chokepoint / single-source-of-truth principle).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MiddleClickAction:
    """A selectable channel-row middle-click behaviour.

    Attributes:
        key: Stable identifier persisted to ``config.middle_click_action``.
        label: Human-readable label shown in the Settings → Interaction combo.
        method: Name of the ``MainWindow`` play method invoked with the clicked
            channel id, e.g. ``"play_channel_resume_by_id"``.
    """

    key: str
    label: str
    method: str


# Ordered so the Settings combo lists them deterministically; the first entry is
# the default and must match ``Config.middle_click_action``.
MIDDLE_CLICK_ACTIONS: tuple[MiddleClickAction, ...] = (
    MiddleClickAction(
        key="playback_position",
        label="Resume from saved position",
        method="play_channel_resume_by_id",
    ),
    MiddleClickAction(
        key="endless_buffer",
        label="Play with endless buffer",
        method="play_channel_open_ended_buffer_by_id",
    ),
)

DEFAULT_MIDDLE_CLICK_ACTION: str = MIDDLE_CLICK_ACTIONS[0].key

_BY_KEY: dict[str, MiddleClickAction] = {a.key: a for a in MIDDLE_CLICK_ACTIONS}


def middle_click_action(key: str) -> MiddleClickAction:
    """Return the registered action for ``key``, falling back to the default.

    Args:
        key: An action key (the persisted ``config.middle_click_action`` value).

    Returns:
        The matching :class:`MiddleClickAction`, or the default action when the
        key is unknown (e.g. a stale config value from a removed action).
    """
    return _BY_KEY.get(key, _BY_KEY[DEFAULT_MIDDLE_CLICK_ACTION])
