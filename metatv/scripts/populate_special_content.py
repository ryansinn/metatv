"""Populate special content categorization for channels

This script analyzes channels and categorizes them into special views:
- PPV (Pay-Per-View events with dates)
- Live Events ([EVENT] or [LIVE-EVENT] tags)
- Sports (sports-related channels)

Usage:
    # Dry-run to see what would be updated
    python -m metatv.scripts.populate_special_content --dry-run
    
    # Update all channels
    python -m metatv.scripts.populate_special_content
    
    # Update only channels from specific provider
    python -m metatv.scripts.populate_special_content --provider "provider_id"
    
    # Force re-categorization of already categorized channels
    python -m metatv.scripts.populate_special_content --force
    
    # Show detailed progress
    python -m metatv.scripts.populate_special_content --verbose

Future expansions:
    - Auto-run on provider refresh
    - Incremental updates (only new/changed channels)
    - Parse sport leagues and teams
    - Parse event dates for live events
    - Clean up expired PPV events
"""

import argparse
from pathlib import Path
from loguru import logger

from metatv.core.config import Config
from metatv.core.database import Database, ChannelDB
from metatv.core.special_content import update_channel_special_content


def populate_special_content(
    config: Config,
    provider_id: str = None,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False
):
    """Populate special content categorization for channels
    
    Args:
        config: Application configuration
        provider_id: Only process channels from this provider (None = all)
        force: Re-categorize already categorized channels
        dry_run: Show what would be updated without making changes
        verbose: Show detailed progress per channel
    """
    
    db = Database(config.database_url)
    session = db.get_session()
    
    try:
        # Query channels
        query = session.query(ChannelDB)
        
        if provider_id:
            query = query.filter(ChannelDB.provider_id == provider_id)
            logger.info(f"Processing channels from provider: {provider_id}")
        else:
            logger.info("Processing all channels")
        
        if not force:
            # Only process uncategorized channels (special_view is NULL)
            query = query.filter(ChannelDB.special_view.is_(None))
            logger.info("Skipping already categorized channels (use --force to re-categorize)")
        else:
            logger.info("Force mode: Re-categorizing all channels")
        
        channels = query.all()
        total = len(channels)
        
        logger.info(f"Found {total:,} channels to process")
        
        if total == 0:
            logger.info("No channels to process")
            return
        
        # Track statistics
        stats = {
            'ppv': 0,
            'live_event': 0,
            'sports': 0,
            'uncategorized': 0,
        }
        
        updated = 0
        
        for i, channel in enumerate(channels, 1):
            # Show progress every 1000 channels
            if i % 1000 == 0 or verbose:
                logger.info(f"Progress: {i:,}/{total:,} ({i*100//total}%)")
            
            # Categorize channel
            was_updated = update_channel_special_content(channel)
            
            if was_updated:
                updated += 1
                category = channel.special_view
                if category:
                    stats[category] = stats.get(category, 0) + 1
                    if verbose:
                        logger.debug(f"  [{category}] {channel.name}")
                else:
                    stats['uncategorized'] += 1
        
        # Display summary
        logger.info(f"\n{'='*60}")
        logger.info("CATEGORIZATION SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Total processed: {total:,}")
        logger.info(f"Updated: {updated:,}")
        logger.info(f"")
        logger.info(f"Categories:")
        logger.info(f"  💰 PPV:         {stats['ppv']:>6,} channels")
        logger.info(f"  🎪 Live Events: {stats['live_event']:>6,} channels")
        logger.info(f"  ⚽ Sports:       {stats['sports']:>6,} channels")
        logger.info(f"  ❓ Other:        {stats['uncategorized']:>6,} channels")
        logger.info(f"{'='*60}")
        
        if dry_run:
            logger.info("DRY RUN: No changes committed to database")
            session.rollback()
        else:
            session.commit()
            logger.success(f"✅ Committed {updated:,} channel updates to database")
        
    except Exception as e:
        logger.error(f"❌ Error during categorization: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        raise
    finally:
        session.close()


def main():
    """Command-line entry point"""
    parser = argparse.ArgumentParser(
        description="Populate special content categorization for channels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run to preview changes
  python -m metatv.scripts.populate_special_content --dry-run
  
  # Update all channels
  python -m metatv.scripts.populate_special_content
  
  # Update specific provider
  python -m metatv.scripts.populate_special_content --provider "provider_id"
  
  # Force re-categorize all channels
  python -m metatv.scripts.populate_special_content --force
  
  # Show detailed per-channel progress
  python -m metatv.scripts.populate_special_content --verbose
        """
    )
    
    parser.add_argument(
        '--provider',
        type=str,
        help='Only process channels from this provider ID'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Re-categorize already categorized channels'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed progress per channel'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logger.remove()
        logger.add(lambda msg: print(msg, end=''), level="DEBUG")
    
    # Load configuration
    config = Config.load()
    logger.info(f"Loaded config. Database: {config.database_url}")
    
    # Run categorization
    populate_special_content(
        config=config,
        provider_id=args.provider,
        force=args.force,
        dry_run=args.dry_run,
        verbose=args.verbose
    )


if __name__ == "__main__":
    main()
