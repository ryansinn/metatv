#!/usr/bin/env python3
"""Analyze channels to identify sports, PPV, and event content patterns

This script examines raw_data from the database to understand what fields
indicate special content categories (sports, PPV, events) and documents
the patterns found.

Usage:
    python analyze_special_content.py
"""

import json
from pathlib import Path
from collections import Counter
from metatv.core.database import Database
from metatv.core.config import Config
from metatv.core.repositories import RepositoryFactory


def main():
    """Analyze special content channels"""
    print("Starting analysis...")
    
    config = Config.load()
    print(f"Config loaded. Database URL: {config.database_url}")
    
    db = Database(config.database_url)
    session = db.get_session()
    print("Database session created")
    
    try:
        # Keywords to search for
        sports_keywords = ['sport', 'football', 'soccer', 'nfl', 'nba', 'nhl', 'mlb', 
                           'boxing', 'ufc', 'fight', 'racing', 'cricket', 'tennis', 
                           'rugby', 'hockey', 'basketball', 'baseball', 'f1', 'moto',
                           'premier league', 'champions league', 'la liga', 'bundesliga',
                           'nascar', 'golf', 'mma', 'wrestling', 'wwe', 'volleyball',
                           'handball', 'cycling', 'olympics', 'espn', 'tsn', 'bein']
        ppv_keywords = ['ppv', 'pay per view', 'pay-per-view', 'pay per-view']
        event_keywords = ['event', 'special', 'live event', 'concert', 'show', 'festival']
        
        repos = RepositoryFactory(session)
        all_channels = repos.channels.get_all()
        
        # Separate organizational headers from playable content
        org_headers = [ch for ch in all_channels if not ch.stream_url]
        playable_channels = [ch for ch in all_channels if ch.stream_url]
        
        print(f"\n{'='*80}")
        print(f"SPECIAL CONTENT ANALYSIS")
        print(f"{'='*80}")
        print(f"\nTotal entries in database: {len(all_channels)}")
        print(f"Organizational headers: {len(org_headers)}")
        print(f"Playable channels: {len(playable_channels)}")
        
        # Show organizational structure
        if org_headers:
            print(f"\n{'='*80}")
            print("ORGANIZATIONAL STRUCTURE (Category Headers)")
            print(f"{'='*80}")
            print("\nThese headers define the category hierarchy:")
            for header in sorted(org_headers[:30], key=lambda x: x.category):
                # Count how many channels reference this header
                referencing_count = sum(1 for ch in playable_channels if ch.category == header.category)
                print(f"  {header.category} → {referencing_count} channels")
            if len(org_headers) > 30:
                print(f"  ... and {len(org_headers) - 30} more headers")
        
        # Find matching channels
        sports_channels = []
        ppv_channels = []
        event_channels = []
        
        for ch in playable_channels:
            # Strip hashtag prefixes (TREX uses ## or # at start)
            name_clean = ch.name.lstrip('#').strip()
            cat_clean = ch.category.lstrip('#').strip()
            
            name_lower = name_clean.lower()
            cat_lower = cat_clean.lower()
            
            if any(kw in name_lower or kw in cat_lower for kw in sports_keywords):
                sports_channels.append(ch)
            if any(kw in name_lower or kw in cat_lower for kw in ppv_keywords):
                ppv_channels.append(ch)
            if any(kw in name_lower or kw in cat_lower for kw in event_keywords):
                event_channels.append(ch)
        
        print(f"\n{'='*80}")
        print("DETECTION RESULTS")
        print(f"{'='*80}")
        print(f"Sports channels found: {len(sports_channels)}")
        print(f"PPV channels found: {len(ppv_channels)}")
        print(f"Event channels found: {len(event_channels)}")
        
        # Analyze each category
        for category_name, channels in [
            ("SPORTS", sports_channels),
            ("PPV", ppv_channels),
            ("EVENTS", event_channels)
        ]:
            if not channels:
                print(f"\n{'='*80}")
                print(f"{category_name} CHANNELS - NONE FOUND")
                print(f"{'='*80}")
                continue
            
            print(f"\n{'='*80}")
            print(f"{category_name} CHANNELS - SAMPLE ANALYSIS")
            print(f"{'='*80}")
            
            # Show sample channels
            samples = channels[:5]
            for i, ch in enumerate(samples, 1):
                print(f"\n--- Sample {i}: {ch.name} ---")
                print(f"  Category: {ch.category}")
                print(f"  Media Type: {ch.media_type}")
                print(f"  EPG Channel ID: {ch.epg_channel_id}")
                
                if ch.raw_data:
                    print(f"  Raw Data Keys: {list(ch.raw_data.keys())}")
                    print(f"  Raw Data (truncated):")
                    json_str = json.dumps(ch.raw_data, indent=4)
                    print(f"  {json_str[:500]}...")
                else:
                    print(f"  Raw Data: None")
            
            # Analyze categories
            print(f"\n--- Category Distribution for {category_name} ---")
            category_counts = Counter(ch.category for ch in channels)
            for cat, count in category_counts.most_common(10):
                print(f"  {cat}: {count} channels")
            
            # Show hashtag pattern examples
            hashtag_cats = [ch.category for ch in channels if ch.category.startswith('#')]
            if hashtag_cats:
                print(f"\n--- Hashtag-Prefixed Categories (TREX Pattern) ---")
                for cat in set(hashtag_cats[:10]):
                    print(f"  {cat}")
            
            # Analyze raw_data keys
            if any(ch.raw_data for ch in channels):
                print(f"\n--- Common Raw Data Fields for {category_name} ---")
                all_keys = []
                for ch in channels:
                    if ch.raw_data and isinstance(ch.raw_data, dict):
                        all_keys.extend(ch.raw_data.keys())
                key_counts = Counter(all_keys)
                for key, count in key_counts.most_common(15):
                    print(f"  {key}: appears in {count}/{len(channels)} channels")
        
        print(f"\n{'='*80}")
        print("RECOMMENDATIONS")
        print(f"{'='*80}")
        
        if sports_channels:
            print("\n✓ Sports channels detected")
            print("  - Recommend adding 'sports' special_category")
            print("  - Consider EPG integration for live schedule")
            print("  - Add league/team metadata extraction")
        
        if ppv_channels:
            print("\n✓ PPV channels detected")
            print("  - Recommend adding 'ppv' special_category")
            print("  - Check for pricing/access fields in raw_data")
            print("  - Add event date/time extraction")
        
        if event_channels:
            print("\n✓ Event channels detected")
            print("  - Recommend adding 'events' special_category")
            print("  - Add event_start_time field")
            print("  - Consider calendar view UI")
        
        if not (sports_channels or ppv_channels or event_channels):
            print("\n⚠ No special content detected")
            print("  - Provider may not have sports/PPV/event channels")
            print("  - Or keywords need adjustment")
            print("  - Check raw_data manually for any channels")
        
        # Save detailed report
        report_path = Path("docs/SPECIAL_CONTENT_ANALYSIS.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, 'w') as f:
            f.write("# Special Content Analysis Report\n\n")
            f.write(f"Generated from {len(all_channels)} total entries\n\n")
            f.write(f"## Summary\n\n")
            f.write(f"- Organizational headers: {len(org_headers)}\n")
            f.write(f"- Playable channels: {len(playable_channels)}\n")
            f.write(f"- Sports channels: {len(sports_channels)}\n")
            f.write(f"- PPV channels: {len(ppv_channels)}\n")
            f.write(f"- Event channels: {len(event_channels)}\n\n")
            
            # Organizational structure section
            if org_headers:
                f.write(f"## Organizational Structure\n\n")
                f.write(f"**{len(org_headers)} category headers** define the content hierarchy:\n\n")
                f.write(f"These headers have no `stream_url` but are referenced by actual channels.\n")
                f.write(f"Useful for:\n")
                f.write(f"- Building hierarchical Browse Mode navigation\n")
                f.write(f"- Grouping channels by category\n")
                f.write(f"- Understanding provider's content organization\n\n")
                f.write(f"### Sample Category Headers\n\n")
                for header in sorted(org_headers[:20], key=lambda x: x.category):
                    referencing_count = sum(1 for ch in playable_channels if ch.category == header.category)
                    f.write(f"- `{header.category}` → {referencing_count} channels\n")
                f.write("\n")
            
            f.write(f"## Provider-Specific Patterns\n\n")
            f.write(f"### TREX Hashtag Categories\n\n")
            f.write(f"- Categories use hashtag prefixes (`##` or `#`) as **organizational headers**\n")
            f.write(f"- These headers have no `stream_url` (can't be played, define hierarchy only)\n")
            f.write(f"- Actual playable channels reference these headers via their `category` field\n")
            f.write(f"- Examples: `## SPORTS`, `# PPV EVENTS`, `## USA | SPORT`\n")
            f.write(f"- Detection: Strip hashtags from channel.category before keyword matching\n")
            f.write(f"- Analysis only includes channels with `stream_url` (playable content)\n\n")
            
            for category_name, channels in [
                ("Sports", sports_channels),
                ("PPV", ppv_channels),
                ("Events", event_channels)
            ]:
                if channels:
                    f.write(f"## {category_name} Channels\n\n")
                    f.write(f"Found {len(channels)} channels\n\n")
                    
                    # Show category patterns
                    f.write("### Category Patterns\n\n")
                    category_counts = Counter(ch.category for ch in channels)
                    for cat, count in category_counts.most_common(5):
                        f.write(f"- `{cat}`: {count} channels\n")
                    f.write("\n")
                    
                    f.write("### Sample Raw Data\n\n")
                    for i, ch in enumerate(channels[:3], 1):
                        f.write(f"#### Sample {i}: {ch.name}\n\n")
                        f.write(f"- Category: `{ch.category}`\n")
                        f.write(f"- Media Type: `{ch.media_type}`\n")
                        f.write(f"- EPG Channel ID: `{ch.epg_channel_id}`\n\n")
                        if ch.raw_data:
                            f.write("```json\n")
                            f.write(json.dumps(ch.raw_data, indent=2))
                            f.write("\n```\n\n")
        
        print(f"\n✓ Detailed report saved to: {report_path}")
        print(f"\n{'='*80}\n")
    
    finally:
        session.close()


if __name__ == "__main__":
    main()
