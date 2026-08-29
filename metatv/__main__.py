"""Main entry point for MetaTV application"""

import sys
import os

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
    from metatv.core.log_paths import ACTIVE_LOG_NAME, log_directory

    log_dir = log_directory(create=True)

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

    # DEBUG was hardcoded here, in the shipped app. Two logger.debug calls in
    # the raw-metadata parser fired 650,101 times each and produced 1.30M of
    # 1.44M lines — 330 MB across the retention window, which then held 8 days
    # of noise where it would otherwise hold 76 days of signal. The level is
    # now INFO by default and DEBUG on request, via METATV_LOG_LEVEL, so a
    # support session can turn it up without a rebuild.
    level = os.environ.get("METATV_LOG_LEVEL", "INFO").upper()
    if level not in {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}:
        level = "INFO"
    logger.add(
        log_dir / ACTIVE_LOG_NAME,
        rotation="10 MB",
        retention="7 days",
        level=level,
    )
    # Name the build in the FIRST line, not just the About dialog. Under
    # rolling releases every push ships, so "0.56.0" no longer identifies a
    # build — a pasted log has to say which commit produced it or a report
    # about it cannot be checked out. Owner: "shouldn't the console log state
    # which version of MetaTV is being launched? it's kind of weird to omit
    # that".
    #
    # Reuses the identity the title bar already shows rather than composing a
    # second one, so the window and the log can never disagree about which build
    # is running. window_title() resolves to "MetaTV (branch sha)" in a checkout
    # and "MetaTV 0.56.0+20260829.a3e7a28" in a packaged build, where the stamped
    # id names the exact commit; the version rides alongside because the branch
    # form does not carry it.
    from metatv import __version__
    from metatv.core.build_info import window_title

    logger.info(f"{window_title()} starting — v{__version__}")


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
