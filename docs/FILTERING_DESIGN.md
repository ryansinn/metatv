# Filtering System Design

## Core Philosophy

**The system operates on an opt-out model. Content is visible by default.**

We cannot know in advance what prefix groups, providers, or content categories will exist in any given user's IPTV library. New providers introduce new prefixes; new categories emerge over time. Any system that requires content to be explicitly *included* to be visible will silently exclude new content as the system evolves — and users will see incomplete results without knowing why.

The correct mental model: **everything is shown unless the user explicitly hides it.** Filters are tools for narrowing or excluding, not for granting visibility.

---

## Excluded Content Remains Discoverable

**Global Exclusions hide content from browse and discovery — they do not erase it.**

When a user excludes "Indian" prefix channels, those channels disappear from the channel list, Discovery shelves, and Recommendations. But if the user navigates to a specific movie's details pane and that movie exists in an Indian-prefixed version, that version appears in the **Other Versions** panel — **grayed out** with an indicator that it's in an excluded category.

**Why this matters**: content boundaries are messy. An Indian-labeled channel may carry English audio with Indian subtitles. A Nigerian-prefixed provider may carry British documentary content. A user who excluded Arabic may still want to know that an Arabic version of their favorite show exists — and might be the only version with certain audio tracks.

The grayed-out display communicates:
- "This version exists, but it's in a category you said you don't want in general."
- "You can still play it if you want to."

This makes Global Exclusions a **browsing preference**, not a hard block. The user's general preference is respected throughout the library; their ability to discover specific content is never fully removed.

**Practical implication**: when implementing any new "Other Versions" or cross-source discovery UI, excluded versions must always appear (visually distinguished) rather than being silently hidden.

---

## Metadata Accuracy Limitation

**Locale-specific filtering is only as good as what the provider labeled.**

The filter system derives everything from the `detected_prefix` field — the token before the separator in each channel name. A US provider and a UK provider may both label channels "EN - Show Title". There is no way to distinguish their origins from the prefix alone.

**Consequences:**
- "English (North America)" matches only channels explicitly prefixed `US` or `CA`. It does not catch `EN`-prefixed channels from North American providers.
- "French (Europe)" catches `FR`, `BE`, `CH`, `LU` prefixed channels. It does not catch `FR`-prefixed channels from Québécois or African providers.
- Most providers use language-code prefixes (EN, ES, FR) regardless of country of origin.

**The right user guidance**: if metadata doesn't indicate the specifics, filter broadly. An American user who wants to reduce non-English content should exclude **Indian**, **Vietnamese**, **Korean**, **Arabic**, **Chinese** (and other language groups) via Global Exclusions — not try to include "English (North America)" only. Global Exclusions at the language-group level is the correct tool for 90% of users.

The locale sub-groups (English (North America), French (Europe), etc.) exist for edge cases where providers *do* use country-code prefixes, and for users who specifically want to drill into that level of precision.

---

## Two-Tier Filter System

Two filter systems with different scopes and mental models.

### Tier 1 — In-Session View Filters (Quick Filter Bar)

**Scope**: Per-view. In-session. Resets are low-cost.

**Mental model**: "Show me only X right now."

**Interaction**: "Only Show:" whitelist-style dropdowns. Selecting "English" narrows results to English channels. Nothing selected = show all.

**Three orthogonal filter axes** (AND logic across axes):

| Axis | Field | Behavior |
|------|-------|----------|
| **Language/Region (Category)** | `detected_prefix` IN selected OR `detected_region` IN selected | **Inclusive** — channels with no language tag also show (controlled by "Show untagged content" toggle) |
| **Quality** | `detected_quality` IN selected | **Exclusive** — only explicitly-tagged channels match |
| **Platform** | `detected_prefix` IN selected | **Exclusive** — only platform-prefixed channels match |

Keeping Platform separate is critical: selecting "English" in Language must never exclude NF, EAR, or D+ channels — those are platform prefixes on a different axis.

**Locale sub-groups**: for languages with multiple regional variants, narrower groups exist alongside the aggregate:
- "English" = all English (EN, UK, US, AU, CA, ZA…) — **use this for most cases**
- "English (North America)" = US, CA only — catches country-code-prefixed channels only
- Same pattern for French (Europe/Canada/Africa), Portuguese (Portugal/Brazil/Africa), Arabic (Gulf/Levant/North Africa), Spanish (Spain/Mexico/South America/Central America)

### Tier 2 — Global Exclusions Modal

**Scope**: All views — Discovery, Recommendations, EPG, channel list. Persistent.

**Mental model**: "Always hide X."

**Interaction**: Blacklist-style checkboxes. Checking a group **hides** all channels in that group everywhere. Nothing checked = hide nothing.

**Primary use case**: language exclusion. An American user opens Exclusions, checks Indian, Vietnamese, Korean, Arabic, Chinese — those language groups disappear from everywhere. One decision, set once, applies across the entire app.

**Two sections**:
1. **Language/Category prefix groups** — hide broad categories everywhere.
2. **Content Types** — hide channel types by source category header (Sports, News, Kids, etc.).

**Does not affect**: Other Versions panel in the details pane — excluded versions always appear there, grayed out. See "Excluded Content Remains Discoverable" above.

---

## Prefix Category Types

Three distinct semantic types of channel prefixes:

| Type | Examples | Filter axis |
|------|----------|------------|
| **Language/Region** | `EN`, `FR`, `DE`, `ES`, `AR`, `TR`, `HI`, `TE` | Language/Category (Tier 1), Exclusions (Tier 2) |
| **Quality** | `4K`, `FHD`, `HD`, `SD`, `HQ`, `LQ` | Quality (Tier 1) |
| **Platform/Service** | `NF`, `EAR`, `D+`, `24/7`, `PRIME` | Platform (Tier 1) |

Canonical prefix→group mappings live in `metatv/core/config.py`:
- `BASE_PREFIX_GROUPS` — language/region groups + locale sub-groups
- `BASE_REGIONAL_GROUPS` — geographic groups (Africa, Europe, Latin America, etc.) orthogonal to language groups
- `BASE_QUALITY_GROUPS`, `BASE_PLATFORM_GROUPS`

---

## Filtering Logic Rules

1. **No filter active = show all content.** Empty selection in either tier hides nothing.

2. **Unmapped prefixes are always visible.** A channel whose `detected_prefix` doesn't appear in any configured group is not excluded by any filter. Unmapped = unclassified, not excluded.

3. **Tier 2 exclusions apply everywhere; Tier 1 applies to channel search only.** The Exclusions modal affects Discovery, Recommendations, EPG, and the channel list. The Quick Filter Bar only narrows channel search results.

4. **Untagged channels** (no detected_prefix): shown by default. "Show untagged content" toggle in Tier 1 controls whether they pass through the language filter. "Hide content with no category label" in Tier 2 is off by default.

5. **Tier 2 exclusions always take precedence** over Tier 1 whitelists. A globally excluded channel stays excluded even if Tier 1 would include it.

6. **Excluded content is never fully hidden.** See the "Excluded Content Remains Discoverable" section above.

---

## Implementation Status

| Feature | Status |
|---------|--------|
| Tier 1 Quick Filter Bar | ✅ Language + Quality + Platform dropdowns |
| Tier 1 whitelist model | ✅ "all selected = no filter" logic |
| Tier 1 locale sub-groups | ✅ English/French/Portuguese/Arabic/Spanish regional variants |
| Three independent SQL axes | ✅ Language inclusive, Quality/Platform exclusive |
| Language suffix detection (EN, (US)) | ✅ `detected_region` column |
| Quality anywhere in name | ✅ `detected_quality` column (prefix + suffix) |
| Tier 2 Exclusions modal | ✅ Blacklist model, opt-out |
| Global Exclusions applied to search | ✅ |
| Prefix normalization | ✅ Full country/language names → standard codes on ingest |
| Geographic regional groups | ✅ 18 continent/area groups in `BASE_REGIONAL_GROUPS` |
| Grayed-out excluded versions in details pane | ✅ |
| Debounced SQL search | ✅ 200ms, 5k page cap |

---

## Roadmap

- [ ] **Filter bar hierarchy** — Language and Region as separate or tree-structured dropdowns; expandable group→prefix drill-down for "Other" prefix review
- [ ] **Regional filter axis** — expose `BASE_REGIONAL_GROUPS` in the filter bar as a "Region" dropdown alongside "Category"
- [ ] **Compound locale approach** — store `detected_language` and `detected_country` separately; enables EN-US / EN-CA as truly distinct queryable values (currently limited by prefix-only detection)
- [ ] **User-defined prefix groups** — UI to assign "Other" prefixes to groups; backed by `user_prefix_overrides` in config
- [ ] **"Copy filters from…" across views** — apply a dialed-in Tier 1 filter from one view (Search/Discover/EPG) to another
- [ ] **"Promote to Global Exclusion"** — convert an active Tier 1 exclusion to a permanent Tier 2 exclusion (requires inversion: everything NOT selected becomes excluded)
- [ ] **Discover shelves** respect Global Exclusions for shelf *visibility* — a shelf should not appear in Manage Discovery Shelves if all its content is globally excluded
- [ ] **EPG On Now / Browse** — add Tier 1 filter bar consistent with the search model
