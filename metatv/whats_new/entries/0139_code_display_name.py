from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=139,
    version="0.9.0",
    date="2026-07-21",
    title="Prefix codes show their human name, not a bare code",
    items=(
        "A channel's prefix chip and the 'Also available as' version chips now show "
        "the readable name plus the code — e.g. \"Arabic (AR)\" for a language code, "
        "\"United States (US)\" for a place — instead of a bare, ambiguous \"AR\".",
        "This uses one shared resolver so a language code (AR → Arabic) is never "
        "rendered as a place, pairing with the AR = Arabic classification fix.",
    ),
    test_steps=(
        "Open an Arabic \"AR\" title's details: the code chip beside the title reads "
        "\"Arabic (AR)\" — the language name, not a bare \"AR\" and not \"Argentina\".",
        "Open a title with an ARG (Argentina) or US version: the version chip reads "
        "\"Argentina (ARG)\" / \"United States (US)\" — place codes still resolve to places.",
        "A title with an unrecognized prefix still shows the raw code (no crash, no "
        "empty label).",
    ),
)
