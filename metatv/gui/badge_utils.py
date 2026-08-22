"""Shared chip/badge widget factories for region codes, quality tiers, audio format, and year."""
from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt

from metatv.core.channel_name_utils import (
    PLATFORM_CODES,
    REGION_FULL_NAMES,
    quality_display,
    quality_tooltip,
)
from metatv.gui import theme as _theme

def _quality_colors() -> dict[str, str]:
    """Quality/codec token → theme color, re-read fresh so a live theme switch applies."""
    return {
        "4K": _theme.COLOR_QUALITY_UHD, "8K": _theme.COLOR_QUALITY_UHD, "UHD": _theme.COLOR_QUALITY_UHD,
        "FHD": _theme.COLOR_QUALITY_FHD,
        "HDR10": _theme.COLOR_QUALITY_FHD, "HDR10+": _theme.COLOR_QUALITY_FHD, "HDR": _theme.COLOR_QUALITY_FHD,
        "HEVC": _theme.COLOR_QUALITY_FHD, "H265": _theme.COLOR_QUALITY_FHD, "H264": _theme.COLOR_QUALITY_FHD,
        "HD": _theme.COLOR_QUALITY_HD,
        "SD": _theme.COLOR_MUTED_2,
        "RAW": _theme.COLOR_QUALITY_RAW, "HQ": _theme.COLOR_QUALITY_RAW,
        "LQ": _theme.COLOR_BORDER,
        "LIVE": _theme.COLOR_QUALITY_LIVE,
    }


def _quality_outline_colors() -> dict[str, str]:
    """Quality/codec token → OUTLINE-chip theme color (channel_list_delegate.py's
    #257 outline-only quality chip ONLY — never used by :func:`make_quality_chip`'s
    solid-fill widget below, which keeps reading :func:`_quality_colors` unchanged).

    ``_quality_colors()``'s ``COLOR_QUALITY_*`` family is a SOLID-FILL palette:
    it pairs a saturated mid-tone hue with light/self-contained text and is
    explicitly held theme-invariant across all three palettes (theme_palettes.py's
    module docstring — "the owner explicitly likes this hue system"). As TEXT/
    BORDER on an outline chip against the app's OWN background instead, those
    same mid-tone values measure well under a 4.5:1 contrast floor on every
    palette (verified: 1.57-4.09:1, none clearing 4.5) — mid-brightness colours
    are hard to read as either light-on-dark or dark-on-light text.

    ``COLOR_QUALITY_OUTLINE_*`` is a SEPARATE, dedicated per-palette family
    (theme_palettes.py) — same hue (H) as the corresponding ``COLOR_QUALITY_*``
    token, lightness tuned per palette so the outline chip's text/border clears
    4.5:1 against ``COLOR_BG_SECTION``: brighter in the two dark palettes
    (Midnight/Graphite), darker in Daylight. See
    ``tests/test_palette_completeness.py``'s
    ``test_quality_outline_chip_contrast_at_least_4_5_every_palette``.
    """
    return {
        "4K": _theme.COLOR_QUALITY_OUTLINE_UHD, "8K": _theme.COLOR_QUALITY_OUTLINE_UHD,
        "UHD": _theme.COLOR_QUALITY_OUTLINE_UHD,
        "FHD": _theme.COLOR_QUALITY_OUTLINE_FHD,
        "HDR10": _theme.COLOR_QUALITY_OUTLINE_FHD, "HDR10+": _theme.COLOR_QUALITY_OUTLINE_FHD,
        "HDR": _theme.COLOR_QUALITY_OUTLINE_FHD,
        "HEVC": _theme.COLOR_QUALITY_OUTLINE_FHD, "H265": _theme.COLOR_QUALITY_OUTLINE_FHD,
        "H264": _theme.COLOR_QUALITY_OUTLINE_FHD,
        "HD": _theme.COLOR_QUALITY_OUTLINE_HD,
        "SD": _theme.COLOR_MUTED_2,
        "RAW": _theme.COLOR_QUALITY_OUTLINE_RAW, "HQ": _theme.COLOR_QUALITY_OUTLINE_RAW,
        "LQ": _theme.COLOR_BORDER,
        "LIVE": _theme.COLOR_QUALITY_OUTLINE_LIVE,
    }


def _chip_base() -> str:
    return (
        "border-radius: 3px; padding: 1px 5px; font-size: " + _theme.FONT_SM + ";"
        " font-weight: bold; color: " + _theme.COLOR_TEXT_HI + "; background: {bg};"
    )


def _region_style() -> str:
    return _chip_base().format(bg=_theme.OVERLAY_15)


def _platform_style() -> str:
    return _chip_base().format(bg=_theme.OVERLAY_PLATFORM_BADGE)


def _audio_style() -> str:
    return _chip_base().format(bg=_theme.COLOR_AUDIO_BADGE)


def _year_style() -> str:
    return (
        f"border: 1px solid {_theme.COLOR_FAINT}; border-radius: 3px; padding: 1px 5px;"
        f" font-size: {_theme.FONT_SM}; color: {_theme.COLOR_MUTED}; background: transparent;"
    )


def make_region_chip(code: str, parent=None) -> QLabel:
    """Chip for a region/country or streaming platform code.

    Platform codes (NF, D+, HBO, PRIME…) use steel-blue; geographic codes use grey.
    """
    style = _platform_style() if code in PLATFORM_CODES else _region_style()
    lbl = QLabel(code, parent)
    lbl.setStyleSheet(style)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setToolTip(REGION_FULL_NAMES.get(code, code))
    return lbl


def make_quality_chip(quality: str, parent=None) -> QLabel:
    """Colored chip for a quality/codec token (HD, SD, 4K, HEVC, etc.).

    The chip TEXT is the viewer-facing label from ``quality_display`` (so ``RAW``
    reads "Uncompressed"), and the tooltip explains any token that isn't really a
    quality tier (HEVC/H265/H264).  The stored token stays the identity — colour
    lookup and every caller keep using it.
    """
    upper = quality.upper()
    color = _quality_colors().get(upper, _theme.COLOR_FAINT)
    lbl = QLabel(quality_display(upper), parent)
    lbl.setStyleSheet(_chip_base().format(bg=color))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setToolTip(quality_tooltip(quality))
    return lbl


def make_audio_chip(audio: str, parent=None) -> QLabel:
    """Muted olive chip for audio presentation format (Multi, Dub, Sub)."""
    lbl = QLabel(audio, parent)
    lbl.setStyleSheet(_audio_style())
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setToolTip({"Multi": "Multiple audio/subtitle tracks", "Dub": "Dubbed", "Sub": "Subtitled"}.get(audio, audio))
    return lbl


def make_year_chip(year: str, parent=None) -> QLabel:
    """Ghost/outlined chip for a year or year-range — far-right, least prominent."""
    lbl = QLabel(year, parent)
    lbl.setStyleSheet(_year_style())
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl
