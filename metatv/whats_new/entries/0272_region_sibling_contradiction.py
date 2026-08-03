"""What's New entry for the sibling-region fix: a title's region was being
filled from unrelated same-name releases, mislabelling English and Arabic
releases as German and inventing a language tag to match."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=272,
    title="Titles are no longer mislabelled with another release's country",
    items=(
        "Some titles showed a country that had nothing to do with them — an "
        "English \"Aladdin\" listed as German, and an Arabic one listed as "
        "German too.",
        "When a title's own name doesn't say where it's from, MetaTV borrows "
        "the country from other copies of the same title. That helps when a "
        "listing genuinely says nothing — but it was also overriding listings "
        "that DID say something. \"EN\" means English, and there is no country "
        "called EN, so an empty country there is a fact, not a gap to fill.",
        "The borrowed country was whichever one happened to be most common "
        "across every copy sharing the title, so in a library with lots of "
        "German content, German won — for titles that were never German.",
        "It got worse from there: the wrong country then produced a wrong "
        "language tag, so the title looked German in filters and fed that back "
        "into recommendations.",
        "A listing that states its own language or country now keeps it. "
        "Listings that genuinely say nothing (e.g. \"MULTI\") still borrow, "
        "which is what the feature is for.",
        "Titles already mislabelled are corrected the next time the library "
        "re-scans names — an existing wrong country isn't erased retroactively.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Find a title whose name starts with a language marker like \"|EN|\" "
        "but which shows an unrelated country (German, say) in the details "
        "pane. Refresh the source so names are re-scanned; the wrong country "
        "is gone rather than replaced with a different wrong one.",
        "Check the same title's Tags section — the invented language tag "
        "(German, for an English title) no longer appears.",
        "Confirm the feature still works where it should: a title whose name "
        "carries no language or country marker at all still picks up a country "
        "from its other copies.",
        "Confirm an agreeing case is untouched: an \"|IT|\" title still shows "
        "IT.",
    ),
)
