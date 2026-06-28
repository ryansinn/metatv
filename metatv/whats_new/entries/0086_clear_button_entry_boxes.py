from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=86,
    version="0.9.0",
    date="2026-06-28",
    title="Inline × clear button now on all text-entry boxes (not just filter/search)",
    items=(
        "The inline × clear button (appears when a box has text) is now present on all "
        "editable single-line text-entry fields — extended beyond the filter/search boxes "
        "standardized in v0.9.0 (What's New #79).",
        "Newly covered entry boxes: EPG 'Track a show' keyword box; EPG Manage 'Add filler "
        "pattern' box; EPG category code picker; Provider add/edit name, URL, username, "
        "password, and EPG override URL; Add Source dialog name and URL fields; Settings "
        "mpv extra-arguments, TMDb API key, TMDb language, and OMDb API key; Preferences "
        "version-prefix entry; VOD watch-alert keyword box.",
        "A self-enforcing source-scan test (tests/test_clear_button_standard.py) now "
        "catches any future QLineEdit that is missing the clear button or a read-only flag.",
    ),
    test_steps=(
        "Open the EPG view → Watchlist tab → click '+ Track a show' → type a word in the "
        "keyword box → an inline × appears inside the right edge → click it → box clears.",
        "Open the EPG view → Manage tab → type a word in 'Add filler pattern…' box → inline "
        "× appears → click it → box clears.",
        "Open Add Source (sidebar + button) → type in the Name field → inline × appears → "
        "click it → name clears; repeat for the URL field.",
        "Open Settings → TMDb/OMDb section → type text in an API key field → inline × "
        "appears → click it → field clears.",
    ),
)
