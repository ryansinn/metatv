#!/usr/bin/env python3
"""Database migration helper - adds missing columns to metadata table"""
import sqlite3
from pathlib import Path

def migrate_database():
    """Add missing columns to metadata table"""
    db_path = Path.home() / ".local/share/metatv/metatv.db"
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
    
    print(f"Migrating database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check existing columns
        cursor.execute("PRAGMA table_info(metadata)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"Existing columns: {columns}")
        
        # Define columns that should exist (from database.py MetadataDB model)
        required_columns = {
            'cast': 'JSON',
            'crew': 'JSON',
            'trailer_url': 'TEXT',
            'tagline': 'TEXT',
            'content_rating': 'TEXT',
            'release_date': 'TEXT',
        }
        
        added_count = 0
        for col_name, col_type in required_columns.items():
            if col_name not in columns:
                print(f"Adding '{col_name}' column ({col_type})...")
                cursor.execute(f"ALTER TABLE metadata ADD COLUMN {col_name} {col_type}")
                conn.commit()
                print(f"✓ Added '{col_name}' column")
                added_count += 1
            else:
                print(f"✓ '{col_name}' column already exists")
        
        # Copy data from actors to cast if needed
        if 'actors' in columns and 'cast' in required_columns:
            print("Migrating data from 'actors' to 'cast'...")
            # Use COALESCE to handle NULL values
            cursor.execute("UPDATE metadata SET cast = actors WHERE cast = '[]' OR cast IS NULL")
            rows_updated = cursor.rowcount
            conn.commit()
            if rows_updated > 0:
                print(f"✓ Migrated {rows_updated} rows from 'actors' to 'cast'")
            else:
                print("✓ No data to migrate")
        
        print(f"\n✅ Migration complete! Added {added_count} columns.")
        
    except sqlite3.Error as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_database()
