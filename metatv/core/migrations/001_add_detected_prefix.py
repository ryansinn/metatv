"""Migration: Add detected_prefix column to channels table

This migration adds the detected_prefix column for filtering support.

To run:
    python -m metatv.core.migrations.001_add_detected_prefix
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
    """Add detected_prefix column to channels table"""
    db_path = get_db_path()
    
    if not db_path.exists():
        logger.warning(f"Database not found at {db_path}")
        logger.info("No migration needed - column will be created on first run")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(channels)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "detected_prefix" in columns:
            logger.info("Column 'detected_prefix' already exists, skipping migration")
            return
        
        # Add column
        logger.info("Adding detected_prefix column to channels table...")
        cursor.execute("ALTER TABLE channels ADD COLUMN detected_prefix TEXT")
        
        # Create index
        logger.info("Creating index on detected_prefix...")
        cursor.execute("CREATE INDEX idx_channels_detected_prefix ON channels(detected_prefix)")
        
        conn.commit()
        logger.success("Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
