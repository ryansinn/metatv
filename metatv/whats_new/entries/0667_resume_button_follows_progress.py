from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=667,
    version="0.120.0",
    date="2026-09-11",
    title="Resume appears as soon as your position is saved",
    items=(
        "The details pane's Resume button used to be drawn once, from what the pane knew "
        "when you opened the title — so a position saved after you closed the player never "
        "showed the Resume option until the list was reloaded.",
        "Resume now follows the saved position. When you close the player, the button "
        "appears within about 20 seconds (as the checkpoint captures your final position). "
        "If you navigate away and come back, Resume is still offered.",
        "The same fix applies to episodes: close an episode's player and its details show "
        "Resume at the saved position.",
    ),
    test_steps=(
        "Play a movie for about a minute, then close the player. Within about 20 seconds, "
        "the details pane should show 'Resume 1:0x' without you having to click the title again.",
        "Click a different title in the list and come back to the movie. Resume should "
        "still be offered.",
        "Play an episode for about a minute and close the player. The episode's details "
        "should show Resume at the saved position.",
    ),
)
