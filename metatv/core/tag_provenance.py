"""Group a tag's feeders by WHERE the fact came from, not how many said it.

The old "confidence" axis was a feeder *count* — a fact with two feeders
outranked a fact with one, regardless of what either feeder actually was. That
conflated "a provider category and a name-parse guess agree" with "two
independent provider categories agree," and it gave no way to answer the
question a reader actually has: is this a fact the file states, a hint the
title carries, or a guess the app made? (project_feeder_provenance_kinds.md:
confidence is feeder COUNT; 78.6% of tags are field-backed, inference-only is
20.2% — the low-confidence chip keys on that *kind*, not a tally.)

The owner's details-pane redesign groups every fact by the STRONGEST kind
among its feeders — "a fact sits in its strongest feeder's group" — so a tag
backed by both a provider category (field) and a name-parse guess
(inference) is shown as a field fact, never as two half-facts. This module is
that grouping, kept pure (no Qt, no database) so the GUI layer
(``metatv/gui/detail_chips.py`` and the details-pane sections that import it)
only has to render what it is handed.

Kinds, strongest to weakest (see :data:`KIND_ORDER`):

* ``observed`` — read directly off the played stream (e.g. an audio track the
  player actually reported).
* ``field`` — a structured field the provider, a user action, or TMDb
  supplied outright (category, header, genre, a user tag, a TMDb credit).
* ``annotation`` — a marker embedded in the title text itself (an audio tag
  like "[DD5.1]", an AI-authored marker).
* ``inference`` — parsed or guessed from the name/region with no explicit
  field behind it.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Feeder name → the kind of evidence it represents. An unknown feeder is
#: treated as the weakest kind (``inference``) by :func:`feeder_kind` rather
#: than raising — a new feeder should degrade gracefully, not crash rendering.
FEEDER_KIND: dict[str, str] = {
    "played_tracks": "observed",
    "provider_probe": "field",     # the provider's own ffprobe (get_vod_info) — stated, not seen
    "provider_detail": "field",    # other get_vod_info facts: alternate titles (o_name)
    "metadata_credits": "field",   # cast / directing credits from the title's metadata
    "provider_category": "field",
    "header": "field",
    "genre": "field",
    "user": "field",
    "tmdb": "field",
    "metadata": "field",
    "audio_annotation": "annotation",
    "name_ai_marker": "annotation",
    "name_parse": "inference",
    "name_cast": "inference",
    "region_inference": "inference",
}

#: Strongest to weakest. A tag's group is decided by the STRONGEST kind among
#: its feeders, never the weakest or an average — one field feeder makes the
#: whole fact a field fact even if an inference feeder also denoted it.
KIND_ORDER: tuple[str, ...] = ("observed", "field", "annotation", "inference")

_KIND_RANK = {kind: index for index, kind in enumerate(KIND_ORDER)}

#: Field-kind feeders that mean "a structured source named this" rather than
#: "the user did" or "TMDb did" — used by :func:`group_label` to decide
#: whether a lone ``tmdb`` feeder should read as "From TMDb" (nothing else
#: backs it) or get folded into the provider's own group.
_PROVIDER_FIELD_FEEDERS = frozenset({"provider_category", "header", "genre", "metadata"})


#: Feeders a re-tag cannot re-derive from the catalog: they came from playing or
#: probing a stream, or from a detail/metadata fetch. A re-tag never deletes a
#: link carrying one — it only strips the derived feeders off it. THE one list
#: (tag_content_tags._delete_derived reads it); a new non-derivable feeder is
#: added here and nowhere else.
PERSISTENT_FEEDERS: frozenset[str] = frozenset({
    "played_tracks", "provider_probe", "provider_detail", "metadata_credits",
})


def feeder_kind(feeder: str) -> str:
    """Return the evidence kind for a single feeder name.

    Args:
        feeder: A feeder name as stored on a tag (e.g. ``"provider_category"``).

    Returns:
        One of :data:`KIND_ORDER`. An unrecognised feeder returns
        ``"inference"``, the weakest kind, rather than raising.
    """
    return FEEDER_KIND.get(feeder, "inference")


def strongest_kind(feeders: Iterable[str]) -> str:
    """Return the strongest evidence kind among *feeders*.

    Args:
        feeders: The feeder names recorded on one tag.

    Returns:
        The kind (from :data:`KIND_ORDER`) of whichever feeder ranks
        strongest. Empty input returns ``"inference"`` — nothing backing a
        fact is the weakest possible case, not an error.
    """
    kinds = [feeder_kind(f) for f in feeders]
    if not kinds:
        return "inference"
    return min(kinds, key=_KIND_RANK.__getitem__)


def group_label(feeders: Iterable[str], *, provider_name: str, metadata_source: str = "") -> str:
    """Return the group heading for one tag's feeders, before upper-casing.

    The heading names WHERE the fact came from, not a confidence score:

    * ``observed`` → "Seen in the file"
    * ``annotation`` → "In the title"
    * ``inference`` → "Guessed"
    * ``field`` → "Yours" when a user supplied it; "From TMDb" when TMDb is
      the only structured source behind it; otherwise "From {provider_name}".

    Callers pass metadata-sourced genres (which carry no per-tag feeder of
    their own) with feeder ``"tmdb"`` when *metadata_source* names a TMDb
    provider, and feeder ``"metadata"`` otherwise — that convention is what
    lets a metadata genre land in "From TMDb" only when TMDb is genuinely the
    source, and in the provider's own group otherwise.

    Args:
        feeders: The feeder names recorded on one tag.
        provider_name: The display name of the channel's provider/source, used
            for the ``"From {provider_name}"`` case.
        metadata_source: Unused by this function directly — documented here
            because it names the convention callers follow when constructing
            *feeders* for a metadata-sourced genre (see above). Accepted so a
            caller can pass it through without the call site needing to know
            that detail lives in the docstring rather than the signature.

    Returns:
        The group heading text, not yet upper-cased (callers upper-case it at
        render time, matching the reference rendering).
    """
    feeders = tuple(feeders)
    kind = strongest_kind(feeders)
    if kind == "observed":
        return "Seen in the file"
    if kind == "annotation":
        return "In the title"
    if kind == "inference":
        return "Guessed"
    # kind == "field"
    if "user" in feeders:
        return "Yours"
    if "tmdb" in feeders and not any(f in feeders for f in _PROVIDER_FIELD_FEEDERS):
        return "From TMDb"
    return f"From {provider_name}"


def GROUP_ORDER(provider_name: str) -> list[str]:
    """Return the fixed display order of :func:`group_label` headings.

    Named like a constant (matching the reference implementation) because
    callers treat it as one — the order is fixed, only the provider slot
    varies, and a plain function is how that varies without becoming a
    second source of truth for the order itself.

    Args:
        provider_name: The channel's provider/source display name, interpolated
            into the "From {provider_name}" slot.

    Returns:
        Group headings in the order the details pane renders them: facts the
        file states first, then the two structured sources, then the user's
        own judgment, then what the title and the guesser contributed.
    """
    return [
        "Seen in the file",
        f"From {provider_name}",
        "From TMDb",
        "Yours",
        "In the title",
        "Guessed",
    ]


def guess_reason(feeders: Iterable[str], region_names: list[str]) -> str:
    """Return the short "why" text shown beside a guessed (inference) fact.

    Args:
        feeders: The feeder names recorded on one tag (or, as the region case
            is commonly checked against a single known feeder, just that
            feeder name — ``in`` matches either).
        region_names: Already-resolved display names ("Sweden (SE)") for the
            region(s) behind a region-based inference. Only consulted when
            ``"region_inference"`` is among *feeders*.

    Returns:
        ``"from region {names}"`` when the guess came from a region
        inference and at least one region name is known, ``"from region"``
        when a region inference has no resolved name, else ``"from title"``.
    """
    if "region_inference" in feeders:
        if region_names:
            return "from region " + ", ".join(region_names)
        return "from region"
    return "from title"
