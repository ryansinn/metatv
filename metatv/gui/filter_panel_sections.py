"""Per-facet rebuild recipes for ``FilterPanel.update_data`` (PERF-17).

``FilterPanel.update_data`` rebuilt all nine dynamic facet sections in one
synchronous pass — measured a 2,037ms main-thread stall at launch (watchdog:
``update_data -> FilterGroupRow.set_flat_items -> row __init__``). Qt widgets
are main-thread only, so the fix is scheduling, not threading:
``update_data`` now hands ``build_chunked`` (``chunked_construction.py``) one
callable per section below, built one per event-loop turn.

Each function here is one section's full rebuild — items assembly,
``set_flat_items``/``set_grouped_items``, and its opt-out ``restore(...)``
call — moved verbatim out of ``update_data`` so build+restore for a given
section stay atomic and ordered within that section's turn. They take the
owning ``FilterPanel`` as ``panel`` and are free to reach into its section
widgets and config, same as the method body they were extracted from.
"""

from __future__ import annotations

from typing import Callable

from metatv.core.channel_name_utils import quality_display

_Restore = Callable[[object, set[str]], None]


def build_language(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Language section — tag values are group names (e.g. "English")."""
    lang_values: dict[str, int] = tag_counts.get('language', {})
    lang_items = sorted(
        [(k, k, v) for k, v in lang_values.items() if v > 0],
        key=lambda x: (-x[2], x[1]),
    )
    prev_lang = set(panel._lang_sec.get_selected_keys())
    panel._lang_sec.set_flat_items(lang_items)
    restore(panel._lang_sec, prev_lang)


def build_region(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Region section — tag values are individual ISO codes (e.g. "US").

    Displayed hierarchically using config.filter_regional_groups: each group is a
    parent, and children are only the ISO codes present in the tag counts.
    """
    region_values: dict[str, int] = tag_counts.get('region', {})
    regional_groups = panel.config.filter_regional_groups
    # Build reverse lookup: ISO code (uppercased) → group name(s)
    code_to_groups: dict[str, list[str]] = {}
    for group_name, codes in regional_groups.items():
        for code in codes:
            code_to_groups.setdefault(code.upper(), []).append(group_name)
    # Accumulate group totals from tag counts
    group_totals: dict[str, int] = {}
    for code, cnt in region_values.items():
        for grp in code_to_groups.get(code.upper(), []):
            group_totals[grp] = group_totals.get(grp, 0) + cnt
    # Build region_data for set_grouped_items
    region_data: list[tuple[str, int, list[tuple[str, str, int]]]] = []
    for group_name in sorted(regional_groups.keys()):
        total = group_totals.get(group_name, 0)
        if total == 0:
            continue
        children: list[tuple[str, str, int]] = [
            (code, panel._region_label(code), region_values.get(code, 0))
            for code in regional_groups[group_name]
            if region_values.get(code, 0) > 0
        ]
        children.sort(key=lambda x: -x[2])
        if children:
            region_data.append((group_name, total, children))
    prev_region = set(panel._region_sec.get_selected_keys())
    panel._region_sec.set_grouped_items(region_data)
    restore(panel._region_sec, prev_region)


def build_platform(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Platform section — tag values are group names (e.g. "Netflix")."""
    platform_values: dict[str, int] = tag_counts.get('platform', {})
    plat_items = sorted(
        [(k, k, v) for k, v in platform_values.items() if v > 0],
        key=lambda x: (-x[2], x[1]),
    )
    prev_plat = set(panel._platform_sec.get_selected_keys())
    panel._platform_sec.set_flat_items(plat_items)
    restore(panel._platform_sec, prev_plat)


def build_quality(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Quality section — tag values are group names (e.g. "HD"); fixed display order."""
    quality_order = ["RAW", "4K / UHD", "HD", "HQ", "SD", "LQ",
                     "CAM / Pre-release"]
    quality_values: dict[str, int] = tag_counts.get('quality', {})
    # (key, LABEL, count): the key stays the stored group name (it is the filter
    # identity); only the label goes through the shared display map, so the
    # "RAW" group chip reads "Uncompressed" without changing what it selects.
    qual_items = [
        (n, quality_display(n), quality_values[n]) for n in quality_order
        if n in quality_values and quality_values[n] > 0
    ]
    for n, v in quality_values.items():
        if n not in quality_order and v > 0:
            qual_items.append((n, quality_display(n), v))
    prev_qual = set(panel._quality_sec.get_selected_keys())
    panel._quality_sec.set_flat_items(qual_items)
    restore(panel._quality_sec, prev_qual)


def build_category(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Category section — tag values are live-channel kinds (e.g. "Sports")."""
    category_values: dict[str, int] = tag_counts.get('category', {})
    category_items = sorted(
        [(k, k, v) for k, v in category_values.items() if v > 0],
        key=lambda x: (-x[2], x[1]),
    )
    prev_category = set(panel._category_sec.get_selected_keys())
    panel._category_sec.set_flat_items(category_items)
    restore(panel._category_sec, prev_category)


def build_genre(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Genre section — tag values are canonical genre names (e.g. "Drama")."""
    genre_values: dict[str, int] = tag_counts.get('genre', {})
    genre_items = sorted(
        [(g, g, c) for g, c in genre_values.items() if c > 0],
        key=lambda x: (-x[2], x[1]),
    )
    prev_genre = set(panel._genre_sec.get_selected_keys())
    panel._genre_sec.set_flat_items(genre_items)
    restore(panel._genre_sec, prev_genre)


def build_subtitle(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Subtitle Language section."""
    subtitle_values: dict[str, int] = tag_counts.get('subtitle', {})
    subtitle_items = sorted(
        [(k, k, v) for k, v in subtitle_values.items() if v > 0],
        key=lambda x: (-x[2], x[1]),
    )
    prev_subtitle = set(panel._subtitle_sec.get_selected_keys())
    panel._subtitle_sec.set_flat_items(subtitle_items)
    restore(panel._subtitle_sec, prev_subtitle)


def build_dub(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Dub Language section."""
    dub_values: dict[str, int] = tag_counts.get('dub', {})
    dub_items = sorted(
        [(k, k, v) for k, v in dub_values.items() if v > 0],
        key=lambda x: (-x[2], x[1]),
    )
    prev_dub = set(panel._dub_sec.get_selected_keys())
    panel._dub_sec.set_flat_items(dub_items)
    restore(panel._dub_sec, prev_dub)


def build_format(panel, tag_counts: dict, restore: _Restore) -> None:
    """Rebuild the Audio Format section — fixed display order (Dub/Original/Multi/Dual)."""
    format_order = ["Dub", "Original", "Multi", "Dual"]
    format_values: dict[str, int] = tag_counts.get('format', {})
    format_items = [
        (n, n, format_values[n]) for n in format_order
        if n in format_values and format_values[n] > 0
    ]
    for n, v in format_values.items():
        if n not in format_order and v > 0:
            format_items.append((n, n, v))
    prev_format = set(panel._format_sec.get_selected_keys())
    panel._format_sec.set_flat_items(format_items)
    restore(panel._format_sec, prev_format)
