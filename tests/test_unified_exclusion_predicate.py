"""Behavioural tests for the ONE shared Global-Exclusion predicate (P1-6).

The user's Global Exclusions are interpreted by a single canonical rule
("language wins over region", shipped #298) with four implementations that must
never fork:

  * ``filter_utils.is_channel_excluded``          — the Python predicate
  * ``filter_utils.channel_exclusion_criterion``  — the SQLAlchemy KEEP twin
  * ``filter_utils.global_exclusion_set``         — the set builder
  * ``main_window_channels._apply_python_exclusions`` — the batch Python twin

These tests pin the rule directly, prove the Python and SQL twins agree on the
exact same matrix (the drift-guard that would catch a future fork), and exercise
the two intended behaviour changes this refactor lands: tag/recipe counts stop
over-hiding language-tagged rows filed under an excluded region, and the details
"Other Versions" panel now greys out prefix-less variants from an excluded region.

Real ``Database`` on a ``tmp_path`` file (never ``:memory:``), per CLAUDE.md.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, ProviderDB
from metatv.core.filter_utils import (
    channel_exclusion_criterion,
    global_exclusion_set,
    is_channel_excluded,
)
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# The canonical matrix: (detected_prefix, detected_region, expected_excluded)
# under excluded = {"IN"}.  Language (prefix) wins; region is the no-prefix
# fallback; "" is treated like None (Python truthiness).
# ---------------------------------------------------------------------------

EXCLUDED = {"IN"}
MATRIX: list[tuple[str | None, str | None, bool]] = [
    ("EN", "IN", False),   # un-excluded prefix keeps the row despite excluded region
    (None, "IN", True),    # no prefix → region fallback hides it
    ("",   "IN", True),    # "" behaves like None → region fallback hides it
    ("IN", "EN", True),    # excluded prefix hides it regardless of region
    (None, None, False),   # nothing to match → kept
    ("EN", None, False),   # un-excluded prefix, no region → kept
]


# ---------------------------------------------------------------------------
# Fixtures — file-backed DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def file_db(tmp_path: Path):
    db_file = tmp_path / "unified_exclusion.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture
def session(file_db):
    s = file_db.get_session()
    s.add(ProviderDB(
        id="p1", name="Test Source", type="xtream", url="http://example",
        is_active=True, account_status="Active",
    ))
    s.commit()
    yield s
    s.close()


def _ch(
    session,
    name: str,
    *,
    provider_id: str = "p1",
    media_type: str = "movie",
    detected_prefix: str | None = None,
    detected_region: str | None = None,
    content_key: str | None = None,
    is_hidden: bool = False,
) -> str:
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        is_hidden=is_hidden,
        detected_prefix=detected_prefix,
        detected_region=detected_region,
        detected_title=name,
        content_key=content_key,
    )
    session.add(ch)
    session.flush()
    return ch.id


# ---------------------------------------------------------------------------
# 1 — is_channel_excluded unit matrix
# ---------------------------------------------------------------------------

class TestIsChannelExcluded:
    @pytest.mark.parametrize("prefix,region,expected", MATRIX)
    def test_matrix(self, prefix, region, expected):
        assert is_channel_excluded(prefix, region, EXCLUDED) is expected

    def test_empty_excluded_never_hides(self):
        # An empty exclusion set is a no-op even for a would-be-excluded row.
        assert is_channel_excluded("IN", "IN", set()) is False
        assert is_channel_excluded(None, "IN", set()) is False


# ---------------------------------------------------------------------------
# 2 — Python ↔ SQL parity drift-guard
# ---------------------------------------------------------------------------

class TestPythonSqlParity:
    def test_criterion_matches_predicate_row_by_row(self, session):
        """The SQL KEEP criterion must survive EXACTLY the rows the Python
        predicate keeps — the guard that a future edit can't fork one twin."""
        ids: dict[str, tuple[str | None, str | None]] = {}
        for prefix, region, _ in MATRIX:
            cid = _ch(session, f"Movie {prefix!r}-{region!r}",
                      detected_prefix=prefix, detected_region=region)
            ids[cid] = (prefix, region)
        session.commit()

        sql_survivors = {
            row[0]
            for row in session.query(ChannelDB.id)
            .filter(channel_exclusion_criterion(EXCLUDED, ChannelDB))
            .all()
        }
        py_survivors = {
            cid for cid, (p, r) in ids.items()
            if not is_channel_excluded(p, r, EXCLUDED)
        }

        assert sql_survivors == py_survivors
        # Sanity against the hand-computed expectation (keep = the False rows).
        assert len(py_survivors) == sum(1 for _, _, ex in MATRIX if not ex) == 3

    def test_empty_excluded_criterion_keeps_all(self, session):
        for prefix, region, _ in MATRIX:
            _ch(session, f"Movie {prefix!r}-{region!r}",
                detected_prefix=prefix, detected_region=region)
        session.commit()

        total = session.query(ChannelDB.id).count()
        kept = (
            session.query(ChannelDB.id)
            .filter(channel_exclusion_criterion(set(), ChannelDB))
            .count()
        )
        assert kept == total == len(MATRIX)


# ---------------------------------------------------------------------------
# 3 — global_exclusion_set builder
# ---------------------------------------------------------------------------

class TestGlobalExclusionSet:
    def test_union_of_categories_and_blocked_prefixes(self):
        cfg = SimpleNamespace(
            global_filter_paused=False,
            global_filter_excluded_categories=["IN"],
            global_filter_excluded_prefixes=["ZZ"],
        )
        assert global_exclusion_set(cfg) == {"IN", "ZZ"}

    def test_paused_yields_empty(self):
        cfg = SimpleNamespace(
            global_filter_paused=True,
            global_filter_excluded_categories=["IN"],
            global_filter_excluded_prefixes=["ZZ"],
        )
        assert global_exclusion_set(cfg) == set()


# ---------------------------------------------------------------------------
# 4 — tag.py faceted counts stop over-hiding language-tagged rows (behaviour change)
# ---------------------------------------------------------------------------

class TestTagScopeBehaviour:
    def test_language_prefix_survives_region_exclusion_in_counts(self, session):
        """Two EN rows filed under region IN + one prefix-less IN row, all tagged
        genre=Action, with IN excluded.  The count must be 2 (both EN rows survive;
        only the prefix-less IN row drops).  Under the OLD prefix-OR-region SQL rule
        the EN/IN row was wrongly dropped, yielding 1."""
        repos = RepositoryFactory(session)
        keep_a = _ch(session, "Heat EN a", detected_prefix="EN", detected_region="IN")
        keep_b = _ch(session, "Heat EN b", detected_prefix="EN", detected_region=None)
        drop   = _ch(session, "Heat noprefix", detected_prefix=None, detected_region="IN")
        for cid in (keep_a, keep_b, drop):
            repos.tags.set_content_tags(cid, [("genre", "Action", "test_feeder")])
        session.commit()

        counts = repos.tags.get_tag_counts_for_facet(
            "genre", excluded_prefixes={"IN"},
        )
        by_value = {c.value: c.channel_count for c in counts}
        assert by_value.get("Action") == 2, (
            "both EN rows survive region-IN exclusion; only the prefix-less IN row drops"
        )

    def test_no_exclusion_counts_all(self, session):
        repos = RepositoryFactory(session)
        for i, (prefix, region) in enumerate([("EN", "IN"), (None, "IN"), ("EN", None)]):
            cid = _ch(session, f"Heat {i}", detected_prefix=prefix, detected_region=region)
            repos.tags.set_content_tags(cid, [("genre", "Action", "test_feeder")])
        session.commit()

        counts = repos.tags.get_tag_counts_for_facet("genre")
        by_value = {c.value: c.channel_count for c in counts}
        assert by_value.get("Action") == 3


# ---------------------------------------------------------------------------
# 5 — details "Other Versions": prefix-less excluded-region variant now filtered
# ---------------------------------------------------------------------------

class TestMetadataVersionsFiltered:
    def _config(self):
        # SimpleNamespace carrying only what _bg_fetch_versions + version_score read.
        return SimpleNamespace(
            global_filter_paused=False,
            global_filter_excluded_categories=["IN"],
            global_filter_excluded_prefixes=[],
            preferred_version_prefixes=[],
            preferred_version_provider_ids=[],
            preferred_version_quality=None,
        )

    def test_prefixless_region_excluded_variant_marked_filtered(self, session, file_db, qapp):
        """Drive the real _bg_fetch_versions: a prefix-less variant filed under the
        excluded region IN is now is_filtered=True, while an EN variant filed under
        IN survives (prefix wins) — closing the ~37k-row gap vs the channel list."""
        from metatv.gui.main_window_metadata import _MetadataMixin

        base   = _ch(session, "Dune EN base", detected_prefix="EN",
                     detected_region="US", content_key="ck-dune")
        var_en = _ch(session, "Dune EN in", detected_prefix="EN",
                     detected_region="IN", content_key="ck-dune")
        var_np = _ch(session, "Dune noprefix", detected_prefix=None,
                     detected_region="IN", content_key="ck-dune")
        session.commit()

        stub = SimpleNamespace(
            db=file_db,
            config=self._config(),
            _versions_loaded=MagicMock(),
        )
        _MetadataMixin._bg_fetch_versions(stub, base)

        stub._versions_loaded.emit.assert_called_once()
        emitted_id, versions = stub._versions_loaded.emit.call_args.args
        assert emitted_id == base
        by_id = {v.channel_id: v for v in versions}

        assert by_id[var_np].is_filtered is True, (
            "prefix-less variant under excluded region IN must be greyed out"
        )
        assert by_id[var_en].is_filtered is False, (
            "EN variant survives region-IN exclusion (language wins over region)"
        )
