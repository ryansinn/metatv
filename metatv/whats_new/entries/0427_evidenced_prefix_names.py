from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=427,
    version="0.54.0",
    date="2026-08-29",
    title="About 111,000 channels get their language or region name back",
    items=(
        "293 of the 421 source codes in a large library had no name at all, so "
        "those channels showed a blank chip where the language or country "
        "should be.",
        "AR alone was 68,593 channels - it means Arabic, though a standard "
        "country list would call it Argentina.",
        "Eleven codes now have names, and two more are recognised as the "
        "streaming services they are rather than places.",
        "Each name was read from the source's own category labels rather than "
        "guessed. Two codes that genuinely mean two different things are left "
        "unnamed on purpose.",
        "Hovering a language or region chip now tells you something. It used "
        "to read 'Language: AR' - the same abbreviation you were already "
        "pointing at. It now reads 'Language: Arabic (AR)'.",
        "For the few codes still without a name, the tooltip says so plainly "
        "instead of calling an unknown code a language. 96% of channels with a "
        "prefix now get a real name on hover.",
    ),
    test_steps=(
        "Browse channels whose prefix is AR and confirm the chip reads Arabic.",
        "Check TM, TG, TL, KD and UR channels show Tamil, Telugu, Telugu, "
        "Kannada and Urdu.",
        "Confirm OD and YP channels show as services (Odido, YuppTV) rather "
        "than as countries.",
        "Confirm filtering by one of these names selects the right channels.",
        "Hover a language chip and confirm the tooltip names the language "
        "rather than repeating the abbreviation on the chip.",
        "Hover a chip with an unusual code and confirm the tooltip does not "
        "claim it is a language it cannot name, and still offers the click "
        "action.",
    ),
)
