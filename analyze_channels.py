#!/usr/bin/env python3
"""Analyze channel naming patterns"""

from metatv.core.database import Database, ChannelDB
from metatv.core.config import Config
from collections import Counter

config = Config.load()
db = Database(config.database_url)
session = db.get_session()

# Get sample channels
channels = session.query(ChannelDB).limit(100).all()

print("Sample of first 50 channel names:\n")
for i, channel in enumerate(channels[:50], 1):
    print(f"{i:3}. {channel.name[:80]}")

print("\n" + "="*80)
print("\nChannels with # symbol:")
hash_channels = [c for c in channels if '#' in c.name]
for channel in hash_channels[:20]:
    print(f"  {channel.name}")

print("\n" + "="*80)
print("\nCategory distribution (top 30):")
categories = session.query(ChannelDB.category, 
                          db.func.count(ChannelDB.id)).group_by(ChannelDB.category).all()
for cat, count in sorted(categories, key=lambda x: x[1], reverse=True)[:30]:
    print(f"  {cat or '(no category)'}: {count:,}")

session.close()
