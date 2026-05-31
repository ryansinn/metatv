# Filtering System Design

## Core Philosophy

**The system operates on an opt-out model. Content is visible by default.**

We cannot know in advance what prefix groups, providers, or content categories will exist in any given user's IPTV library. New providers introduce new prefixes; new categories emerge over time. Any system that requires content to be explicitly *included* to be visible will silently exclude new content as the system evolves — and users will see incomplete results without knowing why.

The correct mental model: **everything is shown unless the user explicitly hides it.** Filters are tools for narrowing or excluding, not for granting visibility.

This applies to both filter systems described below.

---

## Two-Tier Filter System

MetaTV has two filter systems with different scopes and mental models. They are not redundant — they serve different workflows.

### Tier 1 — In-Session View Filters

**Scope**: Per-view. In-session. Resets are low-cost.

Each major view has (or will have) its own in-session whitelist-style filter appropriate to that view's content:

| View | Filter axes |
|------|-------------|
| **Channel Search** | Language/Region, Quality, Platform, Media Type |
| **Discovery** | Genre, Decade, Platform, Media Type (planned) |
| **EPG** | Channel group, Time range (planned) |

These are all Tier 1 filters — they narrow what you see right now in that view. They do not persist as permanent exclusions. The Tier 2 Exclusions always apply underneath them.

#### Quick Filter Bar (Channel Search — current implementation)

**Mental model**: "Show me only X right now."

**Mental model**: "Show me only X right now."

**Interaction**: Whitelist-style dropdowns. The user checks groups they want to *focus on* — selecting "English" narrows results to English channels. Nothing selected = show all.

**Why whitelist here**: The use case is exploratory narrowing ("I want to browse HD English content"). This is the standard pattern in content browsers (Netflix genre filter, Amazon product filter, Spotify genre). Opt-in selection maps naturally to "show me only these."

**Three orthogonal filter axes** (selecting across axes is AND logic):
- **Language/Region** — `EN`, `FR`, `DE`, `ES`, etc.
- **Quality** — `4K`, `HD`, `FHD`, `SD`, etc.
- **Platform** — `NF`, `EAR`, `D+`, `24/7`, etc. (provider/service prefixes that are NOT language identifiers)

Keeping Platform separate is critical: selecting "English" in Language should not exclude NF or EAR channels — those are platform prefixes on a different axis. Without a separate Platform axis, filtering by Language accidentally hides platform-prefixed content.

**Unmapped prefixes**: Channels whose `detected_prefix` doesn't map to any group in any axis are always shown regardless of what's selected. Unmapped = unclassified, not excluded.

### Tier 2 — Exclusions Modal (Global)

**Scope**: All views — Discovery, Recommendations, EPG, channel list. Persistent across sessions.

**Mental model**: "Always hide X."

**Interaction**: Blacklist-style checkboxes. The user checks groups/items they want to *permanently exclude*. Nothing checked = hide nothing.

**Why blacklist here**: The use case is permanent blocking ("I never want Arabic channels" / "hide all SD channels"). Opt-out selection maps naturally to "I'm choosing to remove this from my experience."

**Two sections**:
1. **Categories** — hide broad groups (Language/Region, Quality, Platform). Checking a group hides all channels in that group everywhere.
2. **Hidden Content** — specific channels hidden individually (via the Hide button in the details pane). Equivalent to the current Hidden view. Users can review and unhide from here.

The Exclusions modal is a popup/dialog so the user doesn't lose their current view context.

---

## Prefix Category Types

Three distinct semantic types of channel prefixes:

| Type | Examples | What it means |
|------|----------|---------------|
| **Language/Region** | `EN`, `FR`, `DE`, `ES`, `AR`, `TR` | The language or region of the content |
| **Quality** | `4K`, `FHD`, `HD`, `SD`, `HQ`, `LQ` | Video quality/resolution of the stream |
| **Platform/Service** | `NF`, `EAR`, `D+`, `24/7`, `PRIME` | The streaming service or channel format |

These are orthogonal. A channel can have a platform prefix (NF) without any language prefix. Mixing them into one "Categories" bucket causes filters to behave unexpectedly — filtering on Language should never affect Platform-prefixed channels.

Canonical prefix→group mappings live in `metatv/core/config.py` (`BASE_PREFIX_GROUPS`, `BASE_QUALITY_GROUPS`, `BASE_PLATFORM_GROUPS`). User overrides are applied on top. Never define these mappings elsewhere.

---

## Filtering Logic Rules

1. **No filter active = show all content.** An empty selection in either tier must never hide anything.

2. **Unmapped prefixes are always visible.** A channel whose `detected_prefix` doesn't appear in any configured group is not excluded by any filter. Only channels whose prefix is explicitly in a *deselected* (Tier 1) or *checked* (Tier 2) group are affected.

3. **Tier 2 exclusions apply everywhere; Tier 1 applies to channel search only.** The Exclusions modal affects Discovery, Recommendations, EPG, and the channel list. The Quick Filter Bar only narrows the channel search results.

4. **`detected_prefix IS NULL` channels** (no detectable prefix): controlled separately via "Hide untagged channels" (Tier 1) and "Hide content with no category label" (Tier 2). Off by default in both — untagged channels are visible unless explicitly hidden.

5. **Tier 2 exclusions take precedence.** A channel hidden globally stays hidden even if the Tier 1 filter would include it.

---

## Current Implementation State

| Feature | Status |
|---------|--------|
| Tier 1 Quick Filter Bar | Implemented. Language + Quality dropdowns. **Missing: Platform dropdown.** |
| Tier 1 whitelist model | Implemented with "all selected = no filter" fix for unmapped prefixes. |
| Tier 2 Exclusions modal | Partially implemented as "Global Filter" dialog. Currently whitelist — **needs flip to blacklist.** |
| Hidden Content tab in Exclusions | Not yet unified. Hidden view exists separately. |
| Platform as separate Tier 1 axis | **Not yet implemented.** |

---

## Roadmap

- [ ] **Flip Global Filter to blacklist** — checking a group hides it; nothing checked = hide nothing; rename to "Exclusions"
- [ ] **Add Platform dropdown to Quick Filter Bar** — NF, EAR, D+, 24/7 get their own filter axis
- [ ] **Unified Exclusions modal** — combine Global Filter categories + Hidden Content into one tabbed dialog
- [ ] **Filter presets** — save named filter combos ("HD English", "Platform only", etc.)
- [ ] **Search within excluded results** — for large filtered datasets (50k+)
