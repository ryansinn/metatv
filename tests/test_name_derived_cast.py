"""Name-derived cast: the residual was captured, stored, and then never read (#284).

``parse_channel_name().trailing`` lifts whatever a provider appended after the
year — "EN - Adaptation. 4K (2002) NICOLAS CAGE" — and ``update_detected_prefixes``
stores it in ``ChannelDB.detected_name_cast``.  It had **zero consumers**: nothing
in ``gui/`` or ``tag_decomposer.py`` read the column.  The owner asked the right
question about it — "if it's pruning actor and there is no cast and crew, why not
add it to cast and crew?" — and the answer is provenance: a filename guess and a
verified credit must stay distinguishable, so this lands as a LOW-confidence
``person`` tag under Tags, never in ``MetadataDB.cast``.

The measurement that shaped the rule: across the owner's 414,800 VOD rows, 8,257
names carry a residual over 917 distinct values, and only about half are people.
The rest are language words, formats and studios — POLSKI (918), 4K (652),
DOKUMENT (531), DUBBING (221), NAPISY (122), PIXAR (52).  Emitting those as
``person`` would not be capturing generously; it would be recording something
false.  Confidence ranks a real guess, it does not launder a wrong one.
"""

from __future__ import annotations

import pytest

from metatv.core.channel_name_utils import CONF_WEAK_PRIOR
from metatv.core.tag_decomposer import decompose_name_cast


def _people(residual: str) -> list[str]:
    return [v for (t, v, _c) in decompose_name_cast(residual) if t == "person"]


class TestPeopleAreCaptured:

    @pytest.mark.parametrize("residual, expected", [
        ("NICOLAS CAGE", ["Nicolas Cage"]),
        ("TOM HANKS", ["Tom Hanks"]),
        ("DE NIRO", ["De Niro"]),
        ("- LOUIS DE FUNES", ["Louis De Funes"]),          # leading dash
        ("JACKIE CHAN (ENG-SUB)", ["Jackie Chan"]),        # trailing parenthetical
        ("ALAIN DELON (FRENCH ENG-SUB)", ["Alain Delon"]),
        ("Edward G. Robinson", ["Edward G. Robinson"]),    # initial + period
        ("JEAN-PAUL ROUVE", ["Jean-Paul Rouve"]),          # hyphenated
    ])
    def test_a_person_shaped_residual_becomes_a_person_tag(self, residual, expected):
        assert _people(residual) == expected

    def test_a_multi_credit_residual_splits(self):
        assert _people("DUSTIN HOFFMAN, ROBERT REDFORD") == [
            "Dustin Hoffman", "Robert Redford",
        ]

    def test_a_billed_duo_stays_one_credit(self):
        """"Abbott & Costello" is how they were billed — splitting invents two
        credits that read as separate people."""
        assert _people("ABBOTT & COSTELLO") == ["Abbott & Costello"]

    def test_a_provider_typo_is_captured_faithfully(self):
        """Not silently 'corrected' — this is a record of what the provider said."""
        assert _people("DENZEL WASHIGTON") == ["Denzel Washigton"]

    def test_duplicates_within_one_residual_collapse(self):
        assert _people("TOM HANKS, TOM HANKS") == ["Tom Hanks"]


class TestNonPeopleAreRefused:
    """Every value here is a real, measured residual from the owner's library."""

    @pytest.mark.parametrize("residual", [
        "POLSKI",                        # 918 rows — a language word
        "4K",                            # 652 — quality
        "DOKUMENT",                      # 531 — genre
        "DUBBING",                       # 221 — audio format
        "LQ", "HQ",                      # quality
        "NAPISY",                        # 122 — "subtitles" in Polish
        "BG-AUDIO", "BG AUDIO",          # audio language
        "PIXAR",                         # 52 — a studio, single word
        "BROADWAY MUSICAL",              # a descriptor
        "THE THREE STOOGES COLLECTION",  # a collection label
        "- THE THREE STOOGES COLLECTION",
        "DOKUMENT POLSKI", "POLSKI DOKUMENT",
        "VOSTFR", "TEATR", "ANIMACJA", "LIFETIME", "AI",
    ])
    def test_a_known_non_person_never_becomes_a_person(self, residual):
        assert _people(residual) == [], (
            f"{residual!r} would pollute the person facet — it is a known "
            f"language/format/collection word, not a low-confidence guess"
        )

    @pytest.mark.parametrize("residual", ["", None, "   ", "-", "12345", "!!!"])
    def test_empty_and_junk_yield_nothing(self, residual):
        assert decompose_name_cast(residual) == []


class TestItIsLabelledAsAGuess:

    def test_confidence_is_the_weak_prior(self):
        """A filename guess must not rank alongside a fact the source stated."""
        tags = decompose_name_cast("NICOLAS CAGE")
        assert tags == [("person", "Nicolas Cage", CONF_WEAK_PRIOR)]
        assert CONF_WEAK_PRIOR < 0.5, "must fall under the low-confidence chip style"

    def test_it_is_never_written_into_authoritative_cast(self):
        """The whole reason this is a tag and not a credit.

        Merging it into MetadataDB.cast would make a provider's typo
        indistinguishable from a verified credit, which is the failure the
        column's own docstring exists to prevent.
        """
        import inspect

        from metatv.core.migrations import tag_backfill

        src = inspect.getsource(tag_backfill._collect_tags)
        assert "decompose_name_cast" in src
        # Strip comments — the code must not touch cast, but the comment
        # explaining WHY it must not is allowed to name it.
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.strip().startswith("#")
        )
        for forbidden in ("MetadataDB", "metadata.cast", "cast="):
            assert forbidden not in code

    def test_the_details_pane_labels_the_provenance(self):
        """"Person" would read as a credit; the label has to say where it came from."""
        from metatv.gui.details_sections import _FACET_LABELS

        assert "person" in _FACET_LABELS
        label = _FACET_LABELS["person"]
        assert label != "Person", (
            "a bare 'Person' heading next to Cast & Crew reads as a verified "
            "credit — the label must carry the provenance"
        )
        assert "title" in label.lower() or "name" in label.lower()


class TestTheFeederIsActuallyWired:
    """The bug was 0 consumers — a decomposer nobody calls repeats it exactly."""

    def test_collect_tags_emits_person_tags_from_the_column(self):
        from metatv.core.config import Config
        from metatv.core.migrations.tag_backfill import _collect_tags

        tags = _collect_tags(
            config=Config(),
            category=None, source_category=None,
            detected_prefix=None, detected_quality=None,
            detected_region=None, detected_year="2002",
            raw_data=None, media_type="movie",
            detected_name_cast="NICOLAS CAGE",
        )
        assert ("person", "Nicolas Cage", "name_cast") in tags

    def test_every_collect_tags_call_site_passes_the_column(self):
        """A caller that omits a feeder DELETES its tags — it scrubs generated
        tags and re-derives, so an unseen feeder does not come back.  This is a
        bug that already shipped once here: the re-facet migration silently
        dropped the ai_provenance and audio tags of every row it touched."""
        import pathlib
        import re

        offenders = []
        for path in [
            pathlib.Path("metatv/core/provider_loader.py"),
            pathlib.Path("metatv/core/migrations/tag_backfill.py"),
            pathlib.Path("metatv/core/migrations/category_facet_refacet.py"),
        ]:
            text = path.read_text()
            # Lookbehind skips the `def _collect_tags(` definition itself.
            for m in re.finditer(
                r"(?<!def )_collect_tags\(\s*\n(.*?)\n\s*\)", text, re.S
            ):
                if "detected_name_cast=" not in m.group(1):
                    offenders.append(f"{path}:{text[:m.start()].count(chr(10)) + 1}")
        assert not offenders, (
            "these _collect_tags call sites omit detected_name_cast, so running "
            "them wipes the person tags of every row they touch:\n  "
            + "\n  ".join(offenders)
        )
