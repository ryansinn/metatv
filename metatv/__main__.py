"""Main entry point for MetaTV application"""

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from loguru import logger

from metatv.core.runtime_env import bundle_resource_path
from metatv.core.stream_diagnostics import _redact

from metatv.gui import cursor_affordance
from metatv.gui import theme as _theme
from metatv.gui.main_window import MainWindow
from metatv.core.config import Config
from metatv.core.url_policy import UrlRankingPolicy, set_url_ranking_policy


def setup_logging():
    """Configure application logging"""
    log_dir = Path.home() / ".config" / "metatv" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Redact credentials on EVERY record, before any sink sees it.
    #
    # An Xtream stream URL embeds the subscription's username and password —
    # `{base}/movie/{user}/{pass}/{id}.ext` — and `player_api.php` takes them
    # as `?username=…&password=…`. Seventy-one call sites log a URL. A scan of
    # one developer machine found 26,793 `username=` and 26,761 `password=`
    # occurrences sitting in `~/.config/metatv/logs/` under a seven-day
    # retention, from ordinary use.
    #
    # Fixed HERE rather than at those 71 sites, and the distinction is the
    # whole point: `_redact` already existed and was already imported by
    # `main_window_streaming.py`, which called it at one of its five URL logs.
    # Patching call sites is how you get four out of five — it is the same
    # enumeration failure as the `refresh_theme()` sweep and the hand-listed
    # test stubs. A patcher cannot be forgotten by the next person to write a
    # `logger.info(f"... {url}")`, because they never have to know it exists.
    def _scrub(record):
        record["message"] = _redact(record["message"])

    logger.configure(patcher=_scrub)

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
    # The window and task-switcher icon. There was none until 2026-08-27 —
    # packaging/metatv.spec carried `icon=None, # placeholder omitted for the
    # MVP`, and nothing called setWindowIcon, so every surface fell back to
    # the window manager's generic square.
    _icon = bundle_resource_path("packaging/icon/metatv-256.png")
    if _icon.exists():
        app.setWindowIcon(QIcon(str(_icon)))
    else:
        logger.warning("App icon missing at {} — falling back to the system default", _icon)
    app.setApplicationName("MetaTV")
    app.setOrganizationName("MetaTV")

    # Bundled typefaces (metatv/assets/fonts) — registered before the theme and
    # before any widget, because the type scale sets SIZES and inherits the
    # family from the application font. A face that fails to load is logged and
    # the platform default stands; it must not cost the app its launch.
    from metatv.gui import fonts as _fonts
    _fonts.apply_ui_font(app)

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
