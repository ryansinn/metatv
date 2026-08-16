"""What's New entry: the EPG guide URL is now derived from live credentials on
every fetch, not cached — and the fetch itself now tries every configured host,
not just the first one."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=316,
    title="Re-subscribing to a source no longer silently kills its guide",
    items=(
        "The auto-detected EPG guide URL was built once, the first time a "
        "source ever fetched, and cached forever — so renewing a "
        "subscription with a new username/password on the SAME source left "
        "the guide pointed at the OLD account's credentials, which can never "
        "work again. A real case: the guide went dead for 11 days behind a "
        "green \"AUTODETECTED\" badge that was quietly showing a URL built "
        "from a canceled account. The URL is now derived fresh from the "
        "source's current credentials every time it's needed, so a "
        "credential change is picked up on the very next fetch — nothing to "
        "clear or reset.",
        "The guide fetch itself now tries every one of a source's "
        "configured hosts in reliability order (the same tracker every other "
        "fetch already uses) instead of only ever trying the first one — so "
        "a down or low-ranked host no longer blocks the whole guide. A host "
        "only gets skipped for a connection error, an HTTP error, or a "
        "payload that doesn't parse into any programmes; a guide that "
        "downloads fine but is already out of date is accepted as-is (an "
        "XMLTV guide is often hundreds of thousands of programmes — "
        "re-downloading the same stale content from every other host would "
        "be a real cost for no benefit).",
        "The source editor's auto-detected URL and freshness line now always "
        "reflect the CURRENT credentials, never a stale cached value.",
    ),
    version="0.32.0",
    date="2026-08-16",
    test_steps=(
        "Open a source's editor, note the auto-detected EPG URL, then change "
        "its username/password and save. Reopen the editor — the "
        "auto-detected URL shown (and copied by the click-to-copy line) "
        "must reflect the NEW credentials, not the old ones.",
        "On a source with more than one configured host, temporarily make "
        "the first host unreachable (or check the logs after a real host "
        "outage) and click \"Refresh Guide\". The refresh should still "
        "succeed by trying the source's other configured hosts instead of "
        "failing outright.",
    ),
)
