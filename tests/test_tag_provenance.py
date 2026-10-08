"""Behavioral tests for ``metatv.core.tag_provenance`` (DETAILS-3a).

Covers the pure grouping logic the redesigned details pane renders a fact's
group heading from: the strongest-kind rule, the group-label text per kind,
the fixed group order, and the "why" text beside a guessed fact. Also pins
down the one real policy gap found while building this: ``dtos.py``'s
``_SOURCE_GIVEN_FEEDERS`` and this module's ``FEEDER_KIND`` disagree about
whether ``"header"`` is source-given — see
``test_source_given_feeders_are_a_subset_of_field_kind_feeders`` and
docs/REFACTOR_PLAN.md's ledger (F51) for the detail.
"""

from __future__ import annotations

from metatv.core.tag_provenance import (
    FEEDER_KIND,
    GROUP_ORDER,
    KIND_ORDER,
    feeder_kind,
    group_label,
    guess_reason,
    strongest_kind,
)


# ---------------------------------------------------------------------------
# feeder_kind / strongest_kind
# ---------------------------------------------------------------------------

def test_feeder_kind_known_and_unknown():
    assert feeder_kind("provider_category") == "field"
    assert feeder_kind("played_tracks") == "observed"
    assert feeder_kind("audio_annotation") == "annotation"
    assert feeder_kind("name_parse") == "inference"
    # An unrecognised feeder degrades to the weakest kind rather than raising.
    assert feeder_kind("some_future_feeder") == "inference"


def test_strongest_kind_empty_is_inference():
    assert strongest_kind([]) == "inference"
    assert strongest_kind(()) == "inference"


def test_strongest_kind_single_feeder():
    assert strongest_kind(["played_tracks"]) == "observed"
    assert strongest_kind(["provider_category"]) == "field"
    assert strongest_kind(["audio_annotation"]) == "annotation"
    assert strongest_kind(["name_parse"]) == "inference"


def test_strongest_kind_across_mixed_feeders():
    # field + inference -> field wins (one field feeder makes the whole fact
    # a field fact, even with a weaker feeder also denoting it).
    assert strongest_kind(["name_parse", "provider_category"]) == "field"
    # observed beats everything.
    assert strongest_kind(["played_tracks", "provider_category", "name_parse"]) == "observed"
    # annotation beats inference but loses to field.
    assert strongest_kind(["audio_annotation", "name_parse"]) == "annotation"
    assert strongest_kind(["audio_annotation", "genre"]) == "field"
    # Order of KIND_ORDER itself, sanity-checked.
    assert KIND_ORDER == ("observed", "field", "annotation", "inference")


# ---------------------------------------------------------------------------
# group_label
# ---------------------------------------------------------------------------

def test_group_label_provider_field():
    assert group_label({"provider_category"}, provider_name="TREX Shared") == "From TREX Shared"


def test_group_label_user_wins_over_provider():
    assert group_label({"user", "provider_category"}, provider_name="TREX Shared") == "Yours"


def test_group_label_tmdb_alone():
    assert group_label({"tmdb"}, provider_name="TREX Shared") == "From TMDb"


def test_group_label_tmdb_with_provider_field_is_not_tmdb():
    # tmdb present but a structured provider field also backs it: the
    # provider's own group wins, not "From TMDb".
    assert group_label({"tmdb", "provider_category"}, provider_name="TREX Shared") == "From TREX Shared"


def test_group_label_annotation():
    assert group_label({"audio_annotation"}, provider_name="TREX Shared") == "In the title"


def test_group_label_inference():
    assert group_label({"region_inference"}, provider_name="TREX Shared") == "Guessed"


def test_group_label_mixed_inference_and_field():
    assert group_label({"name_parse", "provider_category"}, provider_name="TREX Shared") == "From TREX Shared"


def test_group_label_observed():
    assert group_label({"played_tracks"}, provider_name="TREX Shared") == "Seen in the file"


# ---------------------------------------------------------------------------
# GROUP_ORDER
# ---------------------------------------------------------------------------

def test_group_order_fixed_sequence():
    assert GROUP_ORDER("TREX Shared") == [
        "Seen in the file",
        "From TREX Shared",
        "From TMDb",
        "Yours",
        "In the title",
        "Guessed",
    ]


# ---------------------------------------------------------------------------
# guess_reason
# ---------------------------------------------------------------------------

def test_guess_reason_region_inference_with_names():
    assert guess_reason("region_inference", ["Sweden (SE)"]) == "from region Sweden (SE)"


def test_guess_reason_region_inference_multiple_names():
    assert guess_reason(["region_inference"], ["Sweden (SE)", "Norway (NO)"]) == (
        "from region Sweden (SE), Norway (NO)"
    )


def test_guess_reason_region_inference_no_names():
    assert guess_reason(["region_inference"], []) == "from the region"


def test_guess_reason_falls_back_to_name():
    assert guess_reason(["name_parse"], []) == "from the name"
    assert guess_reason([], ["Sweden (SE)"]) == "from the name"


# ---------------------------------------------------------------------------
# Cross-module policy check: dtos._SOURCE_GIVEN_FEEDERS vs FEEDER_KIND
# ---------------------------------------------------------------------------

def test_source_given_feeders_are_a_subset_of_field_kind_feeders():
    """``dtos._SOURCE_GIVEN_FEEDERS`` must all be ``"field"`` kind feeders here.

    The two modules answer related but different questions — "is this feeder
    source-given" (dtos.py, confidence scoring) vs "what kind of evidence is
    this feeder" (this module, the details-pane group heading) — and they
    must not quietly diverge on the feeders both actually list. They DO
    diverge on one feeder that is only ever mentioned in a comment, not in
    the set itself: dtos.py's comment calls ``"header"`` "ingestion-inferred"
    while ``FEEDER_KIND`` classifies it ``"field"`` (the 2026-09-09
    measurement that a header is provider-stated). That gap is logged in
    docs/REFACTOR_PLAN.md's duplication ledger (F51) rather than fixed here —
    changing dtos.py's confidence semantics is its own slice.
    """
    from metatv.core.repositories.dtos import _SOURCE_GIVEN_FEEDERS

    field_kind_feeders = {f for f, k in FEEDER_KIND.items() if k == "field"}
    assert _SOURCE_GIVEN_FEEDERS <= field_kind_feeders
