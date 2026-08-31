from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=467,
    version="0.60.0",
    date="2026-08-31",
    title="Error messages you can actually read",
    items=(
        "When a source refresh failed, the notification showed the entire "
        "database statement — tens of thousands of characters of \"(?, ?, ?\" "
        "— with the actual reason scrolled off the top. It now shows just the "
        "reason, like \"database is locked\". The full detail is still written "
        "to the log.",
        "A failed stream offers one button per alternative source, and with "
        "seven of them each button was squashed until its label was cut to "
        "nonsense — \"r Any\", \"ate _\", \"py Er\". The buttons now wrap onto "
        "a second row at their full width instead of shrinking.",
    ),
    test_steps=(
        ("Refresh two sources at once so one fails, and read the failure "
         "notification — it should be one short sentence, not a wall of "
         "punctuation.", "view:browse"),
        "Play something whose stream is down and check the error's buttons: "
        "every label should be fully readable, wrapping to a second row if "
        "there are many.",
        "Hover each button and confirm the tooltip matches its label.",
        "Click one of the alternative-source buttons and confirm it still "
        "does what it says.",
    ),
)
