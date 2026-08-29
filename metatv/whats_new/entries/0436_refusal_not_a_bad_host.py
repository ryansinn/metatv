from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=436,
    version="0.54.0",
    date="2026-08-29",
    title="A blocked IP no longer makes every address look unreliable",
    items=(
        "Sources remember which addresses work, and prefer the reliable ones. "
        "A 403 or 405 was counted as that address failing - but every address "
        "on an account returns it when your IP is blocked or the subscription "
        "has lapsed. It says nothing about the address.",
        "So a VPN session on a blocked endpoint quietly marked down every "
        "address you have, and the rankings stayed wrong afterwards.",
        "It also put every address into a cooldown, delaying the next real "
        "attempt across the board rather than steering around one bad host.",
        "Refusals are still recorded and still shown in the connection test - "
        "they just no longer count against the address that reported them.",
        "A genuine problem with an address - a refused connection, a timeout, "
        "an empty reply, a 500 - counts exactly as before.",
    ),
    test_steps=(
        "Connect through a VPN endpoint the provider blocks and refresh a "
        "source. Confirm the URL list's reliability figures are unchanged "
        "afterwards rather than dropping across the board.",
        "Switch to a working endpoint and confirm the source still prefers the "
        "address it preferred before.",
        "Point one address at a host that does not exist, refresh, and confirm "
        "that address alone loses reliability and drops down the list.",
    ),
)
