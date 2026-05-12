#!/usr/bin/env python3
"""Fix cached metadata - use logo_url as poster_url fallback"""
import sqlite3
from pathlib import Path

def fix_poster_cache():
    """Update cached metadata to use logo_url as poster_url when poster is missing"""
    db_path = Path.home() / ".local/share/metatv/metatv.db"
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return
    
    print(f"Fixing poster cache in: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Find records where poster_url is NULL but we have a channel with logo_url
        print("\nSearching for metadata records with missing posters...")
        cursor.execute("""
            SELECT m.id, c.logo_url, c.name
            FROM metadata m
            JOIN channels c ON c.metadata_id = m.id
            WHERE (m.poster_url IS NULL OR m.poster_url = '')
              AND c.logo_url IS NOT NULL
              AND c.logo_url != ''
        """)
        
        records = cursor.fetchall()
        print(f"Found {len(records)} records to update")
        
        if records:
            # Update poster_url with logo_url
            update_count = 0
            for metadata_id, logo_url, channel_name in records:
                cursor.execute("""
                    UPDATE metadata 
                    SET poster_url = ? 
                    WHERE id = ?
                """, (logo_url, metadata_id))
                update_count += 1
                if update_count <= 5:  # Show first 5
                    print(f"  ✓ Updated '{channel_name}' -> {logo_url[:50]}...")
            
            conn.commit()
            print(f"\n✅ Updated {update_count} metadata records with logo_url as poster")
        else:
            print("✓ No records needed updating")
        
    except sqlite3.Error as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_poster_cache()
