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


# ISO-BMFF (MP4/MOV) top-level box types that legitimately appear at the very start of
# a stream. `ftyp`/`moov` lead a faststart (web-optimised) file; the box type lives at
# bytes 4–8, after the 4-byte size field.
_ISO_BMFF_BOXES = frozenset(
    (b"ftyp", b"styp", b"moov", b"moof", b"mdat", b"free", b"skip", b"wide", b"pnot")
)


def _looks_like_video(chunk: bytes) -> bool:
    """Return True if a chunk begins with a known video-container magic number.

    This must take precedence over the printable-ASCII heuristic: a faststart MP4
    (``ftyp``/``moov`` first) and a Matroska/WebM header are dominated by ASCII box/
    element names (`ftyp`, `isom`, `avc1`, `matroska`, …), so `_looks_like_text` would
    false-positive and the validator would reject perfectly good VOD as a text error.
    """
    if not chunk:
        return False
    if chunk[0] == 0x47:                          # MPEG-TS sync byte
        return True
    if chunk[:4] == b"\x1a\x45\xdf\xa3":          # EBML — Matroska / WebM
        return True
    if len(chunk) >= 8 and chunk[4:8] in _ISO_BMFF_BOXES:  # ISO-BMFF — MP4 / MOV
        return True
    if chunk[:3] == b"\x00\x00\x01":              # MPEG PS/ES start code
        return True
    if chunk[:3] == b"FLV":                       # Flash Video
        return True
    return False


def _looks_like_text(chunk: bytes) -> bool:
    """Return True if a stream response chunk looks like text rather than binary video data.

    MPEG-TS sync byte (0x47) as the first byte is a strong binary signal.
    Otherwise we check the printable-ASCII ratio of the first 256 bytes.

    Note: callers must check :func:`_looks_like_video` first — some binary containers
    (faststart MP4, Matroska) are ASCII-heavy in their first bytes and would trip this.
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
                # A recognised video container wins outright — even if its ASCII-heavy
                # header (faststart MP4, Matroska) would otherwise look like text, and
                # even if the server mislabels the Content-Type.
                if _looks_like_video(chunk):
                    logger.debug(f"Stream URL validated: HTTP {response.status_code}, "
                                 f"video container, got {len(chunk)} bytes")
                    return True, None
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

        # Try alternate provider domains.
        # Per-attempt session.commit() calls are intentional: each stat write
        # (success_count / failure_count) must persist even if a later attempt
        # raises an exception.  session_scope() commits on clean exit and rolls
        # back only the post-last-commit transaction on exception, so earlier
        # explicit commits remain durable.
        with self.db.session_scope() as session:
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
        """Play a media item (live stream or movie) in external player.

        Returns immediately — validation and failover happen in a background
        thread via ``self.executor``; ``_on_stream_ready`` (main-thread slot)
        finishes the launch once the result arrives.
        """
        channel_id = channel.id

        # Prevent double-clicks while loading
        if channel_id in self.loading_channels:
            logger.info(f"Channel {channel_id} is already loading, ignoring double-click")
            self.status_bar.showMessage("Already loading this channel...")
            return

        self.loading_channels.add(channel_id)

        # Guard: stream URL and player availability are known from the channel
        # object already in memory — no DB or network needed here.
        if not channel.stream_url:
            logger.error(f"Channel {channel.name} has no stream URL")
            self.status_bar.showMessage(f"Error: No stream URL for {channel.name}")
            self.loading_channels.discard(channel_id)
            return

        if not self.player_manager.is_available():
            logger.error("No media player available")
            self.status_bar.showMessage("Error: No media player found. Please install mpv.")
            self.loading_channels.discard(channel_id)
            return

        # Show loading notification (must be main thread — creates QTimer)
        notif_id = self.notification_manager.show(
            title="Loading Stream",
            message=f"Buffering {channel.name}...",
            type="info",
            auto_dismiss_ms=5000
        )

        logger.info("=== Playing Channel ===")
        logger.info(f"Name: {channel.name}")
        logger.info(f"Media Type: {channel.media_type}")
        logger.info(f"Stream URL: {channel.stream_url}")
        logger.info(f"Player: {self.player_manager.get_player_name()}")

        # Off-load network validation + failover to the shared executor.
        # _on_stream_ready (connected in MainWindow.__init__) fires on the main thread.
        self.executor.submit(
            self._bg_validate_and_play,
            channel_id,
            channel.name,
            channel.stream_url,
            channel.provider_id,
            notif_id,
        )

    def _bg_validate_and_play(
        self,
        channel_id: str,
        channel_name: str,
        stream_url: str,
        provider_id: str,
        notif_id: str,
    ) -> None:
        """Worker: validate + failover stream URL, then emit _stream_ready.

        Runs in ``self.executor``.  Must NOT touch Qt widgets — all UI work is
        done in ``_on_stream_ready``, which runs on the main thread via the signal.
        """
        try:
            final_url, stream_err = self.validate_and_failover_stream_url(
                stream_url, provider_id
            )
            self._stream_ready.emit({
                "ok": bool(final_url),
                "channel_id": channel_id,
                "channel_name": channel_name,
                "original_url": stream_url,
                "final_url": final_url or "",
                "stream_err": stream_err or "",
                "notif_id": notif_id,
            })
        except Exception as e:
            logger.error(f"Error in _bg_validate_and_play: {e}")
            self._stream_ready.emit({
                "ok": False,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "original_url": stream_url,
                "final_url": "",
                "stream_err": str(e),
                "notif_id": notif_id,
            })

    def _on_stream_ready(self, data: dict) -> None:
        """Main-thread slot: finish player launch or show error after validation."""
        channel_id = data["channel_id"]
        channel_name = data.get("channel_name", "")
        final_url = data.get("final_url", "")
        original_url = data.get("original_url", "")
        stream_err = data.get("stream_err", "")
        notif_id = data.get("notif_id", "")

        if not data.get("ok"):
            logger.error(f"All stream URLs failed validation for {channel_name}")
            self.status_bar.showMessage(f"Error: Stream unavailable for {channel_name}")
            detail = stream_err or "All URLs failed (possibly geo-blocked)"
            self.notification_manager.dismiss(notif_id)
            _p = _pcn(channel_name)
            _display = _p.bare_name or channel_name
            self.notification_manager.show(
                title="Stream Unavailable",
                message=f"{_display}\n{detail}",
                type="error",
                dismissible=True,
                auto_dismiss_seconds=None,
                actions=[("Copy Error", lambda n=channel_name, u=original_url, d=detail:
                    QApplication.clipboard().setText(f"{n}\nURL: {u}\nError: {d}"))],
            )
            if hasattr(self, "stream_retry_manager"):
                self.stream_retry_manager.add_failure(
                    channel_id, channel_name, original_url, detail
                )
            self.loading_channels.discard(channel_id)
            return

        if final_url != original_url:
            logger.info(f"Using failover URL: {final_url}")

        self.status_bar.showMessage(f"Loading: {channel_name}...")

        if self.player_manager.play(final_url, channel_name):
            # Record playback — mark_played is a DB write; run off-thread
            self.executor.submit(self._bg_mark_played, channel_id)

            # Update UI lists in real-time (main thread)
            self.load_history()
            self.load_favorites()
            self._refresh_queue_section()

            QTimer.singleShot(2000, lambda: self.status_bar.showMessage(f"Playing: {channel_name}"))
        else:
            logger.error(f"Failed to play: {channel_name}")
            self.status_bar.showMessage(f"Error playing: {channel_name}")

        QTimer.singleShot(3000, lambda: self.loading_channels.discard(channel_id))

    def _bg_mark_played(self, channel_id: str) -> None:
        """Worker: write play-count + last-played to DB (off main thread)."""
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                repos.channels.mark_played(channel_id)
        except Exception as e:
            logger.error(f"Error marking channel played: {e}")

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
