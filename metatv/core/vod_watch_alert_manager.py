"""VodWatchAlertManager — detect new VOD content matching user-defined keyword rules.

Workers run in a ``ThreadPoolExecutor(max_workers=1)`` to stay within the
SQLite-lock limit.  All config writes and ``NotificationManager`` calls happen
on the Qt main thread via private signals (same pattern as ``EpgManager`` and
``SeriesMonitorManager``).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.notifications import NotificationManager


def _rule_id(rule: dict) -> str:
    """Stable identifier for a rule — the created timestamp (ISO) is unique per add."""
    return rule.get("created", "")


def _matches_rule(channel_name: str, detected_title: str | None,
                  channel_media_type: str, rule: dict) -> bool:
    """Return True if a channel matches a watch-for rule.

    Args:
        channel_name: Raw ChannelDB.name.
        detected_title: ChannelDB.detected_title (may be None for older rows).
        channel_media_type: ChannelDB.media_type ("movie", "series", "live", "unknown").
        rule: A vod_watch_alert rule dict from Config.

    Returns:
        bool: True when the keyword matches and the media_type gate passes.
    """
    match_type = rule.get("match_type", "any")

    # Media-type gate: skip live channels for VOD alerts regardless of rule type
    if channel_media_type == "live":
        return False

    if match_type == "movie" and channel_media_type != "movie":
        return False
    if match_type == "series" and channel_media_type != "series":
        return False

    keyword = (rule.get("text") or "").casefold().strip()
    if not keyword:
        return False

    # Match on detected_title first (prefix-stripped bare title), then full name.
    target = (detected_title or channel_name or "").casefold()
    return keyword in target


class VodWatchAlertManager(QObject):
    """Checks VOD watch-for rules against the channel corpus and fires notifications.

    Signals
    -------
    new_matches_found : pyqtSignal()
        Emitted on the main thread when at least one new match was recorded.
        Views connect to this to refresh their display.

    _notify_match : private pyqtSignal(str, str, str, str)
        Internal signal that marshals a single new match from the worker
        thread to the main thread.
        Args: (rule_created, channel_id, channel_name, rule_text)

    _notify_baseline : private pyqtSignal(str, object)
        Internal signal carrying a NEW rule's entire existing-match set in one
        go, so seeding it costs one config write and one refresh instead of one
        of each per match.
        Args: (rule_created, list[channel_id])
    """

    # Public signal — views connect to this to refresh their display
    new_matches_found = pyqtSignal()

    # Private signal — marshals worker→main thread
    _notify_match = pyqtSignal(str, str, str, str)  # rule_created, channel_id, ch_name, rule_text
    _notify_baseline = pyqtSignal(str, object)  # rule_created, list[channel_id]

    def __init__(
        self,
        db: "Database",
        config: "Config",
        notifications: "NotificationManager | None" = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.config = config
        self.notifications = notifications
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vod_watch_alert"
        )
        # Wire private signal to main-thread slot
        self._notify_match.connect(self._on_new_match)
        self._notify_baseline.connect(self._on_baseline_ready)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self) -> None:
        """Check every VOD watch-for rule against the full channel corpus.

        Intended to be called once on app startup (via ``QTimer.singleShot``)
        and after any provider channel load completes.
        Safe to call from any thread; actual work runs in the executor.
        """
        rules = self.config.get_vod_watch_alerts()
        if not rules:
            return
        self._executor.submit(self._worker_check_rules, rules)

    def baseline_rule(self, rule: dict) -> None:
        """Seed a freshly-added rule with what ALREADY matches, silently.

        A watch-for rule is forward-looking — the dialog that creates it is
        headed "Watch for new content" and promises an alert when matching
        content "appears on any of your sources" — so the catalogue as it
        stands the moment the rule is written is the rule's BASELINE, not a
        pile of news. Without this a new rule behaved as a perpetual search
        result: the owner's "Evil Dead" rule alerted on 102 existing rows
        (roughly eight distinct titles across languages and providers), each
        one a toast, a full config write and a refresh.

        The monitored-series half of this feature has always worked this way —
        ``series_monitor.set_baseline()`` is called the moment a series is
        monitored, so "new episodes" means new SINCE THEN. This is the same
        step for keyword rules.

        Safe to call from any thread; the scan runs in the executor.

        Args:
            rule: The rule dict just added to config.
        """
        self._executor.submit(self._worker_check_rules, [rule], None, True)

    def check_provider(self, provider_id: str) -> None:
        """Check rules against channels belonging to *provider_id* only.

        Called after a provider refresh so we scan the freshly-loaded corpus.
        Safe to call from any thread.
        """
        rules = self.config.get_vod_watch_alerts()
        if not rules:
            return
        self._executor.submit(self._worker_check_rules, rules, provider_id)

    def shutdown(self) -> None:
        """Shut down the executor without blocking the main thread."""
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Worker — runs in executor (NO widget/config access)
    # ------------------------------------------------------------------

    def _worker_check_rules(
        self, rules: list[dict], provider_id: str | None = None,
        baseline: bool = False,
    ) -> None:
        """Scan channels against every rule.

        Args:
            rules: The rules to scan for.
            provider_id: Restrict the scan to one source, or None for all.
            baseline: When True the hits are the rule's STARTING state, not
                news — they are collected and emitted once via
                ``_notify_baseline`` instead of one ``_notify_match`` per hit,
                so seeding costs one config write and no notifications. Same
                query and same matcher either way; only the reporting differs.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        try:
            with self.db.session_scope(commit=False) as session:
                repos = RepositoryFactory(session)

                # Scope to active/visible providers to avoid surfacing content
                # from disabled or expired sources.
                excluded_ids = set(repos.providers.get_hidden_provider_ids())

                q = session.query(
                    ChannelDB.id,
                    ChannelDB.name,
                    ChannelDB.detected_title,
                    ChannelDB.media_type,
                    ChannelDB.provider_id,
                ).filter(
                    ChannelDB.media_type.in_(["movie", "series"]),
                    ChannelDB.is_hidden.is_(False),
                )
                if provider_id is not None:
                    q = q.filter(ChannelDB.provider_id == provider_id)
                if excluded_ids:
                    q = q.filter(ChannelDB.provider_id.notin_(excluded_ids))

                channels = q.all()

        except Exception:
            logger.exception("vod_watch_alert: error querying channels")
            return

        for rule in rules:
            rule_created = _rule_id(rule)
            if not rule_created:
                logger.warning("vod_watch_alert: rule missing 'created' key, skipping")
                continue

            alerted_ids: set[str] = set(rule.get("alerted_ids") or [])
            baseline_ids: list[str] = []

            for (ch_id, ch_name, detected_title, media_type, _pid) in channels:
                if ch_id in alerted_ids:
                    continue  # already alerted — dedup
                if not _matches_rule(ch_name, detected_title, media_type, rule):
                    continue
                if baseline:
                    baseline_ids.append(ch_id)
                    continue
                logger.info(
                    f"vod_watch_alert: new match — rule '{rule.get('text')}' "
                    f"→ '{ch_name}' ({ch_id})"
                )
                # Marshal to main thread
                self._notify_match.emit(
                    rule_created, ch_id, ch_name or "", rule.get("text") or ""
                )

            if baseline:
                logger.info(
                    "vod_watch_alert: baselined rule '{}' with {} existing "
                    "match(es) — it will alert only on content that appears "
                    "from now on",
                    rule.get("text"), len(baseline_ids),
                )
                self._notify_baseline.emit(rule_created, baseline_ids)

    # ------------------------------------------------------------------
    # Main-thread slot
    # ------------------------------------------------------------------

    def _on_new_match(
        self,
        rule_created: str,
        channel_id: str,
        channel_name: str,
        rule_text: str,
    ) -> None:
        """Main-thread handler: record the match in config and fire a notification."""
        # Record channel_id in alerted_ids so we never re-alert the same channel
        self.config.record_vod_alert_match(rule_created, channel_id)

        if self.notifications:
            self.notifications.show(
                title=f"New match: ‘{rule_text}’",
                message=channel_name,
                type="info",
                auto_dismiss_ms=7000,
            )

        self.new_matches_found.emit()

    def _on_baseline_ready(self, rule_created: str, channel_ids: object) -> None:
        """Main-thread slot: seed a new rule's baseline in ONE config write.

        No notification is shown — nothing here is news by definition. The
        single ``new_matches_found`` emit lets the alert surfaces re-read the
        rule's (zero) unviewed count once, rather than once per match.
        """
        ids = list(channel_ids or [])
        if ids:
            self.config.baseline_vod_alert_matches(rule_created, ids)
        self.new_matches_found.emit()
