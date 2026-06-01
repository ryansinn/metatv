# MetaTV — Product Vision & Direction

> The enduring "why" of MetaTV: what it is, who it's for, and the principles every decision serves.
> Leads with vision and philosophy, then v1 focus, then clearly-subordinate stretch ideas. v1 ships
> first and stands on its own; everything under "Stretch" is optional and mostly matters only if
> MetaTV becomes a *product* rather than a personal tool.

## The thesis: a lean, native media manager + companion player

MetaTV is a **lean, native desktop app for curating and playing your media** — built around one
core separation:

- **Curation / management** is rich and powerful: a dense, keyboard-driven UI for tuning in
  *exactly* what you want to watch — multi-source, discovery, recommendations, dedup, EPG, queues.
- **Playback is dead simple and gets out of the way:** picking something opens a plain **mpv**
  window. The management UI disappears; the media just plays.

**How it's actually used (the design center):** an **ambient companion** on a working PC. Media
plays in a simple window that can be **always-on-top / PIP in the corner** of a second display
while you work, and is **occasionally promoted to fullscreen** to relax. Once something is playing,
the content-management UI is out of the picture. It's a **media *and* music** player — something
clean and efficient to manage, curate, and play.

**Leanness is a feature, not an accident.** The "everything in a browser" pipedream has collapsed
under bloat: browsers try to do email + work + browsing + apps, and a single Chrome/Firefox session
balloons past tens of GB of RAM, triggers the GPU, and lets site storage (e.g. WhatsApp) grow to
30 GB+. People now run *multiple* browsers just to segment the overhead. MetaTV is the opposite: a
focused native app using **under 2 GB — mostly cached poster art**. Doing one thing efficiently,
natively, is the point.

## The core purpose: complexity → a mind-reading Discover

The tuning and curation depth is **not the point — it's the engine.** Its job is to turn explicit
tuning + observed behavior + implicit signals into a **Discover** experience so well-aimed it feels
like **reading the user's mind.** The complexity lives *behind* the experience, never in front of
the user. (This is "power without dumbing down" stated precisely: the power is in the engine, the
simplicity is in the output.)

**Two surfaces, two interaction models:**
- **Recommendations = a personal chef.** Served, anticipatory, low-effort: "I know you — here's
  something you'll love." You *receive*. The mind-reading, comfort-friendly surface.
- **Discover = a grocery store where you know the butcher.** *You* shop (full agency), but with
  trusted relationships and knowledgeable guidance, not a cold supermarket. Active browsing
  *scaffolded* by curation — the go-to place to just browse.

**Two axes, not one:**
- *Comfort ↔ explore* — the **mood** axis (what headspace you're in):
  - **Comfort food** — familiar, repeat, low-effort viewing; the default ambient-companion loop
    ("put on something I reliably enjoy and leave it"). Recommendations favor *known affinity* —
    safe, on-taste — and lean on impression-tracking / rotation decay to stay familiar without
    going stale.
  - **Exploration** — curious / mentally-open phases that want something *new*. Recommendations
    favor *novelty* — adjacent-but-unfamiliar, taste-expanding — and deliberately *relax* the
    "already seen / known affinity" pull.
- *Chef ↔ grocery* — the **agency** axis (served vs. choose-with-help).

The axes are independent — you can want the chef to surprise you (explore, served), or browse
comfort food at the grocery (comfort, self-serve). Meeting the user means modeling both, and either
**detecting** the phase (time of day, session length, active-browsing vs. leave-it-on behavior) or
letting the user **signal** it ("surprise me"). The engine already holds the raw materials —
attribute weights, implicit signals, recency decay, impression tracking; the work is treating these
dualities as explicit dimensions over them.

## Design principles (the soul)

1. **Classic — function over form, elegance earned.** The basic idea is timeless, not
   trend-chasing. Function comes *first* (this is why the UX is perfected on raw data before any
   enrichment) — but it's function-*first*, not function-*only*: as the function is perfected, the
   form is made elegant. Elegance is earned by working well, not bolted on.
2. **Power without dumbing down.** Most apps simplify by *subtraction* to chase a
   lowest-common-denominator TV/mobile experience. MetaTV keeps full depth and earns approachability
   through *good design*, never by removing capability. "Capable *and* intuitive."
3. **Good enough on raw data; thrives with context.** The experience is perfected on the most basic
   Xtream data *first* — it must be good with nothing but the minimal stream list, **no external
   metadata required.** AI, TMDb, OMDb, and other 3rd-party context are *progressive enhancement*:
   present, they raise the ceiling (richer dedup, recommendations, discovery); absent, the app is
   still good. Build for the floor; let context raise the ceiling. (Already encoded by the metadata
   provider chain — `ProviderMetadataProvider` zero-latency-first, TMDb/OMDb merge by confidence.)
4. **Separation of management and playback.** The curation UI is rich; playback is just mpv, simple,
   and out of the way. The two never bleed into each other.
5. **Ambient companion ↔ fullscreen relax.** A continuum in one app: a low-chrome, always-on-top /
   PIP corner window that expands to fullscreen — not two separate clients.
6. **Lean & native.** Efficiency is a stated value. No Electron, no browser, no bloat. <2 GB.
7. **Cross-platform desktop, keyboard-driven.** PyQt6 + Python → runs on **Windows, macOS, and
   Linux** (any desktop with Qt + Python). The audience is keyboard-driven media systems.

## v1 — the focus

A great cross-platform desktop media manager + companion player. Most of the curation side already
exists; v1 is about polishing it and nailing the ambient-companion playback loop.

**Curation / management (largely built — polish & reliability):**
- Multi-source by default; **Discover is the primary browse surface** (where the engine's output
  lands), backed by recommendations (preference engine) and cross-source dedup.
- EPG (watchlist / on-now / browse), watch queue, favorites, history.
- A dense, fast, native desktop UX. Media *and* music.

**Playback as a simple companion (the differentiating v1 work):**
- Playback opens a **plain mpv window** with basic controls; already queues a whole season/series.
- **Ambient mode:** low-chrome, **always-on-top / PIP** corner window ↔ **fullscreen** relax mode.
- **Global hotkeys** so playback can be controlled without focusing the window.
- **Playback → DB feedback loop (mpv IPC):** feed play state — current item, position, end-of-file —
  back to the DB to enable **resume playback**, **completion detection**, smarter **history**, and
  **autoplay-next**. (Tracked in `ROADMAP.md` → Playback & Queue; highest-value v1 plumbing because
  it powers the "set it and leave it in the corner" loop.)
- **Glanceable discovery:** "what's next / pick something and leave it on" surfaces that don't demand
  attention — well suited to ambient/continuous (incl. live) content.

## Stretch — "maybe eventually"

### Desktop-embedded video-widget playback (platform-specific)
On Linux/KDE (and similar), target playback at a **specific window or a desktop-embedded video
widget** — media playing *on the desktop itself*, with normal windows covering it when they're on
top (wallpaper/widget-style ambient playback). Experimental and platform-dependent; a natural
extension of the ambient-companion idea.

### Product-only stretch (matters only if MetaTV becomes a product, not a personal tool)
The user is ~99% on PC with the ambient-companion pattern, so the items below serve a *product*
goal, not daily personal use. Recorded for completeness; **deliberately demoted.**

- **Multi-source aggregation** beyond IPTV — API-backed self-hosted servers (Jellyfin → Plex → Emby),
  generic protocols (SMB/NFS/DLNA/WebDAV/local). Only valuable if you actually run such servers with
  content you'd watch this way. The existing `content_dedup` / `preference_engine` /
  `discovery_engine` already *is* the aggregation brain; new sources slot into `ProviderPlugin`.
- **URL-loaded plugin system** — declarative YAML/JSON **manifests** interpreted by built-in engines
  (an index URL = a repository); *data, not code*. Remote addon *services* (Stremio-style, app stays
  an HTTP client) are a possible later option. **Downloaded executable code plugins are rejected**
  (remote code execution; store-banned; the Kodi-reputation trap). Even manifests need a credential
  trust boundary (a source's secret only ever goes to its own host), capability + schema versioning,
  and official-vs-community trust tiers.
- **Headless backend + lean mobile/TV discovery client** — extract `core/` into a FastAPI backend
  (de-Qt the 5 Qt-coupled modules), with a Flutter discovery client (`media_kit`/libmpv) for Android
  TV / iOS. The mobile/TV client only needs to be the *simple discovery surface*, not a port of the
  desktop head UX. No server-side transcoding (native clients play TS + VOD directly). Sideload
  distribution. **For a 99%-PC user this serves the 1%.**
- **Positioning / rebrand** — retire the "IPTV Stream Organizer" tag (inaccurate + piracy-toned).
  Lead with "lean, native media manager + companion player." Keep the "Meta" concept; reconsider
  "TV" only if going public (Facebook/Meta collision + scope).
- **Store eligibility** — a bring-your-own-sources aggregator is App-Store-plausible (the Infuse
  precedent); manage the IPTV piece via BYO positioning (no preloaded providers, never marketed as
  "IPTV"). Only relevant if productized.

## Explicitly out of scope
- **Browser / Electron / web frontend** — *rejected on principle.* It defeats the leanness thesis;
  browser bloat is the exact problem this app exists to avoid.
- **Downloaded executable plugins** — RCE / store-banned / malware vector.
- **Server-side transcoding** — unnecessary; native playback handles TS + VOD directly.
- **Profiles / multi-user** — not in scope; clutter for the personal-tool reality.

## Suggested sequencing
1. **Polish v1 curation** — the management UI as it exists, made reliable; Discover as the primary
   browse surface.
2. **Nail the ambient-companion playback loop** — mpv IPC (resume/history/completion/autoplay-next),
   always-on-top / PIP mode, global hotkeys. This is the soul of the product and the highest-value
   work.
3. **Music as a first-class media type** alongside video.
4. *Everything under "Stretch"* — only if/when MetaTV is being pushed toward a product. Enrichment
   (AI/TMDb/OMDb) and multi-source are *ceiling-raisers layered on a baseline that already works* —
   never prerequisites.
