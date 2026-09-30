from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=679,
    version="0.126.0",
    date="2026-09-29",
    title="A refused stream says why",
    items=(
        "When a source turns a stream away because the account is already "
        "using all of its connections (HTTP 509), the failure message now "
        "says so and names the episode instead of \"that channel.\"",
    ),
    test_steps=(
        "Play an episode on a one-connection source while it is in use "
        "elsewhere — the status line reads 'Nothing is playing: <episode> — "
        "the source is at its connection limit' and the toast names HTTP 509.",
        "Play a title whose stream simply never opens (no 509) — the old "
        "'busy or dead' message still appears.",
    ),
)
