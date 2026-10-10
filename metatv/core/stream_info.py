"""What a stream actually contains, read off the player (PLAYED-1).

The provider's name says "4K" or "|SE|"; the stream says what it really is.
When a channel plays, mpv already knows the resolution, frame rate, codecs,
bitrates and every audio and subtitle track. This module turns mpv's
properties into one plain record (``parse_mpv``) that is stored per channel,
and turns a stored record into the rows the details pane shows
(``display_rows``). Pure functions, no Qt and no database, so a future
"Get details" probe can produce the same record without playing anything.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from metatv.core.channel_name_utils import (
    AUDIO_LANG_WORD_MAP, CODE_FACETS, ISO_639_1_LANGUAGE_NAMES, LANGUAGE_REGION_VARIANTS,
)

#: The mpv properties one capture reads.
MPV_PROPS: tuple[str, ...] = (
    "track-list", "video-params", "video-bitrate", "audio-bitrate",
    "container-fps", "estimated-vf-fps", "file-format", "video-codec",
)

_CODEC_NAMES = {
    "h264": "H.264", "hevc": "HEVC", "h265": "HEVC", "av1": "AV1", "vp9": "VP9",
    "mpeg2video": "MPEG-2", "mpeg4": "MPEG-4", "aac": "AAC", "ac3": "AC-3",
    "eac3": "E-AC-3", "dts": "DTS", "truehd": "TrueHD", "mp3": "MP3", "mp2": "MP2",
    "opus": "Opus", "flac": "FLAC", "dvb_subtitle": "DVB", "dvd_subtitle": "DVD",
    "eia_608": "CC (EIA-608)", "subrip": "SRT", "ass": "ASS", "webvtt": "WebVTT",
    "hdmv_pgs_subtitle": "PGS", "mov_text": "Text",
}


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _kbps(bits_per_second: Any) -> int | None:
    v = _num(bits_per_second)
    return round(v / 1000) if v else None


def parse_mpv(props: dict) -> dict | None:
    """Turn mpv's properties into a stored stream record.

    Args:
        props: ``{name: value}`` for :data:`MPV_PROPS` (missing names → None).

    Returns:
        ``{"video": {...} | None, "audio": [...], "subs": [...],
        "container": str | None}``, or None when mpv reported no tracks at
        all (nothing loaded yet — not worth storing).
    """
    tracks = props.get("track-list") or []
    if not isinstance(tracks, list) or not tracks:
        return None
    vp = props.get("video-params") if isinstance(props.get("video-params"), dict) else {}
    video = None
    audio, subs = [], []
    for t in tracks:
        if not isinstance(t, dict):
            continue
        kind = t.get("type")
        if kind == "video" and not t.get("image") and (video is None or t.get("selected")):
            gamma = (vp.get("gamma") or "").lower()
            video = {
                "codec": t.get("codec"),
                "profile": t.get("codec-profile"),
                "width": vp.get("w") or t.get("demux-w"),
                "height": vp.get("h") or t.get("demux-h"),
                "fps": round(_num(props.get("container-fps")) or _num(t.get("demux-fps"))
                             or _num(props.get("estimated-vf-fps")) or 0, 3) or None,
                "hdr": "HDR10" if gamma == "pq" else "HLG" if gamma == "hlg" else None,
                "bitrate_kbps": _kbps(props.get("video-bitrate")),
            }
        elif kind == "audio":
            audio.append({
                "lang": t.get("lang"),
                "codec": t.get("codec"),
                "profile": t.get("codec-profile"),
                "channels": t.get("demux-channel-count"),
                "samplerate": t.get("demux-samplerate"),
                "bitrate_kbps": _kbps(t.get("demux-bitrate")) or (
                    _kbps(props.get("audio-bitrate")) if t.get("selected") else None),
                "default": bool(t.get("default")),
            })
        elif kind == "sub":
            subs.append({
                "lang": t.get("lang"),
                "title": t.get("title"),        # "Completos CC" tells two tracks apart
                "codec": t.get("codec"),
                "default": bool(t.get("default")),
                "external": bool(t.get("external")),
            })
    return {"video": video, "audio": audio, "subs": subs,
            "container": props.get("file-format")}


# ffprobe reports H.264/HEVC profiles as numbers in some panels' JSON.
_FFPROBE_PROFILES = {("h264", "66"): "Baseline", ("h264", "77"): "Main",
                     ("h264", "100"): "High", ("h264", "110"): "High 10",
                     ("hevc", "1"): "Main", ("hevc", "2"): "Main 10"}


def _fraction(fraction: Any) -> float | None:
    """"24000/1001" → 23.976; "0/0" or junk → None."""
    try:
        num, _, den = str(fraction).partition("/")
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 3) if value > 0 else None


def provider_stream_record(info: dict | None) -> dict | None:
    """A provider's own ffprobe (Xtream ``get_vod_info`` → ``info.video`` /
    ``info.audio`` / ``info.bitrate``) as a stream record — the same shape as
    :func:`parse_mpv`, stored with ``source="provider"``.

    Only the first audio track is reported and no subtitles, and it describes
    the file the provider probed, which can differ from what plays today — so
    it ranks below a played or probed measurement, above any guess.
    """
    if not isinstance(info, dict):
        return None
    v = info.get("video") if isinstance(info.get("video"), dict) else None
    a = info.get("audio") if isinstance(info.get("audio"), dict) else None
    if not v and not a:
        return None
    video = None
    if v:
        codec = (v.get("codec_name") or "").lower()
        profile = str(v.get("profile") or "")
        transfer = (v.get("color_transfer") or "").lower()
        total_kbps = int(info["bitrate"]) if str(info.get("bitrate", "")).isdigit() else None
        vtags = v.get("tags") if isinstance(v.get("tags"), dict) else {}
        track_kbps = _kbps(int(vtags["BPS"])) if str(vtags.get("BPS", "")).isdigit() else None
        audio_kbps = _kbps(int(a["bit_rate"])) if a and str(a.get("bit_rate", "")).isdigit() else None
        video = {
            "codec": codec or None,
            "profile": _FFPROBE_PROFILES.get((codec, profile), profile if not profile.isdigit() else None),
            "width": v.get("width"),
            "height": v.get("height"),
            "fps": _fraction(v.get("avg_frame_rate")) or _fraction(v.get("r_frame_rate")),
            "hdr": "HDR10" if transfer == "smpte2084" else "HLG" if transfer == "arib-std-b67" else None,
            # The track's own BPS tag when the muxer wrote one; else total minus audio.
            "bitrate_kbps": track_kbps or ((total_kbps - audio_kbps) if total_kbps and audio_kbps
                                           else total_kbps),
        }
    audio = []
    if a:
        tags = a.get("tags") if isinstance(a.get("tags"), dict) else {}
        audio.append({
            "lang": tags.get("language") or tags.get("LANGUAGE"),
            "codec": (a.get("codec_name") or "").lower() or None,
            "profile": None,
            "channels": a.get("channels"),
            "samplerate": a.get("sample_rate"),
            "bitrate_kbps": (_kbps(int(a["bit_rate"])) if str(a.get("bit_rate", "")).isdigit()
                             else _kbps(int(tags["BPS"])) if str(tags.get("BPS", "")).isdigit()
                             else None),
            "default": True,
        })
    return {"video": video, "audio": audio, "subs": [], "container": None}


def provider_original_language(info: dict | None) -> str | None:
    """TMDb's original language as a provider passes it on. Xtream panels put it
    in ``country`` ("English") — named for a country, holding a language — or in
    ``original_language`` (an ISO code). A value that is not a known language
    name or code (a real country) yields None."""
    if not isinstance(info, dict):
        return None
    for key in ("original_language", "country"):
        value = str(info.get(key) or "").strip()
        if not value:
            continue
        if value in _LANGUAGE_NAMES:
            return value
        if len(value) <= 3:
            name = language_name(value)
            if name in _LANGUAGE_NAMES:
                return name
    return None


def merge_bitrate(earlier: dict | None, later: dict | None) -> dict | None:
    """Combine two captures of one play: keep the later record, but never let
    a missing later bitrate erase one the earlier capture had."""
    if not later:
        return earlier
    if earlier and later.get("video") and earlier.get("video"):
        if not later["video"].get("bitrate_kbps"):
            later["video"]["bitrate_kbps"] = earlier["video"].get("bitrate_kbps")
    return later


# ── display ──────────────────────────────────────────────────────────────────

def language_name(code: str | None) -> str:
    """mpv's track language → a language name: "eng"/"en"/"es-ES" → "English"/
    "English"/"Spanish". The region subtag of a BCP-47 tag ("es-ES", "pt_BR")
    is dropped; three-letter codes go through the shared provider map, two-
    letter ones through the ISO 639-1 table. Unknown → the code itself."""
    if not code:
        return "Unknown"
    parts = code.strip().replace("_", "-").split("-")
    primary = parts[0]
    if len(parts) > 1:
        # "es-MX" → Spanish (Mexico), "es-419" → Latin American Spanish; es-ES
        # (castellano) is plain Spanish. A 3-letter base ("spa") maps first.
        base = {"spa": "es", "por": "pt"}.get(primary.lower(), primary.lower())
        variant = LANGUAGE_REGION_VARIANTS.get((base, parts[1].upper()))
        if variant:
            return variant
    return (AUDIO_LANG_WORD_MAP.get(primary.upper())
            or ISO_639_1_LANGUAGE_NAMES.get(primary.lower())
            or code.upper())


_LANGUAGE_NAMES = frozenset(AUDIO_LANG_WORD_MAP.values()) | frozenset(ISO_639_1_LANGUAGE_NAMES.values())


def _codec(name: str | None) -> str:
    return _CODEC_NAMES.get((name or "").lower(), (name or "?").upper())


def _channels(n: Any) -> str:
    return {1: "mono", 2: "2.0", 6: "5.1", 8: "7.1"}.get(n, f"{n}ch") if n else ""


def _rate(kbps: Any) -> str:
    if not kbps:
        return ""
    return f"{kbps / 1000:.1f} Mb/s" if kbps >= 1000 else f"{kbps} kb/s"


def resolution_label(height: Any) -> str | None:
    """The quality word a height earns: 2160 → "4K", 1080 → "1080p"…"""
    if not isinstance(height, int) or height <= 0:
        return None
    if height >= 2000:
        return "4K"
    for h in (1440, 1080, 720, 576, 480):
        if height >= h * 0.9:
            return f"{h}p"
    return f"{height}p"


# How a provider's quality claim maps onto a minimum height, for the
# "says 4K · plays 1080p" note. A claim not listed here is not judged.
_CLAIM_MIN_HEIGHT = {"4K": 2000, "UHD": 2000, "2160P": 2000, "FHD": 1000, "1080P": 1000,
                     "HD": 680, "720P": 680}


def display_rows(info: dict, *, claimed_quality: str | None = None) -> list[tuple[str, str]]:
    """Rows for the details pane: ``[(key, value text)]``.

    Args:
        info: A stored record from :func:`parse_mpv`.
        claimed_quality: The channel's provider-stated quality ("4K", "FHD"…);
            when the measured picture falls short of it, the Resolution row
            says so.
    """
    rows: list[tuple[str, str]] = []
    v = info.get("video") or {}
    if v.get("width") and v.get("height"):
        parts = [f"{v['width']}×{v['height']}"]
        if v.get("fps"):
            parts.append(f"{v['fps']:g} fps")
        if v.get("hdr"):
            parts.append(v["hdr"])
        claim = (claimed_quality or "").upper()
        need = _CLAIM_MIN_HEIGHT.get(claim)
        if need and v["height"] < need:
            parts.append(f"says {claimed_quality}, plays {resolution_label(v['height'])}")
        rows.append(("Resolution", " · ".join(parts)))
    if v.get("codec"):
        text = _codec(v["codec"]) + (f" {v['profile']}" if v.get("profile") else "")
        if v.get("bitrate_kbps"):
            text += f" · {_rate(v['bitrate_kbps'])}"
        rows.append(("Video", text))
    for i, a in enumerate(info.get("audio") or []):
        bits = [language_name(a.get("lang")), _codec(a.get("codec")), _channels(a.get("channels"))]
        if a.get("bitrate_kbps"):
            bits.append(_rate(a["bitrate_kbps"]))
        rows.append(("Audio" if i == 0 else "", " ".join(b for b in bits[:3] if b)
                     + (f" · {bits[3]}" if len(bits) > 3 else "")))
    subs = info.get("subs") or []
    if subs:
        rows.append(("Subtitles", " · ".join(_sub_label(s) for s in subs)))
    return rows


def measured_tags(info: dict | None, source: str = "played") -> list[tuple[str, str, str]]:
    """Tags a measurement proves, for search: ``(facet, value, "played_tracks")``.

    Audio languages → ``language``; subtitle tracks with a language →
    ``subtitle``. The ``played_tracks`` feeder ranks as observed — above
    anything the provider states or MetaTV guesses.
    """
    if not info:
        return []
    # Provenance follows the source: heard while streaming is OBSERVED; the
    # provider's own ffprobe is a statement by the provider, ranked below it.
    feeder = "provider_probe" if source == "provider" else "played_tracks"
    out = [("language", language_name(a.get("lang")), feeder)
           for a in info.get("audio") or [] if a.get("lang")]
    out += [("subtitle", language_name(s.get("lang")), feeder)
            for s in info.get("subs") or [] if s.get("lang")]
    return list(dict.fromkeys(out))


def audio_contradicts_prefix(heard: "tuple[str, ...] | list[str]", prefix: str | None) -> bool:
    """True when a copy's measured audio languages exclude the language its
    prefix code denotes — a |SE| copy that is really English. False when
    nothing was heard, the code denotes no language, or they agree.

    Args:
        heard: Language names measured in the stream (``summarize()["audio"]``).
        prefix: The channel's ``detected_prefix``.
    """
    if not heard or not prefix:
        return False
    denoted = {val for kind, val, _c in CODE_FACETS.get(prefix.upper(), ()) if kind == "language"}
    return bool(denoted) and not (denoted & set(heard))


def measured_quality(height: Any) -> str | None:
    """The quality tier a measured height earns, in the app's own quality
    vocabulary (so the badge keeps its tier colour): 4K / FHD / HD / SD."""
    if not isinstance(height, int) or height <= 0:
        return None
    if height >= 2000:
        return "4K"
    if height >= 1000:
        return "FHD"
    if height >= 680:
        return "HD"
    return "SD"


def summarize(record: dict | None) -> dict | None:
    """A stored record reduced to what a copy chip needs.

    Returns:
        ``{"width", "height", "audio": (language names…), "subs": (labels…),
        "at": datetime | None, "source": str}``, or None for no record.
    """
    if not record or not record.get("info"):
        return None
    info = record["info"]
    v = info.get("video") or {}
    return {
        "width": v.get("width"),
        "height": v.get("height"),
        "audio": tuple(dict.fromkeys(
            language_name(a.get("lang")) for a in info.get("audio") or [] if a.get("lang"))),
        "subs": tuple(_sub_label(s) for s in info.get("subs") or []),
        "at": record.get("measured_at"),
        "source": record.get("source", ""),
    }


def _sub_label(s: dict) -> str:
    """"Spanish SRT (Completos CC)" — language, format, and the track's own
    title when it has one (two same-language tracks differ only there)."""
    label = (f"{language_name(s.get('lang'))} {_codec(s.get('codec'))}" if s.get("lang")
             else _codec(s.get("codec")))
    return f"{label} ({s['title']})" if s.get("title") else label


def measured_caption(measured_at: datetime | None, source: str) -> str:
    """"seen when played Oct 9" / "probed Oct 9" / "reported by source Oct 9"."""
    verb = {"probe": "probed", "provider": "reported by source"}.get(source, "seen when played")
    return f"{verb} {measured_at:%b} {measured_at.day}" if measured_at else verb
