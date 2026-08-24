from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=347,
    version="0.41.0",
    date="2026-08-24",
    title="A fourth theme: Gruvbox",
    items=(
        "Settings → Interface → Appearance → Theme now offers Gruvbox "
        "alongside Midnight, Graphite and Daylight — the warm retro palette, "
        "with its own browns, creams and muted accents rather than a recolour "
        "of an existing theme.",
        "It uses the published Gruvbox values directly: the twelve greys from "
        "bg0_h to fg1 are the real ones, and every accent's solid and hover "
        "state is Gruvbox's own \"normal\" and \"bright\".",
        "Switching to it applies immediately, like the other themes — no "
        "restart.",
    ),
    test_steps=(
        "Settings → Interface → Appearance → Theme → pick Gruvbox → OK. The "
        "whole app recolours immediately: warm brown backgrounds, cream text, "
        "no restart needed.",
        "Check the channel list — titles read cream, the quality badge is "
        "Gruvbox yellow, and the language badge is still legible on both a "
        "normal and a selected row.",
        "Select a row → the selection tint is warm, and every badge on the "
        "selected row is still readable against it.",
        "Open the details pane → section headers, the region chips under "
        "\"Also Available\" and the \"+ N more\" link all read clearly.",
        "Open the preview overlay (⤢ on Similar Titles) → it stays the same "
        "dark cinema panel it is in every theme, and its text is legible.",
        "Switch back to Midnight → everything returns with no leftover Gruvbox "
        "patches anywhere.",
    ),
)
