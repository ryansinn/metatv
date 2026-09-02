"""Provider connection-test methods, extracted from ``main_window_providers.py``.

Isolation, not line count: this module owns exactly the "is this provider
reachable right now" concern — the startup sweep (`test_all_providers`), the
per-provider probe (`test_provider_connection`), and the result handler
(`on_connection_test_result`) — separate from the CRUD/refresh lifecycle that
fills the rest of ``main_window_providers.py``. Split out to keep that file
under its ``tests/code_health_baseline.json`` pin when the startup-thread fix
below added a second method.

Not to be confused with ``core/provider_probe.py`` (URL health-check scoring
for the editor's "test all URLs" button) — this module drives the SAME
``ProviderTestThread``/`on_connection_test_result` path the app has always
used for the launch-time connectivity sweep and manual reconnect checks.
"""

from __future__ import annotations

from loguru import logger

from metatv.core.repositories import RepositoryFactory


class _ProviderConnectivityMixin:
    """Provider connection-test methods mixed into :class:`MainWindow`."""

    def test_all_providers(self):
        """Test connection for all active providers on startup.

        The listing read used to run synchronously in ``MainWindow.__init__``,
        opening a NEW pooled connection while startup workers already had the
        DB busy — a sampled 2.3s main-thread stall (watchdog, 2026-09-02).
        Routed through the ``_run_query`` seam: the ``get_all`` read + its
        ``to_model`` conversion happen in the executor; only the per-provider
        test kickoff (already async via ``ProviderTestThread``) runs back on
        the main thread in :meth:`_on_test_all_providers_loaded`.
        """
        self._run_query(
            lambda repos: [
                repos.providers.to_model(p)
                for p in repos.providers.get_all(active_only=True)
            ],
            self._on_test_all_providers_loaded,
            on_error=lambda exc: logger.warning(
                f"test_all_providers: could not load providers to test: {exc}"
            ),
        )

    def _on_test_all_providers_loaded(self, providers: list) -> None:
        """Main-thread slot: kick off a connection test per provider.

        Args:
            providers: Plain ``Provider`` domain objects (via
                ``ProviderRepository.to_model`` — never ORM) loaded off the
                main thread by :meth:`test_all_providers`.
        """
        for provider in providers:
            self.update_provider_status(provider.id, "testing")
            self.test_provider_connection(provider.id)

    def test_provider_connection(self, provider_id: str):
        """Test connection to a specific provider"""
        session = self.db.get_session()
        try:
            from metatv.core.provider_loader import ProviderTestThread

            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(provider_id)
            if not db_provider:
                return

            # Start test in background
            test_thread = ProviderTestThread(
                db_provider.type,
                db_provider.url,
                db_provider.username,
                db_provider.password
            )
            test_thread.result.connect(
                lambda success, msg, pid=provider_id: self.on_connection_test_result(pid, success, msg)
            )

            # Keep thread alive
            self.active_threads.append(test_thread)
            test_thread.finished.connect(
                lambda: self.active_threads.remove(test_thread) if test_thread in self.active_threads else None
            )

            test_thread.start()
        finally:
            session.close()

    def on_connection_test_result(self, provider_id: str, success: bool, message: str):
        """Handle connection test result"""
        logger.info(f"Provider {provider_id} test result: {'online' if success else 'offline'} - {message}")
        self.update_provider_status(provider_id, "online" if success else "offline")
