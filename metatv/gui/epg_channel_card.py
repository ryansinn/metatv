"""The EPG → My Channels pinned-channel card.

Its own module because ``epg_watchlist_mixin`` is a >1000-line file on a
shrink-only ratchet, and because the card is a self-contained widget: it takes
a view and one channel and returns a ``QWidget``, touching the view only for
its ``_channel_*`` display maps and its action seams.

The card was inert until 2026-08-23 — no click handler, no context menu, and a
Play button gated on whether the guide happened to have data — see
``tests/test_epg_pinned_channel_card.py`` for what that cost and what now
holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metatv.core.epg_utils import now_utc as _now_utc
from metatv.core.epg_utils import remaining_str as _remaining_str
from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui.badge_utils import (
    make_audio_chip,
    make_quality_chip,
    make_region_chip,
    make_year_chip,
)

if TYPE_CHECKING:
    from metatv.core.database import EpgProgramDB


def build_pinned_channel_card(view, channel_db_id: str, channel_name: str,
                              prog: "EpgProgramDB | None") -> QWidget:
    """Build a watchlist channel card from stored detected_* fields.

    Reads ``_channel_*`` maps populated by ``_build_name_map`` — no
    ``parse_channel_name()`` call (ingestion-only rule, CLAUDE.md).
    """
    w = QWidget()
    w.setMinimumWidth(280)
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    _theme.style(w, "CARD_BG")
    # The card was inert: no click handler, no menu, and a Play button that
    # only appeared when the channel HAD guide data — so a pinned channel
    # reading "No EPG data" offered a ✕ and nothing else (owner report,
    # 2026-08-23). Both gestures now behave like every other channel
    # surface: click selects, right-click opens the shared channel menu.
    # QPushButtons consume their own clicks, so the ✕ and Play stay
    # independent of the card body.
    cursor_affordance.set_clickable(w)
    w.mousePressEvent = lambda e, cid=channel_db_id: view._emit_channel_selected(cid)
    w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    w.customContextMenuRequested.connect(
        lambda pos, cid=channel_db_id, widget=w: view.show_epg_channel_menu(
            [cid], "epg_on_now", widget.mapToGlobal(pos)
        )
    )
    layout = QVBoxLayout(w)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(3)

    display_quality = view._channel_quality_map.get(channel_db_id, "")
    region = view._channel_region_map.get(channel_db_id, "")
    audio_form = view._channel_audio_map.get(channel_db_id, "")
    prefix = view._channel_prefix_map.get(channel_db_id, "")
    bare_name = view._channel_title_map.get(channel_db_id, channel_name)
    year = view._channel_year_map.get(channel_db_id, "")

    header = QHBoxLayout()
    icon_lbl = QLabel(f"{view.config.series_icon} ")
    _theme.style_fn(icon_lbl, lambda: f"font-size: {_theme.FONT_XL};")
    header.addWidget(icon_lbl)
    if region:
        header.addWidget(make_region_chip(region, w))
    if audio_form:
        header.addWidget(make_audio_chip(audio_form, w))
    if prefix:
        header.addWidget(make_region_chip(prefix, w))
    ch_lbl = QLabel(bare_name)
    _theme.style(ch_lbl, "LIST_TITLE")
    header.addWidget(ch_lbl)
    if display_quality:
        header.addWidget(make_quality_chip(display_quality, w))
    if year:
        header.addWidget(make_year_chip(year, w))
    header.addStretch()

    # Play is unconditional. It used to be gated on ``prog``, which made
    # playability depend on whether the guide happened to know what was on —
    # two unrelated facts. A pinned channel is a channel; it plays.
    play_btn = QPushButton(f"{view.config.play_icon} Play")
    play_btn.setFixedWidth(70)
    play_btn.setToolTip(f"Play {channel_name}")
    _theme.style_fn(play_btn, lambda: (
        f"background: {_theme.COLOR_ACCENT_GREEN};"
        f" color: {_theme.on_fill(_theme.COLOR_ACCENT_GREEN)};"
        " border-radius: 3px; padding: 2px 6px;"
    ))
    play_btn.clicked.connect(lambda _=False, cid=channel_db_id: view._play_channel(cid))
    header.addWidget(play_btn)

    remove_btn = QPushButton(view.config.close_icon)
    remove_btn.setFixedWidth(24)
    remove_btn.setToolTip(f"Stop watching '{channel_name}'")
    _theme.style(remove_btn, "CLOSE_BTN")
    remove_btn.clicked.connect(lambda _=False, cid=channel_db_id: view._unwatch_channel(cid))
    header.addWidget(remove_btn)
    layout.addLayout(header)

    if prog:
        now = _now_utc()
        remain = _remaining_str(prog.stop_time) if prog.stop_time > now else ""
        suffix = f"  ·  {remain}" if remain else ""
        prog_lbl = QLabel(f"  {prog.title}{suffix}")
        _theme.style_fn(prog_lbl, lambda: f"color: {_theme.COLOR_DIM_2}; font-size: {_theme.FONT_MD}; padding-left: 16px;")
        layout.addWidget(prog_lbl)
    else:
        no_epg = QLabel("  No EPG data")
        _theme.style_fn(no_epg, lambda: f"color: {_theme.COLOR_TEXT}; font-size: {_theme.FONT_MD}; padding-left: 16px;")
        layout.addWidget(no_epg)

    return w
