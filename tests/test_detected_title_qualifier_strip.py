"""Behavioral tests for strip_title_qualifiers (#78 and #78 follow-up).

Guards six invariants:

1. ``parse_channel_name`` strips trailing single-token paren qualifiers from
   the bare title (the underlying ``detected_title`` source).

2. Known strip cases: (US), (4K), (HQ), (LQ), (BR), (VOSTFR).

3. Recognized multi-token qualifier strip cases (follow-up): space-containing
   parentheticals where EVERY token is a recognized lang/region/quality/sub/dub
   token are also stripped: (ENG DUB), (SPANISH ENG-SUB), (DUAL AUDIO), etc.
   This includes the interior-year peel: after stripping (SPANISH ENG-SUB) from
   "As Linas Descontinuas (2025) (SPANISH ENG-SUB)" the now-trailing (2025)
   is removed by the next loop iteration.

4. Preserve cases: multi-word parentheticals with ANY unrecognized token stay:
   (30 Monedas), (Soleil Noir), (New York), (The Beginning).

5. End-to-end via ``update_detected_prefixes``: two series that differ only by a
   paren qualifier get the same ``detected_title`` AND the same ``content_key``.

6. ``DetectedTitleReparseTask`` ``needs_run`` / ``on_completed`` gate logic.

All DB tests use file-backed (tmp_path) SQLite — not :memory: (pooled connections
each see an empty schema per CLAUDE.md rule).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(session, *, name: str, provider_id: str = "p1",
                  media_type: str = "series") -> str:
    """Insert a minimal ChannelDB row and return its id."""
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
    ))
    return cid


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables created."""
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'test_title_strip.db'}")
    d.create_tables()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# 1+2. parse_channel_name — single-token strip cases
# ---------------------------------------------------------------------------


class TestParseChannelNameStrip:
    """parse_channel_name strips trailing qualifiers in a loop until stable."""

    def _bare(self, name: str) -> str:
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name).bare_name

    # ── Proven failing cases (root cause of #78) ──────────────────────────

    def test_nf_thirteen_reasons_why_us_4k(self):
        """'NF - 13 Reasons Why (US) (4K)' → bare 'Error: title must be 13 Reasons Why'."""
        bare = self._bare("NF - 13 Reasons Why (US) (4K)")
        assert bare == "13 Reasons Why", (
            f"Expected '13 Reasons Why', got {bare!r}. "
            "Both (US) and (4K) should be stripped."
        )

    def test_fr_1883_vostfr(self):
        """'FR - 1883 (VOSTFR)' → bare '1883'."""
        bare = self._bare("FR - 1883 (VOSTFR)")
        assert bare == "1883", (
            f"Expected '1883', got {bare!r}. (VOSTFR) should be stripped."
        )

    # ── Additional single-token qualifier strip cases ──────────────────────

    def test_strip_hq(self):
        """'X (HQ)' → 'X'."""
        assert self._bare("X (HQ)") == "X"

    def test_strip_lq(self):
        """'X (LQ)' → 'X'."""
        assert self._bare("X (LQ)") == "X"

    def test_strip_br(self):
        """'X (BR)' → 'X' (2-letter country code in parens)."""
        assert self._bare("X (BR)") == "X"

    def test_strip_4k_in_parens(self):
        """'Movie Title (4K)' → 'Movie Title' (digit-starting quality in parens)."""
        assert self._bare("Movie Title (4K)") == "Movie Title"

    def test_strip_us_in_parens(self):
        """'Show (US)' → 'Show' (2-letter region code)."""
        assert self._bare("Show (US)") == "Show"

    def test_strip_multiple_trailing_qualifiers(self):
        """Strips qualifiers in a loop: 'Title (US) (4K)' → 'Title'."""
        assert self._bare("Title (US) (4K)") == "Title"

    def test_already_clean_title_unchanged(self):
        """An already-clean title is returned unchanged."""
        assert self._bare("The Mandalorian") == "The Mandalorian"

    def test_year_stripped_qualifier_then_further_stripped(self):
        """'Show (2019) (US)' → year stripped → then (US) stripped → 'Show'."""
        # year (2019) is stripped in step 5; then (US) is stripped in step 6c loop
        assert self._bare("Show (2019) (US)") == "Show"


# ---------------------------------------------------------------------------
# 3. Multi-token recognized qualifier strip cases (#78 follow-up)
# ---------------------------------------------------------------------------


class TestMultiTokenQualifierStrip:
    """Space-containing parentheticals where ALL tokens are recognized are stripped.

    This is the #78 follow-up fix: the old heuristic (internal space = preserve)
    was too crude and left sub/dub/lang qualifiers like (ENG DUB) and
    (SPANISH ENG-SUB) in the title.  The new allowlist strips them only when
    every leaf token (split on space, dash, slash) is in the recognized vocab.
    """

    def _bare(self, name: str) -> str:
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name).bare_name

    def _strip(self, title: str) -> str:
        from metatv.core.channel_name_utils import strip_title_qualifiers
        return strip_title_qualifiers(title)

    def test_motivating_case_as_linas_descontinuas(self):
        """'As Linas Descontinuas (2025) (SPANISH ENG-SUB)' → 'As Linas Descontinuas'.

        The motivating real-world case from the PR: both the dub qualifier AND the
        interior year must be gone.  After stripping (SPANISH ENG-SUB), the loop
        continues and removes the now-trailing (2025).
        """
        result = self._strip("As Linas Descontinuas (2025) (SPANISH ENG-SUB)")
        assert result == "As Linas Descontinuas", (
            f"Expected 'As Linas Descontinuas', got {result!r}. "
            "(SPANISH ENG-SUB) must be stripped as a recognized qualifier; "
            "then (2025) must peel off in the next loop iteration."
        )

    def test_strip_eng_dub(self):
        """(ENG DUB) is stripped — ENG (lang) + DUB (marker) both recognized."""
        assert self._strip("Movie (ENG DUB)") == "Movie"

    def test_strip_eng_sub(self):
        """(ENG SUB) is stripped — ENG + SUB both recognized."""
        assert self._strip("Movie (ENG SUB)") == "Movie"

    def test_strip_eng_sub_hyphenated(self):
        """(ENG-SUB) is stripped by single-token regex (no space, so existing path)."""
        assert self._strip("Movie (ENG-SUB)") == "Movie"

    def test_strip_spanish_eng_sub(self):
        """(SPANISH ENG-SUB) — SPANISH (lang full name) + ENG + SUB all recognized."""
        assert self._strip("Title (SPANISH ENG-SUB)") == "Title"

    def test_strip_dual_audio(self):
        """(DUAL AUDIO) — both tokens recognized as sub/dub markers."""
        assert self._strip("Title (DUAL AUDIO)") == "Title"

    def test_strip_multi_sub(self):
        """(MULTI SUB) — MULTI in audio norm keys + SUB in sub/dub tokens."""
        assert self._strip("Title (MULTI SUB)") == "Title"

    def test_strip_vost_fr(self):
        """(VOST FR) — VOST (sub/dub marker) + FR (region code) both recognized."""
        assert self._strip("Title (VOST FR)") == "Title"

    def test_strip_leg_pt(self):
        """(LEG PT) — LEG (legendado marker) + PT (lang code) both recognized."""
        assert self._strip("Title (LEG PT)") == "Title"

    def test_strip_pt_br(self):
        """(PT BR) — PT (Portuguese lang code) + BR (Brazil region) both recognized."""
        assert self._strip("Title (PT BR)") == "Title"

    def test_interior_year_peels_after_multi_token_strip(self):
        """Interior (year) is removed after multi-token qualifier is stripped in the loop."""
        result = self._strip("Title (2022) (ENG DUB)")
        assert result == "Title", (
            f"After stripping (ENG DUB), the now-trailing (2022) must also strip; "
            f"got {result!r}"
        )

    def test_via_parse_channel_name_eng_dub(self):
        """parse_channel_name: 'Movie (ENG DUB)' bare == 'Movie'."""
        assert self._bare("Movie (ENG DUB)") == "Movie"

    def test_via_parse_channel_name_spanish_eng_sub(self):
        """parse_channel_name: interior year + multi-token qualifier both stripped."""
        assert self._bare("As Linas Descontinuas (2025) (SPANISH ENG-SUB)") == "As Linas Descontinuas"


# ---------------------------------------------------------------------------
# 4. Preserve cases — only preserve when ANY token is unrecognized
# ---------------------------------------------------------------------------


class TestParseChannelNamePreserve:
    """Multi-word parentheticals with ANY unrecognized token must be preserved."""

    def _bare(self, name: str) -> str:
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name).bare_name

    def _strip(self, title: str) -> str:
        from metatv.core.channel_name_utils import strip_title_qualifiers
        return strip_title_qualifiers(title)

    def test_preserve_30_monedas(self):
        """'30 Coins (30 Monedas)' keeps '(30 Monedas)' — MONEDAS unrecognized."""
        bare = self._bare("30 Coins (30 Monedas)")
        assert "(30 Monedas)" in bare, (
            f"Alt-title '(30 Monedas)' must be preserved; got {bare!r}"
        )

    def test_preserve_soleil_noir(self):
        """'Under a Dark Sun (Soleil Noir)' keeps '(Soleil Noir)' — SOLEIL/NOIR unrecognized."""
        bare = self._bare("Under a Dark Sun (Soleil Noir)")
        assert "(Soleil Noir)" in bare, (
            f"Alt-title '(Soleil Noir)' must be preserved; got {bare!r}"
        )

    def test_preserve_new_york(self):
        """'Show (New York)' keeps '(New York)' — YORK is not a recognized token."""
        result = self._strip("Show (New York)")
        assert "(New York)" in result, (
            f"'(New York)' must be preserved (YORK unrecognized); got {result!r}"
        )

    def test_preserve_the_beginning(self):
        """'Show (The Beginning)' keeps '(The Beginning)' — THE/BEGINNING unrecognized."""
        result = self._strip("Show (The Beginning)")
        assert "(The Beginning)" in result, (
            f"'(The Beginning)' must be preserved; got {result!r}"
        )

    def test_eng_dub_now_stripped_not_preserved(self):
        """(ENG DUB) is now STRIPPED (recognized tokens) — the #78 test flip.

        Previously preserved due to the crude 'internal space = keep' heuristic.
        Under the correct allowlist, ENG (lang code) + DUB (dub marker) are both
        recognized, so (ENG DUB) is a strippable dub qualifier, not an alt-title.
        """
        bare = self._bare("Movie (ENG DUB)")
        assert bare == "Movie", (
            f"(ENG DUB) must now be STRIPPED (ENG=lang, DUB=marker, both recognized); "
            f"got {bare!r}"
        )


class TestParseChannelNamePreserveNumericTitles:
    """A bare trailing 4-digit number that is part of the real title must survive.

    Regression guard: the qualifier-strip loop must use the paren-only
    PAREN_YEAR_SUFFIX_RE, NOT the aggressive YEAR_SUFFIX_RE (whose bare ``\\s+\\d{4}$``
    branch is reserved for content_dedup's KEY normalization). Otherwise legitimate
    numeric titles get truncated: 'Blade Runner 2049' → 'Blade Runner'.
    """

    def _bare(self, name: str) -> str:
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name).bare_name

    @pytest.mark.parametrize("name,expected", [
        ("Blade Runner 2049", "Blade Runner 2049"),
        ("EN - Blade Runner 2049", "Blade Runner 2049"),
        ("Space 1999", "Space 1999"),
        ("The 4400", "The 4400"),
        ("Class of 2009", "Class of 2009"),
        ("Dallas 2019", "Dallas 2019"),
    ])
    def test_bare_trailing_number_in_title_preserved(self, name, expected):
        """A bare trailing year that is part of the title is NOT stripped."""
        assert self._bare(name) == expected, (
            f"{name!r} must keep its trailing number (part of the title); "
            f"got {self._bare(name)!r}"
        )

    def test_paren_year_still_stripped_while_title_number_kept(self):
        """Paren year is metadata (stripped + captured); a title number is kept.

        'Class of 2009 (2008)' → title 'Class of 2009', year '2008'.
        """
        from metatv.core.channel_name_utils import parse_channel_name
        r = parse_channel_name("Class of 2009 (2008)")
        assert r.bare_name == "Class of 2009", (
            f"Title number '2009' must survive; got {r.bare_name!r}"
        )
        assert r.year == "2008", (
            f"Paren year '(2008)' must be captured as the year; got {r.year!r}"
        )


# ---------------------------------------------------------------------------
# 5. End-to-end: update_detected_prefixes collapses variants
# ---------------------------------------------------------------------------


def test_1883_vostfr_and_year_variant_collapse(db):
    """'EN - 1883 (2021)' and 'FR - 1883 (VOSTFR)' → same detected_title AND content_key.

    The year-bearing variant already worked before #78; the VOSTFR variant did not.
    After the fix both must parse to detected_title='1883' and share a content_key.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid_year = _make_channel(session, name="EN - 1883 (2021)", media_type="series")
        cid_vostfr = _make_channel(session, name="FR - 1883 (VOSTFR)", media_type="series")

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        ch_year = session.query(ChannelDB).filter_by(id=cid_year).one()
        ch_vostfr = session.query(ChannelDB).filter_by(id=cid_vostfr).one()
        title_year = ch_year.detected_title
        title_vostfr = ch_vostfr.detected_title
        key_year = ch_year.content_key
        key_vostfr = ch_vostfr.content_key

    assert title_year == "1883", (
        f"EN - 1883 (2021) should parse to detected_title='1883'; got {title_year!r}"
    )
    assert title_vostfr == "1883", (
        f"FR - 1883 (VOSTFR) should parse to detected_title='1883'; got {title_vostfr!r}"
    )
    assert key_year is not None, "Year variant must have a content_key"
    assert key_vostfr is not None, "VOSTFR variant must have a content_key"
    assert key_year == key_vostfr, (
        f"Both '1883' variants must share content_key; "
        f"got year={key_year!r}, vostfr={key_vostfr!r}"
    )


def test_thirteen_reasons_why_us_4k_collapses(db):
    """'NF - 13 Reasons Why (US) (4K)' and 'EN - 13 Reasons Why' → same content_key.

    The multi-qualifier case: both (US) and (4K) must be stripped so the
    bare title is '13 Reasons Why' on both variants.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid_qualified = _make_channel(
            session, name="NF - 13 Reasons Why (US) (4K)", media_type="series"
        )
        cid_clean = _make_channel(
            session, name="EN - 13 Reasons Why", media_type="series"
        )

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        ch_q = session.query(ChannelDB).filter_by(id=cid_qualified).one()
        ch_c = session.query(ChannelDB).filter_by(id=cid_clean).one()
        title_q = ch_q.detected_title
        title_c = ch_c.detected_title
        key_q = ch_q.content_key
        key_c = ch_c.content_key

    assert title_q == "13 Reasons Why", (
        f"qualified variant should have detected_title='13 Reasons Why'; got {title_q!r}"
    )
    assert title_c == "13 Reasons Why", (
        f"clean variant should have detected_title='13 Reasons Why'; got {title_c!r}"
    )
    assert key_q == key_c, (
        f"Both variants must share content_key; got {key_q!r} vs {key_c!r}"
    )


def test_as_linas_descontinuas_spanish_eng_sub_collapses(db):
    """Motivating case: 'As Linas Descontinuas (2025) (SPANISH ENG-SUB)' → clean title.

    End-to-end: update_detected_prefixes must strip both the multi-token qualifier
    (SPANISH ENG-SUB) and the now-exposed interior year (2025), yielding
    detected_title='As Linas Descontinuas'.
    """
    from metatv.core.database import ChannelDB
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid = _make_channel(
            session,
            name="As Linas Descontinuas (2025) (SPANISH ENG-SUB)",
            media_type="movie",
        )

    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.channels.update_detected_prefixes()

    with db.session_scope(commit=False) as session:
        title = session.query(ChannelDB.detected_title).filter_by(id=cid).scalar()

    assert title == "As Linas Descontinuas", (
        f"Expected 'As Linas Descontinuas'; got {title!r}. "
        "Both (SPANISH ENG-SUB) and the interior (2025) must be stripped."
    )


# ---------------------------------------------------------------------------
# 6. DetectedTitleReparseTask — needs_run / on_completed gate
# ---------------------------------------------------------------------------


def test_detected_title_reparse_task_needs_run_and_completion(tmp_path: Path):
    """DetectedTitleReparseTask.needs_run honours version field; on_completed bumps it."""
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.migrations.detected_title_reparse import (
        DetectedTitleReparseTask,
        CURRENT_VERSION,
    )

    config = Config(config_dir=tmp_path / "config")
    assert getattr(config, "detected_reparse_version", 0) == 0

    d = Database(f"sqlite:///{tmp_path / 'task_test.db'}")
    d.create_tables()

    task = DetectedTitleReparseTask(d)

    # Before completion: needs_run must be True.
    assert task.needs_run(config) is True, "needs_run should be True before on_completed"

    # Simulate completion.
    task.on_completed(config)

    # After completion: needs_run must be False.
    assert task.needs_run(config) is False, "needs_run should be False after on_completed"
    assert config.detected_reparse_version == CURRENT_VERSION

    d.close()


def test_detected_title_reparse_task_run_is_noop_on_empty_db(tmp_path: Path):
    """DetectedTitleReparseTask.run() completes without error on an empty database."""
    from metatv.core.database import Database
    from metatv.core.migrations.detected_title_reparse import DetectedTitleReparseTask

    d = Database(f"sqlite:///{tmp_path / 'empty.db'}")
    d.create_tables()

    task = DetectedTitleReparseTask(d)
    # Must not raise.
    task.run(progress_cb=lambda done, total: None, is_cancelled=lambda: False)

    d.close()


def test_detected_title_reparse_task_run_idempotent(tmp_path: Path):
    """Running DetectedTitleReparseTask.run() twice produces identical results."""
    from metatv.core.database import ChannelDB, Database
    from metatv.core.migrations.detected_title_reparse import DetectedTitleReparseTask
    from metatv.core.repositories import RepositoryFactory

    d = Database(f"sqlite:///{tmp_path / 'idempotent.db'}")
    d.create_tables()

    # Seed channels.
    with d.session_scope() as session:
        cid = _make_channel(session, name="FR - 1883 (VOSTFR)", media_type="series")

    task = DetectedTitleReparseTask(d)

    # First run.
    task.run(progress_cb=lambda done, total: None, is_cancelled=lambda: False)

    with d.session_scope(commit=False) as session:
        title_first = session.query(ChannelDB.detected_title).filter_by(id=cid).scalar()
        key_first = session.query(ChannelDB.content_key).filter_by(id=cid).scalar()

    # Second run.
    task.run(progress_cb=lambda done, total: None, is_cancelled=lambda: False)

    with d.session_scope(commit=False) as session:
        title_second = session.query(ChannelDB.detected_title).filter_by(id=cid).scalar()
        key_second = session.query(ChannelDB.content_key).filter_by(id=cid).scalar()

    assert title_first == "1883", f"First run: expected '1883', got {title_first!r}"
    assert title_first == title_second, (
        f"Second run changed detected_title: {title_first!r} → {title_second!r}"
    )
    assert key_first == key_second, (
        f"Second run changed content_key: {key_first!r} → {key_second!r}"
    )

    d.close()
