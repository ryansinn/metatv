"""MPV player plugin implementation"""

import subprocess
import json
import socket
import os
import re
import shutil
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from metatv.core.players.base import PlayerPlugin, QueueMode
from metatv.core.config import Config
from metatv.core.http_headers import stream_user_agent

# Always-on reconnect for transient live-stream drops. These three options have
# been stable across ffmpeg/libavformat for many years and are intentionally
# conservative (no --hls-use-mpegts or newer opts that vary by build).
RECONNECT_FLAG = "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=30"

# Constant instance key used when split_streams_by_source is False.
_SHARED_KEY = "__shared__"


@dataclass
class _Inst:
    """State for a single managed mpv process."""

    process: Optional[subprocess.Popen] = None
    socket_path: str = ""

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class MPVPlayer(PlayerPlugin):
    """MPV media player implementation with per-key instance registry.

    In single-instance (default) mode each *instance key* maps to one
    persistent mpv window.  The key is resolved by the caller:
    - ``"__shared__"`` → the one legacy window (``config.mpv_socket_path``)
    - a provider-id string → a separate window with a derived socket path

    In multiple-instances mode every ``play()`` call always spawns a new
    process (no IPC; the registry / keying does not apply).
    """

    def __init__(self, config: Config):
        """Initialize MPV player.

        Args:
            config: Application configuration.
        """
        self.config = config
        self.single_instance = (config.player_mode == "single-instance")
        # Registry: instance_key → _Inst
        self._instances: dict[str, _Inst] = {}
        # Most recently used key (for default-key fallback in property queries).
        self._last_key: str | None = None
        # Monotonically increasing IPC request id for property queries.
        self._request_id = 100

    # ── Public helpers ───────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        """Player name."""
        return "mpv"

    def is_available(self) -> bool:
        """Check if mpv is available on system."""
        return shutil.which("mpv") is not None

    def active_keys(self) -> list[str]:
        """Return keys whose mpv process is currently alive."""
        return [k for k, inst in self._instances.items() if inst.is_running()]

    # ── Socket-path helpers ─────────────────────────────────────────────────

    def _socket_path_for(self, key: str) -> str:
        """Return the IPC socket path for *key*.

        ``"__shared__"`` → ``config.mpv_socket_path`` (exact legacy value).
        Any other key → base path + ``"-"`` + first-8-hex of MD5(key), which
        is filesystem-safe and stable across restarts.

        This method is pure and unit-testable without launching mpv.

        Args:
            key: Instance key string.

        Returns:
            Absolute path to the IPC socket for this key.
        """
        base = self.config.mpv_socket_path
        if key == _SHARED_KEY:
            return base
        suffix = hashlib.md5(key.encode()).hexdigest()[:8]
        # Ensure the suffix contains only safe filesystem characters (it's
        # hex from MD5 so already [0-9a-f], but be explicit).
        suffix = re.sub(r"[^A-Za-z0-9_-]", "_", suffix)
        return f"{base}-{suffix}"

    # ── Instance lifecycle ──────────────────────────────────────────────────

    def _ensure_instance_running(self, key: str) -> bool:
        """Ensure the mpv instance for *key* is alive with its IPC socket.

        If it is already running, returns True immediately.
        Otherwise launches a new process bound to the key's socket path.

        Args:
            key: Instance key.

        Returns:
            True if the instance is (now) ready, False on launch failure.
        """
        if not self.single_instance:
            return False

        inst = self._instances.get(key)
        if inst is not None and inst.is_running():
            return True

        sock_path = self._socket_path_for(key)

        # Remove stale socket file.
        if os.path.exists(sock_path):
            try:
                os.remove(sock_path)
                logger.info(f"Removed stale socket: {sock_path}")
            except Exception as e:
                logger.warning(f"Could not remove stale socket: {e}")

        try:
            cmd = [
                "mpv",
                f"--input-ipc-server={sock_path}",
                "--force-window=yes",
                "--keep-open=no",
            ]

            if self.config.close_player_when_finished:
                cmd.append("--idle=once")
            else:
                cmd.append("--idle=yes")

            cmd += self._compose_extra_args()

            logger.info(f"Starting mpv instance [{key}]: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            logger.info(f"Started mpv instance [{key}] PID {process.pid}")

            # Wait briefly for socket to appear.
            import time
            for _ in range(10):
                if os.path.exists(sock_path):
                    logger.info(f"Socket ready: {sock_path}")
                    self._instances[key] = _Inst(process=process, socket_path=sock_path)
                    return True
                time.sleep(0.1)

            logger.warning(f"Socket not created within timeout for key [{key}]")
            self._instances[key] = _Inst(process=process, socket_path=sock_path)
            return False

        except Exception as e:
            logger.error(f"Failed to start mpv instance [{key}]: {e}")
            return False

    # ── IPC ─────────────────────────────────────────────────────────────────

    def _send_ipc_command(self, command: dict, key: str) -> bool:
        """Send IPC command to the socket for *key*.

        Args:
            command: JSON command dict.
            key: Instance key whose socket to target.

        Returns:
            True if the command was delivered, False on any error.
        """
        inst = self._instances.get(key)
        if inst is None:
            logger.error(f"No instance for key [{key}]")
            return False
        sock_path = inst.socket_path
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(sock_path)

            command_json = json.dumps(command) + "\n"
            sock.sendall(command_json.encode("utf-8"))

            response = sock.recv(4096).decode("utf-8")
            sock.close()

            logger.debug(f"IPC [{key}] sent: {command}, response: {response}")
            return True

        except FileNotFoundError:
            logger.error(f"Socket not found [{key}]: {sock_path}")
            return False
        except socket.timeout:
            logger.warning(f"IPC command timed out [{key}]")
            return False
        except Exception as e:
            logger.error(f"IPC command failed [{key}]: {e}")
            return False

    # ── Property queries ─────────────────────────────────────────────────────

    def _resolve_key(self, key: str | None) -> str | None:
        """Resolve *key* to a concrete key.

        Resolution order:
        1. ``key`` if explicitly provided (not None).
        2. ``_last_key`` if any play() has been called.
        3. ``_SHARED_KEY`` in single-instance mode (so property queries work
           before the first play() call, matching the old ``self.socket_path``
           behavior).
        4. None (caller should treat this as "no instance, return None").
        """
        if key is not None:
            return key
        if self._last_key is not None:
            return self._last_key
        if self.single_instance:
            return _SHARED_KEY
        return None

    def get_property(self, name: str, key: str | None = None) -> object | None:
        """Query a single mpv property via IPC.

        Args:
            name: mpv property name (e.g. ``"demuxer-cache-duration"``).
            key: Instance key to query; defaults to the most-recently-used key.

        Returns:
            The property value, or None if unavailable / on any error.
        """
        resolved = self._resolve_key(key)
        if resolved is None:
            return None
        inst = self._instances.get(resolved)
        # If no instance is in the registry yet (e.g. property query before
        # first play), derive the socket path from config so IPC still works
        # when the socket happens to exist (the old single self.socket_path
        # behavior was equivalent to always having the shared path available).
        sock_path = inst.socket_path if inst is not None else self._socket_path_for(resolved)

        self._request_id += 1
        rid = self._request_id
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(sock_path)

            command = {"command": ["get_property", name], "request_id": rid}
            sock.sendall((json.dumps(command) + "\n").encode("utf-8"))

            buffer = ""
            try:
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
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
                            continue
                        if msg.get("request_id") != rid:
                            continue
                        if msg.get("error") == "success":
                            return msg.get("data")
                        return None
            finally:
                sock.close()
            return None
        except FileNotFoundError:
            logger.debug(f"get_property: socket not found [{resolved}]: {sock_path}")
            return None
        except socket.timeout:
            logger.debug(f"get_property: timed out reading {name!r} [{resolved}]")
            return None
        except Exception as e:
            logger.debug(f"get_property failed for {name!r} [{resolved}]: {e}")
            return None

    def get_properties(self, names: list[str], key: str | None = None) -> dict:
        """Query several mpv properties.

        Args:
            names: mpv property names to query.
            key: Instance key to query; defaults to the most-recently-used key.

        Returns:
            ``{name: value-or-None}`` for each requested name.
        """
        resolved = self._resolve_key(key)
        return {n: self.get_property(n, key=resolved) for n in names}

    # ── Playback ─────────────────────────────────────────────────────────────

    def play(
        self,
        url: str,
        title: str,
        instance_key: str = _SHARED_KEY,
        start_seconds: int = 0,
        open_ended_buffer: bool = False,
    ) -> bool:
        """Play *url* in the instance identified by *instance_key*.

        In single-instance mode:
        - If the instance for *instance_key* is not running, launch it.
        - Send ``loadfile … replace`` over its IPC socket, with a per-file
          ``start=`` option when *start_seconds* > 0 so mpv begins at the
          saved resume position (no seek-after-load race).
        - Fall back to a new standalone process if IPC fails.

        When *open_ended_buffer* is True, a standalone process is always
        launched with the open-ended disk-backed cache args (see
        ``_open_ended_buffer_args``), regardless of ``single_instance`` mode.
        This is a per-play variant — the normal ``play_media`` path and the
        configured buffer profile are unchanged.

        In multiple-instances mode *instance_key* is ignored; every call
        launches an independent new mpv process (legacy behavior unchanged).

        Args:
            url: Stream URL to play.
            title: Title to display.
            instance_key: Registry key for the target window
                (default ``"__shared__"``).
            start_seconds: Resume position in seconds.  When > 0 the
                ``loadfile`` command embeds ``start=<N>`` as a per-file
                option so mpv begins playback at that offset.  0 means
                start from the beginning (no option injected).
            open_ended_buffer: When True, launch a fresh process with large
                disk-backed cache args instead of the configured profile.
                The existing IPC instance (if any) is NOT reused — buffer
                config is set at process launch time and cannot be patched
                over IPC per-file.

        Returns:
            True if the stream was handed off to mpv, False on failure.
        """
        logger.info(f"MPVPlayer.play: {title} [key={instance_key}]")
        logger.info(f"  URL: {url}")
        logger.info(f"  Mode: {'single-instance' if self.single_instance else 'new-instance'}")
        if start_seconds:
            logger.info(f"  Resume: {start_seconds}s")
        if open_ended_buffer:
            logger.info("  Open-ended buffer mode: disk-backed 2GiB / 3600s readahead")

        # Open-ended buffer launches a fresh standalone process so the large cache
        # args are baked in at process start — mpv's cache settings are not patchable
        # via IPC loadfile per-file options.  start_seconds is carried through so
        # resume-from-offset and open-ended buffer compose correctly.
        if open_ended_buffer:
            return self._launch_new_instance(url, title, start_seconds=start_seconds,
                                             open_ended_buffer=True)

        if self.single_instance:
            if not self._ensure_instance_running(instance_key):
                logger.warning(
                    f"Could not start instance [{instance_key}], falling back to new instance"
                )
                return self._launch_new_instance(url, title)

            # Per-file options string: "start=<N>" starts at a saved position
            # without a post-load seek race.  The 4th argument to loadfile is
            # the per-file options count (0 = none), but mpv IPC uses a
            # positional string argument for per-file opts (mpv docs: the 4th
            # element is the options string as a comma-separated key=value list).
            if start_seconds > 0:
                per_file_opts = f"start={start_seconds}"
                command = {"command": ["loadfile", url, "replace", 0, per_file_opts], "request_id": 1}
            else:
                command = {"command": ["loadfile", url, "replace"], "request_id": 1}

            if self._send_ipc_command(command, instance_key):
                title_command = {
                    "command": ["set_property", "force-media-title", title],
                    "request_id": 2,
                }
                self._send_ipc_command(title_command, instance_key)

                self._last_key = instance_key
                logger.info(f"Sent to mpv instance [{instance_key}]: {title}")
                return True
            else:
                logger.warning(
                    f"IPC command failed [{instance_key}], falling back to new instance"
                )
                return self._launch_new_instance(url, title)
        else:
            # Multiple-instances mode: every play = new window.
            return self._launch_new_instance(url, title)

    def queue(
        self,
        url: str,
        title: str,
        mode: QueueMode = QueueMode.APPEND_PLAY,
        instance_key: str = "__shared__",
    ) -> bool:
        """Add URL to playlist queue in the specified instance.

        Passes ``title`` as a per-file ``force-media-title`` option on the
        ``loadfile`` command so the mpv window title updates when this item
        starts playing, not only when the first episode starts.

        Args:
            url: Stream URL to queue.
            title: Per-item title; embedded as a ``force-media-title`` option
                in the ``loadfile`` command.
            mode: How to add to queue.
            instance_key: Target player instance.  Defaults to the shared key
                (single-window mode).  When Split Streams is active, pass the
                provider's key so the append lands in the correct window.

        Returns:
            True if successful, False otherwise.
        """
        logger.info(f"MPVPlayer.queue: {title} (mode: {mode.value}, key={instance_key})")

        if not self.single_instance:
            logger.warning("Queue mode requires single-instance mode")
            return self.play(url, title, instance_key=instance_key)

        key = instance_key if instance_key != "__shared__" else (self._last_key or _SHARED_KEY)
        if not self._ensure_instance_running(key):
            logger.warning(f"Could not start instance [{key}]")
            return False

        mode_map = {
            QueueMode.REPLACE: "replace",
            QueueMode.APPEND: "append",
            QueueMode.APPEND_PLAY: "append-play",
            QueueMode.INSERT_NEXT: "insert-next",
        }
        mpv_mode = mode_map.get(mode, "append-play")

        # Escape the title for inclusion in mpv's per-file options string.
        # mpv uses a comma-separated key=value list; we only need to escape
        # the handful of characters that are structurally significant there.
        safe_title = title.replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=")
        command = {
            "command": ["loadfile", url, mpv_mode, 0, f"force-media-title={safe_title}"],
            "request_id": 1,
        }

        if self._send_ipc_command(command, key):
            logger.info(f"Queued to mpv [{key}]: {title}")
            return True
        else:
            logger.error(f"Failed to queue [{key}]: {title}")
            return False

    def _launch_new_instance(
        self,
        url: str,
        title: str,
        start_seconds: int = 0,
        open_ended_buffer: bool = False,
    ) -> bool:
        """Launch a standalone (no-IPC) mpv process for *url*.

        Args:
            url: Stream URL.
            title: Title to display.
            start_seconds: When > 0, pass ``--start=<N>`` so mpv begins at
                that offset.  Used when ``open_ended_buffer`` and resume
                position must compose.
            open_ended_buffer: When True, use open-ended disk-backed cache
                args instead of the configured buffer profile.  The reconnect
                flag and user's ``mpv_extra_args`` still apply (appended last).

        Returns:
            True if the process was spawned successfully.
        """
        try:
            if open_ended_buffer:
                extra_args = self._compose_open_ended_buffer_args()
            else:
                extra_args = self._compose_extra_args()

            cmd = ["mpv", f"--force-media-title={title}"] + extra_args
            if start_seconds > 0:
                cmd.append(f"--start={start_seconds}")
            cmd.append(url)

            logger.info(f"Launching new mpv instance: {' '.join(cmd[:3])}...")

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            logger.info("mpv process started")
            return True

        except Exception as e:
            logger.error(f"Failed to launch mpv: {e}")
            return False

    # ── State queries ────────────────────────────────────────────────────────

    def is_running(self, key: str | None = None) -> bool:
        """Check if an mpv instance is currently running.

        Args:
            key: Instance key to check; defaults to ``_last_key``.

        Returns:
            True if the process for the resolved key is alive.
        """
        resolved = self._resolve_key(key)
        if resolved is None:
            return False
        inst = self._instances.get(resolved)
        if inst is None:
            return False
        return inst.is_running()

    def stop(self, key: str | None = None) -> bool:
        """Stop playback in an instance.

        Args:
            key: Instance key to stop; defaults to ``_last_key``.

        Returns:
            True if the quit command was sent successfully.
        """
        logger.info("Stopping mpv playback")
        resolved = self._resolve_key(key)
        if resolved is None:
            return False
        if self.single_instance and self.is_running(resolved):
            command = {"command": ["quit"], "request_id": 1}
            return self._send_ipc_command(command, resolved)
        return False

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Terminate ALL instances' processes and remove ALL their sockets.

        Iterates the full registry so no orphan window or socket is left
        behind when the application closes.
        """
        logger.info("Cleaning up MPVPlayer resources")

        for key, inst in list(self._instances.items()):
            if inst.is_running():
                logger.info(f"Terminating mpv instance [{key}] PID {inst.process.pid}")
                inst.process.terminate()
                try:
                    inst.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    logger.warning(f"mpv instance [{key}] did not terminate, killing")
                    inst.process.kill()

            if inst.socket_path and os.path.exists(inst.socket_path):
                try:
                    os.remove(inst.socket_path)
                    logger.info(f"Removed socket [{key}]: {inst.socket_path}")
                except Exception as e:
                    logger.warning(f"Could not remove socket [{key}]: {e}")

        self._instances.clear()

    # ── Arg composition (unchanged) ──────────────────────────────────────────

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

        **Override-all shortcut:** when ``config.mpv_args_override_all`` is ``True``,
        returns *only* ``config.mpv_extra_args`` — the caller takes full manual control
        and all built-in flags (UA, reconnect, buffer, prebuffer) are skipped.

        Otherwise the composed order is:
        ``base_args`` (UA + reconnect) + ``buffer_args`` + ``prebuffer_args`` + ``user_args``.

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

        Prebuffer flags (``--cache-pause-initial=yes`` + ``--cache-pause-wait=<secs>``)
        are injected after buffer flags when ``config.prebuffer_before_play`` is ``True``.
        ``--cache=yes`` is prepended to them *only* when ``buffer_args`` did not already
        emit it (i.e. the ``"reconnect_only"`` profile), so the command never carries a
        duplicate ``--cache=yes``.

        User args (``config.mpv_extra_args``) are appended LAST so they win via
        mpv's last-value rule — including any user-supplied ``--user-agent`` or
        cache overrides applied by the Diagnose feature.

        Returns:
            The composed list of extra args to pass on the mpv command line.
        """
        user_args = list(self.config.mpv_extra_args)

        # Override-all: user takes full manual control — skip all built-in flags.
        if getattr(self.config, "mpv_args_override_all", False):
            return user_args

        size = self.config.default_cache_size

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

        # Prebuffer: gate startup on cache pre-filling (mpv --cache-pause-initial).
        prebuffer_args: list[str] = []
        if getattr(self.config, "prebuffer_before_play", False):
            wait = getattr(self.config, "prebuffer_wait_secs", 10)
            # --cache=yes is required for cache-pause-initial to take effect, but
            # only add it when buffer_args didn't already (every profile except
            # "reconnect_only" emits it, as does the explicit-size path) — otherwise
            # the launch command carries a redundant duplicate "--cache=yes".
            if "--cache=yes" not in buffer_args:
                prebuffer_args.append("--cache=yes")
            prebuffer_args += [
                "--cache-pause-initial=yes",
                f"--cache-pause-wait={wait}",
            ]

        return base_args + buffer_args + prebuffer_args + user_args

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

    def _compose_open_ended_buffer_args(self) -> list[str]:
        """Build mpv args for open-ended disk-backed buffering.

        Replaces the configured buffer profile for one launch, giving mpv
        permission to cache as far ahead as the stream allows — up to a
        2 GiB disk-backed cap and a 3600-second readahead window.  This lets
        the user build a large buffer lead to ride out an unstable stream.

        Composition (same shape as ``_compose_extra_args``):
        * Canonical UA + always-on reconnect flag (same as normal path).
        * Open-ended cache flags INSTEAD of the configured buffer profile:
          ``--cache=yes --cache-on-disk=yes --demuxer-readahead-secs=3600
          --demuxer-max-bytes=2GiB``
        * User args (``mpv_extra_args``) appended LAST so they still win via
          mpv's last-value rule.

        The ``mpv_args_override_all`` shortcut is honoured — when set, only
        user args are returned (same as the normal path).

        Returns:
            List of mpv argument strings.
        """
        user_args = list(self.config.mpv_extra_args)

        # Override-all: user takes full manual control — skip all built-in flags.
        if getattr(self.config, "mpv_args_override_all", False):
            return user_args

        base_args = [f"--user-agent={stream_user_agent()}", RECONNECT_FLAG]
        buffer_args = [
            "--cache=yes",
            "--cache-on-disk=yes",
            "--demuxer-readahead-secs=3600",
            "--demuxer-max-bytes=2GiB",
        ]

        return base_args + buffer_args + user_args
