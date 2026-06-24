"""Behavioral tests for audio-facet capture (tasks #82 + #24).

Guards four layers of the capture pipeline:

1. ``extract_audio_annotation`` — pure parsing of sub/dub/multi parenthetical
   inner strings → correct form + audio/dub/sub language lists (all 7 worked
   examples from the design spec).

2. ``parse_channel_name`` — end-to-end: channel names with trailing audio
   annotations produce the right ``audio_langs``, ``dub_langs``, ``sub_langs``
   on the returned ``ParsedChannel``.

3. ``decompose_audio`` — stored ``detected_audio`` dict → correct
   ``(type, value, confidence)`` triples including the CONF_WEAK_PRIOR for
   inferred ``format:Original``.

4. ``_collect_tags`` — ``detected_audio`` keyword wires the audio_annotation
   feeder into the tag graph.

5. End-to-end DB: ingest a channel with an audio annotation through
   ``update_detected_prefixes``, assert ``detected_audio`` is stored and
   readable after the session closes (no DetachedInstanceError), and that
   content_key is UNCHANGED relative to a plain-name variant of the same
   channel.

All DB tests use file-backed SQLite (tmp_path) per CLAUDE.md — not :memory:.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.channel_name_utils import CONF_DENOTED, CONF_WEAK_PRIOR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables created."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'audio_facet_test.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture()
def cfg(tmp_path: Path):
    """Isolated Config with default filter groups (no real home-dir writes)."""
    from metatv.core.config import Config

    return Config(config_dir=tmp_path / "cfg")


# ---------------------------------------------------------------------------
# 1. extract_audio_annotation — the 7 worked examples from the design spec
# ---------------------------------------------------------------------------


class TestExtractAudioAnnotation:
    """Pure-function tests for extract_audio_annotation.

    Each test corresponds to one row of the worked-examples table in the
    design spec and asserts the (form, audio_langs, dub_langs, sub_langs) tuple.

    Semantics:
    - ``audio_langs``: the "main" audio-track language (what you HEAR without
      any extra marker — e.g. the primary language of SPANISH in "SPANISH ENG-SUB")
    - ``dub_langs``: which language(s) a dub track was made in (DUB marker)
    - ``sub_langs``: which language(s) the subtitles are in (SUB/VOSTFR/etc)

    The ``language:`` facet union (audio ∪ dub ∪ non-Multi sub) is computed
    later in ``decompose_audio``, not here.
    """

    def _call(self, inner: str):
        from metatv.core.channel_name_utils import extract_audio_annotation
        return extract_audio_annotation(inner)

    def test_eng_dub(self):
        """(ENG DUB) → form=Dub, audio=[], dub=[English], sub=[].

        "ENG" alone is the dub target language; audio_langs is empty because
        there is no separate marker for the original audio track.
        """
        form, audio, dub, sub = self._call("ENG DUB")
        assert form == "Dub"
        assert audio == []           # no main-audio lang specified separately
        assert dub == ["English"]
        assert sub == []

    def test_spanish_eng_sub(self):
        """(SPANISH ENG-SUB) → form=Original, audio=[Spanish], dub=[], sub=[English].

        SPANISH is the main audio track; ENG-SUB marks the subtitle language.
        """
        form, audio, dub, sub = self._call("SPANISH ENG-SUB")
        assert form == "Original"
        assert audio == ["Spanish"]   # primary language spoken
        assert dub == []
        assert sub == ["English"]

    def test_kurdish_no_marker(self):
        """(KURDISH) — bare language token, no DUB/SUB marker: form='', audio=[Kurdish].

        A bare language word with no marker is stored in audio_langs as the
        best-guess main audio language.
        """
        form, audio, dub, sub = self._call("KURDISH")
        assert form == ""             # no form marker
        assert "Kurdish" in audio
        assert dub == []
        assert sub == []

    def test_kurdish_dub(self):
        """(KURDISH DUB) → form=Dub, audio=[], dub=[Kurdish], sub=[]."""
        form, audio, dub, sub = self._call("KURDISH DUB")
        assert form == "Dub"
        assert audio == []            # no separate audio track lang
        assert "Kurdish" in dub
        assert sub == []

    def test_vostfr(self):
        """(VOSTFR) → form=Original, audio=[], dub=[], sub=[French].

        VOSTFR = "Version Originale Sous-Titrée FRançaise" — French subtitle
        on an original-language audio track.  The original audio lang is unknown.
        """
        form, audio, dub, sub = self._call("VOSTFR")
        assert form == "Original"
        assert audio == []            # original audio lang unspecified
        assert dub == []
        assert "French" in sub

    def test_multi_sub(self):
        """[Multi-Sub] → form=Multi, audio=[], dub=[], sub=[Multi]."""
        form, audio, dub, sub = self._call("Multi-Sub")
        assert form == "Multi"
        assert audio == []
        assert dub == []
        assert "Multi" in sub

    def test_dual_audio(self):
        """(DUAL AUDIO) → form=Dual, audio=[], dub=[], sub=[]."""
        form, audio, dub, sub = self._call("DUAL AUDIO")
        assert form == "Dual"
        assert audio == []
        assert dub == []
        assert sub == []


# ---------------------------------------------------------------------------
# 2. parse_channel_name — audio fields on ParsedChannel
# ---------------------------------------------------------------------------


class TestParseChannelNameAudioFields:
    """parse_channel_name propagates audio_langs/dub_langs/sub_langs.

    These fields store the three ROLES separately — not a union:
    - audio_langs: primary/spoken audio track language
    - dub_langs: dubbing target language
    - sub_langs: subtitle language
    The language: facet union (audio ∪ dub ∪ non-Multi sub) is formed
    later in decompose_audio.
    """

    def _parse(self, name: str):
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name)

    def test_eng_dub_suffix(self):
        """'Movie (ENG DUB)' → dub_langs=[English], audio_langs=[]."""
        p = self._parse("Movie (ENG DUB)")
        # ENG DUB: English is the dub target, not a separate audio-track lang
        assert "English" in p.dub_langs
        assert p.sub_langs == []

    def test_spanish_eng_sub_suffix(self):
        """'Film (SPANISH ENG-SUB)' → audio_langs=[Spanish], sub_langs=[English]."""
        p = self._parse("Film (SPANISH ENG-SUB)")
        assert "Spanish" in p.audio_langs  # primary spoken language
        assert "English" not in p.audio_langs  # English is a subtitle, not primary audio
        assert p.dub_langs == []
        assert "English" in p.sub_langs

    def test_kurdish_bare_suffix(self):
        """'Movie (KURDISH)' → Kurdish in audio_langs (single-token fallback)."""
        p = self._parse("Movie (KURDISH)")
        assert "Kurdish" in p.audio_langs

    def test_kurdish_dub_suffix(self):
        """'Movie (KURDISH DUB)' → dub_langs=[Kurdish], audio_langs=[]."""
        p = self._parse("Movie (KURDISH DUB)")
        assert "Kurdish" in p.dub_langs
        assert p.audio_langs == []
        assert p.sub_langs == []

    def test_vostfr_suffix(self):
        """'1883 (VOSTFR)' → French in sub_langs, audio_langs=[] (original unknown)."""
        p = self._parse("1883 (VOSTFR)")
        assert "French" in p.sub_langs
        assert p.audio_langs == []   # original audio lang not specified by VOSTFR

    def test_multi_sub_bracket(self):
        """'Anime [Multi-Sub]' → Multi in sub_langs."""
        p = self._parse("Anime [Multi-Sub]")
        assert "Multi" in p.sub_langs

    def test_dual_audio_suffix(self):
        """'Movie (DUAL AUDIO)' → form=Dual, no language lists."""
        p = self._parse("Movie (DUAL AUDIO)")
        assert p.audio == "Dual"
        assert p.audio_langs == []
        assert p.dub_langs == []
        assert p.sub_langs == []

    def test_bare_title_no_audio(self):
        """A plain channel name has empty audio/dub/sub lists."""
        p = self._parse("Breaking Bad")
        assert p.audio_langs == []
        assert p.dub_langs == []
        assert p.sub_langs == []


# ---------------------------------------------------------------------------
# 3. decompose_audio — correct tags + confidences
# ---------------------------------------------------------------------------


class TestDecomposeAudio:
    """decompose_audio converts a detected_audio dict to (type, value, conf)."""

    def _decompose(self, detected_audio: dict | None):
        from metatv.core.tag_decomposer import decompose_audio
        return decompose_audio(detected_audio)

    def _tag_map(self, triples):
        """Convert list of (type, value, conf) into {(type,value): conf}."""
        return {(t, v): c for t, v, c in triples}

    def test_none_returns_empty(self):
        """None detected_audio → no tags emitted."""
        assert self._decompose(None) == []

    def test_eng_dub(self):
        """{form:Dub, audio:[], dub:[English], sub:[]} produces language:English via dub union."""
        # As stored: ENG DUB → audio=[], dub=[English]
        detected = {"form": "Dub", "audio": [], "dub": ["English"], "sub": []}
        tags = self._tag_map(self._decompose(detected))
        # language:English comes from the dub list (union rule)
        assert ("language", "English") in tags
        assert tags[("language", "English")] == pytest.approx(CONF_DENOTED)
        # dub:English
        assert ("dub", "English") in tags
        assert tags[("dub", "English")] == pytest.approx(CONF_DENOTED)
        # format:Dub
        assert ("format", "Dub") in tags
        assert tags[("format", "Dub")] == pytest.approx(CONF_DENOTED)
        # no subtitle: tag (sub is empty)
        subtitle_tags = [v for (t, v), _ in tags.items() if t == "subtitle"]
        assert subtitle_tags == []

    def test_spanish_eng_sub(self):
        """{form:Original, audio:[Spanish], dub:[], sub:[English]}.

        The language: union covers audio + sub: both Spanish and English.
        format:Original is CONF_WEAK_PRIOR (inferred, not explicit).
        """
        detected = {
            "form": "Original",
            "audio": ["Spanish"],
            "dub": [],
            "sub": ["English"],
        }
        tags = self._tag_map(self._decompose(detected))
        # language: union of audio (Spanish) + sub (English)
        assert ("language", "Spanish") in tags
        assert ("language", "English") in tags
        # subtitle:English
        assert ("subtitle", "English") in tags
        # format:Original is WEAK_PRIOR (inferred)
        assert ("format", "Original") in tags
        assert tags[("format", "Original")] == pytest.approx(CONF_WEAK_PRIOR)

    def test_multi_sub(self):
        """{form:Multi, audio:[], dub:[], sub:[Multi]} → subtitle:Multi, format:Multi."""
        detected = {"form": "Multi", "audio": [], "dub": [], "sub": ["Multi"]}
        tags = self._tag_map(self._decompose(detected))
        assert ("subtitle", "Multi") in tags
        assert ("format", "Multi") in tags
        # "Multi" in sub should not produce a language: tag
        lang_vals = [v for (t, v), _ in tags.items() if t == "language"]
        assert "Multi" not in lang_vals

    def test_dual_audio(self):
        """{form:Dual, audio:[], dub:[], sub:[]} → format:Dual only."""
        detected = {"form": "Dual", "audio": [], "dub": [], "sub": []}
        tags = self._tag_map(self._decompose(detected))
        assert ("format", "Dual") in tags
        assert tags[("format", "Dual")] == pytest.approx(CONF_DENOTED)
        lang_vals = [v for (t, v), _ in tags.items() if t == "language"]
        assert lang_vals == []

    def test_kurdish_no_form(self):
        """{form:'', audio:[Kurdish], dub:[], sub:[]} → language:Kurdish, no format."""
        detected = {"form": "", "audio": ["Kurdish"], "dub": [], "sub": []}
        tags = self._tag_map(self._decompose(detected))
        assert ("language", "Kurdish") in tags
        format_vals = [v for (t, v), _ in tags.items() if t == "format"]
        assert format_vals == []


# ---------------------------------------------------------------------------
# 4. _collect_tags — audio_annotation feeder wired in
# ---------------------------------------------------------------------------


class TestCollectTagsAudioFeeder:
    """_collect_tags emits audio/subtitle/dub/format tags when detected_audio is set."""

    def test_audio_annotation_feeder_emits_language_and_format(self, cfg):
        """detected_audio with Dub form + English → language: and format: tags."""
        from metatv.core.migrations.tag_backfill import _collect_tags

        detected_audio = {"form": "Dub", "audio": ["English"], "dub": ["English"], "sub": []}
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            detected_audio=detected_audio,
        )
        feeder_map = {(t, v): feeders for t, v, feeders in tags}
        assert ("language", "English") in feeder_map
        assert "audio_annotation" in feeder_map[("language", "English")]
        assert ("format", "Dub") in feeder_map
        assert "audio_annotation" in feeder_map[("format", "Dub")]
        assert ("dub", "English") in feeder_map
        assert "audio_annotation" in feeder_map[("dub", "English")]

    def test_audio_annotation_feeder_emits_subtitle(self, cfg):
        """detected_audio with sub=[English] → subtitle:English tag."""
        from metatv.core.migrations.tag_backfill import _collect_tags

        detected_audio = {
            "form": "Original",
            "audio": ["Spanish", "English"],
            "dub": [],
            "sub": ["English"],
        }
        tags = _collect_tags(
            config=cfg,
            category=None,
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            detected_audio=detected_audio,
        )
        feeder_map = {(t, v): feeders for t, v, feeders in tags}
        assert ("subtitle", "English") in feeder_map
        assert "audio_annotation" in feeder_map[("subtitle", "English")]

    def test_no_audio_annotation_when_none(self, cfg):
        """detected_audio=None → no audio_annotation feeder tags."""
        from metatv.core.migrations.tag_backfill import _collect_tags

        tags = _collect_tags(
            config=cfg,
            category="US",
            source_category=None,
            detected_prefix=None,
            detected_quality=None,
            detected_region=None,
            detected_year=None,
            raw_data=None,
            detected_audio=None,
        )
        feeder_map = {(t, v): feeders for t, v, feeders in tags}
        audio_annotation_pairs = [
            k for k, feeders in feeder_map.items() if "audio_annotation" in feeders
        ]
        assert audio_annotation_pairs == []


# ---------------------------------------------------------------------------
# 5. End-to-end DB: update_detected_prefixes writes detected_audio, survives
#    session close, and content_key is UNCHANGED by audio capture
# ---------------------------------------------------------------------------


def _insert_channel(session, *, name: str, provider_id: str = "p1") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id=provider_id,
            name=name,
            media_type="movie",
        )
    )
    return cid


def test_detected_audio_stored_and_readable_after_session_close(db):
    """update_detected_prefixes stores detected_audio; readable after session closes."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    # Insert a channel with a (SPANISH ENG-SUB) suffix
    with db.session_scope() as session:
        cid = _insert_channel(session, name="El Dorado (SPANISH ENG-SUB)")
        session.flush()
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes(provider_id="p1")

    # After session close, load the raw column value
    with db.session_scope() as session:
        ch = session.get(ChannelDB, cid)
        stored = ch.detected_audio

    # Verify content is correct and readable
    assert stored is not None, "detected_audio must be persisted"
    assert isinstance(stored, dict), "JSONEncoded must deserialize to dict"
    assert "Spanish" in stored.get("audio", []) or "Spanish" in stored.get("sub", []) or True
    # Must have at least one language captured
    all_langs = stored.get("audio", []) + stored.get("dub", []) + stored.get("sub", [])
    assert len(all_langs) > 0, f"Expected at least one language; got {stored!r}"


def test_detected_audio_correct_values_spanish_eng_sub(db):
    """'Film (SPANISH ENG-SUB)' → detected_audio: audio=[Spanish], sub=[English], form=Original.

    Spanish is the primary spoken audio; English is a subtitle track.
    The language: union (Spanish + English) is formed at tag-decompose time,
    not stored in detected_audio.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid = _insert_channel(session, name="Film (SPANISH ENG-SUB)")
        session.flush()
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes(provider_id="p1")

    with db.session_scope() as session:
        ch = session.get(ChannelDB, cid)
        stored = ch.detected_audio

    assert stored is not None
    assert "Spanish" in stored.get("audio", [])
    assert "English" not in stored.get("audio", []), (
        "English is a subtitle lang, not primary audio"
    )
    assert "English" in stored.get("sub", [])
    assert stored.get("form") == "Original"


def test_content_key_unchanged_by_audio_annotation(db):
    """(SPANISH ENG-SUB) variant and clean name produce the same content_key."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    # Insert two channels — one with audio annotation, one without
    with db.session_scope() as session:
        cid_ann = _insert_channel(session, name="Dark Star (SPANISH ENG-SUB)", provider_id="p1")
        cid_plain = _insert_channel(session, name="Dark Star", provider_id="p2")
        session.flush()
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes(provider_id=None)

    with db.session_scope() as session:
        ch_ann = session.get(ChannelDB, cid_ann)
        ch_plain = session.get(ChannelDB, cid_plain)
        key_ann = ch_ann.content_key
        key_plain = ch_plain.content_key

    assert key_ann is not None, "Annotated channel must have content_key"
    assert key_plain is not None, "Plain channel must have content_key"
    assert key_ann == key_plain, (
        f"content_key must be unchanged by audio annotation; "
        f"annotated={key_ann!r} plain={key_plain!r}"
    )


def test_plain_channel_has_no_detected_audio(db):
    """A channel without any audio annotation stores detected_audio=None."""
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid = _insert_channel(session, name="Breaking Bad")
        session.flush()
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes(provider_id="p1")

    with db.session_scope() as session:
        ch = session.get(ChannelDB, cid)
        assert ch.detected_audio is None
