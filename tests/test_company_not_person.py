"""Studios are not people (ledger F59): the credit writer skips them, a migration clears the rest."""

from __future__ import annotations

from sqlalchemy import text

from metatv.core.database import ChannelDB


def test_credit_tags_skip_a_studio_in_the_director_field():
    from metatv.core.tag_decomposer import credit_tags
    items = credit_tags([{"name": "Penn Badgley", "character": "Joe"}],
                        "A+E Studios, Greg Berlanti, Alloy Entertainment")
    people = [(t, v) for t, v, *_ in items]
    assert people == [("cast", "Penn Badgley"), ("director", "Greg Berlanti")]


def _seed(db):
    with db.session_scope() as s:
        s.add(ChannelDB(id="c1", source_id="1", provider_id="p", name="YOU", media_type="series"))
    with db.session_scope() as s:
        key = s.query(ChannelDB.channel_key).filter_by(id="c1").scalar()
        for tid, value in ((1, "A+E Studios"), (2, "Greg Berlanti"), (3, "Ltd.")):
            s.execute(text("INSERT INTO tags (id, type, value) VALUES (:i, 'person', :v)"),
                      {"i": tid, "v": value})
            s.execute(text("INSERT INTO content_tags (channel_key, tag_id, source, feeders, qualifier)"
                           " VALUES (:k, :i, 0, '4', 2)"), {"k": key, "i": tid})
        s.execute(text("INSERT INTO tag_aliases (type, value, tag_id) VALUES ('person', 'AE Studios', 1)"))


def _count(db, sql):
    with db.session_scope() as s:
        return s.execute(text(sql)).scalar()


def test_the_migration_removes_companies_and_keeps_people(db):
    from metatv.core.migrations.company_person_cleanup import CompanyPersonCleanupTask
    _seed(db)
    task = CompanyPersonCleanupTask(db)
    task.run(lambda *_: None, lambda: False)
    assert _count(db, "SELECT group_concat(value) FROM tags WHERE type='person'") == "Greg Berlanti"
    assert _count(db, "SELECT count(*) FROM content_tags") == 1
    assert _count(db, "SELECT count(*) FROM tag_aliases") == 0
    task.run(lambda *_: None, lambda: False)                 # idempotent
    assert _count(db, "SELECT count(*) FROM tags WHERE type='person'") == 1


def test_the_task_is_registered_and_version_gated():
    from types import SimpleNamespace

    from metatv.core.migrations import registry
    from metatv.core.migrations.company_person_cleanup import CURRENT_VERSION, CompanyPersonCleanupTask
    assert ("company_person_cleanup", "CompanyPersonCleanupTask", "") in registry.TASKS
    task = CompanyPersonCleanupTask.__new__(CompanyPersonCleanupTask)
    assert task.needs_run(SimpleNamespace(company_person_cleanup_version=0))
    assert not task.needs_run(SimpleNamespace(company_person_cleanup_version=CURRENT_VERSION))
