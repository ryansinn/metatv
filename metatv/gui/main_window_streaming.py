"""Streaming mixin — stream URL validation, failover, and media-launch methods.

Extracted from MainWindow; mixed in via:
    class MainWindow(_StreamingMixin, QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from loguru import logger
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from metatv.core.channel_name_utils import parse_channel_name as _pcn
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import parse_provider_urls
from metatv.providers.xtream import _DEFAULT_HEADERS


def _looks_like_text(chunk: bytes) -> bool:
    """Return True if a stream response chunk looks like text rather than binary video data.

    MPEG-TS sync byte (0x47) as the first byte is a strong binary signal.
    Otherwise we check the printable-ASCII ratio of the first 256 bytes.
    """
    if not chunk:
        return False
    if chunk[0] == 0x47:   # MPEG-TS sync byte — definitely binary
        return False
    printable = sum(1 for b in chunk[:256] if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D))
    return (printable / min(len(chunk), 256)) > 0.85


class _StreamingMixin:
    """Mixin providing stream URL validation, failover, and player-launch methods."""

    def validate_stream_url(self, url: str, timeout: int = 5) -> tuple[bool, str | None]:
        """Validate a stream URL by reading its first bytes.

        Returns ``(is_valid, error_message)``.  ``error_message`` is set when
        the server delivers a text error (e.g. "This channel is not available")
        instead of binary video data so the caller can surface it to the user.

        HEAD requests are unreliable for IPTV (servers often return 5xx on HEAD
        while serving fine on GET), so we use a streaming GET and read one chunk.
        """
        try:
            logger.debug(f"Validating stream URL: {url}")
            with requests.get(
                url,
                stream=True,
                timeout=(timeout, timeout),
                allow_redirects=True,
                headers=_DEFAULT_HEADERS,
            ) as response:
                if response.status_code >= 400:
                    logger.warning(f"Stream URL returned HTTP {response.status_code}")
                    return False, f"HTTP {response.status_code}"
                chunk = next(response.iter_content(chunk_size=256), None)
                if chunk is None:
                    logger.warning(f"Stream URL returned no data")
                    return False, None
                # Detect text error messages (e.g. "This channel is not available")
                ct = response.headers.get("Content-Type", "").lower()
                is_text_ct = any(t in ct for t in ("text/", "application/json"))
                if is_text_ct or _looks_like_text(chunk):
                    msg = chunk.decode("utf-8", errors="replace").strip()
                    msg = msg.splitlines()[0][:160]   # first line, ≤160 chars
                    logger.warning(f"Stream URL returned text error: {msg!r}")
                    return False, msg or "Stream unavailable"
                logger.debug(f"Stream URL validated: HTTP {response.status_code}, got {len(chunk)} bytes")
                return True, None
        except requests.exceptions.Timeout:
            logger.warning(f"Stream URL validation timeout: {url}")
            return False, None
        except requests.exceptions.ConnectionError:
            logger.warning(f"Stream URL connection failed: {url}")
            return False, None
        except Exception as e:
            logger.warning(f"Stream URL validation error: {e}")
            return False, None

    def validate_and_failover_stream_url(
        self,
        stream_url: str,
        provider_id: str,
        source_id: str,
        media_type: str,
    ) -> tuple[str, str | None]:
        """Validate stream URL and try alternate provider URLs if needed.

        Returns ``(working_url, error_message)``.
        ``working_url`` is empty when all URLs fail; ``error_message`` is the
        server-provided text (e.g. "This channel is not available") or None.
        """
        ok, err_msg = self.validate_stream_url(stream_url)
        if ok:
            return stream_url, None

        logger.warning(f"Primary URL failed validation: {stream_url}")

        # If the primary URL returned a clear text error (e.g. "not available"),
        # skip alternate-URL probing — the error is content-level, not URL-level.
        if err_msg:
            return "", err_msg

        # Extract base URL from stream URL
        parsed = urlparse(stream_url)
        original_base = f"{parsed.scheme}://{parsed.netloc}"

        # Try alternate provider domains
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            provider_db = repos.providers.get_by_id(provider_id)

            if not provider_db:
                logger.error(f"Provider not found: {provider_id}")
                return "", None

            provider_model = repos.providers.to_model(provider_db)
            candidate_bases = [u for u in provider_model.ordered_urls() if u.rstrip('/') != original_base]

            if not candidate_bases:
                logger.warning(f"Provider {provider_db.name} has no alternate URLs configured")
                logger.error("No working alternate URLs found")
                return "", None

            logger.info(f"Trying {len(candidate_bases)} alternate URL(s) for {provider_db.name} (reliability order)")

            raw_urls = parse_provider_urls(provider_db.urls)

            for alt_base in candidate_bases:
                new_stream_url = self.reconstruct_stream_url(stream_url, original_base, alt_base)
                logger.info(f"Trying: {new_stream_url}")

                url_entry = next((u for u in raw_urls if u.get('url', '').rstrip('/') == alt_base), None)
                alt_ok, alt_err = self.validate_stream_url(new_stream_url)
                if alt_ok:
                    logger.info("Alternate URL validated successfully")
                    if url_entry:
                        url_entry['success_count'] = url_entry.get('success_count', 0) + 1
                        url_entry['last_success'] = datetime.now().isoformat()
                        provider_db.urls = raw_urls
                        repos.providers.update(provider_db)
                        session.commit()
                    return new_stream_url, None
                else:
                    if url_entry:
                        url_entry['failure_count'] = url_entry.get('failure_count', 0) + 1
                        url_entry['last_failure'] = datetime.now().isoformat()
                        provider_db.urls = raw_urls
                        repos.providers.update(provider_db)
                        session.commit()
                    if alt_err:
                        return "", alt_err   # content-level error; stop trying

            logger.error("No working alternate URLs found")
            return "", None

        finally:
            session.close()

    def reconstruct_stream_url(self, original_url: str, old_base: str, new_base: str) -> str:
        """Reconstruct stream URL with new base domain

        Args:
            original_url: Original full stream URL
            old_base: Old base URL to replace
            new_base: New base URL

        Returns:
            Reconstructed URL
        """
        # Simple string replacement
        if original_url.startswith(old_base):
            return original_url.replace(old_base, new_base, 1)
        return original_url

    def play_media(self, channel):
        """Play a media item (live stream or movie) in external player"""
        channel_id = channel.id

        # Prevent double-clicks while loading
        if channel_id in self.loading_channels:
            logger.info(f"Channel {channel_id} is already loading, ignoring double-click")
            self.status_bar.showMessage("Already loading this channel...")
            return

        self.loading_channels.add(channel_id)

        # Get a fresh session for playback recording
        session = self.db.get_session()
        try:
            repos = RepositoryFactory(session)
            # Refresh channel object in this session
            channel = repos.channels.get_by_id(channel_id)

            if not channel:
                logger.error(f"Channel not found: {channel_id}")
                self.status_bar.showMessage("Error: Channel not found")
                self.loading_channels.discard(channel_id)
                return

            # Validate stream URL
            if not channel.stream_url:
                logger.error(f"Channel {channel.name} has no stream URL")
                self.status_bar.showMessage(f"Error: No stream URL for {channel.name}")
                return

            # Check if player is available
            if not self.player_manager.is_available():
                logger.error("No media player available")
                self.status_bar.showMessage("Error: No media player found. Please install mpv.")
                return

            # Show loading notification
            notif_id = self.notification_manager.show(
                title="Loading Stream",
                message=f"Buffering {channel.name}...",
                type="info",
                auto_dismiss_ms=5000
            )

            # Launch player
            logger.info(f"=== Playing Channel ===")
            logger.info(f"Name: {channel.name}")
            logger.info(f"Media Type: {channel.media_type}")
            logger.info(f"Stream URL: {channel.stream_url}")
            logger.info(f"Player: {self.player_manager.get_player_name()}")

            # Validate and failover if needed
            final_url, stream_err = self.validate_and_failover_stream_url(
                channel.stream_url,
                channel.provider_id,
                channel.source_id,
                channel.media_type
            )

            if not final_url:
                logger.error(f"All stream URLs failed validation for {channel.name}")
                self.status_bar.showMessage(f"Error: Stream unavailable for {channel.name}")
                detail = stream_err if stream_err else "All URLs failed (possibly geo-blocked)"
                self.notification_manager.dismiss(notif_id)
                _p = _pcn(channel.name)
                _display = _p.bare_name or channel.name
                self.notification_manager.show(
                    title="Stream Unavailable",
                    message=f"{_display}\n{detail}",
                    type="error",
                    dismissible=True,
                    auto_dismiss_seconds=None,
                    actions=[("Copy Error", lambda n=channel.name, u=final_url, d=detail:
                        QApplication.clipboard().setText(f"{n}\nURL: {u}\nError: {d}"))],
                )
                if hasattr(self, "stream_retry_manager"):
                    self.stream_retry_manager.add_failure(
                        channel.id, channel.name, channel.stream_url, detail
                    )
                self.loading_channels.discard(channel_id)
                return

            if final_url != channel.stream_url:
                logger.info(f"Using failover URL: {final_url}")

            self.status_bar.showMessage(f"Loading: {channel.name}...")

            # Play using player manager
            if self.player_manager.play(final_url, channel.name):
                # Record playback in database
                repos.channels.mark_played(channel.id)
                logger.info(f"Recorded playback: {channel.name} (play count: {channel.play_count + 1})")

                # Update UI lists in real-time
                self.load_history()
                self.load_favorites()
                self._refresh_queue_section()

                # Update status after brief delay
                QTimer.singleShot(2000, lambda: self.status_bar.showMessage(f"Playing: {channel.name}"))
            else:
                logger.error(f"Failed to play: {channel.name}")
                self.status_bar.showMessage(f"Error playing: {channel.name}")

            # Remove from loading set after delay
            QTimer.singleShot(3000, lambda: self.loading_channels.discard(channel_id))

        except Exception as e:
            logger.error(f"Error playing channel: {e}")
            self.status_bar.showMessage(f"Error playing channel: {e}")
            self.loading_channels.discard(channel_id)
        finally:
            session.close()

    def launch_new_mpv(self, url: str):
        """Launch a new mpv instance"""
        cmd = ["mpv"] + self.config.mpv_extra_args + [url]
        logger.info(f"Launching new mpv: {' '.join(cmd)}")
        # Use DEVNULL to prevent pipe buffer from filling and blocking
        process = subprocess.Popen(cmd,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        logger.info(f"mpv process started with PID: {process.pid}")

    def ensure_single_mpv_running(self):
        """Ensure single mpv instance is running with IPC"""
        # Check if mpv is already running
        if self.mpv_process and self.mpv_process.poll() is None:
            logger.info("Single mpv instance already running")
            return True

        # Clean up old socket
        if os.path.exists(self.mpv_socket):
            try:
                os.remove(self.mpv_socket)
            except Exception as e:
                logger.warning(f"Could not remove old socket: {e}")

        # Start mpv with IPC and idle mode
        cmd = [
            "mpv",
            "--idle",
            "--force-window",
            f"--input-ipc-server={self.mpv_socket}",
            "--title=MetaTV Player"
        ] + self.config.mpv_extra_args

        try:
            self.mpv_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"Started single mpv instance with PID {self.mpv_process.pid}")

            # Wait a moment for socket to be created
            for i in range(10):
                if os.path.exists(self.mpv_socket):
                    logger.info(f"mpv IPC socket ready: {self.mpv_socket}")
                    return True
                time.sleep(0.1)

            logger.warning("mpv socket not created in time")
            return False
        except Exception as e:
            logger.error(f"Failed to start single mpv instance: {e}")
            return False

    def play_in_single_mpv(self, url: str, title: str) -> bool:
        """Send URL to single mpv instance via IPC"""
        # Ensure mpv is running
        if not self.ensure_single_mpv_running():
            return False

        # Check socket exists
        if not os.path.exists(self.mpv_socket):
            logger.warning(f"mpv socket not found: {self.mpv_socket}")
            return False

        try:
            # Connect to mpv IPC socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.mpv_socket)

            # Send loadfile command
            command = {
                "command": ["loadfile", url, "replace"]
            }
            sock.send((json.dumps(command) + "\n").encode('utf-8'))

            # Optional: Set media title
            title_command = {
                "command": ["set_property", "media-title", title]
            }
            sock.send((json.dumps(title_command) + "\n").encode('utf-8'))

            sock.close()
            logger.info(f"Sent URL to single mpv instance: {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to communicate with mpv: {e}")
            return False
