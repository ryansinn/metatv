"""What one fact in a channel row looks like — the ``_Cell`` type, the slot
order, and the builder that turns each model role into one.

Split out of ``channel_list_delegate`` so the two halves of the row can be read
separately: this module answers *what a fact is and where it goes in the
reading order*, the delegate answers *how it is painted and where on screen*.
Nothing here touches a painter, a rect or a font — a cell is a value.

The three emphasis tiers (#298) live in :class:`_Cell`'s own docstring; the two
order constants (:data:`ROW_META_ORDER`, :data:`ROW_RAIL_ORDER`) are the single
declaration every painter asks for its subset, which is what stopped the meta
line and the rail from drifting apart the way the two densities once did.

Every name here is re-exported from ``channel_list_delegate`` — that module
stays the published surface, so a caller (and every existing test) keeps
importing from one place.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

from metatv.core.channel_name_utils import (
    PLATFORM_CODES,
    collection_display,
    platform_display,
    quality_display,
)
from metatv.gui import theme as _theme
from metatv.gui.badge_utils import _quality_outline_colors

#: How genres join INSIDE the genre segment. A slash, not a comma: the genres
#: are alternatives describing one title, and the row reads "Thriller / Drama".
_GENRE_JOINER = " / "


class _Cell(NamedTuple):
    """One paintable unit, in one of the row's THREE emphasis tiers (#298).

    - **Tier 1, fill** — ``is_chip=True``, ``bg`` set: a solid fill with
      ``fg``-coloured text on it. Language only, plus genuine row state.
    - **Tier 2, tinted text** — ``is_chip=False``: a bare text run in the
      facet's hue, no box at all. Region, genre, platform, collection.
    - **Tier 3, outline** — ``is_chip=True, outline=True``: a border stroke
      (``border``, defaulting to ``fg``) around an UNFILLED interior, text in
      ``fg``. Quality and year.

    ``border`` exists because tier 3 has two members with different needs:
    quality's stroke is its tier hue (same as its text), while the year's text
    is neutral metadata but its box must be quieter still than that text.
    """

    text: str
    is_chip: bool
    fg: str        # QColor-constructible token/hex (theme.* or a QColor.name())
    bg: Optional[str] = None   # fill token — tier 1 only; None on an outline chip
                               # (an alpha wash as a RESTING fill is a hover
                               # effect in the wrong place — owner directive)
    outline: bool = False      # True => border-only chip (tier 3), never filled
    border: Optional[str] = None  # outline stroke token; falls back to ``fg``
    # Facet identity + hover copy (#24). A delegate-painted chip has no widget,
    # so it cannot carry setToolTip() — the view hit-tests the painted rect and
    # renders `tip` itself. `facet`/`value` are what a click filters on; both
    # empty means the cell is decorative and neither hovers nor clicks.
    facet: str = ""
    value: str = ""
    tip: str = ""


def _edged_on_selection(cell: _Cell) -> _Cell:
    """Give a filled chip a stroke in its own foreground.

    Needed for exactly one collision, and it is a structural one rather than an
    oversight: the language chip's fill is ``facet.language-fill`` (step 4 of
    the accent-adjacent hue) and the SELECTED ROW's fill is
    ``primary.container`` (step 4 of the accent). On a selected row those two
    measure **1.0:1** — the chip vanishes into the row.

    The fix is a border rather than dropping the fill, because dropping it would
    flip ``is_chip`` and take the chip's horizontal padding with it — the cell
    would get NARROWER on selection, and "nothing moves when a row is selected"
    is the row's first rule. A stroke is drawn ON the rect: same width, same
    place, visible again.
    """
    return cell._replace(border=cell.fg)


# ---------------------------------------------------------------------------
# Chip order — ONE definition, deliberately not emergent from the paint code.
# ---------------------------------------------------------------------------

CHIP_SLOT_QUALITY = "quality"
CHIP_SLOT_VARIANTS = "variants"
CHIP_SLOT_GENRE = "genre"
CHIP_SLOT_COLLECTION = "collection"
CHIP_SLOT_YEAR = "year"
CHIP_SLOT_REGION = "region"          # region OR platform — one field, two hues
CHIP_SLOT_SUBTITLE = "subtitle"
CHIP_SLOT_LANGUAGE_2 = "language_secondary"
CHIP_SLOT_LANGUAGE = "language"

#: The META LINE, left to right — one run of tinted text segments joined by
#: ``·``, which is tier 2 ("tinted text, no box") applied to a whole line.
#:
#: **No kind word.** The row states its kind with the mark in its own gutter,
#: and a list filtered to movies read "Movie · … / Movie · … / Movie · …" down
#: every row — a column of the same word, spending the meta line's most valuable
#: position on the one fact the icon beside it had already made unambiguous
#: (owner report, against the real library). Kind is still structural; it is
#: just not structural TWICE.
#:
#: The year lost its outline box here. #298 gave it one so it would not read as
#: part of whatever text abutted it — a real problem when it sat loose in a
#: right-hand rail. Inside a ``·``-separated line the separator does that job,
#: and a box around one segment of a sentence is louder than the sentence.
ROW_META_ORDER: tuple[str, ...] = (
    CHIP_SLOT_YEAR,
    CHIP_SLOT_REGION,
    CHIP_SLOT_GENRE,
    CHIP_SLOT_COLLECTION,
    CHIP_SLOT_VARIANTS,
)

#: The RIGHT-HAND RAIL, left to right, right-aligned as a group against the
#: action gutter.
#:
#: **The language family only, and quality is deliberately NOT here.** Quality
#: sits immediately after the title instead (see ``_paint_title``), for the
#: reason that outranks tidiness: it is present on 6.6% of rows, so a rail
#: holding both put the language badge in a DIFFERENT COLUMN depending on
#: whether this particular row happened to have a quality token — the language
#: badge visibly jumped left and right down a scrolling list (owner report).
#:
#: A right-aligned group is only stable if every member is always present. The
#: language family is: the channel's OWN language is flush right (owner spec,
#: #298), and the optional secondary/sub-dub markers extend LEFTWARD from it, so
#: the column a reader actually tracks never moves.
#:
#: Ratings are not here and are not anywhere in the row: they are not objective,
#: and in this library the top of the range is a wall of identical 10.0s.
ROW_RAIL_ORDER: tuple[str, ...] = (
    CHIP_SLOT_SUBTITLE,
    CHIP_SLOT_LANGUAGE_2,
    CHIP_SLOT_LANGUAGE,
)

#: Every slot the row can paint, in reading order — kept as ONE declaration so
#: a future Settings → Interface reorder has a single tuple to permute. Quality
#: leads because it is painted FIRST, against the title.
ROW_CHIP_ORDER: tuple[str, ...] = (CHIP_SLOT_QUALITY,) + ROW_META_ORDER + ROW_RAIL_ORDER

#: How many genres a row will show before it stops (#298 — "show multiple
#: genres when present"). ``detected_genres`` regularly holds 4+ segments;
#: past three they stop being scannable and start eating the title's box.
_MAX_GENRES = 3


def _ordered(by_slot: dict[str, list[_Cell]], slots: tuple[str, ...]) -> list[_Cell]:
    """Cells for *slots*, sorted by :data:`ROW_CHIP_ORDER` and flattened.

    A slot may hold several cells (genre, which paints one per genre); they keep
    their own relative order inside the slot.
    """
    out: list[_Cell] = []
    for slot in ROW_CHIP_ORDER:
        if slot in slots:
            out.extend(by_slot.get(slot, ()))
    return out


def _region_label(code: str) -> str:
    """Human-readable name for a region/language code, for hover copy only.

    Reads the curated ``REGION_FULL_NAMES`` table (CLAUDE.md's lookup-table
    rule — never a parallel dict here) and falls back to the raw code, which is
    what an unmapped or provider-invented token should show.
    """
    from metatv.core.channel_name_utils import REGION_FULL_NAMES, normalize_region_code

    if not code:
        return ""
    full = REGION_FULL_NAMES.get(normalize_region_code(code))
    return f"{full} ({code})" if full else code


# ---------------------------------------------------------------------------
# Cell builders — map a raw role value to a paintable _Cell (or None to omit).
# ---------------------------------------------------------------------------

#: Semantic icon role per kind, resolved through ``icons.vector_key`` — the row
#: never names an icon-pack key itself.
#:
#: There is no matching table of kind WORDS any more. The row used to open its
#: meta line with "Movie"/"Series"/"Live"; against the real library that
#: rendered as the same word repeated down every row of a filtered list, saying
#: nothing the mark in the gutter had not already said.
_KIND_ICON_ROLES: dict[str, str] = {"live": "live", "movie": "movie", "series": "series"}


def _year_cell(year) -> Optional[_Cell]:
    """Year — TIER 2, neutral text on the meta line.

    #298 boxed the year (owner call: "put an outline on the year") because it
    was a bare number loose in a right-hand rail, where it read as part of
    whatever abutted it. On the V3 meta line the ``·`` separator does that job,
    so the box would be a second separator drawn around one word of a sentence.
    """
    # Coerce: the year reaches us as a str from ChannelListDTO but as an int
    # from some model stubs/roles, and a non-str text reaches QFontMetrics
    # .horizontalAdvance() and raises.
    if not year:
        return None
    # No facet: "year" is not a tag facet (tag_decomposer emits audio /
    # collection / genre / language / quality / region), so there is nothing
    # to filter on. Tooltip only.
    return _Cell(str(year), False, _theme.COLOR_ROW_META, tip=f"Released {year}")


def _quality_cell(token: str) -> Optional[_Cell]:
    """Quality chip — TIER 3, OUTLINE ONLY: border + text in the tier's colour
    from ``_quality_outline_colors()``, over an interior that is not filled at
    all (#298 dropped the ``OVERLAY_08`` tint the chip used to carry — an
    alpha wash is a hover effect, and using one as a resting fill is what put
    an un-authored, un-themeable grey into the row).

    Quality is the row's one CLAIM rather than a category — "this copy is 4K" —
    which is why it gets a border when no other facet does, and why it paints
    immediately after the title instead of in the right-hand rail: it qualifies
    the title, and a claim separated from what it qualifies reads as a
    different fact.

    Deliberately reads ``_quality_outline_colors()``, NOT ``_quality_colors()``
    (still used unchanged by ``badge_utils.make_quality_chip``'s solid-fill
    widget elsewhere): ``COLOR_QUALITY_*`` is a SOLID-FILL palette, held
    theme-invariant on purpose (theme_palettes.py's module docstring — "the
    owner explicitly likes this hue system"), so it can't be palette-tuned for
    contrast the way the LANG_CHIP-idiom facets' ``COLOR_ACCENT_*``
    foregrounds are — as TEXT/BORDER against the app's OWN background instead,
    those same values measured 1.57-4.09:1, well under a 4.5:1 floor, on
    EVERY palette (not just Daylight). ``COLOR_QUALITY_OUTLINE_*`` is a
    separate, dedicated per-palette family — same hue as the corresponding
    ``COLOR_QUALITY_*`` token, lightness tuned per palette (brighter in the
    two dark palettes, darker in Daylight) so text/border clears 4.5:1
    against ``COLOR_BG_SECTION`` everywhere — see
    ``tests/test_palette_completeness.py``'s
    ``test_quality_outline_chip_contrast_at_least_4_5_every_palette``.

    """
    if not token:
        return None
    upper = token.upper()
    color = _quality_outline_colors().get(upper, _theme.COLOR_FAINT)
    return _Cell(quality_display(upper), True, color, None, outline=True,
                 facet="quality", value=upper,
                 tip=f"Picture quality: {quality_display(upper)} — click to show "
                     f"only {quality_display(upper)} versions")


def _region_or_platform_cell(code: str, platform_style: str) -> Optional[_Cell]:
    """Region-or-platform — TIER 2, tinted text, for ``LANGUAGE_ROLE``
    (``detected_region`` — the field doubles as BOTH a geographic region code
    and a streaming-platform code, e.g. ``"US"`` vs ``"NF"``/``"A+"``).

    Two distinct hues, no box on either: a recognized :data:`PLATFORM_CODES`
    member paints in ``COLOR_ROW_PLATFORM`` (``platform_display`` resolves the
    brand name per *platform_style*), anything else in ``COLOR_ROW_REGION``.

    Platform used to be the single LOUDEST treatment in the row — a solid
    purple fill — for a fact almost nobody scans by. It now sits in the same
    tier as its neighbours and keeps its hue, which is the part that was
    carrying the meaning.
    """
    if not code:
        return None
    if code in PLATFORM_CODES:
        brand = platform_display(code, platform_style)
        return _Cell(
            brand, False, _theme.COLOR_ROW_PLATFORM,
            facet="region", value=code,
            tip=f"Streaming platform: {brand} — click to show only {brand}",
        )
    return _Cell(code, False, _theme.COLOR_ROW_REGION,
                 facet="region", value=code,
                 tip=f"Region: {_region_label(code)} — click to show only this region")


def _language_cell(text: str, *, filterable: bool = True) -> Optional[_Cell]:
    """Language family — TIER 1, the row's ONLY facet fill: the channel's own/
    secondary language and any sub/dub marker (``PRIMARY_LANGUAGE_ROLE``,
    ``SECONDARY_LANGUAGE_ROLE``, ``SUBTITLE_MARKER_ROLE``) all share one hue
    and one treatment.

    Language keeps the fill on the owner's call — it is the highest-value facet
    after the title itself, and a tier system with nothing in its top tier
    would just be a flatter version of the same problem. ``COLOR_ROW_LANGUAGE``
    on ``COLOR_ROW_LANGUAGE_FILL`` is a same-hue pair (Radix step 11 text on
    step 4 fill), so the chip clears 4.5:1 without a neutral in sight.
    """
    if not text:
        return None
    if not filterable:
        # Sub/dub markers ("AR-SUB") are NOT language tags — there is no facet
        # that can filter them (the audio facet is empty in practice), so the
        # chip explains itself and stops there. Giving it facet="language"
        # rendered a pointing-hand cursor over a click that silently did
        # nothing, which is worse than no affordance.
        return _Cell(text, True, _theme.COLOR_ROW_LANGUAGE,
                     _theme.COLOR_ROW_LANGUAGE_FILL,
                     tip=f"Subtitles/dub: {text}")
    return _Cell(text, True, _theme.COLOR_ROW_LANGUAGE,
                 _theme.COLOR_ROW_LANGUAGE_FILL,
                 facet="language", value=text,
                 tip=f"Language: {_region_label(text)} — click to show only this language")


def _genre_cell(genre: str) -> Optional[_Cell]:
    """One genre — TIER 2, tinted text in ``COLOR_ROW_GENRE``."""
    if not genre:
        return None
    return _Cell(genre, False, _theme.COLOR_ROW_GENRE,
                 facet="genre", value=genre,
                 tip=f"Genre: {genre} — click to show only {genre}")


def _genre_cells(genres, fallback: str = "") -> list[_Cell]:
    """Up to :data:`_MAX_GENRES` genres as ONE segment, joined by
    :data:`_GENRE_JOINER` — "Thriller / Drama", the mockup's own reading.

    Returns a list because the slot machinery is list-shaped and because the
    joined run still has to carry ONE facet/value pair for click-to-filter; the
    value is the FIRST genre, which is the one a reader means when they click a
    run that starts with it. Splitting the run back into one clickable cell per
    genre is a real option later — it needs per-word hit rects, which is a
    different change from this one.

    Reads the ingestion-computed ``detected_genres`` list; *fallback* is the
    single ``detected_genre`` for rows ingested before that column existed and
    not yet re-swept. Neither is ever re-derived at render — both are stored
    fields (``update_detected_prefixes``).
    """
    values = [g for g in (genres or ()) if g]
    if not values and fallback:
        values = [fallback]
    seen: set[str] = set()
    ordered: list[str] = []
    for genre in values:
        if genre in seen:
            continue
        seen.add(genre)
        ordered.append(genre)
        if len(ordered) >= _MAX_GENRES:
            break
    if not ordered:
        return []
    return [_Cell(_GENRE_JOINER.join(ordered), False, _theme.COLOR_ROW_GENRE,
                  facet="genre", value=ordered[0],
                  tip=f"Genre: {', '.join(ordered)} — click to show only {ordered[0]}")]


def _category_cell(category: str, platform_code: str = "",
                   filter_category: str = "") -> Optional[_Cell]:
    """Collection — TIER 2, but NEUTRAL text (``COLOR_ROW_COLLECTION``), not a
    hue.

    Every other tier-2 member carries a facet hue. Collection deliberately does
    not: the palette publishes one hue per facet and no two may share one, so a
    fifth hue here would either be invented or borrowed from a facet that
    already means something else — and a borrowed hue is a false statement
    about the data. Dropping the box is the change; the grey was already right.

    The TEXT is a render-layer transform via
    :func:`~metatv.core.channel_name_utils.collection_display` (trailing
    media-type token stripped + a leading platform-duplicate token stripped
    when *platform_code* is this row's own recognized platform code) — never
    touches the stored ``detected_collection`` (Discover reads that verbatim
    and must keep SERIES/MOVIES, #257 owner directive)."""
    display = collection_display(category, platform_code or None)
    if not display:
        return None
    # DISPLAY comes from detected_collection (cleaned); the FILTER value is the
    # curated ChannelDB.category, a different column — that is what the
    # collection filter matches, and filtering on the displayed string returns
    # nothing. Falls back to the display value only when no curated category
    # exists, which the applier treats as "nothing to filter on".
    return _Cell(display, False, _theme.COLOR_ROW_COLLECTION,
                 facet="collection", value=(filter_category or ""),
                 tip=f"Collection: {display} — click to show only this collection")


def _variant_badge_cell(count: int) -> Optional[_Cell]:
    """Collapsed-variant "×N" badge (Settings → Interface → "Collapse quality/
    language versions") — plain neutral text.

    Omitted (None) for singleton/uncollapsed rows — ``ChannelListDTO.
    variant_count`` defaults to 1 whenever collapsing is off, so this is a
    no-op everywhere the setting is unused."""
    if not count or count <= 1:
        return None
    return _Cell(f"×{count}", False, _theme.COLOR_ROW_META,
                 tip=f"{count} versions of this title were collapsed into one row "
                     f"(Settings → Interface → Collapse quality/language versions)")
