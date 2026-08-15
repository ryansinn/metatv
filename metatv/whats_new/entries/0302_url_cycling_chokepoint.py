"""What's New entry: URL cycling now has one definition, and every cycling
call actually teaches the reliability ranker something."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=302,
    title="Slow/failing sources now actually get demoted",
    items=(
        "Every source with backup URLs cycles through them on failure, but "
        "five of the seven places that did this (get_categories, "
        "fetch_series_info, fetch_vod_info, get_server_info, "
        "fetch_account_info) never recorded what happened — a chronically "
        "slow or failing host could sit at the top of the reliability ranking "
        "forever, because nothing ever told it otherwise.",
        "All seven now share one recorder (UrlCycler). The two that already "
        "recorded outcomes (channel refresh, stream-failover) only tracked "
        "success/failure counts — timestamps never moved, so Sources never "
        "showed an accurate last-success/last-failure time. Both are fixed "
        "at the same chokepoint.",
        "Also fixed along the way: persisting those stats to disk could "
        "silently no-op due to a SQLAlchemy quirk (mutating the JSON blob's "
        "dicts in place before reassigning made old and new compare equal, "
        "so the database write was skipped entirely) — counts and timestamps "
        "now reliably survive a restart.",
    ),
    version="0.27.1",
    date="2026-08-15",
    test_steps=(
        "Add a source with two alternate URLs (Settings → source → "
        "Connection tab). Refresh the source. In the URL list, the tried URL "
        "shows an updated success count and a 'last ok' date.",
        "Edit one URL to a bad host, refresh again — that URL's failure "
        "count and last-failure time update; the working URL keeps its "
        "success stats.",
        "Restart the app and reopen the source's Connection tab — the "
        "success/failure counts and last-success/last-failure times from "
        "before the restart are still shown (proves the DB write actually "
        "persisted, not just an in-memory count).",
    ),
)
