"""What's New entry: one-time sweep clearing wrongly-inherited regions, plus
scroll preservation across every sidebar-section refresh."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=275,
    title="Wrong country labels cleaned out, and lists stop jumping to the top",
    items=(
        "Around 78,000 titles carried a country that nothing about them "
        "supported — English and Arabic films labelled German, Apple TV+ and "
        "Netflix titles handed whichever country happened to be most common in "
        "your library. A one-time cleanup runs on next launch and removes them.",
        "It only ever REMOVES a wrong country, never guesses a different one. "
        "No country is honest; a made-up one is how this started.",
        "Countries that a title genuinely states are kept. A Disney+ title "
        "under a \"UK|\" category keeps UK; a Prime title under \"US|\" keeps "
        "US. Only the borrowed ones go.",
        "The bogus country also produced a bogus LANGUAGE — an English film "
        "tagged German purely because it had been given a German country. "
        "Those are removed too, so the title stops showing up under the wrong "
        "language in filters and recommendations.",
        "Separately: refreshing a sidebar list no longer scrolls you back to "
        "the top. Marking one item watched deep in the Watch Queue used to "
        "rebuild the section and lose your place, which made bulk tidying "
        "miserable. Your scroll position is now kept.",
    ),
    version="0.26.0",
    date="2026-08-03",
    test_steps=(
        "Launch the app and watch for the \"Correcting mislabelled regions\" "
        "progress step. Check the logs for \"cleared N mislabelled regions\".",
        "Open a title you know was wrongly labelled (an English or Arabic film "
        "showing a German flag/region). The region is now blank rather than "
        "wrong, and its Tags no longer list the wrong language.",
        "Confirm legitimate regions survived: find a title whose own category "
        "starts with a country marker (e.g. \"US| PRIME\", \"UK| DISCOVERY +\") "
        "— it still shows that country.",
        "Scroll deep into the Watch Queue in the sidebar, then mark an item "
        "watched. The list stays where you were instead of jumping to the top.",
        "Do the same in Recommended and Favorites — same result.",
        "Relaunch: the region cleanup does NOT run a second time.",
    ),
)
