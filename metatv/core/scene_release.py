"""The scene-release pass of the name parser ("Title 2024 1080p WEB-DL ...") —
split out of channel_name_utils (ledger F30).
"""

from __future__ import annotations

import re

from metatv.core.quality_vocab import _Attributes, _collapse_same_rank, _SOURCE_QUALITY_NORM, AUDIO_CODEC_NORM, ENCODING_NORM, QUALITY_TIER_RANK, RESOLUTION_TO_QUALITY


# --- Scene-release filenames -------------------------------------------------
#
# 1,268 rows in the owner's library render a torrent filename as their title:
# "Onder.Het.Maaiveld.2023.DUTCH.1080p.WEB.h264-TRIPEL",
# "Ceu.em.Chamas-Skyfire.2019.1080p.WEB-DL.x264.DUAL-COMANDO.TO". The
# end-anchored loop in _strip_attributes cannot reach them: it walks backwards
# one token at a time and stops at the first thing it does not recognise, and
# these names END in a release-group tag ("-TURG", "XT", "COMANDO.TO") that no
# vocabulary will ever contain. One unknown token at the tail hides everything
# in front of it.
#
# So this is a FORWARD pass. It finds where the title stops rather than where
# the junk starts, which is the only direction that works when the tail is
# open-ended.
#
# HARD markers are the vocabulary that qualifies a name AND marks the cut. Each
# was measured across the owner's 467,373 distinct names and none appears as a
# real title word. A pixel height and an encoding never do; the source tags are
# the same words a torrent group uses and nothing else.
_SCENE_HARD_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    r"(?:2160|1440|1080|720|576|480|360)[pi]"          # resolution
    r"|x26[45]|[Hh][._ ]?26[45]|HEVC|XviD|DivX"        # encoding
    r"|WEB[._ -]?DL|WEB[._ -]?Rip|Blu[._ -]?Ray"       # source
    r"|BD[._ -]?Rip|BR[._ -]?Rip|BRRp|HD[._ -]?Rip"
    r"|HDTV|DVD[._ -]?Rip|REMUX"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# SOFT markers are harvested only from the tail of a name that has ALREADY
# qualified on two hard markers. They are held back because each one is a real
# title somewhere: "GR - Opus (2025)" is a film, and DTS, Atmos and FLAC are all
# plausible channel names. Position, not vocabulary, is what makes them safe
# here — everything after the cut is provider junk by construction.
_SCENE_SOFT_AUDIO_RE = re.compile(
    r"(?<![A-Za-z0-9])("
    r"DDP?[._ -]?5[._ ]1|DD\+|E[-._ ]?AC[-._ ]?3|AC[-._ ]?3"
    r"|AAC(?:[._ -]?2[._ ]0)?|DTS(?:[-._ ]?HD)?|TrueHD|Atmos|Opus|FLAC"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

#: Two hard markers, not one. "BLURAY-DE - Bonhoeffer (2024)" carries exactly
#: one and is NOT a scene release — BLURAY-DE is the provider's category prefix,
#: which the prefix pass already strips correctly. Cutting on a single marker
#: would turn that title into "-DE - Bonhoeffer". Likewise "UK| MORE4 HEVC HD"
#: has one, and cutting there would throw away the HD that follows it.
_SCENE_MIN_HARD_MARKERS = 2

#: Separators a scene filename uses in place of spaces. Converted only in the
#: surviving title, never in the tail — "DDP5.1" must keep its dot long enough
#: to be recognised.
_SCENE_TRAILING_YEAR_RE = re.compile(r"\s+((?:19|20)\d{2})$")
_SCENE_SEP_RE = re.compile(r"[._]+")
_SCENE_EDGE_RE = re.compile(r"^[\s\-–—_.|]+|[\s\-–—_.|]+$")


def _sub_outside_brackets(pattern: "re.Pattern[str]", repl: str, text: str) -> str:
    """Apply a substitution to ``text``, leaving bracketed spans untouched.

    Args:
        pattern: What to replace.
        repl: Replacement string.
        text: Subject text; ``(...)`` and ``[...]`` spans are passed through.

    Returns:
        The substituted text.
    """
    out: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "([":
            if depth == 0:
                out.append(pattern.sub(repl, text[start:i]))
                start = i
            depth += 1
        elif ch in ")]" and depth:
            depth -= 1
            if depth == 0:
                out.append(text[start:i + 1])
                start = i + 1
    tail = text[start:]
    out.append(tail if depth else pattern.sub(repl, tail))
    return "".join(out)


def _canonical_audio_codec(token: str) -> str:
    """Fold a scene filename's spelling of a codec onto an AUDIO_CODEC_NORM key.

    A filename writes the same codec five ways — ``DDP5.1``, ``DDP.5.1``,
    ``DDP 5.1``, ``DDP-5.1``, ``DDP_5_1`` — because the separator is whatever
    the release group used, and it is the same character that separates every
    other field. Stripping separators outright is wrong: it turns ``DDP5.1``
    into ``DDP51``, which is in no vocabulary, and it welds ``DTS-HD`` shut.

    Args:
        token: The codec exactly as it appeared in the name.

    Returns:
        A key suitable for ``AUDIO_CODEC_NORM``, or the folded token when the
        vocabulary has no entry for it.
    """
    t = re.sub(r"\s+", " ", token.upper().replace("_", " ")
               .replace(".", " ").replace("-", " ")).strip()
    t = re.sub(r"^E\s*A\s*C\s*3$", "EAC3", t)
    t = re.sub(r"^A\s*C\s*3$", "AC3", t)
    t = t.replace("DTS HD", "DTS-HD").replace("TRUE HD", "TRUEHD")
    return re.sub(r"^(DDP?|AAC)\s*(\d)\s*(\d)$", r"\1\2.\3", t)


def _extract_scene_release(bare: str) -> "tuple[str, _Attributes] | None":
    """Split a scene-release filename into its title and its attributes.

    Returns ``None`` when the name is not a scene release, so the caller falls
    through to the ordinary end-anchored passes unchanged. This is deliberately
    a hard gate: the pass rewrites a title, and rewriting one that was already
    right is worse than leaving junk on one that was already wrong.

    Args:
        bare: A channel name with its provider prefix already removed.

    Returns:
        ``(title, attributes)`` for a scene release, else ``None``.

    Examples:
        >>> t, a = _extract_scene_release("Atlas.2024.1080p.WEB-DL.x264.DDP5.1")
        >>> t, a.quality, a.encoding, a.audio_codec
        ('Atlas 2024', ['FHD'], 'H.264', 'DD+ 5.1')
    """
    hard = list(_SCENE_HARD_RE.finditer(bare))
    if len(hard) < _SCENE_MIN_HARD_MARKERS:
        return None

    head, tail = bare[: hard[0].start()], bare[hard[0].start():]

    quality: list[str] = []
    encoding = audio_codec = ""
    for match in hard:
        token = match.group(1).upper().replace(".", "").replace(" ", "").replace("-", "")
        if token in RESOLUTION_TO_QUALITY:
            token = RESOLUTION_TO_QUALITY[token]
        if token in ENCODING_NORM:
            encoding = encoding or ENCODING_NORM[token]
            continue
        if token in _SOURCE_QUALITY_NORM:
            token = _SOURCE_QUALITY_NORM[token]
        elif token not in QUALITY_TIER_RANK:
            # A source tag with no quality meaning (WEBDL, BLURAY, REMUX). It
            # told us where the cut goes; it is not an attribute.
            continue
        if token not in quality:
            quality.append(token)

    if (am := _SCENE_SOFT_AUDIO_RE.search(tail)):
        codec = _canonical_audio_codec(am.group(1))
        audio_codec = AUDIO_CODEC_NORM.get(codec, codec)

    # Dots are the filename's word separator — but only OUTSIDE a bracket. An
    # episode's air date rides along in parentheses ("Kral Kaybederse 10 BLM
    # (22.04.2025)") and converting those dots turns a date into three numbers.
    title = _SCENE_EDGE_RE.sub("", _sub_outside_brackets(_SCENE_SEP_RE, " ", head))
    title = re.sub(r"\s{2,}", " ", title)
    # "Atlas.2024.1080p…" leaves "Atlas 2024", and step 5's year strip requires
    # parentheses — deliberately, because "Blade Runner 2049" is a title. Here
    # the position settles it: a bare year directly before the first scene
    # marker IS the release year, that being the whole convention. Re-punctuate
    # rather than extract, so the ONE year strip stays the only one.
    title = _SCENE_TRAILING_YEAR_RE.sub(r" (\1)", title)

    return title, _Attributes(_collapse_same_rank(quality), "", encoding, audio_codec)
