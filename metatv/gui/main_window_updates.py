"""MainWindow mixin — in-app update notifications (assisted download).

Keeps all Qt-GUI interaction for the update flow (NotificationManager banners,
``QDesktopServices`` reveal/open) on the main thread and out of the core
:class:`~metatv.core.update_checker.UpdateChecker` (which stays Qt-widget-free).

Scope: detect a newer version, prompt, and assist the download (drop the
``.dmg`` in ~/Downloads and open it so the user drags the new app into
Applications).  A fully-silent download→swap→relaunch is intentionally NOT here
— it is fragile for unsigned builds and wants notarization first (see the PR /
docs/update-checker note).
"""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from loguru import logger

_RELEASES_PAGE = "https://github.com/ryansinn/metatv/releases/latest"


class _UpdatesMixin:
    """Main-thread slots for the :class:`UpdateChecker` signal surface."""

    # -- automatic / manual "newer version found" -----------------------------

    def _on_update_available(self, info) -> None:
        """Show the non-modal "update available" banner with the three actions."""
        self.notification_manager.show(
            title=f"MetaTV {info.latest} is available",
            message=(
                f"You're on {info.current}. Download the update, "
                f"skip this version, or decide later."
            ),
            type="info",
            dismissible=True,
            actions=[
                ("Download", lambda i=info: self._start_update_download(i)),
                ("Skip this version", lambda i=info: self._skip_update_version(i)),
                ("Later", lambda: None),
            ],
        )

    def _on_update_none(self, info) -> None:
        """Manual check finished with nothing newer (info) or an error (None)."""
        if info is None:
            self.notification_manager.show(
                title="Couldn't check for updates",
                message="No network, or GitHub is unreachable. Try again later.",
                type="warning",
                auto_dismiss_ms=6000,
            )
        else:
            self.notification_manager.show(
                title="You're up to date",
                message=f"MetaTV {info.current} is the latest version.",
                type="success",
                auto_dismiss_ms=5000,
            )

    # -- download / reveal ----------------------------------------------------

    def _start_update_download(self, info) -> None:
        """Begin the assisted download, or open the releases page as fallback."""
        if info.dmg_url:
            self.notification_manager.show(
                title="Downloading update…",
                message="Saving the new MetaTV to your Downloads folder.",
                type="info",
                auto_dismiss_ms=4000,
            )
            self.update_checker.download_update(info)
        else:
            # No packaged .dmg asset on this release — hand off to the browser.
            QDesktopServices.openUrl(QUrl(info.release_url or _RELEASES_PAGE))

    def _on_update_downloaded(self, path: str) -> None:
        """Open the downloaded ``.dmg`` (mounts it on macOS) or report failure."""
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            self.notification_manager.show(
                title="Update downloaded",
                message=f"Saved to {path}. Open it and drag MetaTV into Applications.",
                type="success",
                auto_dismiss_ms=8000,
            )
        else:
            logger.warning("Update download failed; opening releases page")
            self.notification_manager.show(
                title="Download failed",
                message="Could not download the update. Opening the releases page.",
                type="error",
                auto_dismiss_ms=6000,
            )
            QDesktopServices.openUrl(QUrl(_RELEASES_PAGE))

    # -- skip / manual --------------------------------------------------------

    def _skip_update_version(self, info) -> None:
        """Record the skipped version so the auto banner stops for it."""
        self.config.update_skip_version = info.latest
        try:
            self.config.save()
        except Exception as exc:  # pragma: no cover - best-effort persistence
            logger.debug(f"Could not persist update_skip_version: {exc}")
        self.notification_manager.show(
            title=f"Skipping {info.latest}",
            message="You won't be notified about this version again.",
            type="info",
            auto_dismiss_ms=5000,
        )

    def _manual_update_check(self) -> None:
        """Run a manual check (bypasses the enable/throttle/skip gates)."""
        self.notification_manager.show(
            title="Checking for updates…",
            type="info",
            auto_dismiss_ms=3000,
        )
        self.update_checker.check_async(manual=True)
