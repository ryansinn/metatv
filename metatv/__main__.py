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
    
    # Load configuration
    config = Config.load()
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("MetaTV")
    app.setOrganizationName("MetaTV")
    
    # Create and show main window
    window = MainWindow(config)
    window.show()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
