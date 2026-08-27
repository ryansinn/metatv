from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=382,
    version="0.41.0",
    date="2026-08-26",
    title="Put the upcoming programmes away, and one row height for the whole sidebar",
    items=(
        "Watch Alerts' EPG group now has an UPCOMING sub-heading over the "
        "programmes that have not started yet. Click it to fold them away and "
        "keep just your alerts and what is on right now - the section shrinks "
        "to match, so the space goes to whatever is below it.",
        "What is on now has no heading of its own. It is at the top where it "
        "always was, and a label there would cost a row to say what you can "
        "already see.",
        "While it is folded, the heading carries a chip showing when the next "
        "one starts - so putting the list away does not cost you the one fact "
        "you were keeping it open for. It disappears again when you expand.",
        "The choice is remembered, and a guide refresh no longer re-opens it.",
        "Every sidebar section now draws its content rows at the same height. "
        "Watch Alerts sized its rows from the font's full line box so "
        "descenders could not clip; the other sections sized theirs from their "
        "contents and stayed at a fixed height whatever the font. Above a 13px "
        "interface font that showed as two different row heights in one "
        "sidebar - 6px apart at the largest sizes.",
    ),
    test_steps=(
        "Open Watch Alerts with several EPG matches. Programmes that have not "
        "started are now under an UPCOMING heading with a count, indented one "
        "step under EPG.",
        "Click the UPCOMING heading - those rows fold away, the count stays, "
        "and the Watch Alerts section gets visibly shorter.",
        "A time chip appears at the right of the UPCOMING heading. It must "
        "read the same time the first row under it showed before you "
        "collapsed, and must vanish when you expand again.",
        "Check the section below Watch Alerts - it should grow into the space "
        "that was released.",
        "Wait for the guide to refresh, or switch views and back - UPCOMING "
        "must still be collapsed.",
        "Click UPCOMING again - every programme comes back in the same order.",
        "Restart the app - the collapsed or expanded state is restored.",
        "Compare row heights between Watch Alerts, Recommended and Watch Queue "
        "- content rows should be the same height in all three.",
        "Check a title with a descender, e.g. 'Stargate SG-1' - the tail of "
        "the g must not be clipped in any section.",
    ),
)
