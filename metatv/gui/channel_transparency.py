"""The channel list's filter-transparency bar — one descriptor per axis.

When the channel list comes back empty (or short), this bar says WHY: how many
results each filter layer is holding back, and a click to lift that layer for
this view only.

**Why this is a module rather than code in two big files.** It used to be a hand
enumeration spread over nine sites — the measurement, the ``params`` publish,
the reads, the ``elif`` condition, the render signature, its booleans, its
render body, its ``or``-chain, and a button-name tuple in ``refresh_theme``.
Adding one axis meant editing all nine, and every one of them was a place a
future axis could be forgotten.

That is not hypothetical. The adult-content gate WAS an axis nobody had added,
so a category whose 28 channels are all flagged rendered 0 rows under the
message "try a different search" — the bar could not report a filter it had
never been told about, and the honest branch was unreachable. Ledger F26.

Each axis differs in three ways that a blind merge of the five bodies would have
destroyed, so they are DATA rather than one generic body:

* **How it is measured** — a Python-side diff, a SQL re-query with one axis
  lifted, a ``has_dead()`` probe, or (for the adult gate) a measurement taken
  only on an empty page. That still lives in ``_query_channels``, which owns the
  session; this module owns presentation.
* **What its click does** — four lift their own layer for one view. The adult
  gate opens its SETTING instead: those four are filters a user can trip by
  accident, while the gate is a choice they made, so the honest response is to
  name it and hand over the switch rather than quietly flip it.
* **What it says** — each has its own noun ("hidden by Global Exclusions",
  "unavailable (repeated play failures)").

Adding an axis is therefore one entry in :data:`AXES` plus its measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from PyQt6.QtWidgets import QPushButton

from metatv.gui import icons as _icons

#: Prefix marking a count as a floor rather than an exact total.
AT_LEAST = "≥"


def count_label(n: int, is_floor: bool) -> str:
    """Format a hidden-count, marking a floor as one rather than a total."""
    return f"{AT_LEAST} {n:,}" if is_floor else f"{n:,}"


@dataclass(frozen=True)
class TransparencyAxis:
    """One clickable segment of the transparency bar.

    Attributes:
        key: Short name used for the ``hidden_by_<key>`` count and its
            ``hidden_by_<key>_is_floor`` flag — so the params dict, the render
            arguments and this table cannot drift apart.
        attr: The ``MainWindow`` attribute holding this segment's button.
        icon: The glyph, from ``icons.py`` (never a literal here).
        handler: Name of the host method the click calls. A NAME rather than a
            bound method because the table is built at import time, before any
            window exists.
        suffix: What the button says after the count.
        tooltip: Hover text — what this layer is and what clicking does.
    """

    key: str
    attr: str
    icon: str
    handler: str
    suffix: str
    tooltip: str


AXES: tuple[TransparencyAxis, ...] = (
    TransparencyAxis(
        key="exclusions",
        attr="_channel_exclusion_btn",
        icon=_icons.global_exclusion_icon,
        handler="_show_exclusion_hidden",
        suffix="hidden by Global Exclusions  —  show",
        tooltip=(
            "Your Global Exclusions are hiding these results (their region / category "
            "is excluded).\nClick to temporarily show them for this view only.\n"
            "Your Global Exclusions are not changed; searching or changing filters "
            "restores the view."
        ),
    ),
    TransparencyAxis(
        key="search",
        attr="_channel_filter_btn",
        icon=_icons.search_filter_icon,
        handler="_show_filtered_results",
        suffix="hidden by search filters  —  show",
        tooltip=(
            "Your current Category / Quality / Platform filters are hiding these "
            "results.\nClick to temporarily show them. Filters are not changed.\n"
            "Changing filters or searching again restores normal filtered view."
        ),
    ),
    TransparencyAxis(
        key="dead",
        attr="_channel_dead_btn",
        icon=_icons.dead_stream_icon,
        handler="_show_dead_hidden",
        suffix="unavailable (repeated play failures)  —  show",
        tooltip=(
            "These channels have repeatedly failed to play and are held back from "
            "the list.\nClick to temporarily show them for this view only.\n"
            "Nothing is deleted; searching or changing filters restores the view."
        ),
    ),
    TransparencyAxis(
        key="keywords",
        attr="_channel_keyword_btn",
        icon=_icons.keyword_exclusion_icon,
        handler="_show_keyword_hidden",
        suffix="hidden by keywords  —  show",
        tooltip=(
            "Your Global Exclusions keyword list is hiding these results (their\n"
            "title matches one of your keywords).\nClick to temporarily show them "
            "for this view only.\n"
            "Your keyword list is not changed; searching or changing filters "
            "restores the view."
        ),
    ),
    TransparencyAxis(
        key="adult",
        attr="_channel_adult_btn",
        icon=_icons.adult_filter_icon,
        # The odd one out, and deliberately so — this OPENS THE SETTING rather
        # than lifting the layer for one view. The four above are filters a user
        # can trip by accident; the gate is a choice they made, so the honest
        # response is to name it and hand over the switch.
        handler="_open_adult_settings",
        suffix="hidden as adult content  —  change in Settings",
        tooltip=(
            "These results are flagged as adult content, which is hidden by your\n"
            "current setting.\nClick to open Settings → Content and change it.\n"
            "Nothing is deleted — this is a setting, not a filter on this view."
        ),
    ),
)

#: Every button attribute the bar owns — the one list ``refresh_theme`` and any
#: skeleton test host should iterate, rather than re-typing four names.
BUTTON_ATTRS: tuple[str, ...] = tuple(axis.attr for axis in AXES)


def build_segments(host, layout, style: str) -> None:
    """Create one button per axis on *host* and add it to *layout*.

    Args:
        host: The ``MainWindow``; each button is stored as ``host.<axis.attr>``
            and connected to ``host.<axis.handler>``.
        layout: The bar's ``QHBoxLayout``.
        style: The shared segment stylesheet, composed by the caller from theme
            tokens (it re-applies the same string in ``refresh_theme``).
    """
    for axis in AXES:
        button = QPushButton()
        button.setVisible(False)
        button.setStyleSheet(style)
        button.setToolTip(axis.tooltip)
        button.clicked.connect(getattr(host, axis.handler))
        layout.addWidget(button)
        setattr(host, axis.attr, button)


def render(host, counts: dict, floors: dict) -> None:
    """Show each segment whose count is > 0, and the bar if any of them is.

    Args:
        host: The ``MainWindow``. Missing buttons are tolerated so a skeleton
            test host renders without wiring all of them.
        counts: ``{axis.key: int}``; a missing key reads as 0.
        floors: ``{axis.key: bool}``; a missing key reads as False.

    Notes:
        ``__dict__.get`` rather than ``hasattr``: PyQt raises ``RuntimeError``
        (not ``AttributeError``) for attribute access on a ``__new__``'d
        ``MainWindow``, so ``hasattr`` does not absorb it and the guard itself
        would explode. Same trap as #351/#375.
    """
    if host.__dict__.get("_channel_filter_bar") is None:
        return

    any_shown = False
    for axis in AXES:
        count = counts.get(axis.key, 0)
        shown = count > 0
        any_shown = any_shown or shown
        button = host.__dict__.get(axis.attr)
        if button is None:
            continue
        if shown:
            button.setText(
                f"{axis.icon} {count_label(count, floors.get(axis.key, False))} "
                f"{axis.suffix}"
            )
        button.setVisible(shown)

    host._channel_filter_bar.setVisible(any_shown)
