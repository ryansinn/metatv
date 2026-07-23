"""Global Exclusions for the AI-provenance ``content_type`` tags (#304 follow-up).

Proves the new content-provenance Global Exclusion actually hides content and
renders friendly names — the whole point of the feature:

(a) Engine — a channel tagged ``content_type:ai_generated`` is dropped by the
    channel-list Python exclusion twin AND by the tag-count scope when the slug is
    in ``global_filter_excluded_tag_content_types``, and reappears when paused.
(b) Distinct values — excluding ``ai_generated`` never hides an ``ai_voiceover``
    channel (the two content_type values are independent).
(c) Display map — ``content_type_display`` returns "AI Generated" / "AI Voiceover",
    and the Global Exclusions "Content Provenance" section renders those labels.
(d) Chip active-state — the Exclusions chip reads active when only the new key is set.

Real ``Database`` on a ``tmp_path`` file (never :memory: — a shared-connection
requirement for session_scope), per the tests rule.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def file_db(tmp_path: Path):
    db = Database(f"sqlite:///{tmp_path / 'ai_excl.db'}")
    db.create_tables()
    yield db
    db.close()


def _add_channel(session, name: str, media_type: str = "movie") -> str:
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid,
            source_id=str(uuid.uuid4()),
            provider_id="p1",
            name=name,
            media_type=media_type,
        )
    )
    session.flush()
    return cid


@pytest.fixture
def seeded(file_db):
    """Three channels: one AI-generated, one AI-voiceover, one plain.

    Returns ``(ai_gen_id, ai_vo_id, plain_id, db)``.
    """
    with file_db.session_scope() as session:
        repos = RepositoryFactory(session)

        ai_gen = _add_channel(session, "[MV] Star - Born To Win")
        repos.tags.set_content_tags(
            ai_gen,
            [("content_type", "ai_generated", "name_parse"),
             ("genre", "Music", "test_feeder")],
        )

        ai_vo = _add_channel(session, "PL - Bugonia (2025)")
        repos.tags.set_content_tags(
            ai_vo,
            [("content_type", "ai_voiceover", "name_parse"),
             ("genre", "Drama", "test_feeder")],
        )

        plain = _add_channel(session, "Ordinary Movie")
        repos.tags.set_content_tags(
            plain, [("genre", "Drama", "test_feeder")]
        )

    return ai_gen, ai_vo, plain, file_db


# ---------------------------------------------------------------------------
# (a) Engine — id-set twin + tag-count scope hide, paused reveals
# ---------------------------------------------------------------------------


def test_channel_ids_for_content_types_resolves_excluded_set(seeded):
    """The id-set twin (channel-list / EPG / Other-Versions primitive) resolves
    exactly the channels carrying the excluded content_type."""
    ai_gen, ai_vo, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        got = repos.tags.channel_ids_for_content_types({"ai_generated"})
    assert got == {ai_gen}, "only the ai_generated channel is in the excluded id-set"


def test_python_exclusion_twin_drops_ai_channel(seeded):
    """_apply_python_exclusions drops a channel whose id is in the content-type set
    (the channel-list layer) and keeps it when the set is empty (paused)."""
    from metatv.gui.main_window_channels import _apply_python_exclusions

    ai_gen, ai_vo, plain, db = seeded
    with db.session_scope(commit=False) as session:
        rows = session.query(ChannelDB).all()
        excluded_ids = {ai_gen}

        kept = _apply_python_exclusions(rows, set(), set(), excluded_ids)
        kept_ids = {c.id for c in kept}
        assert ai_gen not in kept_ids, "ai_generated channel hidden"
        assert {ai_vo, plain} <= kept_ids, "other channels survive"

        # Paused → empty id-set → nothing hidden (channel reappears).
        kept_paused = _apply_python_exclusions(rows, set(), set(), set())
        assert ai_gen in {c.id for c in kept_paused}, "reappears when nothing excluded"


def test_tag_count_scope_drops_ai_generated(seeded):
    """The SQL twin via the tag-count scope: the content_type facet count for
    ai_generated is gone once excluded; paused (no exclusion) shows it again."""
    ai_gen, ai_vo, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)

        # No exclusion → both AI values present in the content_type facet.
        base = {
            d.value: d.channel_count
            for d in repos.tags.get_tag_counts_for_facet("content_type")
        }
        assert base.get("ai_generated") == 1
        assert base.get("ai_voiceover") == 1

        # Exclude ai_generated → its value drops out of the scoped counts.
        excluded = {
            d.value: d.channel_count
            for d in repos.tags.get_tag_counts_for_facet(
                "content_type", excluded_tag_content_types={"ai_generated"}
            )
        }
        assert "ai_generated" not in excluded, "excluded value no longer counted"
        assert excluded.get("ai_voiceover") == 1, "the other value is untouched"


def test_faceted_query_scope_excludes_ai_channel(seeded):
    """A faceted query scoped with excluded_provider_ids + the content-type set
    drops the AI channel from a genre browse (Discover-via-recipe surface)."""
    ai_gen, ai_vo, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        # Music genre: only the ai_generated channel carries it.
        got = repos.tags.get_channel_ids_by_tag_facets(
            {"genre": {"Music"}},
            excluded_provider_ids=[],            # opt into visible-channel scope
            excluded_tag_content_types={"ai_generated"},
        )
        assert ai_gen not in got, "ai_generated dropped from the scoped facet query"


# ---------------------------------------------------------------------------
# (b) Distinct values — ai_generated exclusion never hides ai_voiceover
# ---------------------------------------------------------------------------


def test_voiceover_not_hidden_by_generated_exclusion(seeded):
    ai_gen, ai_vo, plain, db = seeded
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        excluded_ids = repos.tags.channel_ids_for_content_types({"ai_generated"})
    assert ai_vo not in excluded_ids, "ai_voiceover is a distinct value, not excluded"
    assert excluded_ids == {ai_gen}


# ---------------------------------------------------------------------------
# (c) Display map + dialog render path
# ---------------------------------------------------------------------------


def test_content_type_display_names():
    from metatv.core.channel_name_utils import content_type_display

    assert content_type_display("ai_generated") == "AI Generated"
    assert content_type_display("ai_voiceover") == "AI Voiceover"
    assert content_type_display("ppv") == "PPV"
    assert content_type_display("live_event") == "Live Event"
    # Unknown slug degrades gracefully — never a raw snake_case token.
    assert content_type_display("future_kind") == "Future Kind"


def test_dialog_content_provenance_section_shows_display_names(seeded, qtbot):
    """The Global Exclusions dialog builds a 'Content Provenance' section whose
    checkboxes read the friendly display names, not the raw slugs."""
    from metatv.core.config import Config
    from metatv.gui.global_filter_dialog import GlobalFilterDialog

    _ai_gen, _ai_vo, _plain, db = seeded
    cfg = Config()  # isolated tmp HOME via conftest autouse fixture
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)

    labels = {cb.text() for _slug, cb, _row in dlg._content_provenance_rows}
    slugs = {slug for slug, _cb, _row in dlg._content_provenance_rows}
    assert slugs == {"ai_generated", "ai_voiceover"}, "both AI values listed"
    assert "AI Generated" in labels
    assert "AI Voiceover" in labels
    assert "ai_generated" not in labels, "raw slug must not be shown"


def test_dialog_saves_checked_provenance_slugs(seeded, qtbot):
    """Checking a provenance row writes the slug into the new config key on save."""
    from metatv.core.config import Config
    from metatv.gui.global_filter_dialog import GlobalFilterDialog

    _ai_gen, _ai_vo, _plain, db = seeded
    cfg = Config()
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)

    for slug, cb, _row in dlg._content_provenance_rows:
        if slug == "ai_generated":
            cb.setChecked(True)
    dlg._save_and_accept()

    assert cfg.global_filter_excluded_tag_content_types == ["ai_generated"]


# ---------------------------------------------------------------------------
# (d) Exclusions chip active-state includes the new key
# ---------------------------------------------------------------------------


def test_chip_active_state_includes_new_key():
    """_update_filter_btn_state reports active when ONLY the new key is set."""
    from metatv.gui.main_window_nav import _NavMixin
    from metatv.core.config import Config

    class _FakeChip:
        def __init__(self):
            self.calls = []

        def set_filter_state(self, active, paused):
            self.calls.append((active, paused))

    class _Stub:
        pass

    stub = _Stub()
    stub.config = Config()
    stub._filter_chip = _FakeChip()

    # Nothing set → inactive.
    _NavMixin._update_filter_btn_state(stub)
    assert stub._filter_chip.calls[-1][0] is False

    # Only the content-provenance key set → active.
    stub.config.global_filter_excluded_tag_content_types = ["ai_generated"]
    _NavMixin._update_filter_btn_state(stub)
    assert stub._filter_chip.calls[-1][0] is True, "chip active with only the new key set"
