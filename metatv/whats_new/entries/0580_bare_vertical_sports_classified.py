from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=580,
    version="0.94.0",
    date="2026-09-03",
    title="Bare vertical forms (racing, grappling, flofc) classify to their sports",
    items=(
        "Three bare FLO vertical forms now classify to their sport: '| racing:' "
        "events become Racing, '| grappling:' becomes MMA, and '| flofc:' becomes "
        "Soccer — ~319 events leave 'Unknown' sport at next launch.",
        "A one-time repair pass at next launch re-classifies the affected events "
        "so they appear in their sport's lane instead of the General pool.",
    ),
    test_steps=(
        "Open Sports → Racing chip after the launch repair: '| racing:' FLSP "
        "events appear there, not under Unknown/General.",
        "No '| grappling:' or '| flofc:' events remain classified Unknown — they "
        "sort under MMA and Soccer respectively.",
    ),
)
