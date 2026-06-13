# Source Ingestion Generalization — Scoping & Design

**Status:** Scoping / design only. No code, intake processors, or filters to be written
until the open questions in §6 are answered. This document exists to fully characterize
why the new **IPTV Ninja** source produces zero content, to quantify how our two existing
sources (**TREX Shared**, **ProSat**) actually differ, and to design a generic
processor / graceful-fallback so that *any valid provider yields results — even crude ones*.

**Author context:** written from a read-only audit of the live database
(`~/.local/share/metatv/metatv.db`, 1.2 GB, all three sources present) and the ingestion
code path. All percentages below are measured from real rows, not estimated.

---

## 1. One-line diagnosis — CONFIRMED by live probe (2026-06-13)

> **IPTV Ninja's content is valid, standard Xtream JSON — but its server _trickles_ huge
> payloads (~227 KB/s), so the very first content call exceeds the client's hardcoded 60 s
> read timeout, the fetch aborts, and the loader reports the resulting 0 channels as a
> _success_.** The failure is a **slow-server / large-payload timeout**, compounded by a
> **silent-success loader** — not provider type, auth, response shape, dialect, category
> gating, or any render-time filter.

**Measured directly against Ninja's endpoint** (`operator1.barfik.org`, Chrome UA, same as
the client):

| Action | HTTP | Body | Full download time | Shape |
|---|---|---|---|---|
| auth (`player_api.php`) | 200 | 465 B | 0.6 s | `{user_info, server_info}` ✓ |
| `get_live_categories` | 200 | 60 KB | 1.7 s | bare list ✓ |
| `get_live_streams` | 200 | **18.4 MB** | **81.2 s** | bare list ✓ |
| `get_vod_streams` | 200 | 38.6 MB+ | ~170 s (extrapolated) | bare list ✓ |
| `get_series` | 200 | 6.0 MB+ | ~27 s (extrapolated) | bare list ✓ |

The throughput is ~227 KB/s. `_get_streams` uses `ClientTimeout(total=60)` — a *total*
deadline covering the entire body read. `get_live_streams` is the **first** call in
`_fetch_from_base`; at 81 s it is guaranteed to raise `asyncio.TimeoutError`, which
`_get_streams` **re-raises** (it's in the failover tuple), which `fetch_channels` treats as a
connection failure. Ninja has a single URL, so failover is immediately exhausted and
`fetch_channels` returns `[]`. The data is never the problem; the deadline is.

Everything downstream of "fetch returned a non-empty list" is fine and source-agnostic. The
two real defects are: (1) a **fixed total-timeout that punishes slow-but-healthy servers**,
and (2) a **fetch/loader path that cannot tell "this provider has no content" apart from "we
timed out reading it" — and calls both success.**

---

## 2. The pipeline, and every point content can silently vanish

```
AddProviderDialog ─▶ ProviderDB(type="xtream") ─▶ ProviderLoadThread.load_provider()
        │                                                 │
        │                                                 ▼
        │                          XtreamProvider.fetch_channels()  ◀── DIALECT LAYER
        │                                 ├─ ordered_urls() failover
        │                                 ├─ get_live_streams()   → [] on non-200 / non-list
        │                                 ├─ get_vod_streams()    → [] on non-200 / non-list
        │                                 └─ get_series()         → [] on non-200 / non-list
        │                                                 │
        │                          convert_to_channel() per row (stream_id, name, url…)
        │                                                 ▼
        │                          dedup by channel.id (keep last)
        │                                                 ▼
        │                          store loop (merge) ─▶ ChannelDB rows
        │                                                 ▼
        │                          _categorize_special_content() (PPV/Events/Sports)
        │                          update_detected_prefixes()   ◀── PARSE/ORGANIZE LAYER
        │                          get_prefix_stats()
        ▼                                                 ▼
   get_all(...) render  ◀── FILTER LAYER (include_untagged=True by default)
```

### Silent-drop / silent-success points (ranked by how likely they explain Ninja = 0)

1. **`XtreamAPI._get_streams` swallows shape/HTTP errors → returns `[]`.**
   `metatv/providers/xtream.py:236`. A non-200, or a 200 whose body is *not a bare JSON
   list* (object-wrapped, HTML error page, `{"data":[...]}`), returns `[]` with only a
   `logger.error`. Connection-level errors (`ClientError`, timeout) re-raise for URL
   cycling; **everything else is silent.**

2. **`fetch_channels` returns `[]` but via the _success_ path.**
   `metatv/providers/xtream.py:315`. If all three actions returned `[]` without raising,
   `_fetch_from_base` returns `[]`, the URL's `success_count` is incremented, and the loader
   proceeds as if the read worked.

3. **`ProviderLoadThread.load_provider` reports 0 as success.**
   `metatv/core/provider_loader.py:210`:
   ```python
   self.finished.emit(True, f"Loaded {total:,} channels successfully")
   ```
   With `total == 0` this emits **`(True, "Loaded 0 channels successfully")`**. This is the
   crux of the blindspot: a total fetch failure is indistinguishable from a legitimately
   empty provider, and both look like success to the user.

4. **Render filters are _not_ the cause.** `get_all(... include_untagged=True,
   adult_mode="all" ...)` (`channel.py:179`) shows un-prefixed, un-categorized channels by
   default. A source whose names match none of our patterns still renders. (One caveat — §5d
   — an *active* global prefix filter inherited from TREX/ProSat use can hide a new source's
   differently-prefixed channels, but that produces "fewer than expected," not "zero at
   import.")

5. **Provider-type mismatch is a _different_ failure we should also close.** The Add dialog
   offers `["Xtream", "M3U (coming soon)"]` (`dialogs.py:47`); index 1 saves
   `type="m3u"`, which `ProviderRegistry` does not register (`factory.py:62` registers only
   `xtream`). `get_provider("m3u")` → `None` → `finished.emit(False, "Unknown provider
   type: m3u")`. Ninja is `xtream`, so this is **not** Ninja's bug — but it is a latent
   "valid-looking source yields nothing" trap and belongs in the same fix.

---

## 3. Quantified dialect comparison (measured from the live DB)

| Dimension | **TREX Shared** | **ProSat** | Where the assumption lives |
|---|---|---|---|
| Live separator | pipe `\|` — 47,072 / 55,288 (**85%**) | star `★` — 18,905 / 20,356 (**93%**) | `_SEPARATOR_RE` `[★\|]` |
| VOD separator | dash `· - ·` — 180,700 / 189,939 (**95%**) | star `★` — 119,544 / 120,011 (**99.6%**) | `_SEPARATOR_RE` `- ` |
| Year format | `(1963)` parenthetical | ` - 2019` trailing-dash | `_YEAR_RE` groups 1 & 2 |
| Positional category headers | `##…##` — 1,018 live rows | **0** | `_parse_hash_header` (`provider_loader.py:26`) |
| `source_category` populated | **902** distinct labels | **0** | derived only from `##` headers |
| Quality marker | trailing `4K` / `FHD` token | trailing `FHD` token | `_QUALITY_SUFFIX_RE` |
| Tag-detection rate (live / movie / series) | 68% / 95% / 99% | 93% / 99.6% / 97% | end-to-end parser fit |

**Representative names:**

```
TREX  live   EN| CHRISTMAS 1 4K            ProSat live   FR ★ M6 MUSIC FHD
TREX  movie  EN - Cleopatra (1963)         ProSat movie  DE ★ Die Eiskönigin 2 - 2019
```

**Reading of the data:**

- TREX and ProSat are **two different Xtream dialects** that happen to be jointly covered by
  one hand-tuned regex set. TREX is pipe-for-live / dash-for-VOD / parenthetical-year /
  `##`-headers. ProSat is star-for-everything / trailing-dash-year / no headers.
- The parser's high tag-rate is a *fit to these two dialects*, not evidence of generality.
  A third dialect (e.g. `[US] Title`, `Title (US)`, `US: Title`, tab/colon separators, or
  no prefix at all) would parse to "untagged" — still **renders**, but with no
  region/quality/category enrichment. That is the "crude but present" baseline we want to
  guarantee and make visible.
- The `##…##` positional-header mechanism and the entire `source_category` feature are
  **TREX-only today** (ProSat: 0). Any logic that assumes `source_category` exists is
  implicitly TREX-specific.

---

## 4. The true generic contract (what is actually common to all sources)

Stripping away the dialect-specific layers, every source we support reduces to:

**Transport (Xtream):**
- `player_api.php` auth endpoint returns `user_info.auth == 1` and a `status`.
- Three content actions: `get_live_streams`, `get_vod_streams`, `get_series`.
- **Assumed but not guaranteed:** each returns a *bare JSON list* of stream dicts when
  called with no `category_id`.

**Per-stream minimum viable channel (MVC):**
- `stream_id` (or `series_id`) → identity
- `name` → display
- a constructible stream URL (`/live|movie|series/{user}/{pass}/{id}.{ext}`)
- `media_type` (assigned by which action returned it, not by the data)

Everything else — prefix, region, quality, year, category, special-content class — is
**enrichment**, derived by pattern-matching the `name`. Enrichment is allowed to fail per
row without dropping the row. **This is the contract the generic processor must protect:**
*if a row has an id, a name, and a URL, it must reach the channel list.* The audit confirms
that contract already holds at the parse/filter layer (untagged channels render); the gap is
that the **transport layer can return zero rows and call it success.**

---

## 5. Confirmed root cause (live probe, 2026-06-13)

The probe in §1 settled it. The four hypotheses this section originally listed — response
shape mismatch, category gating, endpoint/param dialect, bot/ratelimit — were **all wrong**.
Ninja returns 200 + standard bare-list JSON for every action. The single cause is:

> **A fixed `ClientTimeout(total=60)` total read deadline, applied to a server that delivers
> a healthy-but-large 18.4 MB live payload at ~227 KB/s (81 s).** The first content call
> times out → re-raised as a connection failure → single-URL failover exhausted →
> `fetch_channels` returns `[]` → loader stores 0 and reports success.

Why this is the correct frame for the generalization work:

- **It is the inverse of the dialect blindspot, but the same class of bug:** our ingestion is
  silently tuned to the *operating envelope* of TREX/ProSat (fast servers, bare-list shape,
  pipe/star separators). Ninja is inside the Xtream spec but outside that envelope on the one
  axis — throughput — that we hardcoded.
- **`total` is the wrong timeout primitive for bulk catalog reads.** A *total* deadline
  conflates "the server is dead" with "the server is slow but streaming." The correct
  primitive is a **socket-read (inactivity) timeout** (`aiohttp.ClientTimeout(sock_read=...)`,
  optionally with `sock_connect`): it fires only when *no bytes arrive* for N seconds, so a
  steady trickle never trips it while a genuinely hung connection still does. This is the
  targeted fix and it cannot regress TREX/ProSat (their reads never stall).
- **`max_connections = 1` raises the stakes.** A full sequential refresh holds the single
  connection for live (81 s) + VOD (~170 s) + series (~27 s) ≈ 4.5 min. Any concurrent
  playback or a second provider's fetch contends for that slot. Timeout strategy and
  connection accounting are linked for slow single-slot providers.

The original instrumentation argument still stands and is now *proven by example*: had the
fetch path produced an Ingest Report, Ninja would have said "live fetch: timed out after 60 s,
18 MB partial" instead of "Loaded 0 channels successfully." Visibility would have made this a
five-minute diagnosis instead of a forensic one.

---

## 6. Proposed design — a per-source ingest pipeline with a report and a dialect profile

Two separable layers of generalization. **Build the visibility layer first; defer the
auto-detection layer** until the Ninja dialect is known.

### Layer 1 — Transport resilience + an Ingest Report (the actual fix for "no content")

1. **Timeout strategy: replace `total=60` with a socket-read (inactivity) timeout
   (THE direct fix for Ninja).** Change `_get_streams` / `_get_categories` from
   `ClientTimeout(total=60)` to `ClientTimeout(sock_connect=<small>, sock_read=<N>)`. A slow
   server that keeps sending bytes never trips it; a hung one still does. Confirmed against
   Ninja: 18 MB at 227 KB/s = 81 s of *continuous* transfer, which a 60 s `total` kills but a
   `sock_read=30` would not. Cannot regress fast providers. (If we ever need a hard ceiling,
   make it generous — minutes, not 60 s — and per-payload, not global.)

2. **Ingest Report (highest *visibility* priority, smallest surface).** Have the fetch/store
   path return a structured per-source report: per action `{http_status, timed_out,
   raw_was_list, raw_count, kept_after_dedup}`, then `stored`, `tagged`, `untagged`. The
   loader decides success from the report, not from `len(channels)`. Concretely: **`total ==
   0` (and especially a timed-out action) must surface as a warning state** — e.g. "IPTV
   Ninja: live fetch timed out after 60 s (18 MB partial) — server is slow; raising the read
   timeout may help", never `emit(True, "Loaded 0 channels successfully")`. This converts the
   silent blindspot into an actionable message for *any* future source, whatever the cause.

3. **Response-shape tolerance (defensive, NOT causal here).** Ninja already returns bare
   lists, so this does not fix Ninja — but `data if isinstance(data, list) else []` silently
   eating an object-wrapped response is the *next* latent blindspot of the same family. Add a
   normalization step that also accepts common object-wrapped shapes and unwraps to a list,
   logging which shape was seen. Strictly additive. Lower priority than items 1–2.

4. **Category-iteration fallback (secondary benefit for slow servers).** If a bulk content
   action times out or returns empty *but* its category list is non-empty, iterate categories
   and aggregate. For Ninja this is a *resilience bonus*: per-category responses are far
   smaller than the 18–38 MB bulk blobs, so each finishes well under any timeout — a natural
   fallback when the monolithic call is too slow. Bounded, opt-in, triggered only on the
   timeout/empty-bulk path so TREX/ProSat never pay for it.

5. **M3U / unknown type honesty.** Either implement a minimal M3U provider or stop offering a
   type the factory can't service; and make `get_provider(None)` failures surface in the same
   Ingest Report channel rather than a transient notification. (Scope decision in §7.)

### Layer 2 — Generic parse/organize fallback (the "crude but present" guarantee)

5. **Formalize the Minimum-Viable-Channel passthrough.** Document and test the invariant from
   §4: id + name + URL ⇒ renders, regardless of prefix/category recognition. Today this is
   *emergent* (because `include_untagged=True`); make it an explicit, tested guarantee so a
   future filter change can't silently break it for unknown sources.

6. **Surface the untagged bucket.** When a source has a high untagged rate, expose it ("N
   channels couldn't be categorized — browse raw") instead of letting low-enrichment content
   hide in plain sight. Discoverability, not new parsing.

7. **Per-source Dialect Profile (deferred — the real generalization).** Instead of one global
   regex set hand-fitted to TREX+ProSat, sample each source's names at ingest, detect the
   dominant separator / year / header style, and store a per-source profile that drives
   parsing. This removes the structural blindspot ("a third source's dialect is nobody's
   default") but is a larger design with its own risks (mis-detection on mixed catalogs). **Do
   not start this until Layers 1–2 ship and the Ninja dialect is empirically known** — that
   real example should be the first test fixture for the profile design.

### Why this ordering

Layer 1.1 (the `sock_read` timeout) is the **direct, confirmed fix** that makes Ninja load,
and it cannot regress fast providers. Layer 1.2 (the Ingest Report) is the highest-value
*visibility* change — it would have made Ninja's failure self-explanatory on day one and
covers every future cause, not just this one. Shape tolerance and category fallback are
defensive hardening for the *next* envelope violation. The MVC guarantee and untagged
surfacing make "crude results" a contract rather than a happy accident. The Dialect Profile is
the principled end-state but must be driven by a real third dialect — which, now that Ninja is
characterized (TREX-style `- ` VOD names, pipe-and-`GOLD|`-style live, superscript `ᴿᴬᵂ`
quality), we can begin to source.

---

## 7. Scope boundaries, open questions, immediate next step

**In scope for the eventual first PR (the confirmed fix, behavior-preserving for TREX/ProSat):**
- **`sock_read` timeout** replacing `total=60` in `_get_streams`/`_get_categories` — makes
  Ninja load. The one change that resolves the reported symptom.
- The Ingest Report + "0 channels (or a timed-out action) is a warning, not a success."

**Deferred (separate concerns, one PR each):**
- Response-shape tolerance (additive hardening; not causal for Ninja).
- Category-iteration fallback (resilience bonus for slow servers).
- M3U type decision (separate concern; one-PR-per-concern).
- Per-source Dialect Profile (Layer 2.7) — the big one; Ninja is now a candidate fixture.

**Open questions to answer before writing the larger processors:**
1. ~~What does Ninja's `get_live_streams` return?~~ **ANSWERED §1/§5:** standard bare list,
   18.4 MB, 81 s — the cause is the 60 s `total` timeout. The first-PR fix follows directly.
2. What `sock_read` value? (Proposed: 30–45 s of *inactivity* — long enough for a stalled CDN
   hop, short enough to fail a dead socket; validate against the slowest observed real server.)
3. Is `source_category`/`##`-header logic meant to stay TREX-specific, or be generalized into
   the Dialect Profile? (Currently 100% TREX; Ninja also emits superscript quality like `ᴿᴬᵂ`
   and `GOLD|`-style live prefixes — additional dialect data points.)
4. M3U: implement, or remove from the Add dialog? (Don't leave a type that yields nothing.)
5. Should an *active global prefix filter* (§2.4 caveat) auto-relax when a brand-new source is
   added, so its differently-prefixed channels aren't hidden on first load?

**Status of the diagnostic:** DONE (2026-06-13). The §1/§5 probe was run against Ninja's
primary URL with approval; it consumed the single connection slot briefly and confirmed the
root cause. No app code was changed. The design above is now decision-ready, not hypothetical.
```

