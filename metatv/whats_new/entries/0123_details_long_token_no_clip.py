from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=123,
    version="0.9.0",
    date="2026-06-29",
    title="Details: titles with a long release-name/URL no longer push the pane off-screen",
    items=(
        "Follow-up to the poster fix: some specific variants of a title still pushed "
        "the poster, the Play / Watch Later buttons, and the right-hand metadata past "
        "the edge of the details pane while other variants of the SAME title were fine.",
        "Cause: those variants had a long 'word' with no spaces in their description, "
        "tagline, or other text — e.g. a scene-release name like "
        "'A.Long.Title.1998.1080p.BluRay.x265-GROUP' or a URL. A wrapping text label "
        "can only break at spaces, so a no-space token made the whole pane as wide as "
        "that token and everything else got laid out off the right edge.",
        "Now every wrapping text label in the details pane (overview, tagline, cast & "
        "crew, technical details, recommendation reason, live channel info) breaks such "
        "tokens onto the next line and stays inside the pane — so the layout is the same "
        "for every variant regardless of how messy a provider's text is.",
    ),
    test_steps=(
        "Open a title whose details previously overran the right edge for only SOME of "
        "its sources (e.g. Cowboy Bebop's ProSat variant). Confirm the poster, the Play "
        "and Watch Later buttons, and the title/year all stay inside the pane.",
        "Click through the variant chips under 'Also available as' for that title: every "
        "variant now fits the pane the same way (none pushes content off the right edge).",
        "Open a title whose overview/description contains a long no-space token or a URL: "
        "the text wraps onto multiple lines within the pane instead of widening it.",
        "Drag the details pane narrower and wider: all text reflows within the pane at "
        "every width.",
    ),
)
