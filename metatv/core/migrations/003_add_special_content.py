"""Migration: Add special content columns to channels table

This migration adds columns for PPV, live events, and sports categorization:
- special_view: Type of special view (ppv, live_event, sports, or NULL)
- event_start_time: Parsed start time for PPV/events
- sport_type: Sport type (soccer, basketball, etc.)
- league_name: League name (Premier League, NBA, etc.)
- team_name: Team name (Manchester United, Lakers, etc.)
- event_metadata: JSON field for additional parsed data

To run:
    python -m metatv.core.migrations.003_add_special_content
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
    """Add special content columns to channels table"""
    db_path = get_db_path()
    
    if not db_path.exists():
        logger.warning(f"Database not found at {db_path}")
        logger.info("No migration needed - columns will be created on first run")
        return
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Check which columns already exist
        cursor.execute("PRAGMA table_info(channels)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        columns_to_add = {
            "special_view": "TEXT",  # 'ppv', 'live_event', 'sports', or NULL
            "event_start_time": "DATETIME",  # Parsed event date/time
            "sport_type": "TEXT",  # 'soccer', 'basketball', 'football', etc.
            "league_name": "TEXT",  # 'Premier League', 'NBA', 'NFL', etc.
            "team_name": "TEXT",  # 'Manchester United', 'Lakers', etc.
            "event_metadata": "JSON",  # Additional parsed data
        }
        
        added_count = 0
        for col_name, col_type in columns_to_add.items():
            if col_name in existing_columns:
                logger.info(f"Column '{col_name}' already exists, skipping")
            else:
                logger.info(f"Adding {col_name} column ({col_type})...")
                cursor.execute(f"ALTER TABLE channels ADD COLUMN {col_name} {col_type}")
                added_count += 1
        
        if added_count > 0:
            conn.commit()
            logger.success(f"✅ Migration complete: {added_count} column(s) added")
        else:
            logger.info("All columns already exist, no changes needed")
        
    except sqlite3.Error as e:
        logger.error(f"❌ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
