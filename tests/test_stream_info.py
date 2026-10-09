"""PLAYED-1: mpv's view of a playing stream → a stored record → Details rows.

The fixture is the A&E stream from the owner's 2026-10-08 log: h264 High
1920x1080 @59.94, English HE-AAC + Spanish AAC, DVB + EIA-608 subtitles.
"""
from datetime import datetime

from metatv.core.stream_info import display_rows, measured_caption, parse_mpv

AE_PROPS = {
    "track-list": [
        {"type": "video", "id": 1, "codec": "h264", "codec-profile": "High",
         "demux-w": 1920, "demux-h": 1080, "demux-fps": 59.9401, "selected": True},
        {"type": "audio", "id": 1, "lang": "eng", "codec": "aac", "codec-profile": "HE-AAC",
         "demux-channel-count": 2, "demux-samplerate": 48000, "selected": True},
        {"type": "audio", "id": 2, "lang": "spa", "codec": "aac",
         "demux-channel-count": 2, "demux-samplerate": 48000},
        {"type": "sub", "id": 1, "codec": "dvb_subtitle"},
        {"type": "sub", "id": 2, "codec": "eia_608", "default": True},
    ],
    "video-params": {"w": 1920, "h": 1080, "gamma": "bt.1886"},
    "video-bitrate": 4_200_000, "audio-bitrate": 93_000,
    "container-fps": 59.9401, "file-format": "mpegts",
}


def test_parse_reads_every_track():
    info = parse_mpv(AE_PROPS)
    assert info["video"]["width"] == 1920 and info["video"]["height"] == 1080
    assert info["video"]["bitrate_kbps"] == 4200
    assert [a["lang"] for a in info["audio"]] == ["eng", "spa"]
    assert info["audio"][0]["bitrate_kbps"] == 93          # the selected track
    assert [s["codec"] for s in info["subs"]] == ["dvb_subtitle", "eia_608"]


def test_nothing_loaded_is_not_stored():
    assert parse_mpv({"track-list": []}) is None


def test_rows_name_languages_and_measurements():
    rows = {(k or f"+{i}"): v for i, (k, v) in enumerate(display_rows(parse_mpv(AE_PROPS)))}
    assert rows["Resolution"] == "1920×1080 · 59.94 fps"
    assert rows["Video"] == "H.264 High · 4.2 Mb/s"
    assert rows["Audio"].startswith("English AAC 2.0")
    assert any(v.startswith("Spanish AAC 2.0") for v in rows.values())
    assert rows["Subtitles"] == "DVB · CC (EIA-608)"


def test_a_claim_the_stream_does_not_meet_is_called_out():
    rows = dict(display_rows(parse_mpv(AE_PROPS), claimed_quality="4K"))
    assert "says 4K, plays 1080p" in rows["Resolution"]
    rows = dict(display_rows(parse_mpv(AE_PROPS), claimed_quality="FHD"))
    assert "says" not in rows["Resolution"]


def test_hdr_is_named():
    props = dict(AE_PROPS, **{"video-params": {"w": 3840, "h": 2160, "gamma": "pq"}})
    assert "HDR10" in dict(display_rows(parse_mpv(props)))["Resolution"]


def test_caption_says_how_it_was_measured():
    when = datetime(2026, 10, 9, 20, 0)
    assert measured_caption(when, "played") == "seen when played Oct 9"
    assert measured_caption(when, "probe") == "probed Oct 9"
