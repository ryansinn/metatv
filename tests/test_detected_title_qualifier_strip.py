"""Behavioral tests for fix #78: strip trailing quality/region/subtitle qualifiers
from detected_title in parse_channel_name() and update_detected_prefixes().

Guards five invariants:

1. ``parse_channel_name`` strips trailing single-token paren qualifiers from
   the bare title (the underlying ``detected_title`` source).

2. Known strip cases: (US), (4K), (HQ), (LQ), (BR), (VOSTFR).

3. Preserve cases: multi-word alt-titles (30 Monedas), (Soleil Noir), (ENG DUB)
   must NOT be stripped (internal space = alt-language title).

4. End-to-end via ``update_detected_prefixes``: two series that differ only by a
   paren qualifier get the same ``detected_title`` AND the same ``content_key``.

5. ``DetectedTitleReparseTask`` ``needs_run`` / ``on_completed`` gate logic.

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
# 1+2. parse_channel_name — strip cases
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
# 3. Preserve cases — multi-word alt-language titles must NOT be stripped
# ---------------------------------------------------------------------------


class TestParseChannelNamePreserve:
    """Multi-word parenthetical alt-titles (internal space) must be preserved."""

    def _bare(self, name: str) -> str:
        from metatv.core.channel_name_utils import parse_channel_name
        return parse_channel_name(name).bare_name

    def test_preserve_30_monedas(self):
        """'30 Coins (30 Monedas)' keeps '(30 Monedas)' — internal space."""
        bare = self._bare("30 Coins (30 Monedas)")
        assert "(30 Monedas)" in bare, (
            f"Alt-title '(30 Monedas)' must be preserved; got {bare!r}"
        )

    def test_preserve_soleil_noir(self):
        """'Under a Dark Sun (Soleil Noir)' keeps '(Soleil Noir)' — internal space."""
        bare = self._bare("Under a Dark Sun (Soleil Noir)")
        assert "(Soleil Noir)" in bare, (
            f"Alt-title '(Soleil Noir)' must be preserved; got {bare!r}"
        )

    def test_preserve_eng_dub_with_space(self):
        """'Movie (ENG DUB)' keeps '(ENG DUB)' — internal space prevents stripping."""
        bare = self._bare("Movie (ENG DUB)")
        # ENG DUB has internal space — _PAREN_QUALIFIER_RE requires no space
        assert "(ENG DUB)" in bare, (
            f"'(ENG DUB)' has an internal space and must be preserved; got {bare!r}"
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
# 4. End-to-end: update_detected_prefixes collapses variants
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


# ---------------------------------------------------------------------------
# 5. DetectedTitleReparseTask — needs_run / on_completed gate
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
