from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=620,
    version="0.101.0",
    date="2026-09-07",
    title="A stream the source is holding says so, and keeps trying",
    items=(
        "When a one-connection source holds a new stream until it frees the "
        "previous one, the status bar now counts the wait and names the "
        "source instead of showing a silent spinner.",
        "The player retries a held connection every ten seconds instead of "
        "waiting on it indefinitely.",
        "The player's own exit reason now reaches the log, so a stream that "
        "dies while opening is retried once as designed.",
    ),
    test_steps=(
        "Switch between two titles on the same one-connection source → the "
        "status bar reads \"Waiting for <source> to free the previous "
        "stream… Ns\" until video starts.",
        "The log carries \"mpv[…] exited rc=0 after …s (Quit)\" when you "
        "close the player.",
    ),
)
