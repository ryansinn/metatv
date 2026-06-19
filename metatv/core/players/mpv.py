"""MPV player plugin implementation"""

import subprocess
import json
import socket
import os
import shutil
from typing import Optional
from loguru import logger

from metatv.core.players.base import PlayerPlugin, QueueMode
from metatv.core.config import Config
from metatv.core.http_headers import stream_user_agent

# Always-on reconnect for transient live-stream drops. These three options have
# been stable across ffmpeg/libavformat for many years and are intentionally
# conservative (no --hls-use-mpegts or newer opts that vary by build).
RECONNECT_FLAG = "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=30"


class MPVPlayer(PlayerPlugin):
    """MPV media player implementation with single-instance IPC support"""
    
    def __init__(self, config: Config):
        """Initialize MPV player
        
        Args:
            config: Application configuration
        """
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.socket_path = config.mpv_socket_path
        self.single_instance = (config.player_mode == "single-instance")
        # Monotonically increasing IPC request id for property queries. Replies are
        # matched by this id so interleaved event lines on the socket are skipped.
        self._request_id = 100
    
    @property
    def name(self) -> str:
        """Player name"""
        return "mpv"
    
    def is_available(self) -> bool:
        """Check if mpv is available on system"""
        return shutil.which("mpv") is not None
    
    def is_running(self) -> bool:
        """Check if mpv process is currently running"""
        if self.process is None:
            return False
        return self.process.poll() is None

    @staticmethod
    def _buffer_profile_args(profile: str) -> list[str]:
        """Return mpv buffer flags for the given profile name.

        Args:
            profile: One of ``"reconnect_only"``, ``"modest"``, or ``"large"``.
                     Any unknown value is treated as ``"modest"`` (safe default).

        Returns:
            List of mpv argument strings for the requested buffer profile.
        """
        if profile == "reconnect_only":
            return []
        if profile == "large":
            return ["--cache=yes", "--cache-secs=30", "--demuxer-readahead-secs=30"]
        # "modest" is the default; unknown values fall back here rather than crashing.
        return ["--cache=yes", "--cache-secs=10", "--demuxer-readahead-secs=20"]

    def _compose_extra_args(self) -> list[str]:
        """Build the effective extra mpv args.

        Always prepends the canonical User-Agent and the always-on reconnect flag
        so transient live-stream drops self-heal. The reconnect flag uses three
        conservative, long-stable ffmpeg/libavformat options.

        Buffer flags are determined as follows:
        - If ``config.default_cache_size`` is an explicit, valid size (e.g. ``"100M"``),
          the legacy explicit-cache path is used: ``--cache=yes``,
          ``--demuxer-max-bytes=<N>iB``, ``--demuxer-readahead-secs=30``.  This is
          the power-user override and is unchanged by the profile setting.
        - Otherwise (``"auto"``, empty, or an unrecognized size), buffer flags are
          derived from ``config.buffer_profile`` via :meth:`_buffer_profile_args`.

        User args (``config.mpv_extra_args``) are appended LAST so they win via
        mpv's last-value rule — including any user-supplied ``--user-agent`` or
        cache overrides applied by the Diagnose feature.

        Returns:
            The composed list of extra args to pass on the mpv command line.
        """
        size = self.config.default_cache_size
        user_args = list(self.config.mpv_extra_args)

        # Canonical User-Agent must come first; user's own --user-agent in user_args
        # appears later and wins (mpv honours the last value).
        base_args = [f"--user-agent={stream_user_agent()}", RECONNECT_FLAG]

        byte_size = self._to_mpv_bytesize(size) if (size and size != "auto") else None

        if byte_size is not None:
            # Power-user explicit size: preserve the existing demuxer-max-bytes path.
            buffer_args = [
                "--cache=yes",
                f"--demuxer-max-bytes={byte_size}",
                "--demuxer-readahead-secs=30",
            ]
        else:
            # Auto / empty / unrecognized: use the profile-driven buffer flags.
            buffer_args = self._buffer_profile_args(self.config.buffer_profile)

        return base_args + buffer_args + user_args

    @staticmethod
    def _to_mpv_bytesize(size: str) -> Optional[str]:
        """Convert a config cache size (e.g. ``"50M"``) to an mpv ``<bytesize>``.

        mpv's ``--demuxer-max-bytes`` accepts binary suffixes (``KiB``/``MiB``/
        ``GiB``). The config stores plain decimal-style suffixes (``"50M"``), so a
        trailing ``K``/``M``/``G`` is stripped and re-added as the matching binary
        unit; a bare number defaults to ``MiB``.

        Args:
            size: Configured cache size string (e.g. ``"50M"``, ``"250M"``).

        Returns:
            An mpv-accepted bytesize string (e.g. ``"50MiB"``), or ``None`` if the
            value cannot be parsed.
        """
        unit_map = {"K": "KiB", "M": "MiB", "G": "GiB"}
        raw = size.strip()
        if not raw:
            return None

        suffix = raw[-1].upper()
        if suffix in unit_map:
            number = raw[:-1].strip()
            unit = unit_map[suffix]
        else:
            number = raw
            unit = "MiB"

        if not number.isdigit():
            return None

        return f"{number}{unit}"
    
    def _ensure_single_instance_running(self) -> bool:
        """Ensure single mpv instance is running with IPC socket
        
        Returns:
            True if instance is ready, False otherwise
        """
        if not self.single_instance:
            return False
        
        # Check if already running
        if self.is_running():
            return True
        
        # Remove stale socket
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
                logger.info(f"Removed stale socket: {self.socket_path}")
            except Exception as e:
                logger.warning(f"Could not remove stale socket: {e}")
        
        # Start mpv with IPC socket
        try:
            cmd = [
                "mpv",
                f"--input-ipc-server={self.socket_path}",
                "--force-window=yes",  # Show window immediately
                "--keep-open=no"  # Don't pause at end of video
            ]
            
            # Configure idle behavior (whether to quit when playlist is empty)
            if self.config.close_player_when_finished:
                # Quit after video finishes (will restart quickly on next play)
                cmd.append("--idle=once")
            else:
                # Keep window open for next video (instant channel switching)
                cmd.append("--idle=yes")
            
            cmd += self._compose_extra_args()

            logger.info(f"Starting single mpv instance: {' '.join(cmd)}")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            logger.info(f"Started single mpv instance with PID {self.process.pid}")
            
            # Wait briefly for socket to be created
            import time
            for _ in range(10):  # Wait up to 1 second
                if os.path.exists(self.socket_path):
                    logger.info(f"Socket ready: {self.socket_path}")
                    return True
                time.sleep(0.1)
            
            logger.warning("Socket not created within timeout")
            return False
            
        except Exception as e:
            logger.error(f"Failed to start single mpv instance: {e}")
            return False
    
    def _send_ipc_command(self, command: dict) -> bool:
        """Send IPC command to mpv socket
        
        Args:
            command: JSON command dict
            
        Returns:
            True if successful, False otherwise
        """
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(self.socket_path)
            
            command_json = json.dumps(command) + "\n"
            sock.sendall(command_json.encode('utf-8'))
            
            # Read response
            response = sock.recv(4096).decode('utf-8')
            sock.close()
            
            logger.debug(f"IPC command sent: {command}, response: {response}")
            return True
            
        except FileNotFoundError:
            logger.error(f"Socket not found: {self.socket_path}")
            return False
        except socket.timeout:
            logger.warning("IPC command timed out")
            return False
        except Exception as e:
            logger.error(f"IPC command failed: {e}")
            return False
    
    def get_property(self, name: str) -> object | None:
        """Query a single mpv property via IPC.

        Returns the value, or None on any failure / unavailable property. Skips
        interleaved event lines (which have no ``request_id``) and matches the
        reply by the ``request_id`` that was sent. Never raises.

        Args:
            name: mpv property name (e.g. ``"demuxer-cache-duration"``).

        Returns:
            The property value, or None if unavailable / on any error.
        """
        self._request_id += 1
        rid = self._request_id
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(self.socket_path)

            command = {"command": ["get_property", name], "request_id": rid}
            sock.sendall((json.dumps(command) + "\n").encode("utf-8"))

            # mpv sends newline-delimited JSON. The reply for our request can be
            # preceded by asynchronous event lines (no request_id) — accumulate
            # bytes, parse complete lines, and only act on the matching reply.
            buffer = ""
            try:
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break  # socket closed before a matching reply
                    buffer += data.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(msg, dict) or "request_id" not in msg:
                            continue  # event line — skip
                        if msg.get("request_id") != rid:
                            continue  # reply to some other request — skip
                        if msg.get("error") == "success":
                            return msg.get("data")
                        return None
            finally:
                sock.close()
            return None
        except FileNotFoundError:
            logger.debug(f"get_property: socket not found: {self.socket_path}")
            return None
        except socket.timeout:
            logger.debug(f"get_property: timed out reading {name!r}")
            return None
        except Exception as e:
            logger.debug(f"get_property failed for {name!r}: {e}")
            return None

    def get_properties(self, names: list[str]) -> dict:
        """Query several mpv properties.

        One socket round trip per name is fine (cheap unix-socket calls).

        Args:
            names: mpv property names to query.

        Returns:
            ``{name: value-or-None}`` for each requested name.
        """
        return {n: self.get_property(n) for n in names}

    def play(self, url: str, title: str) -> bool:
        """Play a URL

        Args:
            url: Stream URL to play
            title: Title to display

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"MPVPlayer.play: {title}")
        logger.info(f"  URL: {url}")
        logger.info(f"  Mode: {'single-instance' if self.single_instance else 'new-instance'}")
        
        if self.single_instance:
            # Use single instance with IPC
            if not self._ensure_single_instance_running():
                logger.warning("Could not start single instance, falling back to new instance")
                return self._launch_new_instance(url, title)
            
            # Send loadfile command via IPC
            command = {
                "command": ["loadfile", url, "replace"],
                "request_id": 1
            }
            
            if self._send_ipc_command(command):
                # Set media title
                title_command = {
                    "command": ["set_property", "force-media-title", title],
                    "request_id": 2
                }
                self._send_ipc_command(title_command)
                
                logger.info(f"Sent to single mpv instance: {title}")
                return True
            else:
                logger.warning("IPC command failed, falling back to new instance")
                return self._launch_new_instance(url, title)
        else:
            # Launch new instance
            return self._launch_new_instance(url, title)
    
    def queue(self, url: str, title: str, mode: QueueMode = QueueMode.APPEND_PLAY) -> bool:
        """Add URL to playlist queue
        
        Args:
            url: Stream URL to queue
            title: Title to display
            mode: How to add to queue
            
        Returns:
            True if successful, False otherwise
            
        Note:
            mpv's IPC protocol doesn't support setting titles for queued playlist items.
            All queued items will show the currently playing item's title until they
            start playing. To fix this properly, we need to implement the IPC event
            system (Phase 4) to listen for playlist-pos changes and set titles when
            each file starts playing.
        """
        logger.info(f"MPVPlayer.queue: {title} (mode: {mode.value})")
        
        if not self.single_instance:
            logger.warning("Queue mode requires single-instance mode")
            return self.play(url, title)
        
        if not self._ensure_single_instance_running():
            logger.warning("Could not start single instance")
            return False
        
        # Map QueueMode to mpv loadfile flag
        mode_map = {
            QueueMode.REPLACE: "replace",
            QueueMode.APPEND: "append",
            QueueMode.APPEND_PLAY: "append-play",
            QueueMode.INSERT_NEXT: "insert-next"
        }
        
        mpv_mode = mode_map.get(mode, "append-play")
        
        # Send loadfile command with appropriate flag
        # TODO: Set title when file starts playing (requires IPC event monitoring)
        command = {
            "command": ["loadfile", url, mpv_mode],
            "request_id": 1
        }
        
        if self._send_ipc_command(command):
            logger.info(f"Queued to mpv: {title}")
            return True
        else:
            logger.error(f"Failed to queue: {title}")
            return False
    
    def _launch_new_instance(self, url: str, title: str) -> bool:
        """Launch new mpv instance for URL
        
        Args:
            url: Stream URL
            title: Title to display
            
        Returns:
            True if successful, False otherwise
        """
        try:
            cmd = [
                "mpv",
                f"--force-media-title={title}"
            ] + self._compose_extra_args() + [url]
            
            logger.info(f"Launching new mpv instance: {' '.join(cmd[:3])}...")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            logger.info(f"mpv process started with PID: {process.pid}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to launch mpv: {e}")
            return False
    
    def stop(self) -> bool:
        """Stop playback
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("Stopping mpv playback")
        
        if self.single_instance and self.is_running():
            # Send quit command via IPC
            command = {"command": ["quit"], "request_id": 1}
            return self._send_ipc_command(command)
        
        return False
    
    def cleanup(self):
        """Cleanup resources (terminate process, remove socket)"""
        logger.info("Cleaning up MPVPlayer resources")
        
        # Terminate process if running
        if self.is_running():
            logger.info("Terminating mpv process")
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning("mpv did not terminate, killing")
                self.process.kill()
        
        # Remove socket
        if os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
                logger.info(f"Removed socket: {self.socket_path}")
            except Exception as e:
                logger.warning(f"Could not remove socket: {e}")
