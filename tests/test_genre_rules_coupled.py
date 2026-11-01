"""The two genre derivations move together (ledger F49).

Genre is derived twice from the same rule tables: the stored ``detected_genre(s)``
(``detected_genre_backfill``) and the genre TAGS (``tag_backfill``). Each has
its own version counter, so a change to the tables could bump one and leave the
other's stored values on the old rules — the two would then disagree about a
title's genre with nothing reporting it.

This fingerprints every table both read. If it fails: you changed the genre
rules. Bump ``detected_genre_backfill.CURRENT_VERSION`` AND
``tag_backfill.CURRENT_TAG_BACKFILL_VERSION`` (each re-derives its half for
every user on next launch), then record the new fingerprint and both versions
in ``RECORDED`` below.
"""

from __future__ import annotations

import hashlib
import json

RECORDED = {"fingerprint": "122364daa1283d6b", "detected_genre": 3, "tag_backfill": 15}


def _fingerprint() -> str:
    from metatv.core import filter_utils as fu
    from metatv.core import genre_words as gw

    def canon(v):
        if isinstance(v, dict):
            return sorted((str(k), canon(x)) for k, x in v.items())
        if isinstance(v, (set, frozenset)):
            return sorted(str(x) for x in v)
        if isinstance(v, (list, tuple)):
            return [canon(x) for x in v]
        return v
    tables = {
        "genre_norm": fu._GENRE_NORM, "bad_tokens": fu._BAD_GENRE_TOKENS,
        "phrases": gw.GENRE_PHRASES, "words": gw.GENRE_WORDS, "strings": gw.GENRE_STRINGS,
        "not_genres": gw.NOT_GENRES, "field_platforms": gw.GENRE_FIELD_PLATFORMS,
    }
    blob = json.dumps({k: canon(v) for k, v in tables.items()}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def test_genre_rules_and_both_versions_are_recorded_together():
    from metatv.core.migrations import detected_genre_backfill, tag_backfill
    versions = {"detected_genre": detected_genre_backfill.CURRENT_VERSION,
                "tag_backfill": tag_backfill.CURRENT_TAG_BACKFILL_VERSION}
    assert _fingerprint() == RECORDED["fingerprint"], (
        "The genre rule tables changed. Bump BOTH detected_genre_backfill.CURRENT_VERSION "
        "and tag_backfill.CURRENT_TAG_BACKFILL_VERSION, then record the new fingerprint "
        f"({_fingerprint()}) and versions in RECORDED (see this module's docstring).")
    for name, recorded in versions.items():
        assert recorded >= RECORDED[name], f"{name} went backwards"


def test_the_fingerprint_sees_a_table_change(monkeypatch):
    from metatv.core import genre_words
    before = _fingerprint()
    monkeypatch.setitem(genre_words.GENRE_WORDS, "zzz-test-word", "Western")
    assert _fingerprint() != before
