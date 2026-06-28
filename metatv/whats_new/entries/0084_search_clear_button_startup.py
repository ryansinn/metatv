from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=84,
    version="0.8.0",
    date="2026-06-28",
    title="Search clear (×) shows immediately when a search term is restored at startup",
    items=(
        "When the app reopens with a remembered search term, the clear (×) button now"
        " appears right away instead of staying hidden until you edit the box.",
    ),
    test_steps=(
        "Type a term in the channel search box, then quit and relaunch the app (with"
        " 'remember search' enabled). The box reopens with your term AND the clear (×)"
        " button visible — clicking × clears it without needing to edit first.",
    ),
)
