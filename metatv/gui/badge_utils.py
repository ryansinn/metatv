"""Shared chip/badge widget factories for region codes, quality tiers, audio format, and year."""
from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt

from metatv.core.channel_name_utils import PLATFORM_CODES, REGION_FULL_NAMES
from metatv.gui import theme as _theme

_QUALITY_COLORS: dict[str, str] = {
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

_CHIP_BASE = (
    "border-radius: 3px; padding: 1px 5px; font-size: 10px;"
    " font-weight: bold; color: white; background: {bg};"
)

_REGION_STYLE  = _CHIP_BASE.format(bg=_theme.OVERLAY_15)
_PLATFORM_STYLE = _CHIP_BASE.format(bg=_theme.OVERLAY_PLATFORM_BADGE)
_AUDIO_STYLE   = _CHIP_BASE.format(bg=_theme.COLOR_AUDIO_BADGE)
_YEAR_STYLE = (
    f"border: 1px solid {_theme.COLOR_FAINT}; border-radius: 3px; padding: 1px 5px;"
    f" font-size: 10px; color: {_theme.COLOR_MUTED}; background: transparent;"
)


def make_region_chip(code: str, parent=None) -> QLabel:
    """Chip for a region/country or streaming platform code.

    Platform codes (NF, D+, HBO, PRIME…) use steel-blue; geographic codes use grey.
    """
    style = _PLATFORM_STYLE if code in PLATFORM_CODES else _REGION_STYLE
    lbl = QLabel(code, parent)
    lbl.setStyleSheet(style)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setToolTip(REGION_FULL_NAMES.get(code, code))
    return lbl


def make_quality_chip(quality: str, parent=None) -> QLabel:
    """Colored chip for a quality/codec token (HD, SD, 4K, HEVC, etc.)."""
    upper = quality.upper()
    color = _QUALITY_COLORS.get(upper, _theme.COLOR_FAINT)
    lbl = QLabel(upper, parent)
    lbl.setStyleSheet(_CHIP_BASE.format(bg=color))
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


def make_audio_chip(audio: str, parent=None) -> QLabel:
    """Muted olive chip for audio presentation format (Multi, Dub, Sub)."""
    lbl = QLabel(audio, parent)
    lbl.setStyleSheet(_AUDIO_STYLE)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setToolTip({"Multi": "Multiple audio/subtitle tracks", "Dub": "Dubbed", "Sub": "Subtitled"}.get(audio, audio))
    return lbl


def make_year_chip(year: str, parent=None) -> QLabel:
    """Ghost/outlined chip for a year or year-range — far-right, least prominent."""
    lbl = QLabel(year, parent)
    lbl.setStyleSheet(_YEAR_STYLE)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl
