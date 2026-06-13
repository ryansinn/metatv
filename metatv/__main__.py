"""Main entry point for MetaTV application"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from loguru import logger

from metatv.gui.main_window import MainWindow
from metatv.core.config import Config


def setup_logging():
    """Configure application logging"""
    log_dir = Path.home() / ".config" / "metatv" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        log_dir / "metatv.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG"
    )
    logger.info("MetaTV starting...")


def main():
    """Main application entry point"""
    setup_logging()

    # Load configuration (returns tuple: config, recovered_from_backup)
    config, recovered_from_backup = Config.load()

    # Save config to create .yaml file and backup on first startup
    try:
        config.save()
    except Exception as e:
        logger.error(f"Failed to save config on startup: {e}")

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("MetaTV")
    app.setOrganizationName("MetaTV")

    # Create and show main window
    window = MainWindow(config, config_recovered=recovered_from_backup)
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
