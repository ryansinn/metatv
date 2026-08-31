"""Downloads: the MainWindow half of saving a VOD for offline watching.

Its own module rather than a few more methods on ``_FavoritesMixin`` because
downloads are not a favourites concern — they share only the fact that both
are reached from the channel menu. Sibling of ``main_window_updates.py`` and
``main_window_history.py``: one mixin per concern, folded into ``MainWindow``.

The transfer itself lives in :mod:`metatv.core.download_manager`, which holds
no Qt at all — this module is the wiring and the two sentences the user reads.
"""

from __future__ import annotations

from loguru import logger

from metatv.core.download_manager import DownloadManager
from metatv.core.models import MediaType
from metatv.core.repositories import RepositoryFactory


class _DownloadsMixin:
    """Construct the download manager and start a download from the menu."""

    def _setup_downloads(self) -> None:
        """Build the manager and give it the accountant the player already uses.

        One accountant, so a download and a play on the same source can never
        both believe they hold that provider's single connection. The preempt
        callback is what makes a click on Play win: the manager parks its
        transfer at the byte it reached and resumes when the slot comes back.
        """
        accountant = self.player_manager.connection_accountant
        self.download_manager = DownloadManager(self.db, self.config, accountant)
        accountant._on_preempt = self.download_manager.on_preempted
        self.download_manager.start()
        self._register_cleanable("downloads", self.download_manager.shutdown)
        logger.debug("Download manager ready")

    def download_channel_by_id(self, channel_id: str) -> None:
        """Queue a VOD for download to the local library.

        Sibling of ``play_channel_deep_cache_by_id`` and gated the same way —
        VOD only. The difference is persistence: the deep cache is a scratch
        file purged when playback stops, this one stays. For a SERIES the
        normal drill-in is used, because a series has no single stream to save.

        The transfer itself is the ``DownloadManager``'s problem, including
        waiting for a free connection slot on this source — the click only
        enqueues, so it never blocks the UI thread on the network.

        Args:
            channel_id: The channel's unique ID string.
        """
        with self.db.session_scope() as session:
            channel = RepositoryFactory(session).channels.get_playable_dto(channel_id)
        if not channel:
            return
        if channel.media_type == MediaType.SERIES:
            self.drill_into_series(channel)
            return

        manager = getattr(self, "download_manager", None)
        if manager is None:
            return
        queued = manager.enqueue(
            channel_id=channel.id,
            provider_id=channel.provider_id,
            channel_name=channel.name,
            source_url=channel.stream_url,
        )
        manager_ui = getattr(self, "notification_manager", None)
        if manager_ui is None:
            return
        if queued:
            manager_ui.show(
                title=f"Downloading {channel.name}",
                message="It pauses by itself while you watch anything on this source.",
                type="info",
                dismissible=True,
            )
        else:
            # Already queued or already saved. Silence would read as a click
            # that did nothing, which is the same complaint as a dead button.
            manager_ui.show(
                title=f"{channel.name} is already in your downloads",
                message="",
                type="info",
                dismissible=True,
            )
