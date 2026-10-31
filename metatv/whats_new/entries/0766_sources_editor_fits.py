from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=766,
    version="0.203.0",
    date="2026-10-31",
    title="The Sources editor fits narrower windows",
    items=("In a narrower window the Sources editor used to cut off its right edge "
           "(\"Refresh Guid…\", \"Refresh A…\"). Its rows now wrap instead: the action "
           "buttons, Account Info and the Save/Discard footer fold onto a second line, and "
           "long server addresses shorten in the middle with the full address on hover.",
           "Clicking the auto-detected guide address now confirms the copy the same way the "
           "server addresses do.",
           "The adult-content option now reads \"Treat every channel as adult\"; the full "
           "explanation is on its tooltip.",),
    test_steps=("Open Sources and narrow the window until the editor is tight — the action "
                "buttons and the footer wrap onto a second line and nothing is cut off at the "
                "right on the Summary, Connection or Settings tab.",
                "On Connection, hover a shortened server address — the tooltip shows the full "
                "address; click it and paste somewhere — the full address was copied.",
                "On Settings, click the auto-detected guide URL — \"Copied ✓\" appears and the "
                "full URL is on the clipboard.",
                "Widen the window again — the editor looks as before, with the action buttons "
                "on one right-aligned row.",),
)
