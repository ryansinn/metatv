# Sonnet Execution Prompt — Ingest Visibility + Prefix Lexicon (post-Ninja)

Paste the block below into a fresh Claude Sonnet session (with tools, in this repo) to execute
two small, well-scoped follow-ups surfaced while diagnosing the **IPTV Ninja "0 channels"**
incident. The root cause (a fixed `total=60` read timeout killing a slow server's healthy-but-
large catalog) is **already fixed** on branch `fix/xtream-slow-server-timeout` and proven
end-to-end (Ninja loaded 280,989 channels). These two tasks are the *follow-ups*, not the fix.

Read `docs/SOURCE_INGESTION_GENERALIZATION.md` first — it is the scoping document this prompt
implements. Read `docs/SONNET_EXECUTION_PROMPT_BAND7.md` for the anti-pattern banner; the same
rules apply verbatim here.

---

````text
You are an implementing engineer in the MetaTV repository (Python/PyQt6 IPTV client). Execute
the two tasks below. They are SEPARATE CONCERNS — one PR each, in order. Do not bundle them.

════════════════════════════════════════════════════════
⛔ ANTI-PATTERNS THAT GOT PRIOR PRs DOWNGRADED — DO NOT REPEAT ⛔
════════════════════════════════════════════════════════
(Full text in docs/SONNET_EXECUTION_PROMPT_BAND7.md. The three that matter most here:)
  1. SHAPE-ONLY / ZERO-RESULT TESTS. Every behavior change ships ≥1 test that EXECUTES the
     changed path against a real in-memory DB / real object and asserts the outcome that would
     actually break. A substring/AST assertion ("emit(False" in src) is not coverage. For DB
     tests use a file-backed tmp_path SQLite (NOT :memory:, whose pooled connections each get
     an empty DB) and call create_tables().
  2. INVENTING A THIRD PATTERN. Use the established ones: session_scope() for DB work, signals
     for cross-thread, the loguru logger, icons.py / theme.py for any glyph or style. If the
     established path genuinely doesn't fit, ASK or record a plan item — don't multiply patterns.
  3. DISREGARDING A FUNDAMENTAL RULE FOR CONVENIENCE. Re-read the relevant CLAUDE.md Critical
     Rule before any shortcut. The rules OVERRIDE convenience.

ONE CONCERN PER PR. Branch each task off `main` (after the timeout fix merges). Run
`venv/bin/python -m pytest tests/ -q` green before committing. Do NOT merge — the owner merges.

────────────────────────────────────────────────────────
TASK A (PR 1) — A fetch that yields 0 channels must NEVER report success
────────────────────────────────────────────────────────
THE BUG THIS CLOSES: `provider_loader.py` ends `load_provider()` with
`self.finished.emit(True, f"Loaded {total:,} channels successfully")` even when `total == 0`.
That is exactly why the Ninja timeout was invisible for so long: a total fetch failure
(timeout, all-URLs-failed, HTTP errors) is reported to the user as "Loaded 0 channels
successfully." (See SOURCE_INGESTION_GENERALIZATION.md §2.3 and §6 Layer 1.2.)

REQUIRED OUTCOME (the floor — do at least this):
  • When a load produces 0 stored channels, the `finished` signal must carry `success=False`
    with an ACTIONABLE message, never the success string. Suggested copy: "Connected to
    {name}, but received 0 channels — the server may be slow, rate-limited, or returned no
    content. Check the logs and try again." The message must NOT contain the word "successfully".
  • The decision must be driven by the outcome, not by an exception that may not fire: today
    `fetch_channels` returns `[]` via its *success* path when all URLs fail silently, so you
    cannot rely on a raise. Branch on the result.

RECOMMENDED (do if it stays cheap — otherwise record as a follow-up, don't balloon the PR):
  • Thread a minimal per-stage signal into the message so it says *why* 0 happened — e.g. carry
    the live/vod/series fetched counts and a `timed_out` flag out of `_fetch_from_base`
    (return a small dataclass, or set attributes on the thread) so the message can distinguish
    "all three actions returned empty" from "live fetch timed out." Keep it UI-free in the
    provider layer; the loader composes the user-facing string. Do NOT restructure the
    `ProviderPlugin` ABC or rewrite the storage loop — this is a decision-and-messaging change.

GUARDRAILS:
  • Do not change the happy path: a healthy load still emits `(True, "Loaded N channels
    successfully")`. Only the 0-result branch changes.
  • `on_provider_refresh_finished` in main_window already routes `success` to a notification —
    confirm a `False` here surfaces as a warning/error toast, not a silent drop.

TESTS (behavioral, per anti-pattern #1):
  • Drive the REAL `ProviderLoadThread.load_provider()` against a file-backed tmp_path Database
    with a STUB provider plugin whose `fetch_channels` returns `[]`; capture the `finished`
    signal and assert `success is False` and "successfully" not in the message.
  • Same harness, stub returns a couple of real `Channel`s; assert `success is True` and the
    rows are stored. (Pins that you didn't break the happy path.)
  • If you add the per-stage report, assert the message reflects the stub's stage counts.

────────────────────────────────────────────────────────
TASK B (PR 2) — Evaluate & fold in unrecognized PREFIX tokens (SOURCE-INDEPENDENT)
────────────────────────────────────────────────────────
PRINCIPLE — READ TWICE: prefixes are NOT a per-source feature. There is ONE canonical lexicon,
`metatv/core/channel_name_utils.py` (REGION_FULL_NAMES, _FULL_NAME_TO_CODE, _ALIAS_MAP,
PLATFORM_CODES, QUALITY_TOKENS), and the CLAUDE.md "Lookup tables — single source of truth"
rule forbids a parallel per-source dict. This task is "identify the tokens and decide their
canonical meaning," not "add Ninja's prefixes." The source is EVIDENCE and PROVENANCE, never a
key.

PROOF THIS IS SOURCE-INDEPENDENT (measured 2026-06-13): the Ninja populate surfaced 206
detected_prefix tokens (30,809 channels) that the lexicon does not recognize. **All 206 of
them already appear in TREX and/or ProSat as well.** Ninja introduced zero new tokens — it just
provided a complete dataset that re-exposed gaps that were always present. So: fix them once, in
the canonical tables, and they improve every source at once.

WHAT TO DO per token — classify, don't guess:
  • Region / country / language code → add to REGION_FULL_NAMES (and _FULL_NAME_TO_CODE or
    _ALIAS_MAP if it's a full name / alias of an existing canonical code).
  • Streaming platform / service → PLATFORM_CODES + a REGION_FULL_NAMES display name.
  • Quality token → QUALITY_TOKENS.
  • Compound (LANG-PLATFORM / GENRE-LANG, e.g. `UK-NOWTV`, `ES-C`, `CZ-PLAY`, `PL-VIP`,
    `WESTERN-DE`, `BLURAY-DE`, `IN-PREM`) → these belong to the compound-locale work
    (`_COMPOUND_PREFIX_RE` + the documented compound-locale debt). EVALUATE and LIST them, but
    do NOT re-map `_BRACKET_LANG_NORM` or the compound regex here — record them for that PR.
  • Genuinely-not-a-prefix (genre/marketing noise, e.g. `BLUE`, `BEE`, `ARADA`, `CATLAK`,
    Turkish words) → leave UNtagged; do not invent a region for it. Note it as "intentionally
    not a prefix" so the next person doesn't re-litigate.

PROVENANCE (this is what the owner asked for): every token you add gets a short inline comment
citing where the assignment was derived/cited from — e.g.
`"MXC": "Mexico",  # surfaced in TREX + IPTV Ninja live catalogs, 2026-06`. The comment is for
TRACEABILITY of the decision, NOT a coupling — the token works for all sources regardless.

CONSERVATISM (mandatory): ambiguous 2-letter tokens are a known trap (project_filter_system
memory already flags AS/EX/SC/TG). Several high-count unknowns are ambiguous and MUST NOT be
guessed — list them with options and leave them untagged pending owner input rather than
assigning a wrong meaning:
  • `EX` (6,801) — region? or "Exclusive"/genre marketing? (ambiguous — do not assign blind)
  • `TM`, `TL`, `UR`, `KD`, `OD`, `MO`, `GO`, `YP`, `MG`, `BA`, `WC`, `PB`, `BK` — evaluate
    each against the channel samples (`SELECT name ... WHERE detected_prefix='TM' LIMIT 20`)
    before assigning; many will be languages (UR=Urdu? PB=Punjabi? KD=Kurdish? OD=Odia?) but
    CONFIRM from the data, don't assume.
Likely-safe additions to evaluate first (still confirm from samples): `MXC` (1,467, Mexico),
`AFR`/`AF`/`AFG`/`ANG`/`ARM`/`AZ` (regions), `ISR`/`IS` (Israel/Iceland — disambiguate!),
`STH`, `NEXT`/`JOYN`/`VIX`/`PLAY+`/`A+`/`CITY`/`NOWTV` (platforms).

HOW TO REGENERATE THE FULL LIST (don't hardcode — the data is the source of truth):
```sql
-- per provider, the detected_prefix tokens + counts; cross-check a token across all three
SELECT detected_prefix, COUNT(*) c FROM channels
WHERE provider_id IN (<trex>,<prosat>,<ninja>) AND detected_prefix<>''
GROUP BY detected_prefix ORDER BY c DESC;
-- inspect a token's real names before assigning meaning
SELECT name FROM channels WHERE detected_prefix='<TOKEN>' LIMIT 25;
```

TESTS: `tests/test_compound_prefix.py` and the channel-name parser tests are the harness. For
each token you ADD, add a parse assertion (e.g. `parse_channel_name("MXC ★ Foo").region ==
"MXC"` / normalizes as intended). Do NOT write a test that just asserts the dict contains a key
— assert the PARSE BEHAVIOR the addition enables. Ambiguous tokens you deliberately leave
untagged get a test pinning that they stay untagged (so a later careless add is caught).

OUT OF SCOPE for both PRs (record in the Band/scoping doc, do not start):
  • The untagged DIALECTS the populate exposed — colon-delimited country (`DK: PLAY TV2`),
    leading-colon (`:Viaplay DK 23`), Turkish episode markers (`NN. Bölüm`, `S01E02` in movie
    rows that are really series), and the `- NO EVENT STREAMING - | 8K EXCLUSIVE |` PPV
    placeholder format. These need PARSER changes / the per-source Dialect Profile
    (SOURCE_INGESTION_GENERALIZATION.md §6 Layer 2.7), not lexicon entries. Note them; defer.
  • Compound `LANG-PLATFORM` tokens (above) → compound-locale PR.

────────────────────────────────────────────────────────
WRAP-UP (per CLAUDE.md Session Wrap SOP)
────────────────────────────────────────────────────────
Per PR: tests green → commit (end message with the Opus co-author footer) → update docs
(SOURCE_INGESTION_GENERALIZATION.md: tick the item; list deferred dialects/compounds) → update
memory if a new pattern/decision landed → push the branch → report what landed and what was
deliberately deferred (especially every ambiguous prefix you left untagged and why). Do not
merge.
````
