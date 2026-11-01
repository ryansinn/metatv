from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=777,
    version="0.213.0",
    date="2026-10-31",
    title="Server addresses show when they failed; Most played opens the title",
    items=("In a source's Analytics tab, each server address shows its last 20 requests as "
           "ticks, oldest to newest — tall for one that worked, short for one that failed — and "
           "when it last worked. An address that worked for months and then died no longer looks "
           "the same as a flaky one. The card names the address MetaTV tries first.",
           "Click a title under Most played to open it in Search.",
           "The tab fits a narrow Sources editor again (it no longer forces it wider than 400 px).",
           "More provider prefixes are understood: KA (Kannada), PJ/PU (Punjabi), QC (Quebec), "
           "the -PREM premium packages, SD/CAM (tagged as a camcorder copy), DE-TOP and "
           "AHL-TEAM.",),
    test_steps=("Open Sources → TREX → Analytics — Server addresses has \"Last 20\", \"Speed\" and "
                "\"Last worked\" columns, ticks per address, and an \"In use:\" line.",
                "Hover the ticks — the tooltip says how many of the last requests worked.",
                "Click Futurama (or any title) under Most played — Search opens on that title.",
                "Drag the editor narrow — it still goes down to about 400 px with everything visible.",
                "Unrecognized prefixes no longer lists IN-KA, IN-PU, IN-PREM, PB-PREM, SD/CAM, "
                "DE-TOP or AHL-TEAM.",),
)
