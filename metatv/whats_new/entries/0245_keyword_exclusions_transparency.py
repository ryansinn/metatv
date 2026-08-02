"""What's New entry for Global Exclusions keyword transparency (mirror-not-cage)."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=245,
    title="Keyword exclusions are countable and recoverable",
    items=(
        "Every keyword row in Global Exclusions now shows a live count of how "
        "many channels it matches (e.g. \"wrestling — 412 channels\"), computed "
        "in the background so the dialog never freezes on a large library. A "
        "keyword that matches nothing is clearly marked \"no matches\" instead "
        "of just quietly doing nothing — an easy way to catch a typo.",
        "The channel list's filter bar gains a 🔤 \"N hidden by keywords — "
        "show\" segment, exactly like the existing 🔒 Global Exclusions and ⚠ "
        "unavailable segments. Click it to reveal what your keyword list is "
        "hiding for that one view — nothing is deleted, and your settings are "
        "never changed by looking.",
    ),
    version="0.22.0",
    date="2026-08-02",
    test_steps=(
        "Open Global Exclusions → Keywords → add a keyword → after a moment "
        "its row shows \"— N channels\" (not stuck on \"counting…\").",
        "Add a keyword you know matches nothing (e.g. \"zzzznomatch\") → its "
        "row reads \"— no matches\", visually muted.",
        "Save, then browse to a view where that keyword hid results → the "
        "gold filter bar shows a \"🔤 N hidden by keywords — show\" segment.",
        "Click that segment → the previously hidden titles appear for this "
        "view only; search or change filters → the segment's hidden set is "
        "hidden again (your keyword list itself is untouched).",
        "Click the × on a keyword row in the dialog → the row disappears; "
        "click OK → that keyword no longer hides anything.",
    ),
)
