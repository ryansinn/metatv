"""What's New entry: the details pane now reflects rating/favorite/suppression
changes made from other views (Watch Queue, sidebar, channel list) without
needing to re-select the title."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=311,
    title="Details pane now updates live when you act from elsewhere",
    items=(
        "Liking, disliking, favoriting, or marking a title \"Not Interested\" "
        "from the Watch Queue, sidebar, or channel list left the details pane's "
        "buttons frozen if that title was already open there — its action state "
        "was only ever loaded once, on selection.",
        "A single publish point now announces every such change; the details "
        "pane (and the channel-list row) re-reads the real state right away, so "
        "the buttons update immediately no matter which view the change came "
        "from.",
    ),
    version="0.28.0",
    date="2026-08-15",
    test_steps=(
        "Open a movie's details pane (so its Like/Dislike/Favorite buttons are "
        "visible), then dislike the same title from the Watch Queue (or channel "
        "list) without re-selecting it in the details pane — the details pane's "
        "Dislike button lights up on its own.",
        "With the same title still open, favorite it from the channel list — "
        "the details pane's favorite star fills in without re-selecting the "
        "title.",
    ),
)
