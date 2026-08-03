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
        "\"Other versions\" chips in the details pane put a source symbol on "
        "every chip even when there was only one source to distinguish — the "
        "same symbol repeated down the whole list, crowding out the region and "
        "quality labels that actually differ. The symbol now appears only when "
        "the versions genuinely span more than one source; the source is still "
        "named in each chip's tooltip either way.",
        "Rows in the results list ran flush to both edges, so text on the right "
        "sat under the vertical scrollbar. Rows now have matching breathing "
        "room on both sides.",
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
        "With ONE source configured, open a title that has several versions — "
        "the \"Also available as\" chips show region/quality only, with no "
        "repeated source symbol. Hovering a chip still names the source in the "
        "tooltip.",
        "With TWO or more sources configured, open a title whose versions come "
        "from both — the source symbol reappears on the chips, because it now "
        "distinguishes something.",
        "Scroll the results list with the vertical scrollbar visible — "
        "right-aligned text (year, language, quality) sits clear of the "
        "scrollbar instead of underneath it, and the left edge has matching "
        "space.",
    ),
)
