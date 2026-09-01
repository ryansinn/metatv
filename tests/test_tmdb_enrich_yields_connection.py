"""TMDb enrichment must yield the provider connection to playback.

Owner, 2026-09-01: *"this need to play 4 times to get it to play never used to
happen"* and *"I never used to even have to hit Play anyway, it used to just
play"*.

Their log shows the SAME url alternating within seconds:

    02:20:54  validate -> HTTP 500   02:21:14  validate -> HTTP 206
    02:21:20  validate -> HTTP 500   02:21:27  validate -> HTTP 206

That is contention, not a broken stream. Most accounts allow ONE connection,
and ``tmdb_enrichment_manager`` calls ``get_vod_info`` against the same provider
continuously — its genre backfill appears in every log the owner sent — while
being invisible to :class:`ConnectionAccountant`.

#622 fixed exactly this for ``series_monitor`` and left this manager behind;
``metadata_manager`` and ``epg_manager`` are still unenrolled.
"""

from __future__ import annotations

from unittest.mock import MagicMock



def _manager(accountant=None):
    from metatv.core.tmdb_enrichment_manager import TmdbEnrichmentManager
    m = TmdbEnrichmentManager.__new__(TmdbEnrichmentManager)
    m._accountant = accountant
    return m


class TestEnrichmentIsOutrankedByRealWork:

    def test_playback_evicts_an_enrichment_batch(self):
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.player_manager import PLAYBACK_PREEMPTS
        from metatv.core.tmdb_enrichment_manager import ENRICH_KIND, ENRICH_PREEMPTS

        acct = ConnectionAccountant(capacity_resolver=lambda p: 1)
        m = _manager(acct)
        assert m._acquire_slot("p1", "enrich-1") is True
        assert acct.acquire("p1", "playback", "play-1",
                            preempt_kinds=PLAYBACK_PREEMPTS).granted, (
            "playback must evict a background enrichment batch, not lose the "
            "connection to it")
        assert ENRICH_PREEMPTS == (), "enrichment must displace nothing"
        assert ENRICH_KIND == "monitor"

    def test_enrichment_stands_down_while_playback_holds(self):
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.player_manager import PLAYBACK_PREEMPTS

        acct = ConnectionAccountant(capacity_resolver=lambda p: 1)
        acct.acquire("p1", "playback", "play-1", preempt_kinds=PLAYBACK_PREEMPTS)
        m = _manager(acct)
        assert m._acquire_slot("p1", "enrich-1") is False, (
            "enrichment took the connection while a stream was playing — this "
            "is what made the pre-flight probe return HTTP 500")

    def test_a_download_also_outranks_enrichment(self):
        from metatv.core.connection_accountant import ConnectionAccountant
        from metatv.core.download_manager import DOWNLOAD_PREEMPTS

        acct = ConnectionAccountant(capacity_resolver=lambda p: 1)
        m = _manager(acct)
        m._acquire_slot("p1", "enrich-1")
        assert acct.acquire("p1", "download", "dl-1",
                            preempt_kinds=DOWNLOAD_PREEMPTS).granted


class TestEnrolmentDoesNotBreakEnrichment:

    def test_an_unwired_manager_still_enriches(self):
        """No accountant (tests/headless) must not disable the backfill."""
        m = _manager(None)
        assert m._acquire_slot("p", "h") is True
        m._release_slot("p", "h")

    def test_the_slot_is_released(self):
        from metatv.core.connection_accountant import ConnectionAccountant
        acct = ConnectionAccountant(capacity_resolver=lambda p: 1)
        m = _manager(acct)
        m._acquire_slot("p1", "enrich-1")
        m._release_slot("p1", "enrich-1")
        assert acct.in_use("p1") == 0, "a leaked slot would block all playback"

    def test_a_broken_accountant_does_not_stop_enrichment(self):
        """Bookkeeping failure must not cost the user their backfill."""
        acct = MagicMock()
        acct.acquire.side_effect = RuntimeError("boom")
        m = _manager(acct)
        assert m._acquire_slot("p", "h") is True
        acct.release.side_effect = RuntimeError("boom")
        m._release_slot("p", "h")   # must not raise
