"""Player manager facade for simple player operations"""

from typing import Optional
from loguru import logger

from metatv.core.config import Config
from metatv.core.connection_accountant import AcquireResult, ConnectionAccountant
from metatv.core.players.base import PlayerPlugin, QueueMode
from metatv.core.players.mpv import MPVPlayer


class PlayerManager:
    """Facade for managing media player operations with instance limit enforcement"""

    def __init__(self, config: Config):
        """Initialize player manager

        Args:
            config: Application configuration
        """
        self.config = config
        self.player: Optional[PlayerPlugin] = None
        # Instance key → provider_id of the content last played into it. Lets the
        # UI label each player window's health readout with its source (the key is
        # the provider_id when split is on, but "__shared__" when off — this map
        # resolves the shared window too).
        self._key_provider: dict[str, str] = {}
        self._init_connection_accounting()
        self._initialize_player()

    def _init_connection_accounting(self) -> None:
        """Construct the connection accountant + its provider-capacity cache.

        Split out from ``__init__`` so tests that build a ``PlayerManager`` via
        ``PlayerManager.__new__`` (bypassing ``__init__`` for a lighter fake
        with no real mpv) can call this one method after setting ``self.config``
        instead of hand-assembling the accountant's internals.
        """
        # provider_id → the most recent provider_max_connections passed to
        # play()/check_capacity() for it. Read by _effective_capacity, the
        # resolver injected into the accountant below.
        self._provider_caps: dict[str, int] = {}
        self.connection_accountant = ConnectionAccountant(capacity_resolver=self._effective_capacity)

    def _initialize_player(self):
        """Initialize the appropriate player based on configuration"""
        # For now, only MPV is supported
        # Future: Add VLC, ffplay, etc.

        mpv = MPVPlayer(self.config)
        if mpv.is_available():
            self.player = mpv
            logger.info(f"Initialized player: {self.player.name}")
        else:
            logger.error("No media player available! Please install mpv.")
            self.player = None

    # ── Instance-key resolution ─────────────────────────────────────────────

    def _resolve_instance_key(self, provider_id: str | None, force_split: bool = False) -> str:
        """Resolve the mpv instance key for a play request.

        Returns *provider_id* when ``(force_split or
        config.split_streams_by_source)`` is True and *provider_id* is a
        non-empty string; otherwise returns the shared singleton key
        ``"__shared__"``.

        ``force_split`` lets callers (e.g. "Play in New Window") open a
        per-source window regardless of the global split toggle.

        This method is pure and unit-testable without a real player.

        Args:
            provider_id: The channel's provider_id (may be None or empty).
            force_split: When True, treat the split flag as enabled even if
                ``config.split_streams_by_source`` is False.

        Returns:
            The instance key to pass to the player.
        """
        if (force_split or getattr(self.config, "split_streams_by_source", False)) and provider_id:
            return provider_id
        return "__shared__"

    # ── Connection accounting ───────────────────────────────────────────────

    def _effective_capacity(self, provider_id: str) -> int:
        """Capacity resolver injected into ``ConnectionAccountant``.

        Interprets ``config.max_player_instances``:

        - ``-1`` → unlimited (returns ``0``, the accountant's unlimited sentinel).
        - ``0`` → defer to the provider's own stream limit — the last
          ``provider_max_connections`` passed to ``play()``/``check_capacity()``
          for this provider (cached in ``_provider_caps``; ``1`` if never seen).
        - Anything else → an explicit cap applied uniformly to every provider.

        This replaces the old (dead) ``_get_effective_max_instances`` — same
        semantics, now feeding the accountant instead of an unreachable
        ``running_instances`` length check.
        """
        config_max = self.config.max_player_instances
        if config_max == -1:
            return 0
        if config_max == 0:
            return self._provider_caps.get(provider_id, 1)
        return config_max

    def _reconcile_connections(self) -> None:
        """Sweep holders whose mpv process has died since the last decision.

        See ``ConnectionAccountant.reconcile`` for why this is on-query
        (called here, at the top of ``play()``/``stop()``) rather than
        timer-driven. A no-op when no player is available.
        """
        if self.player:
            self.connection_accountant.reconcile(self.player.active_keys())

    def check_capacity(
        self,
        provider_id: str | None,
        provider_max_connections: int,
        force_new_window: bool = False,
    ) -> AcquireResult | None:
        """Read-only pre-flight for a prospective ``play()`` call.

        Does not mutate accounting state. Callers use this to decide whether
        to show a "connection limit reached" warning *before* calling
        ``play()``, instead of calling it and having it silently return False.

        Args:
            provider_id: The channel's provider_id.
            provider_max_connections: The provider's stream limit (0 = use
                config semantics; see ``_effective_capacity``).
            force_new_window: Same meaning as in ``play()``.

        Returns:
            ``None`` when *provider_id* is falsy — no accounting applies, it
            is always safe to proceed. Otherwise the ``AcquireResult`` that a
            subsequent ``play()`` call would produce right now.
        """
        if not provider_id:
            return None
        self._reconcile_connections()
        self._provider_caps[provider_id] = provider_max_connections
        key = self._resolve_instance_key(provider_id, force_split=force_new_window)
        return self.connection_accountant.preview(provider_id, key)

    # ── Public API ───────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if a player is available

        Returns:
            True if player is available, False otherwise
        """
        return self.player is not None and self.player.is_available()

    def get_player_name(self) -> Optional[str]:
        """Get name of current player

        Returns:
            Player name or None if no player available
        """
        return self.player.name if self.player else None

    def play(
        self,
        url: str,
        title: str,
        provider_id: str | None = None,
        provider_max_connections: int = 1,
        force_new_window: bool = False,
        start_seconds: int = 0,
        open_ended_buffer: bool = False,
        deep_buffer: bool = False,
        channel_id: str = "",
    ) -> bool:
        """Play a URL, enforcing the provider's connection limit.

        Resolves the instance key from *provider_id* and the
        ``split_streams_by_source`` config flag, registers/reuses a slot in
        the ``ConnectionAccountant``, then delegates to the player.

        Args:
            url: Stream URL to play.
            title: Title to display.
            provider_id: The channel's provider_id; used to key the player
                window when ``split_streams_by_source`` is enabled, and to
                account this play against the provider's connection limit.
            provider_max_connections: Max simultaneous connections the
                provider allows (``ProviderDB.max_connections``). Callers with
                provider context should always pass the real value — see
                ``check_capacity`` for the pre-flight callers use to warn
                before this would return False.
            force_new_window: When True, this play is keyed by provider_id
                regardless of the split toggle — used by "Play in New Window"
                to open/replace a separate per-source window.
            start_seconds: Resume position in seconds.  When > 0 the player
                begins at that offset (mpv per-file ``start=`` option).
                0 means start from the beginning.
            open_ended_buffer: When True, the player uses a large disk-backed
                cache (up to 2 GiB, 3600 s readahead) instead of the configured
                bounded buffer profile.
            deep_buffer: When True (VOD-only — see ``channel_menu.py``'s
                ``play_deep_cache`` action), the player also records the raw
                stream to disk ("Buffer without limit" / deep-cache mode) —
                see ``MPVPlayer.play``.
            channel_id: The channel/episode id being played — threaded through
                to name the deep-cache recording deterministically. Ignored
                unless ``deep_buffer`` is True.

        Returns:
            True if successful, False otherwise (including when the
            provider's connection limit would be exceeded).
        """
        if not self.player:
            logger.error("No player available")
            return False

        self._reconcile_connections()

        key = self._resolve_instance_key(provider_id, force_split=force_new_window)

        if provider_id:
            self._provider_caps[provider_id] = provider_max_connections
            old_provider = self._key_provider.get(key)
            if old_provider and old_provider != provider_id:
                # This key is being repointed at a different provider (e.g. a
                # reused window switching sources) — release its old slot
                # before acquiring the new one.
                self.connection_accountant.release(old_provider, key)
            acquired = self.connection_accountant.acquire(provider_id, "playback", key)
            if not acquired.granted:
                logger.warning(
                    f"Connection limit reached for provider {provider_id}: "
                    f"{len(acquired.holders)}/{acquired.capacity} slot(s) in use "
                    f"(holders={acquired.holders}). Callers should pre-flight via "
                    f"check_capacity() to offer a 'replace oldest' action instead "
                    f"of hitting this silent failure."
                )
                return False

        result = self.player.play(
            url, title, instance_key=key, start_seconds=start_seconds,
            open_ended_buffer=open_ended_buffer,
            deep_buffer=deep_buffer, channel_id=channel_id,
        )

        if provider_id:
            if result:
                # Remember which source is playing in this window (for the health readout).
                self._key_provider[key] = provider_id
            else:
                # Launch failed after the slot was acquired — don't leak it.
                self.connection_accountant.release(provider_id, key)

        return result

    def queue(
        self,
        url: str,
        title: str,
        mode: QueueMode = QueueMode.APPEND_PLAY,
        provider_id: str | None = None,
    ) -> bool:
        """Add URL to playlist queue.

        Args:
            url: Stream URL to queue.
            title: Title to display.  Passed as a per-item ``force-media-title``
                so the mpv window title updates as each queued item starts.
            mode: How to add to queue.
            provider_id: The episode's source provider id — used to resolve the
                correct instance key under Split Streams (must match the key of
                the currently-playing episode so the append lands in the right
                window).

        Returns:
            True if successful, False otherwise.
        """
        if not self.player:
            logger.error("No player available")
            return False

        key = self._resolve_instance_key(provider_id)
        return self.player.queue(url, title, mode, instance_key=key)

    def stop(self, key: str | None = None) -> bool:
        """Stop playback

        Args:
            key: Instance key to stop; defaults to the most-recently-used key.

        Returns:
            True if successful, False otherwise
        """
        if not self.player:
            return False

        self._reconcile_connections()
        result = self.player.stop(key=key)

        # Release the accounting slot for an explicit key immediately — a
        # deterministic release (vs. waiting for the next play()'s reconcile
        # to notice the process died) matters for the "replace oldest" flow,
        # which stops the oldest holder then immediately retries play().
        # A None key (stop the default/most-recently-used instance) is
        # best-effort: it's swept up by the next play()'s reconcile once the
        # process actually exits.
        if key is not None:
            provider_id = self._key_provider.get(key)
            if provider_id:
                self.connection_accountant.release(provider_id, key)

        return result

    def is_running(self, key: str | None = None) -> bool:
        """Check if player is currently running.

        Args:
            key: Instance key to check; defaults to the most-recently-used key.

        Returns:
            True if the player process is running
        """
        if not self.player:
            return False

        return self.player.is_running(key=key)

    def get_properties(self, names: list[str], key: str | None = None) -> dict:
        """Query several player runtime properties.

        Args:
            names: Property names to query (player-specific).
            key: Instance key to query; defaults to the most-recently-used key.

        Returns:
            ``{name: value-or-None}`` for each requested name; all-None if no
            player is available.
        """
        if not self.player:
            return {n: None for n in names}
        return self.player.get_properties(names, key=key)

    def active_keys(self) -> list[str]:
        """Return the instance keys whose player processes are currently alive.

        Returns an empty list when no player is available or no instances are
        running.  Delegates to ``MPVPlayer.active_keys()``.

        Returns:
            List of active instance key strings.
        """
        if not self.player:
            return []
        return self.player.active_keys()

    def provider_for_key(self, key: str | None) -> str | None:
        """Return the provider_id of the content last played into instance *key*.

        Args:
            key: Instance key (provider_id when split is on, ``"__shared__"``
                when off). None returns None.

        Returns:
            The provider_id last played into that window, or None if unknown.
        """
        if key is None:
            return None
        return self._key_provider.get(key)

    def resolve_key(self, provider_id: str | None, force_new_window: bool = False) -> str:
        """Public: the instance key a ``play()`` with these args would target.

        Lets callers map a play to its mpv window (e.g. watch-progress capture)
        without duplicating the split/force-new-window keying logic.
        """
        return self._resolve_instance_key(provider_id, force_split=force_new_window)

    def send_command(self, cmd: list, key: str | None = None) -> bool:
        """Send a raw mpv IPC command — thin wrapper over ``MPVPlayer.send_command``.

        Per the player-instance-keying rule, callers never touch MPVPlayer
        directly; this is the sanctioned seam for ad-hoc IPC (hotkeys,
        mini-player, future Wave-5 slices) that doesn't fit play/queue/stop.

        Args:
            cmd: mpv JSON IPC command list, e.g. ``["cycle", "pause"]``.
            key: Instance key to target; defaults to the most-recently-used key.

        Returns:
            True if delivered, False if no player is available or delivery failed.
        """
        if not self.player:
            return False
        return self.player.send_command(cmd, key=key)

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def cleanup(self):
        """Cleanup player resources"""
        if self.player:
            self.player.cleanup()

        # Every instance is being torn down — release all accounting state
        # (equivalent to reconciling against an empty alive-set).
        self.connection_accountant.reconcile([])
        logger.info("Player manager cleanup complete")
