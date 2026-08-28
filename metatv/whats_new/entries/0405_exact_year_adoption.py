from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=405,
    version="0.53.0",
    date="2026-08-28",
    title="A film could stay split from its copies because a remake existed",
    items=(
        "When one copy of a film is matched to a title database and another is "
        "not, the app fills in the gap by looking at copies with the same name.",
        "It looked at every copy of that name across all years at once. So if "
        "the catalogue also held a remake, the whole name became ambiguous and "
        "it refused to match anything - even for a copy whose year matched its "
        "sibling exactly.",
        "An exact year match is now enough on its own, because a film is "
        "identified by its title and year. A remake from another year no longer "
        "blocks it.",
        "On a real library this reconnects 102 films that were sitting split "
        "from their own other copies. A missing year still does not count as a "
        "match - two copies that both lack a year stay separate, because that "
        "is a guess rather than evidence.",
    ),
    test_steps=(
        "Find a film you own in several copies where one shows richer details "
        "than the others, and open it.",
        "Check 'Other Versions' - copies that used to be missing should now be "
        "listed with it.",
        "Find a film that shares its name with a remake from another year and "
        "confirm the two are still shown as separate films.",
        "Confirm a film with no year listed has not been merged with a "
        "different film of the same name.",
    ),
)
