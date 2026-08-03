"""What's New entry for the 2026-08-02 owner UX-pass batch: a channel-list
banner stranded over unrelated views, the Sources "Add Source" CTA rendering as
dim grey text, and the series monitor fetching on into interpreter shutdown."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=266,
    title="Three fixes from the UX pass: stranded banner, invisible Add Source, noisy shutdown",
    items=(
        "The channel-list banners (\"N hidden by Global Exclusions\", the "
        "search-filter and unavailable notices, the zero-sources prompt) live "
        "beside the channel list rather than inside any view, so switching to "
        "Sources or another view left them stranded on screen — reporting a "
        "channel count over a view it had nothing to do with. Switching views "
        "now clears them.",
        "\"+ Add Source\" in the Sources header was borrowing the style of a "
        "small de-emphasised icon button, so it rendered as dim grey text with "
        "no button shape — easy to read as disabled, and it is the one control "
        "someone with no sources has to find. It is now a filled accent button.",
        "The series monitor kept fetching episode lists after the app had "
        "already closed its database, logging an error per monitored series on "
        "every exit. Shutdown now signals the in-flight check to stop instead "
        "of only refusing new ones.",
    ),
    version="0.25.0",
    date="2026-08-02",
    test_steps=(
        "Open the channel list with Global Exclusions active so the yellow "
        "\"N hidden by Global Exclusions — show\" banner appears, then click "
        "Sources in the sidebar — the banner is gone, not floating above the "
        "Sources header.",
        "Repeat with the search-filter banner: search to hide some results, "
        "switch to EPG or Discover, confirm nothing is stranded, then switch "
        "back to the channel list and confirm the banner returns.",
        "Open Sources — \"+ Add Source\" top-right is a filled accent button "
        "with clearly readable text, obviously clickable rather than greyed "
        "out. Switch theme in Settings and reopen Sources: it stays legible in "
        "all three themes.",
        "With at least one monitored series, quit the app and check "
        "~/.config/metatv/logs/ — no \"cannot schedule new futures after "
        "interpreter shutdown\" errors after \"Database connection closed\".",
    ),
)
