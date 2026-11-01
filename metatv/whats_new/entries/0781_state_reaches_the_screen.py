from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=781,
    version="0.217.0",
    date="2026-11-01",
    title="Watched, favourite, queue and alert changes show everywhere at once",
    items=("Marking a film watched or unwatched from the list now updates the details pane too — "
           "its watched badge and Resume button no longer show the old state.",
           "An episode's Favourite and Queue buttons in the details pane now change when you click "
           "them, and changes made in the series tree reach the pane.",
           "Favouriting an episode in the details pane updates the series tree's menu.",
           "Setting an alert with the bell in a channel's schedule updates Watch Alerts in the "
           "sidebar straight away.",),
    test_steps=("Select a film so the details pane shows it, then right-click it in the list → "
                "Mark as Watched — the poster's watched check appears at once.",
                "Open a series, select an episode, click Favourite in the details pane — the button "
                "changes; right-click the episode in the tree — it offers Unfavorite.",
                "Click Watch Queue for the episode in the details pane — the button changes.",
                "Select a live channel with a schedule, click a programme's bell — Watch Alerts "
                "in the sidebar lists it without switching views.",),
)
