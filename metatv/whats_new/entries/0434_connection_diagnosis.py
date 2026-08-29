from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=434,
    version="0.54.0",
    date="2026-08-29",
    title="When every address fails, the app now says why",
    items=(
        "Testing a source used to show a row of red badges and nothing else. "
        "If all of them failed you were on your own working out whether it was "
        "the network, the subscription, or something else.",
        "A 403 or 405 from every address means the addresses WORK and the "
        "provider is refusing who you appear to be - usually a VPN endpoint "
        "whose IP the provider blocks. The app now says exactly that, and "
        "suggests switching endpoint.",
        "Nothing answering at all is the opposite problem, and now reads as a "
        "network or DNS one rather than an account one.",
        "If the provider says the subscription is inactive, or rejects the "
        "username and password, that is reported directly - no point changing "
        "addresses when the server has already told us the answer.",
        "The HTTP codes behind the verdict are quoted, so you can check it "
        "rather than take its word.",
        "Nothing appears when at least one address works. A partial failure is "
        "normal; that is what having several addresses is for.",
    ),
    test_steps=(
        "Edit a source, set every URL to an address that does not exist, and "
        "press Test Connection - confirm the panel says nothing answered and "
        "points at the network rather than the account.",
        "With a working source connected through a VPN whose IP the provider "
        "blocks, press Test Connection and confirm the panel names the VPN as "
        "the likely cause and quotes the HTTP code.",
        "Enter a wrong password and confirm the panel says the credentials "
        "were rejected rather than blaming the connection.",
        "Fix one URL so it works, re-test, and confirm the panel disappears "
        "entirely rather than warning about the failures that remain.",
    ),
)
