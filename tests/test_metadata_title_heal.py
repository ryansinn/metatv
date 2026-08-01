"""The detected_title re-parse migration also heals stale metadata.title copies.

Regression guard for the #345/#349 interaction: #345 copied the (then-current)
detected_title into metadata.title for provider-fallback rows; #349's mid-name-year
pre-cut then made detected_title cleaner (stripping trailing "(YYYY) CAST"), but the
stored metadata.title stayed stale — and the details pane shows metadata.title, so it
regressed to the raw-looking form. The migration now refreshes metadata.title from the
clean detected_title for exactly the polluted rows, leaving genuine titles untouched.
"""

from __future__ import annotations

from metatv.core.database import Database, ChannelDB, MetadataDB
from metatv.core.migrations.detected_title_reparse import DetectedTitleReparseTask


def _run(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'heal.db'}")
    db.create_tables()
    DetectedTitleReparseTask(db).run(lambda d, t: None, lambda: False)
    return db


def test_stale_cast_laden_metadata_title_is_healed(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'heal.db'}")
    db.create_tables()
    with db.session_scope() as s:
        s.add(MetadataDB(id="m1", title="From Dusk Till Dawn 4K (1996) HARVEY KEITEL, TARANTINO"))
        s.flush()
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", media_type="movie",
                        metadata_id="m1",
                        name="EN - From Dusk Till Dawn 4K (1996) HARVEY KEITEL, TARANTINO"))
    DetectedTitleReparseTask(db).run(lambda d, t: None, lambda: False)
    with db.session_scope() as s:
        ch = s.query(ChannelDB).filter_by(id="c1").first()
        meta = s.query(MetadataDB).filter_by(id="m1").first()
        assert ch.detected_title == "From Dusk Till Dawn"   # re-parse cleaned the title
        assert meta.title == "From Dusk Till Dawn"           # stale metadata copy healed
    db.close()


def test_real_distinct_title_is_not_touched(tmp_path):
    # A genuine provider/TMDb title (no embedded parenthesized year after the clean
    # base) must survive — the year-signature guard protects it.
    db = Database(f"sqlite:///{tmp_path / 'keep.db'}")
    db.create_tables()
    with db.session_scope() as s:
        s.add(MetadataDB(id="m2", title="Star Wars: The Empire Strikes Back"))
        s.flush()
        s.add(ChannelDB(id="c2", source_id="s2", provider_id="p1", media_type="movie",
                        metadata_id="m2", name="EN - Star Wars (1980)"))
    DetectedTitleReparseTask(db).run(lambda d, t: None, lambda: False)
    with db.session_scope() as s:
        meta = s.query(MetadataDB).filter_by(id="m2").first()
        assert meta.title == "Star Wars: The Empire Strikes Back"  # untouched
    db.close()
