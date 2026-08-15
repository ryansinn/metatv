"""Main entry point for MetaTV application"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from loguru import logger

from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui.main_window import MainWindow
from metatv.core.config import Config
from metatv.core.url_policy import UrlRankingPolicy, set_url_ranking_policy


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

    # Resolve the provider-URL ranking knobs ONCE, here, from the loaded config.
    # Provider.ordered_urls() reads the resolved policy rather than a Config —
    # the six busiest cycling call sites live in providers/xtream.py, which has
    # no Config access by design. Without this line the three url_* settings are
    # decorative: everything falls back to defaults and editing config.yaml does
    # nothing.
    set_url_ranking_policy(UrlRankingPolicy.from_config(config))

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("MetaTV")
    app.setOrganizationName("MetaTV")

    # Pointing-hand cursor on hover for clickable controls (single app-level
    # event filter; kept referenced on the app so it isn't garbage-collected).
    app._cursor_affordance_filter = cursor_affordance.install(app)

    # Apply the user's saved theme BEFORE any widget/window is constructed —
    # both the design-token layer (every ``theme.COLOR_*``/semantic constant
    # widgets read while building their stylesheets) and the QPalette floor
    # (metatv/gui/theme.py's qt_palette(), #253) so a cold launch on a
    # non-default theme renders correctly end-to-end, not just after a live
    # Settings round-trip via MainWindow.refresh_theme().
    _theme.apply_theme(config.theme_name)

    # Create and show main window
    window = MainWindow(config, config_recovered=recovered_from_backup)
    window.show()

    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
