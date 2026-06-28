from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=103,
    version="0.9.0",
    date="2026-06-28",
    title="Details pane refinements: double-click, middle-click, Watch Later, logos & genres",
    items=(
        "New setting — Settings → Playback → 'Default double-click action': choose "
        "whether a bare double-click resumes (when a saved position exists) or always "
        "starts from the beginning. The details Play button always starts from the "
        "beginning and Resume always resumes, independent of this setting.",
        "Middle-click a title in the channel list to do the OPPOSITE of your "
        "double-click default — a quick way to get the other behavior without the "
        "right-click menu.",
        "'Watch Later' (queue) graduated out of the slim icon rail to a clear, "
        "full-width labeled button directly under the Play/Resume row.",
        "Live channel logos now fill the same space as a movie poster — scaled and "
        "centered on the poster card instead of a tiny strip with a big empty gap "
        "below. Low-res logos are upscaled only modestly so they don't pixelate.",
        "Movie genres (and the rating/IMDb/TMDb/runtime badges) now wrap to the next "
        "line instead of running off the right edge of the details pane.",
    ),
    test_steps=(
        "Settings → Playback: confirm 'Default double-click action' shows two choices "
        "(Resume / Start from beginning), defaults to Resume; set it to 'Start from "
        "beginning' and save.",
        "With the default set to 'Start from beginning', double-click a "
        "partially-watched movie and confirm it starts at 0; switch the setting back "
        "to Resume, double-click again, and confirm it resumes from the saved position.",
        "With the default = Resume, MIDDLE-click a partially-watched movie and confirm "
        "it starts from the beginning (the opposite). Set the default = beginning, "
        "middle-click again, and confirm it RESUMES.",
        "Open a movie's details: confirm the details 'Play' button always starts from "
        "the beginning and 'Resume' always resumes, regardless of the setting above.",
        "Open a movie's details and confirm a full-width 'Watch Later' button sits "
        "directly under the Play/Resume row (NOT an icon in the left rail); click it "
        "and confirm it toggles in/out of the queue.",
        "Open a LIVE channel with a logo (e.g. FOX EAST): confirm the logo fills the "
        "poster area (centered on the card) rather than a small strip with empty space "
        "below, and the category/country line still shows beneath it.",
        "Open a movie with many genres (e.g. Cowboy Bebop) in a narrow details pane "
        "and confirm the genre chips wrap onto multiple rows instead of overflowing "
        "off the right edge.",
    ),
)
