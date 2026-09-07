"""Migration: Add max_connections column to providers table

This migration adds the max_connections column for player instance limiting support.

To run:
    python -m metatv.core.migrations.002_add_max_connections

**Not importable and never run.** Like its now-deleted siblings
(001_add_detected_prefix.py, 003_add_special_content.py — dead-code sweep B,
docs/REFACTOR_PLAN.md row D43), a leading digit makes this unimportable as a
module and nothing globs or import_module's it by path. Unlike those two,
``max_connections`` was added to ``ProviderDB`` the SAME commit as this file
(2026-05-12, one day after the initial commit) — it is not part of the
original schema `tests/test_schema_upgrade_adds_every_column.py` grandfathers,
and it has no ``Database._migrate()`` ALTER TABLE entry either. Left
undeleted rather than silently dropped: a database created before 2026-05-12
and never since touched by this dead script may be missing the column. Fixing
that (an ALTER TABLE entry) is a real, separate change — out of scope for a
deletion-only sweep.
"""

import sqlite3
from pathlib import Path
from loguru import logger


def get_db_path() -> Path:
    """Get database path"""
    db_dir = Path.home() / ".local" / "share" / "metatv"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "metatv.db"


def migrate():
    """Add max_connections column to providers table"""
    db_path = get_db_path()
    
    if not db_path.exists():
        logger.warning(f"Database not found at {db_path}")
        logger.info("No migration needed - column will be created on first run")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(providers)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "max_connections" in columns:
            logger.info("Column 'max_connections' already exists, skipping migration")
            return
        
        # Add column with default value
        logger.info("Adding max_connections column to providers table...")
        cursor.execute("ALTER TABLE providers ADD COLUMN max_connections INTEGER DEFAULT 1")
        
        conn.commit()
        logger.success("✅ Migration complete: max_connections column added")
        
    except sqlite3.Error as e:
        logger.error(f"❌ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
