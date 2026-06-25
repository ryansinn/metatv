"""Streaming mixin — stream URL validation, failover, and media-launch methods.

Extracted from MainWindow; mixed in via:
    class MainWindow(_StreamingMixin, QMainWindow): ...

All methods access state set in MainWindow.__init__ via ``self.*``.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

import requests
from loguru import logger
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from metatv.core.channel_name_utils import parse_channel_name as _pcn
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.provider import parse_provider_urls
from metatv.gui import icons as _icons
from metatv.providers.xtream import _DEFAULT_HEADERS


def format_playback_health(cache_duration_s, cache_speed_bytes, drop_count) -> str:
    """Build the nav-bar playback-health string.

    e.g. ``"▶ 18s buffer · 6.2 Mbps · 0 drops"``. Missing parts (None) are shown
    as ``"—"`` but the returned string is always well-formed.

    Args:
        cache_duration_s: Demuxer cache duration in seconds (mpv
            ``demuxer-cache-duration``), or None if unavailable.
        cache_speed_bytes: Network download speed in bytes/sec (mpv
            ``cache-speed``), or None if unavailable.
        drop_count: Dropped frame count (mpv ``frame-drop-count``), or None.

    Returns:
        The composed health string, prefixed with the play glyph.
    """
    if cache_duration_s is None:
        buffer_part = "—s buffer"
    else:
        buffer_part = f"{int(round(cache_duration_s))}s buffer"

    if cache_speed_bytes is None:
        speed_part = "— Mbps"
    else:
        mbps = cache_speed_bytes * 8 / 1e6
        speed_part = f"{mbps:.1f} Mbps"

    if drop_count is None:
        drops_part = "— drops"
    else:
        drops_part = f"{int(drop_count)} drops"

    return f"{_icons.play_icon} " + " · ".join((buffer_part, speed_part, drops_part))


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
                    # Auth/gating codes (401 Unauthorized, 403 Forbidden, 511 Network
                    # Authentication Required) are treated as *uncertain* — the stream
                    # may still play in mpv (e.g. a shared-account cap the server reports
                    # as HTTP 511, but mpv negotiates differently).  Return a sentinel
                    # error string that the failure path can distinguish from a hard text
                    # error, so "Play Anyway" is always offered.
                    if response.status_code in (401, 403, 511):
                        return False, f"HTTP {response.status_code}"
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

    def play_media(
        self,
        channel,
        force_new_window: bool = False,
        open_ended_buffer: bool = False,
        start_override: int | None = None,
    ):
        """Play a media item (live stream or movie) in external player.

        Returns immediately — validation and failover happen in a background
        thread via ``self.executor``; ``_on_stream_ready`` (main-thread slot)
        finishes the launch once the result arrives.

        Args:
            channel: Channel DTO / ORM object with ``stream_url``, ``name``,
                ``provider_id``, etc.
            force_new_window: When True, the stream is keyed by provider_id
                regardless of the ``split_streams_by_source`` toggle — used by
                "Play in New Window" to open/replace a separate per-source window.
            open_ended_buffer: When True, the player uses a large disk-backed
                cache (up to 2 GiB, 3600 s readahead) instead of the configured
                bounded buffer profile.  Use this to build a big buffer lead to
                ride out an unstable stream.
            start_override: When set, forces the seek position regardless of
                ``config.playback_resume_mode`` and the channel's saved progress.
                ``0`` forces start from the beginning; a positive int forces resume
                to that specific second.  ``None`` means "use the setting default".
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

        # Determine resume position.
        # Priority: start_override (explicit per-play) > config.playback_resume_mode > no-resume.
        # Live channels and VOD with no saved progress always start at 0.
        # The write-side invariant (record_watch_progress) guarantees watch_progress > 0
        # implies watch_completed is False, so the watch_completed check is redundant and
        # is omitted here — this also heals any legacy rows stuck with progress > 0 and
        # watch_completed = True from before the fix landed.
        from metatv.core.models import MediaType
        is_live = (channel.media_type == MediaType.LIVE)
        watch_progress = int(getattr(channel, "watch_progress", 0) or 0)

        if start_override is not None:
            # Explicit per-play override wins unconditionally (but still 0 for live).
            start_seconds = start_override if not is_live else 0
        elif not is_live and watch_progress > 0:
            # VOD with a saved resume position: apply the user's default mode.
            resume_mode = getattr(self.config, "playback_resume_mode", "resume")
            start_seconds = watch_progress if resume_mode == "resume" else 0
        else:
            start_seconds = 0

        # Off-load network validation + failover to the shared executor.
        # _on_stream_ready (connected in MainWindow.__init__) fires on the main thread.
        self.executor.submit(
            self._bg_validate_and_play,
            channel_id,
            channel.name,
            channel.stream_url,
            channel.provider_id,
            notif_id,
            force_new_window,
            start_seconds,
            open_ended_buffer,
        )

    # ── Auth/gating HTTP codes that are treated as uncertain (advisory, not hard) ──
    # mpv negotiates differently from requests — a pre-flight HTTP 511 or 403 that
    # signals a shared-account cap may still play fine in mpv.  These codes always
    # surface "Play Anyway" rather than suppressing the stream silently.
    _ADVISORY_HTTP_CODES: frozenset[int] = frozenset({401, 403, 511})

    def _is_advisory_error(self, stream_err: str) -> bool:
        """Return True if *stream_err* is an uncertain pre-flight error code.

        Advisory errors offer "Play Anyway" in the failure toast and are NOT
        fed to ``stream_retry_manager`` as confirmed dead streams.

        Args:
            stream_err: The error string from ``validate_stream_url``, e.g.
                ``"HTTP 511"`` or a server-supplied text message.

        Returns:
            ``True`` when the error is a known advisory HTTP status code.
        """
        if not stream_err:
            return False
        for code in self._ADVISORY_HTTP_CODES:
            if stream_err == f"HTTP {code}":
                return True
        return False

    def _bg_validate_and_play(
        self,
        channel_id: str,
        channel_name: str,
        stream_url: str,
        provider_id: str,
        notif_id: str,
        force_new_window: bool = False,
        start_seconds: int = 0,
        open_ended_buffer: bool = False,
    ) -> None:
        """Worker: validate + failover (same-source, then cross-source siblings).

        Phase 1 — same-source failover (existing path):
            Try the channel's primary URL; if that fails, cycle through the
            provider's alternate base URLs via ``validate_and_failover_stream_url``.

        Phase 2 — cross-source sibling failover (new):
            If every same-source URL fails and the channel has a ``content_key``,
            look up sibling channels on OTHER providers that share the same
            ``content_key`` (``ChannelRepository.get_content_key_siblings``).
            Try each active sibling in ranked order (active providers first, then
            by quality tier).  First one that validates wins; emit success silently
            (no failure toast).

        On total failure the emit payload carries the original channel's URL,
        any sibling alternatives (so the failure toast can offer them), and
        a flag marking whether the error is advisory (→ "Play Anyway" offered).

        Runs in ``self.executor``.  Must NOT touch Qt widgets — all UI work is
        done in ``_on_stream_ready``, which runs on the main thread via the signal.
        """
        # ── Phase 1: same-source validate + failover ────────────────────────
        try:
            final_url, stream_err = self.validate_and_failover_stream_url(
                stream_url, provider_id
            )
        except Exception as e:
            logger.error(f"Error in _bg_validate_and_play phase 1: {e}")
            final_url, stream_err = "", str(e)

        if final_url:
            self._stream_ready.emit({
                "ok": True,
                "channel_id": channel_id,
                "channel_name": channel_name,
                "original_url": stream_url,
                "final_url": final_url,
                "stream_err": "",
                "notif_id": notif_id,
                "provider_id": provider_id,
                "force_new_window": force_new_window,
                "start_seconds": start_seconds,
                "open_ended_buffer": open_ended_buffer,
                "advisory": False,
                "siblings": [],
            })
            return

        # ── Phase 2: cross-source sibling failover ───────────────────────────
        siblings: list[dict] = []
        content_key: str = ""
        try:
            with self.db.session_scope(commit=False) as session:
                from metatv.core.repositories import RepositoryFactory as _RF
                ch = session.get(
                    __import__("metatv.core.database", fromlist=["ChannelDB"]).ChannelDB,
                    channel_id,
                )
                if ch:
                    content_key = ch.content_key or ""
                if content_key:
                    all_siblings = _RF(session).channels.get_content_key_siblings(
                        content_key, channel_id
                    )
                    siblings = all_siblings   # includes inactive — failure toast shows them
                    active_siblings = [s for s in all_siblings if s.get("is_active")]
                    # Try active siblings in ranked order (up to 3 attempts)
                    for sib in active_siblings[:3]:
                        sib_url = sib.get("stream_url") or ""
                        if not sib_url:
                            continue
                        sib_ok, _sib_err = self.validate_stream_url(sib_url)
                        if sib_ok:
                            # Sibling works — emit success using the sibling's provider_id
                            self._stream_ready.emit({
                                "ok": True,
                                "channel_id": sib["id"],
                                "channel_name": channel_name,   # keep user-facing name
                                "original_url": stream_url,
                                "final_url": sib_url,
                                "stream_err": "",
                                "notif_id": notif_id,
                                "provider_id": sib["provider_id"],
                                "force_new_window": force_new_window,
                                "start_seconds": start_seconds,
                                "open_ended_buffer": open_ended_buffer,
                                "advisory": False,
                                "siblings": [],
                                "sibling_failover": True,   # for status-bar annotation
                                "sibling_name": sib.get("name", ""),
                            })
                            return
        except Exception as e:
            logger.warning(f"Error in _bg_validate_and_play phase 2 (sibling failover): {e}")
            siblings = []

        # ── Total failure — emit for the failure toast ───────────────────────
        is_advisory = self._is_advisory_error(stream_err)
        self._stream_ready.emit({
            "ok": False,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "original_url": stream_url,
            "final_url": "",
            "stream_err": stream_err or "",
            "notif_id": notif_id,
            "provider_id": provider_id,
            "force_new_window": force_new_window,
            "start_seconds": start_seconds,
            "open_ended_buffer": open_ended_buffer,
            "advisory": is_advisory,
            "siblings": siblings,   # list of dicts for the failure toast
        })

    def _on_stream_ready(self, data: dict) -> None:
        """Main-thread slot: finish player launch or show error after validation.

        Deduplication: the same channel_id can race through multiple failover
        attempts.  We track the most-recently-shown failure notif per channel so
        duplicate toasts are dismissed before a new one is shown (one toast only).
        """
        if "_stream_fail_notifs" not in self.__dict__:
            self._stream_fail_notifs: dict[str, str] = {}  # channel_id → notif_id

        channel_id = data["channel_id"]
        channel_name = data.get("channel_name", "")
        final_url = data.get("final_url", "")
        original_url = data.get("original_url", "")
        stream_err = data.get("stream_err", "")
        notif_id = data.get("notif_id", "")
        is_advisory = data.get("advisory", False)
        siblings: list[dict] = data.get("siblings", [])

        if not data.get("ok"):
            logger.error(f"All stream URLs failed validation for {channel_name}")
            self.status_bar.showMessage(f"Error: Stream unavailable for {channel_name}")
            detail = stream_err or "All URLs failed (possibly geo-blocked)"
            self.notification_manager.dismiss(notif_id)
            # Dismiss any prior failure toast for this channel (deduplicate)
            prior_fail_notif = self._stream_fail_notifs.pop(channel_id, None)
            if prior_fail_notif:
                self.notification_manager.dismiss(prior_fail_notif)

            _p = _pcn(channel_name)
            _display = _p.bare_name or channel_name

            # Build actions: always Copy Error; advisory → Play Anyway; siblings → extra
            actions = []

            # Play Anyway — offered for advisory (auth/gating) errors AND as a
            # general escape hatch so the user can override the pre-flight check.
            _pid = data.get("provider_id")
            _fnw = data.get("force_new_window", False)
            actions.append((
                "Play Anyway",
                lambda _url=original_url, _name=channel_name, _p=_pid, _fnw=_fnw:
                    self.player_manager.play(
                        _url, _name,
                        provider_id=_p,
                        force_new_window=_fnw,
                    )
            ))

            # Active sibling sources — each gets an "Also on X" action (up to 3)
            active_sibs = [s for s in siblings if s.get("is_active")]
            for sib in active_sibs[:3]:
                sib_name = sib.get("name", "")
                sib_url = sib.get("stream_url") or ""
                sib_pid = sib.get("provider_id")
                sib_label = f"Try {sib.get('detected_prefix') or sib.get('detected_region') or sib_name}"
                if not sib_url:
                    continue
                actions.append((
                    sib_label,
                    lambda _u=sib_url, _n=channel_name, _p=sib_pid, _fnw=_fnw:
                        self.player_manager.play(
                            _u, _n,
                            provider_id=_p,
                            force_new_window=_fnw,
                        )
                ))

            # Inactive sibling sources (offer reactivate + play)
            inactive_sibs = [s for s in siblings if not s.get("is_active")]
            for sib in inactive_sibs[:2]:
                sib_name = sib.get("name", "")
                sib_url = sib.get("stream_url") or ""
                sib_pid = sib.get("provider_id")
                sib_prefix = sib.get("detected_prefix") or sib.get("detected_region") or ""
                if not sib_url or not sib_pid:
                    continue
                label = f"Reactivate & play {sib_prefix or sib_name}"
                actions.append((
                    label,
                    lambda _pid=sib_pid, _u=sib_url, _n=channel_name, _fnw=_fnw:
                        self._reactivate_and_play_sibling(_pid, _u, _n, _fnw)
                ))

            actions.append(
                ("Copy Error", lambda n=channel_name, u=original_url, d=detail:
                    QApplication.clipboard().setText(f"{n}\nURL: {u}\nError: {d}"))
            )

            fail_notif_id = self.notification_manager.show(
                title="Stream Unavailable",
                message=f"{_display}\n{detail}",
                type="error",
                dismissible=True,
                auto_dismiss_seconds=None,
                actions=actions,
            )
            self._stream_fail_notifs[channel_id] = fail_notif_id

            # Only record a confirmed failure for non-advisory errors
            if not is_advisory and hasattr(self, "stream_retry_manager"):
                self.stream_retry_manager.add_failure(
                    channel_id, channel_name, original_url, detail
                )
            self.loading_channels.discard(channel_id)
            return

        if data.get("sibling_failover"):
            sib_label = data.get("sibling_name", "")
            logger.info(f"Cross-source failover: using sibling {sib_label!r}")
            self.status_bar.showMessage(
                f"Switched to alternate source for {channel_name}…"
            )
        elif final_url != original_url:
            logger.info(f"Using failover URL: {final_url}")

        self.status_bar.showMessage(f"Loading: {channel_name}...")

        force_new_window = data.get("force_new_window", False)
        open_ended_buffer = bool(data.get("open_ended_buffer", False))
        start_seconds = int(data.get("start_seconds", 0) or 0)
        if start_seconds:
            logger.info(f"Resuming {channel_name} at {start_seconds}s")
        if open_ended_buffer:
            logger.info(f"Open-ended buffer mode for {channel_name}")
        if self.player_manager.play(
            final_url, channel_name,
            provider_id=data.get("provider_id"),
            force_new_window=force_new_window,
            start_seconds=start_seconds,
            open_ended_buffer=open_ended_buffer,
        ):
            # Record playback — mark_played is a DB write; run off-thread. The same
            # worker registers this instance for watch-progress capture (it already
            # loads the channel, so it knows the media_type).
            if not hasattr(self, "_watch_tracking"):
                self._watch_tracking = {}
            _watch_key = self.player_manager.resolve_key(
                data.get("provider_id"), force_new_window
            )
            self.executor.submit(self._bg_mark_played, channel_id, _watch_key)
            self._start_watch_capture()

            # Update UI lists in real-time (main thread)
            self.load_history()
            self.load_favorites()
            self._refresh_queue_section()

            # Warm the source-glyph cache so the health readout can label which
            # stream its data refers to (one trivial PK read per new source).
            pid = data.get("provider_id")
            if pid and pid not in self._provider_icons:
                self._provider_icons[pid] = self._lookup_provider_icon(pid)

            # Begin polling mpv for the live playback-health readout (main thread).
            self._start_playback_health()

            QTimer.singleShot(2000, lambda: self.status_bar.showMessage(f"Playing: {channel_name}"))
        else:
            logger.error(f"Failed to play: {channel_name}")
            self.status_bar.showMessage(f"Error playing: {channel_name}")

        QTimer.singleShot(3000, lambda: self.loading_channels.discard(channel_id))

    def _reactivate_and_play_sibling(
        self,
        provider_id: str,
        stream_url: str,
        channel_name: str,
        force_new_window: bool = False,
    ) -> None:
        """Main-thread action: reactivate a disabled provider, then play its stream.

        Called by the "Reactivate & play" action in the failure toast when the user
        explicitly opts into an inactive-source variant (mirror-not-cage: we surfaced
        the option; they chose it).  The provider is re-activated then the URL is
        passed directly to player_manager (no extra validation — the user already
        consented to the playback attempt).

        Args:
            provider_id: The inactive provider to reactivate.
            stream_url: The sibling channel's stream URL to play immediately after.
            channel_name: Display name for the player window.
            force_new_window: When True, open/replace a separate per-source window.
        """
        try:
            with self.db.session_scope() as session:
                from metatv.core.repositories import RepositoryFactory as _RF
                provider = _RF(session).providers.get_by_id(provider_id)
                if provider:
                    provider.is_active = True
        except Exception as exc:
            logger.warning(f"_reactivate_and_play_sibling: failed to reactivate {provider_id}: {exc}")
        self.player_manager.play(
            stream_url, channel_name,
            provider_id=provider_id,
            force_new_window=force_new_window,
        )

    def _bg_mark_played(self, channel_id: str, key: str | None = None) -> None:
        """Worker: write play-count + last-played to DB (off main thread).

        Also registers this instance for watch-progress capture — VOD **movies**
        only (live has no completion; episodes use their own play path). If a
        non-movie now plays on *key*, drop any stale tracking so a previous movie
        in the same window isn't captured against the new stream.
        """
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                repos.channels.mark_played(channel_id)
                if key is not None:
                    ch = repos.channels.get_by_id(channel_id)
                    if ch is not None and ch.media_type == "movie":
                        self._watch_tracking[key] = {
                            "content_id": channel_id,
                            "media_type": "movie",
                            "played_via": "manual",
                        }
                    else:
                        self._watch_tracking.pop(key, None)
        except Exception as e:
            logger.error(f"Error marking channel played: {e}")

    # ---- Watch-progress capture (resume position + completion) ----------------
    # A periodic checkpoint persists each active play's position/completion via the
    # repository chokepoint, independent of the playback-health readout so it stays
    # correct under Split Streams (each window captured against the content IT plays).

    def _start_watch_capture(self) -> None:
        """Start (or resume) the periodic watch-progress checkpoint timer."""
        if not hasattr(self, "_watch_tracking"):
            self._watch_tracking = {}
        if getattr(self, "_watch_checkpoint_timer", None) is None:
            self._watch_checkpoint_timer = QTimer(self)
            self._watch_checkpoint_timer.setInterval(20_000)  # 20s checkpoint
            self._watch_checkpoint_timer.timeout.connect(self._watch_checkpoint_tick)
            self._register_cleanable(
                "watch_checkpoint_timer", self._watch_checkpoint_timer.stop
            )
        if not self._watch_checkpoint_timer.isActive():
            self._watch_checkpoint_timer.start()

    def _watch_checkpoint_tick(self) -> None:
        """Timer tick (main thread): sample + persist each active play's progress.

        For queued episode plays, passes a *snapshot* of the mutable tracking
        dict to the worker — the worker may increment ``last_seen_pos`` in-place
        via ``_update_last_seen_pos``; the snapshot lets the worker reason about
        the queue without racing against future ticks.  Non-episode and
        single-episode tracks continue to pass ``dict(info)`` as before.
        """
        keys = self.player_manager.active_keys()
        tracking = getattr(self, "_watch_tracking", {})
        # Finalise + drop tracking for windows that have closed between ticks.
        for k in list(tracking.keys()):
            if k not in keys:
                info = tracking.pop(k, None)
                if info and info.get("media_type") == "episode" and info.get("queue"):
                    # Instance disappeared — finalise the episode that was playing
                    # at last_seen_pos so its progress isn't lost between ticks.
                    pos = info.get("last_seen_pos", 0)
                    queue = info["queue"]
                    if 0 <= pos < len(queue):
                        self.executor.submit(
                            self._bg_finalise_episode,
                            queue[pos]["content_id"],
                            "queue" if pos > 0 else info.get("played_via", "manual"),
                        )
                    # If the queue advanced past the first episode, emit the
                    # queue-end signal so the main thread can show "Still here?".
                    # Episodes at indices 1..pos (inclusive) were auto-advanced;
                    # index 0 is the user-started episode (last_played_via="manual").
                    if pos > 0 and getattr(self.config, "prompt_after_autoplay", True):
                        auto_ids = [
                            queue[i]["content_id"]
                            for i in range(1, min(pos + 1, len(queue)))
                        ]
                        if auto_ids:
                            self._queue_end_detected.emit(auto_ids)
        if not keys:
            self._watch_checkpoint_timer.stop()
            return
        for key in keys:
            info = tracking.get(key)
            if info:
                self.executor.submit(self._bg_capture_watch, key, dict(info))

    def _bg_finalise_episode(self, content_id: str, played_via: str) -> None:
        """Worker: mark an episode 100% complete when it is auto-advanced past.

        Called when mpv's playlist-pos advances beyond an episode (meaning mpv
        played it to the end) or when the player window closes with a queued
        episode in flight.  Using ``record_watch_progress`` at 100% honours the
        sticky-completion rule in the repository — a later rewatch can still
        update the resume point without un-completing.

        Args:
            content_id: The episode DB id to finalise.
            played_via: ``"manual"`` for the user-started episode, ``"queue"``
                for every auto-advanced one.
        """
        try:
            threshold = getattr(self.config, "watch_complete_threshold", 0.9)
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                # Synthesise a 100%-complete read so record_watch_progress sets
                # watch_completed=True (any dur > 0 with pos==dur crosses threshold).
                repos.episodes.record_watch_progress(
                    content_id, 1.0, 1.0, threshold, played_via
                )
        except Exception as exc:
            logger.debug(f"Episode finalise failed for {content_id!r}: {exc}")

    def _bg_capture_watch(self, key: str, info: dict) -> None:
        """Worker: read mpv position for *key* and persist watch progress.

        For queued episode plays (``info["queue"]`` present) the worker:
        1. Reads ``playlist-pos`` alongside ``time-pos`` / ``duration``.
        2. Finalises every episode the playlist has auto-advanced past since
           the previous tick (``last_seen_pos`` < current pos) by calling
           ``_bg_finalise_episode`` — those episodes played to the end.
        3. Records live progress for the *current* episode (at ``playlist-pos``)
           via ``record_watch_progress`` so partial state is not lost.

        For single-episode and movie tracks the behaviour is unchanged.

        Args:
            key: Player instance key (from ``player_manager.resolve_key``).
            info: Snapshot of the tracking entry at the time the tick fired.
                  Mutating it does not affect the live tracking dict; the
                  ``last_seen_pos`` update is applied to the *live* dict via
                  ``_update_last_seen_pos``.
        """
        try:
            queue = info.get("queue")
            if queue:
                # Queued-episode branch: follow playlist-pos.
                props = self.player_manager.get_properties(
                    ["time-pos", "duration", "playlist-pos"], key=key
                )
                pos_s = props.get("time-pos")
                dur_s = props.get("duration")
                pl_pos = props.get("playlist-pos")

                # playlist-pos is None when mpv is idle / finished.
                if pl_pos is None or pos_s is None:
                    return

                # Guard: playlist-pos may briefly exceed our queue length
                # (e.g. mpv adds an item between play and our tick).
                if not (0 <= pl_pos < len(queue)):
                    return

                threshold = getattr(self.config, "watch_complete_threshold", 0.9)
                last_pos = info.get("last_seen_pos", 0)

                # Finalise every episode that the playlist advanced past since
                # the last tick.  Each one played to the end (mpv auto-advanced).
                if pl_pos > last_pos:
                    for passed_idx in range(last_pos, pl_pos):
                        passed = queue[passed_idx]
                        via = "manual" if passed_idx == 0 else "queue"
                        # Schedule the finalise in this same worker call — we're
                        # already off the main thread so direct call is fine.
                        self._bg_finalise_episode(passed["content_id"], via)
                    # Update last_seen_pos in the LIVE tracking dict so the next
                    # tick doesn't re-finalise the same episodes.
                    self._update_last_seen_pos(key, pl_pos)

                # Record live progress for the currently-playing episode.
                if dur_s and dur_s > 0:
                    current = queue[pl_pos]
                    via = "manual" if pl_pos == 0 else "queue"
                    with self.db.session_scope() as session:
                        repos = RepositoryFactory(session)
                        repos.episodes.record_watch_progress(
                            current["content_id"], pos_s, dur_s, threshold, via
                        )
            else:
                # Single-episode / movie branch: unchanged behaviour.
                props = self.player_manager.get_properties(["time-pos", "duration"], key=key)
                pos_s = props.get("time-pos")
                dur_s = props.get("duration")
                if pos_s is None or not dur_s or dur_s <= 0:
                    return
                threshold = getattr(self.config, "watch_complete_threshold", 0.9)
                with self.db.session_scope() as session:
                    repos = RepositoryFactory(session)
                    played_via = info.get("played_via", "manual")
                    if info.get("media_type") == "episode":
                        repos.episodes.record_watch_progress(
                            info["content_id"], pos_s, dur_s, threshold, played_via
                        )
                    else:
                        repos.channels.record_watch_progress(
                            info["content_id"], pos_s, dur_s, threshold, played_via
                        )
        except Exception as e:
            logger.debug(f"Watch-progress capture failed for {key}: {e}")

    def _update_last_seen_pos(self, key: str, new_pos: int) -> None:
        """Main-thread-safe update of ``last_seen_pos`` in the live tracking dict.

        Called from the off-thread ``_bg_capture_watch`` worker.  The GIL makes
        this single dict-item assignment atomic in CPython, so no additional
        locking is needed here — but callers must never read-modify-write the
        nested dict in a non-atomic way from the worker thread.

        Args:
            key: Player instance key.
            new_pos: The new ``last_seen_pos`` value (current ``playlist-pos``).
        """
        tracking = getattr(self, "_watch_tracking", {})
        live = tracking.get(key)
        if live is not None and live.get("queue") is not None:
            live["last_seen_pos"] = new_pos

    # ---- "Still here?" end-of-queue prompt (Slice 3b-4) --------------------
    #
    # When a queued auto-advance run ends, the off-thread tick emits
    # _queue_end_detected with the ids of every auto-advanced episode.  This
    # main-thread slot shows a modal prompt; Yes promotes them to 'manual'
    # (solid icon, advances the resume anchor), No leaves them as 'queue' (gray).

    def _on_queue_end_detected(self, auto_episode_ids: list) -> None:
        """Main-thread slot: show "Still here?" prompt after a queue-auto-advance run ends.

        Called when the ``_queue_end_detected`` signal fires (emitted from the
        off-thread checkpoint tick after a queued player window closes with
        ``last_seen_pos > 0``).

        Args:
            auto_episode_ids: Episode DB ids that were auto-advanced (played via
                ``'queue'``). These are episodes at queue indices 1‥last_seen_pos.
                Index 0 is already ``'manual'`` (the user explicitly started it).
        """
        if not auto_episode_ids:
            return
        if not getattr(self.config, "prompt_after_autoplay", True):
            return

        # Build a human-friendly label — show the episode count, not raw ids.
        count = len(auto_episode_ids)
        if count == 1:
            ep_label = "1 more episode"
        else:
            ep_label = f"{count} more episodes"

        dlg = QDialog(self)
        dlg.setWindowTitle("Still watching?")
        dlg.setModal(True)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        msg = QLabel(
            f"The queue auto-advanced through {ep_label}.\n\n"
            "Did you watch them?"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            # User confirmed — promote all auto-advanced episodes to 'manual' so
            # they render as solid and advance the resume anchor past them.
            self.executor.submit(self._bg_promote_queue_episodes, auto_episode_ids)
        else:
            logger.debug(
                f"Queue-end prompt dismissed — {count} episode(s) remain queue-watched"
            )

    def _bg_promote_queue_episodes(self, episode_ids: list) -> None:
        """Worker: flip ``last_played_via`` to ``'manual'`` for confirmed episodes.

        Runs off the main thread.  Uses ``mark_episodes_as_engaged`` from the
        episode repository — a thin bulk updater that commits once.

        Args:
            episode_ids: DB ids of the episodes to promote.
        """
        try:
            with self.db.session_scope() as session:
                repos = RepositoryFactory(session)
                updated = repos.episodes.mark_episodes_as_engaged(episode_ids)
                logger.info(
                    f"Promoted {updated}/{len(episode_ids)} queue-watched episode(s) "
                    "to manual engagement after user confirmation"
                )
        except Exception as exc:
            logger.warning(f"Failed to promote queue-watched episodes: {exc}")

    def _lookup_provider_icon(self, provider_id: str) -> str:
        """Return a source's display glyph (trivial PK read; cached by caller).

        Args:
            provider_id: The provider whose icon to fetch.

        Returns:
            The provider's configured icon, the default provider glyph as a
            fallback, or "" on any error.
        """
        try:
            with self.db.session_scope(commit=False) as session:
                p = RepositoryFactory(session).providers.get_by_id(provider_id)
                if p:
                    return getattr(p, "icon", "") or self.config.provider_icon
        except Exception as e:
            logger.debug(f"provider-icon lookup failed for {provider_id}: {e}")
        return ""

    def _source_icon_for_key(self, key: str | None) -> str:
        """Return the cached source glyph for the player window keyed by *key*."""
        pid = self.player_manager.provider_for_key(key)
        if not pid:
            return ""
        return self._provider_icons.get(pid, "")

    # ---- Live playback-health indicator -------------------------------------
    #
    # A QTimer polls mpv's IPC socket every ~2s. The socket query runs on the
    # shared executor (never the main thread); the result is marshalled back via
    # the _playback_health_ready signal (same pattern as _stream_ready). The
    # timer self-stops after a short idle grace so there's no perpetual polling
    # once you stop watching; it restarts on the next play_media.

    def _start_playback_health(self) -> None:
        """Start (or resume) polling mpv for the playback-health readout.

        Lazily creates the QTimer on first use and registers its stop() with the
        cleanup registry exactly once. Safe to call on every play.
        """
        if not hasattr(self, "_playback_health_timer") or self._playback_health_timer is None:
            self._playback_health_timer = QTimer(self)
            self._playback_health_timer.setInterval(2000)
            self._playback_health_timer.timeout.connect(self._playback_health_tick)
            self._health_query_inflight = False
            self._register_cleanable(
                "playback_health_timer", self._playback_health_timer.stop
            )

        self._health_idle_ticks = 0
        # A new play always follows the most-recently-used window. Without this,
        # a readout the user clicked to cycle (pinning _health_view_key to some
        # window) stays pinned forever — so after that window goes idle or they
        # play elsewhere, the readout keeps polling the stale/idle instance and
        # shows nothing. Reset to "follow latest" on every play.
        self._health_view_key = None
        if not self._playback_health_timer.isActive():
            self._playback_health_timer.start()

    def _playback_health_tick(self) -> None:
        """Timer tick (main thread): kick off an off-thread mpv probe.

        Stops polling only when *no* instance is alive, and never lets probes
        pile up if one is still in flight.

        Liveness is decided from ``active_keys()`` (every live window), not from
        ``is_running()`` (which checks only ``_last_key``): closing the most-
        recent window must not blank the readout while other windows still play.
        The probed key is always a *live* one (see ``_resolve_health_key``).
        """
        keys = self.player_manager.active_keys()
        if not keys:
            # No live instance at all — hide and stop polling (restarts on play).
            self._playback_health_label.hide()
            self._playback_health_timer.stop()
            return

        if getattr(self, "_health_query_inflight", False):
            return  # a probe is still running — don't pile up

        key = self._resolve_health_key(keys)
        self._health_querying_key = key

        self._health_query_inflight = True
        self.executor.submit(self._bg_query_playback_health, key)

    def _resolve_health_key(self, keys: list[str]) -> str:
        """Pick which live player window the readout should display.

        Honours a pinned view (click-to-cycle) while its window is still alive;
        otherwise follows the most-recently-used window, falling back to the
        first live key when that window has been closed. The returned key is
        always currently alive, so closing one window never blanks the readout
        for the windows still playing.

        Args:
            keys: The currently-live instance keys (non-empty).

        Returns:
            A key guaranteed to be present in *keys*.
        """
        view = getattr(self, "_health_view_key", None)
        if view and view in keys:
            return view
        last = getattr(getattr(self.player_manager, "player", None), "_last_key", None)
        return last if last in keys else keys[0]

    def _bg_query_playback_health(self, key: str | None = None) -> None:
        """Worker (executor — NO widget access): query mpv, marshal result back.

        Always emits (even on failure) so the result slot can clear the in-flight
        flag; emits ``(key, None)`` on any error.

        Args:
            key: Instance key to query; None targets the most-recently-used window.
        """
        try:
            props = self.player_manager.get_properties(
                ["path", "demuxer-cache-duration", "cache-speed", "frame-drop-count"],
                key=key,
            )
        except Exception as e:
            logger.debug(f"playback-health probe failed: {e}")
            props = None
        self._playback_health_ready.emit((key, props))

    def _on_playback_health_ready(self, payload) -> None:
        """Main-thread slot: update the nav-bar label from a probe result.

        Idle detection: mpv stays running with ``--idle=yes`` even when nothing
        is loaded, so we detect idle via the ``path`` property (null/absent when
        idle) rather than is_running(). After a short idle grace the timer stops
        so there's no perpetual polling.

        When multiple windows are open, a position marker ``"[i/n] "`` is
        prepended and the tooltip invites the user to click to cycle windows.
        """
        self._health_query_inflight = False

        key, props = payload

        # None (probe error) or no loaded file → idle / nothing playing.
        if not props or not props.get("path"):
            self._playback_health_label.hide()
            self._health_idle_ticks = getattr(self, "_health_idle_ticks", 0) + 1
            if self._health_idle_ticks >= 8:  # ~16s idle → stop polling
                self._playback_health_timer.stop()
            return

        self._health_idle_ticks = 0
        text = format_playback_health(
            props.get("demuxer-cache-duration"),
            props.get("cache-speed"),
            props.get("frame-drop-count"),
        )

        # Resolve which window this reading belongs to.
        shown_key = key
        if shown_key is None:
            shown_key = getattr(
                getattr(self.player_manager, "player", None), "_last_key", None
            )

        # Source glyph labels *which* stream the data refers to (shown whether one
        # or many windows are open). The [i/n] marker (multi only) adds count +
        # position; the glyph is what tells the two apart at a glance.
        src_icon = self._source_icon_for_key(shown_key)
        prefix = f"{src_icon} " if src_icon else ""

        keys = self.player_manager.active_keys()
        n = len(keys)
        if n > 1:
            try:
                idx = keys.index(shown_key) + 1
            except (ValueError, TypeError):
                idx = 1
            prefix = f"[{idx}/{n}] {prefix}"
            self._playback_health_label.setToolTip(
                f"Click to cycle between {n} open players · buffer · download speed · dropped frames"
            )
        else:
            self._playback_health_label.setToolTip(
                "Live playback health (buffer · download speed · dropped frames)"
            )

        self._playback_health_label.setText(prefix + text)
        self._playback_health_label.show()

    def _on_health_readout_clicked(self) -> None:
        """Main-thread slot: cycle the health readout to the next open player window.

        When only one window is open this is a no-op.  Otherwise the pinned
        ``_health_view_key`` advances to the next live key (wrapping around), and
        an immediate off-thread probe is kicked off so the readout updates without
        waiting for the next timer tick.
        """
        keys = self.player_manager.active_keys()
        if len(keys) <= 1:
            return  # nothing to cycle

        # Determine the currently-shown key.
        current = getattr(self, "_health_view_key", None)
        if not (current and current in keys):
            # Not pinned — resolve from _last_key.
            current = getattr(
                getattr(self.player_manager, "player", None), "_last_key", None
            )
        if current not in keys:
            current = keys[0]

        # Advance to the next key (wrap around).
        try:
            idx = keys.index(current)
        except ValueError:
            idx = 0
        next_key = keys[(idx + 1) % len(keys)]
        self._health_view_key = next_key

        # Kick off an immediate probe for the newly-selected window.
        if not getattr(self, "_health_query_inflight", False):
            self._health_query_inflight = True
            self._health_querying_key = next_key
            self.executor.submit(self._bg_query_playback_health, next_key)

