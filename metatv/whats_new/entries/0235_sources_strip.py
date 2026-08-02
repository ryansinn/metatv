from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=235,
    version="0.20.0",
    date="2026-08-02",
    title="Sources moved out of the sidebar into a status strip + manager",
    items=(
        "The Sources sidebar section is gone. In its place: a compact status "
        "strip pinned above Settings showing 'N active / M expiring' plus a "
        "Refresh All button. Click the strip to open the new full-window "
        "Sources manager — every source listed on the left, the selected "
        "source's configuration and actions (refresh, analyze, toggle "
        "active, EPG refresh) in the center.",
    ),
    test_steps=(
        "Look at the bottom of the sidebar, above Settings — a 'Sources' "
        "strip shows an active/expiring summary and a ⟳ Refresh All button.",
        "Click the strip → the Sources manager view opens with every source "
        "listed on the left.",
        "Click a source on the left → its configuration appears in the "
        "center; edit and Save → the strip's summary and the row update.",
        "Click ⟳ Refresh All on the strip → sources refresh via the same "
        "queue as before; the button shows a busy state while it runs.",
    ),
)
