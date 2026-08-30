from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=448,
    version="0.56.0",
    date="2026-08-29",
    title="The stream diagnostic stops blaming your connection",
    items=(
        "Every failed response was reported as \"Couldn't reach the stream\". "
        "For most of them that is backwards: the server answered, so it is up, "
        "reachable, and simply refusing.",
        "It now says which. A refusal names the cause and what to do about it: "
        "a 403 is usually your account's connection limit, so stop whatever "
        "else is playing; a 404 means the provider removed the title and a "
        "source refresh will clear it; a 405 means the server would not serve "
        "that request shape, and the stream itself may well play normally.",
        "Only a genuine failure to connect - no answer at all - still reads as "
        "unreachable.",
        "The Tools menu had two diagnostics entries and one of them did "
        "nothing. It is gone; the working one is now called Stream "
        "diagnostics, matching the window it opens.",
        "Tools > Filters did nothing either, and it was not only a menu entry: "
        "the \"Manage content filters\" item in a title's details pane fed into "
        "the same dead end. Both now open Global Exclusions, which is what "
        "they are called from here on.",
    ),
    test_steps=(
        "Open Tools and confirm there is one diagnostics entry, named Stream "
        "diagnostics, and no plain \"Diagnostics\" item.",
        "Select a channel, run Stream diagnostics on a stream that fails, and "
        "confirm the headline names a refusal with a cause and next step "
        "rather than \"Couldn't reach the stream\".",
        "Pull your network cable or disable wifi, run it again, and confirm "
        "that case still reads as unreachable.",
        "Open Tools > Global Exclusions and confirm the dialog opens.",
        "Right-click a category prefix in a title's details pane, choose "
        "\"Manage Global Exclusions…\", and confirm the same dialog opens.",
    ),
)
