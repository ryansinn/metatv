from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=755,
    version="0.192.0",
    date="2026-10-20",
    title="Sources are added in the Sources screen",
    items=("Add Source now opens the Sources screen on a blank source, the same form "
           "you edit sources on, with the icon picker and room for several server "
           "addresses. Test Connection checks every address and explains a failure in "
           "words. Add Source turns on once a test passes; changing the username, "
           "password or addresses needs a new test.",
           "Opening MetaTV with no sources places you on that form.",
           "Fixed: passwords containing &, # or + could never pass the connection test.",),
    test_steps=("Open Sources and press Add Source — a blank source opens with Add Source "
                "greyed out. Enter a server address, username and password and press Test "
                "Connection: on success Add Source turns on; pressing it adds the source "
                "and starts loading its channels.",
                "Enter a wrong password and test — it fails and Add Source stays off. "
                "Correct the password and test again — it passes without restarting MetaTV.",
                "Start MetaTV with no sources — it opens on the blank Add Source form."),
)
