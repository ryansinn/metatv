"""Streaming XMLTV parser — never loads the full file into RAM."""

import gzip
import io
import re
import unicodedata
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional
from xml.etree import ElementTree as ET

from loguru import logger

# Superscript badges embedded in programme titles by some providers
_LIVE_BADGE = "ᴸᶦᵛᵉ"
_NEW_BADGE  = "ᴺᵉʷ"

# Matches the XMLTV datetime format: "20260512153000 +0200"
_DT_RE = re.compile(r"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\s*([+-]\d{4})")

# Gzip magic number — the first two bytes of any gzip stream (RFC 1952).
_GZIP_MAGIC = b"\x1f\x8b"


class XmltvAborted(Exception):
    """The caller's ``on_progress`` callback asked to abandon the fetch.

    Distinct from every other exception ``parse_xmltv_url`` can raise, all of
    which mean "this host did not give us a guide". This one means "we are
    going away" — the app is shutting down and nobody is left to receive the
    result — and it says nothing whatsoever about the host.

    The difference is not cosmetic: the EPG fetch path records a URL failure
    for any exception it sees, so without a type to tell these apart, closing
    the app mid-fetch permanently marks the host it happened to be using (and
    then every fallback host) as unreliable.
    """


class XmltvEvicted(Exception):
    """The connection this fetch holds was taken back for playback (EPG-2b).

    ``XmltvAborted`` means "we are going away — keep nothing"; this means the
    opposite: the app is very much alive, playback just needs the one
    connection this download is using, and every programme parsed so far is
    worth keeping. That is safe *because* of iterparse's "end"-event
    guarantee this parser relies on throughout — an item lands in
    ``channels``/``programmes`` only once its element has fully CLOSED, so
    there is no such thing as a half-read row here, only fewer of them.

    A caller's ``on_progress`` raises this bare to signal the eviction;
    ``parse_xmltv_url`` catches that and re-raises a second instance carrying
    the ``channels``/``programmes`` collected so far, which is what callers
    read.
    """

    def __init__(self, channels: "list[XmltvChannel] | None" = None,
                 programmes: "list[XmltvProgramme] | None" = None) -> None:
        super().__init__("guide fetch evicted for playback")
        self.channels: "list[XmltvChannel]" = channels if channels is not None else []
        self.programmes: "list[XmltvProgramme]" = programmes if programmes is not None else []


@dataclass
class XmltvChannel:
    epg_id: str
    display_name: str
    icon_url: str = ""


@dataclass
class XmltvProgramme:
    channel_id: str
    title: str
    description: str
    start_time: datetime   # UTC
    stop_time: datetime    # UTC
    is_live: bool = False
    is_new: bool = False


_PROGRESS_INTERVAL = 10_000  # call on_progress every N programmes


def parse_xmltv_url(
    url: str,
    timeout: int = 120,
    on_progress: Optional[Callable[[int], None]] = None,
) -> tuple[list[XmltvChannel], list[XmltvProgramme]]:
    """Download and parse an XMLTV feed.

    Uses iterparse so the 140MB+ file is never fully in memory at once.
    Returns (channels, programmes) as fully-materialised lists so callers
    don't need to keep the HTTP connection open.

    Args:
        url: Full XMLTV URL including credentials.
        timeout: HTTP timeout in seconds.
        on_progress: Optional callback called with current programme count
            every 10,000 programmes. Called from the worker thread.

    Returns:
        Tuple of (channels list, programmes list).
    """
    logger.info(f"Fetching XMLTV from {url[:60]}…")

    channels: list[XmltvChannel] = []
    programmes: list[XmltvProgramme] = []

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MetaTV/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            # Wrap in a BufferedReader so we can peek the first two bytes for the
            # gzip magic number without consuming them — ET.iterparse still reads
            # the SAME stream from the start afterward.
            buffered = io.BufferedReader(response)
            content_encoding = (response.headers.get("Content-Encoding", "") or "").lower()
            is_gzip = (
                buffered.peek(2)[:2] == _GZIP_MAGIC
                or url.lower().endswith(".gz")
                or content_encoding == "gzip"
            )
            if is_gzip:
                logger.info("XMLTV feed is gzip-compressed; decompressing on the fly")
                stream = gzip.GzipFile(fileobj=buffered)
            else:
                stream = buffered

            context = ET.iterparse(stream, events=("end",))
            try:
                for _event, elem in context:
                    if elem.tag == "channel":
                        ch = _parse_channel(elem)
                        if ch:
                            channels.append(ch)
                        elem.clear()

                    elif elem.tag == "programme":
                        prog = _parse_programme(elem)
                        if prog:
                            programmes.append(prog)
                            if on_progress and len(programmes) % _PROGRESS_INTERVAL == 0:
                                on_progress(len(programmes))
                        elem.clear()

            except (ET.ParseError, gzip.BadGzipFile, EOFError, zlib.error) as e:
                # Truncated/incomplete XML, or a corrupt/truncated gzip stream — use
                # whatever we collected so far. A gzip decode failure degrades
                # exactly like a plain-XML truncation: best-effort partial guide
                # rather than losing the whole fetch.
                logger.warning(
                    f"XMLTV feed truncated, malformed, or corrupt gzip ({e}); "
                    f"using {len(programmes)} programmes collected before the error"
                )
            except XmltvEvicted:
                # Re-raise carrying the payload (unlike the truncation family
                # above, which is absorbed) so the caller can tell this apart
                # from a normal, complete parse.
                logger.info(
                    f"guide fetch evicted for playback after {len(programmes):,} "
                    f"programmes — keeping the fully parsed ones"
                )
                raise XmltvEvicted(channels, programmes) from None

    except (XmltvAborted, XmltvEvicted):
        # Neither is a fetch error — teardown or a preemption, not something
        # this host did. Propagate silently so it is not logged/recorded below.
        raise
    except Exception as e:
        logger.error(f"XMLTV fetch/parse error: {e}")
        raise

    logger.info(f"XMLTV parsed: {len(channels)} channels, {len(programmes)} programmes")
    return channels, programmes


def _parse_channel(elem: ET.Element) -> XmltvChannel | None:
    epg_id = (elem.get("id") or "").strip()
    if not epg_id or epg_id.startswith("#"):
        return None
    name_el = elem.find("display-name")
    display_name = (name_el.text or "").strip() if name_el is not None else ""
    icon_el = elem.find("icon")
    icon_url = (icon_el.get("src") or "") if icon_el is not None else ""
    return XmltvChannel(epg_id=epg_id, display_name=display_name, icon_url=icon_url)


def _parse_programme(elem: ET.Element) -> XmltvProgramme | None:
    channel_id = (elem.get("channel") or "").strip()
    if not channel_id or channel_id.startswith("#"):
        return None

    start_str = elem.get("start", "")
    stop_str  = elem.get("stop", "")
    try:
        start_time = _parse_xmltv_datetime(start_str)
        stop_time  = _parse_xmltv_datetime(stop_str)
    except ValueError:
        return None

    title_el = elem.find("title")
    raw_title = (title_el.text or "").strip() if title_el is not None else ""
    if not raw_title:
        return None

    clean_title, is_live, is_new = _strip_badges(raw_title)

    desc_el = elem.find("desc")
    description = (desc_el.text or "").strip() if desc_el is not None else ""

    return XmltvProgramme(
        channel_id=channel_id,
        title=clean_title,
        description=description,
        start_time=start_time,
        stop_time=stop_time,
        is_live=is_live,
        is_new=is_new,
    )


def _parse_xmltv_datetime(s: str) -> datetime:
    """Parse XMLTV timestamp like '20260512153000 +0200' into a UTC datetime."""
    m = _DT_RE.match(s.strip())
    if not m:
        raise ValueError(f"Unrecognised XMLTV datetime: {s!r}")

    year, month, day, hour, minute, second, tz_str = m.groups()
    tz_sign = 1 if tz_str[0] == "+" else -1
    tz_hours = int(tz_str[1:3])
    tz_mins  = int(tz_str[3:5])
    offset = timedelta(hours=tz_hours, minutes=tz_mins) * tz_sign

    naive = datetime(int(year), int(month), int(day),
                     int(hour), int(minute), int(second))
    # Return naive UTC to match the EpgProgramDB storage format (see CLAUDE.md:
    # "start_time / stop_time are stored as UTC-naive datetimes"). Keeping tzinfo
    # here would make _fetch_worker's `max_stop < now_utc()` compare aware-vs-naive.
    return naive - offset


def _strip_badges(title: str) -> tuple[str, bool, bool]:
    """Remove ᴸᶦᵛᵉ / ᴺᵉʷ superscript badges from a title.

    Returns:
        (clean_title, is_live, is_new)
    """
    is_live = _LIVE_BADGE in title
    is_new  = _NEW_BADGE  in title
    clean = title.replace(_LIVE_BADGE, "").replace(_NEW_BADGE, "").strip()
    return clean, is_live, is_new


def _is_superscript(ch: str) -> bool:
    """True for a modifier/superscript form of an ordinary letter or digit."""
    if ch.isascii():
        return False
    decomposed = unicodedata.normalize("NFKD", ch)
    return (
        decomposed != ch
        and decomposed.strip() != ""
        and all(c.isalnum() for c in decomposed)
    )


def _drop_superscript_runs(name: str) -> str:
    """Remove whitespace-delimited tokens that are entirely superscript.

    Whole tokens only: a name that merely *contains* a decorated character is
    left alone rather than half-erased.
    """
    kept = [tok for tok in name.split()
            if not (tok and all(_is_superscript(c) for c in tok))]
    return " ".join(kept) if kept else name


def normalize_channel_name(name: str) -> str:
    """Normalize a channel display-name for fuzzy matching.

    Two sources describe the same channel differently, and this is what has to
    make them equal. Measured on the owner's library, the old rules matched
    **2 of 17,951** ProSat channels against a 260,275-programme guide — because
    they missed on three counts at once::

        'OD| ESPN 4 ᴴᴰ'   (guide)    ->  'od| espn 4 ᴴᴰ'
        '|NL| ESPN 4 HD'  (channel)  ->  '|nl| espn 4'

    * **The prefix survived.** The old separator class was ``[★◉•·]`` and never
      included ``|``, which is the separator both of these actually use — so
      ``OD|`` and ``|NL|`` stayed in the string and could never be equal.
    * **Superscripts are invisible to an ASCII vocabulary.** ``ᴴᴰ`` is not
      ``HD``, so the quality strip skipped it while stripping the plain ``HD``
      on the other side — the two diverged *because* one was cleaned.
    * **It was a second vocabulary.** ``parse_channel_name`` already knows every
      prefix separator, every quality token and their order, and already runs at
      ingestion to produce ``detected_*``. Re-implementing a worse version here
      is the "compute once at ingestion" principle inverted.

    So: fold the unicode forms to ASCII, then hand the result to the canonical
    parser and keep its ``bare_name``. Region is deliberately NOT part of the
    key — it is carried separately and enforced by ``epg_tld_compatible``, which
    is what stops a UK channel adopting an Italian guide. Dropping the region
    here and gating on it there is the existing design; this just stops the
    region from also blocking the name comparison.

    After: **2,743** of those ProSat channels match and pass the region gate.

    Args:
        name: A raw display name from either an XMLTV feed or a channel row.

    Returns:
        Lowercased, whitespace-collapsed bare name — "" when nothing survives.
    """
    from metatv.core.channel_name_utils import parse_channel_name

    # Superscript runs are DECORATION and are dropped whole, not folded to
    # ASCII. Folding handles the six the parser's quality vocabulary knows
    # ('ᴴᴰ'->HD, '⁴ᴷ'->4K, 'ʰᵉᵛᶜ'->HEVC ...) but leaves the twenty it does not
    # — 'ᴿᴬᵂ' is the single most common token in the library (6,305 channels)
    # and would survive as the word "raw", so 'TLC ᴿᴬᵂ' and 'TLC' still would
    # not meet. Dropping the run is uniform and needs no second vocabulary.
    #
    # It is also why this is scoped to SUPERSCRIPT rather than to a word list:
    # "GOLD" and "SUPER" are real channel names, and a token list would strip
    # them. As decoration, 'ᴳᴼᴸᴰ' is unambiguous.
    folded = _drop_superscript_runs(name or "")
    # Brackets are removed BEFORE parsing, not after: a trailing "[LIVE-EVENT]"
    # sits between the parser and the quality token it strips from the end, so
    # "SKY SPORT 4K [LIVE-EVENT]" would keep its 4K while the plainer
    # "Sky Sport 4K" lost it — the two would then differ *because* one carried
    # a tag. Only bracketed content goes: a bare LIVE can be the channel's real
    # name, and stripping the word would turn "LIVENOW FROM FOX" into
    # "NOW FROM FOX".
    folded = re.sub(r"\[[^\]]*\]", " ", folded)
    parsed = parse_channel_name(folded)
    bare = parsed.bare_name or folded
    return " ".join(bare.lower().split())
