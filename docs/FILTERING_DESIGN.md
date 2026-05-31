# Filtering System Design

## Core Philosophy

**The system operates on an opt-out model. Content is visible by default.**

We cannot know in advance what prefix groups, providers, or content categories will exist in any given user's IPTV library. New providers introduce new prefixes; new categories emerge over time. Any system that requires content to be explicitly *included* to be visible will silently exclude new content as the system evolves — and users will see incomplete results without knowing why.

The correct mental model: **everything is shown unless the user explicitly hides it.** Tier 1 filters narrow a view temporarily. Tier 2 Global Exclusions permanently suppress content from browsing. Neither is a hard block — excluded content always remains discoverable through direct navigation.

---

## Excluded Content Remains Discoverable

**Global Exclusions hide content from browse and discovery — they do not erase it.**

When a user excludes "Indian" prefix channels, those channels disappear from the channel list, Discovery shelves, and Recommendations. But if the user navigates to a specific movie's details pane and that movie exists in an Indian-prefixed version, that version appears in the **Other Versions** panel — **grayed out** with an indicator that it's in an excluded category.

**Why this matters**: content boundaries are messy. An Indian-labeled channel may carry English audio with Indian subtitles. A Nigerian-prefixed provider may carry British documentary content. A user who excluded Arabic may still want to know that an Arabic version of their favorite show exists — and might be the only version with certain audio tracks.

The grayed-out display communicates:
- "This version exists, but it's in a category you said you don't want in general."
- "You can still play it if you want to."

This makes Global Exclusions a **browsing preference**, not a hard block.

**Practical implication**: when implementing any new "Other Versions" or cross-source discovery UI, excluded versions must always appear (visually distinguished) rather than being silently hidden.

---

## Why There Is No Per-Item Filter Exemption

Users sometimes want a specific channel or title to always appear even when its category is globally excluded. We deliberately do not support this.

**The existing tools already solve this:**

1. Pause Global Exclusions (the Exclusions chip) — the entire library becomes visible.
2. Find the content and add it to Watchlist, Favorites, or Watch Queue.
3. Resume exclusions.

Once content is in a curated collection, it is permanently accessible regardless of what filters are active. Watchlist, Favorites, and Watch Queue show their contents without applying Global Exclusions — those are things the user has explicitly decided they want, and filters are about reducing noise in general browsing.

**The rule:** if a user wants something to always be accessible, they add it to a curated collection. Filters are for browsing. Collections are for decisions.

---

## Two-Tier Filter System

### Tier 1 — In-Session View Filters (Quick Filter Bar)

**Scope**: Per-view. In-session. Low cost to change or clear.

**Mental model**: "Show me this right now."

**Interaction**: Additive multi-select dropdowns. Selecting more options always grows the result set — it never reduces it. Nothing selected on an axis = no filter applied for that axis (show all).

### Tier 2 — Global Exclusions Modal

**Scope**: All views — Discovery, Recommendations, EPG, channel list. Persistent across sessions.

**Mental model**: "Never show me this unless I specifically go looking."

**Interaction**: Blacklist-style three-state checkboxes (on / off / partial for hierarchical groups). Checking a group **hides** all channels in that group everywhere. Nothing checked = hide nothing.

**Primary use case**: language exclusion. An American user opens Exclusions, checks Indian, Vietnamese, Korean, Arabic, Chinese — those language groups disappear from everywhere. One decision, set once, applies across the entire app.

**Does not affect**: Other Versions panel in the details pane — excluded versions always appear there, grayed out.

---

## Tier 1 Filter Logic — Identity Pool + Quality

The key insight: **filters grow the result set, they do not shrink it** (except Quality).

### Identity Pool (Language OR Region OR Platform)

Language, Region, and Platform are three ways to describe "content I want to see." Selecting any combination across these three axes produces a **union** — more selections always mean more content.

```
identity_pool = (selected_languages) OR (selected_regions) OR (selected_platforms)
result        = identity_pool AND (selected_qualities)
```

**Why OR, not AND:**
- Language and Region are two lenses on the same cultural audience. A viewer who wants content from Mexico fundamentally understands Spanish — the same person who would select Language=Spanish. Selecting both expands the pool, not restricts it.
- A user browsing for French cinema is probably thinking of France, not Francophone Africa. But a viewer from Senegal looking for content from home has a completely different intent. The source metadata tells us which is which — we surface that context so the user can make an informed choice, not flatten it all into "French."
- Someone who wants "Spanish content" OR "Latin American content" should see everything they want. Forcing AND would return near-nothing because channels are classified as either language OR region, rarely both.

**Quality is the only restrictive axis.** Selecting Quality=HD narrows the identity pool to HD results only. Within Quality, multi-select is OR (HD or 4K = either).

### No selection on any axis

- No languages, regions, or platforms selected = all channels in the pool (no identity filter).
- No quality selected = all quality tiers shown (no quality filter).
- Both axes empty = show everything (same as default view).

---

## The Five Filter Axes

### Axis 1 — Language

**What it means**: the spoken/audio language of the content, as classified by the channel prefix.

**Behavior**: OR within the axis (multi-select grows pool). Also ORs with Region and Platform.

**Includes by default**:
- Dubbed variants for the selected language (`DUB`, `DUBBED`)
- Subtitled variants for the selected language (`SUB`)

A user selecting Spanish gets Spanish-audio channels, Spanish-dubbed channels, and Spanish-subtitled channels — all directed at Spanish-speaking audiences.

**Locale sub-groups**: for languages with meaningful regional variants, narrower groups exist alongside the aggregate:
- "French" = all French content (FR, FRA, FRANCE, Francophone Africa, Quebec, etc.)
- "French (France)" = FR, FRA, FRANCE prefixes only — for the user who specifically wants French cinema from France, not Cameroonian TV
- Same pattern for English (UK / North America / Australia), Portuguese (Portugal / Brazil), Arabic (Gulf / Levant / North Africa), Spanish (Spain / Mexico / South America)

**Known limitation**: locale sub-groups only catch channels that are explicitly country-code prefixed. A channel labeled `EN ★ CNN` cannot be distinguished from one labeled `US ★ CNN` — both are English, but only the latter is caught by "English (North America)." Filter broadly when provider labeling is inconsistent.

### Axis 2 — Region

**What it means**: the geographic origin or audience target of the content, as classified by the channel prefix.

**Behavior**: OR within the axis (multi-select grows pool). Also ORs with Language and Platform.

**Hierarchy**: Continent → Sub-region → Country/City/Area

```
Americas
  ├─ North America (US, CA, MX...)
  ├─ Central America (GT, HN, CR...)
  └─ South America
       ├─ Brazil (BR, BRA)
       ├─ Argentina (AR, ARG)
       └─ ...

Europe
  ├─ Western Europe (FR, DE, IT, ES, PT...)
  ├─ Eastern Europe (PL, RO, CZ...)
  └─ ...

Africa
  ├─ North Africa (MA, DZ, TN, LY, EG...)
  ├─ West Africa (NG, GH, SN, CI...)
  └─ ...

Asia
  ├─ East Asia (CN, JP, KR, TW...)
  ├─ South Asia (IN, PK, BD...)
  └─ Southeast Asia (TH, VN, ID, PH...)

...
```

**Why Region matters**: a viewer abroad who wants to follow their home country's news and culture selects Region=Mexico — they get exactly Mexican-labeled content (MX, MEX, MEXICO prefixes) without sifting through 10,000 Spanish-language channels. This precision is only possible because the source explicitly labeled those channels as Mexican.

**Relationship with Language**: a prefix like `MX` belongs to BOTH the Spanish language group AND the Mexico region group. Selecting Language=Spanish catches MX channels. Selecting Region=Mexico also catches MX channels. The difference is precision: Language=Spanish casts a wide net across all Spanish content; Region=Mexico scopes to explicitly Mexican-labeled content only.

**UI**: Three-state hierarchical selector (on / off / partial) — same model as Global Exclusions dialog. Selecting a continent automatically includes all its sub-regions; selecting a sub-region marks the continent as partial.

### Axis 3 — Platform

**What it means**: branded service or delivery platform (NF, PRIME, EAR, VIX, D+, etc.).

**Behavior**: OR within the axis (multi-select grows pool). Also ORs with Language and Region.

**No "Streaming" catchall**: each service is its own selectable group. Bundling 18,000 channels into one "Streaming" group provides no value — users need to be able to select Netflix independently from Amazon Prime independently from EAR.

**EAR specifically**: EAR (Arabic-Subtitled Foreign Content) is a platform/service classification — it is NOT an Arabic-language group. EAR channels carry content in English, French, Brazilian Portuguese, and other source languages with Arabic subtitles added. Filtering Language=Arabic does not surface EAR channels; filtering Platform=EAR does. EAR is also included in the Multi/Subtitle group for discoverability by Arabic-audience users who want subtitle content.

**DSTV specifically**: DSTV (MultiChoice / DStv Sub-Saharan Africa) is a regional service classification. Its channels are directed at an African audience and appear in the Africa regional group. Content language varies (often English). Not a language group.

### Axis 4 — Quality

**What it means**: technical resolution and encoding tier.

**Behavior**: AND with the identity pool (restrictive). OR within the axis (4K or HD = either).

**Tiers**: RAW, 4K / UHD, FHD / 1080p, HD / 720p, SD, and untagged (no quality marker).

**RAW**: highest-tier streams — often uncompressed or minimally processed, frequently at 4K or above. Separate from the 4K group because RAW is a delivery characteristic, not just a resolution label. Users seeking the best available quality specifically want RAW.

**Detection**: `detected_quality` column, populated by `update_detected_prefixes()` on ingestion. Scans both the prefix position and suffix position in the channel name (quality markers appear in both places: `4K ★ Channel Name` and `Channel Name ᴴᴰ ᴿᵃʷ`). Also falls back to the API `quality` field when name-based detection fails.

### Axis 5 — Audio / Subtitle (modifier on Language)

Sub and Dub are included within the Language axis — they are not a separate filter dropdown.

When a user selects Language=Spanish:
- Channels with Spanish audio are included
- Channels dubbed into Spanish (`ES DUB`, `ES DUBBED`) are included
- Channels with Spanish subtitles (`ES SUB`) are included

The value target is the Spanish-speaking audience — whether the content serves them via audio, dubbing, or subtitles is a delivery detail, not a filter dimension. A separate Sub/Dub toggle would incorrectly reduce the pool.

**EAR vs individual SUB labels**: EAR is a service-level platform that bundles foreign content with Arabic subtitles — it belongs in Platform, not the Language axis. Individual per-channel `SUB` labels (e.g., `ES ★ Título SUB EN`) are per-channel classifications that flow into the subtitle language group for that specific language.

---

## Prefix Group Membership

**One true raw value, multiple group memberships.**

Each channel has one `detected_prefix` (the normalized token parsed from the channel name — e.g., "EAR", "NF", "ARG", "EN"). This is the truth. Group membership is derived at classification time: a prefix can appear in multiple group definitions in `config.py`.

- `MX` appears in: Spanish language group + Mexico region group + Latin America region group
- `EAR` appears in: Platform group + Multi/Subtitle group (not Arabic language group)
- `AS` appears in: Asia region group (not a language group — AS is broad Asian content: Korean, Japanese, Chinese, South Asian, Southeast Asian)

The SQL `detected_prefix IN (group_members)` query handles multi-group membership naturally — no additional columns required for discoverability.

---

## Metadata Accuracy Limitation

**Regional precision is only as good as what the provider labeled.**

Locale sub-groups and country-level region filters only work when providers use country-code prefixes (`US`, `MX`, `FR`). Many providers use language-code prefixes (`EN`, `ES`, `FR`) regardless of country of origin — those channels cannot be distinguished geographically.

**The right user guidance**: filter at the language or continent level when provider labeling is inconsistent. Country-level precision is a bonus when the source gives us that metadata; it is not guaranteed.

---

## Filtering Logic Rules

1. **No filter active = show all content.** Empty selection on any axis applies no filter for that axis.

2. **Selections grow the pool.** Language=Spanish + Language=French shows more than either alone. Language=Spanish + Region=Mexico shows more than either alone.

3. **Quality is the only AND restriction.** Everything else ORs.

4. **Unmapped prefixes are always visible.** A channel whose `detected_prefix` doesn't appear in any configured group is not excluded by any filter. Unmapped = unclassified, not excluded.

5. **Tier 2 Global Exclusions apply everywhere; Tier 1 applies to the active view only.** Exclusions affect Discovery, Recommendations, EPG, and the channel list. The Quick Filter Bar only narrows the current view.

6. **Tier 2 exclusions take precedence over Tier 1.** A globally excluded channel is hidden from browse even if a Tier 1 filter would include it. It remains accessible in Other Versions (grayed out) and in curated collections (Favorites, Watchlist, Watch Queue).

7. **Excluded content is never fully hidden.** See the "Excluded Content Remains Discoverable" section above.

---

## Canonical Data Locations

| Data | Location |
|------|----------|
| Language groups + locale sub-groups | `metatv/core/config.py` → `BASE_PREFIX_GROUPS` |
| Geographic regional hierarchy | `metatv/core/config.py` → `BASE_REGIONAL_GROUPS` |
| Quality tiers | `metatv/core/config.py` → `BASE_QUALITY_GROUPS` |
| Platform/service groups | `metatv/core/config.py` → `BASE_PLATFORM_GROUPS` |
| Prefix normalization / alias map | `metatv/core/channel_name_utils.py` → `_ALIAS_MAP`, `normalize_region_code()` |
| Quality detection | `metatv/core/filter_utils.py` → `extract_quality()` |
| Filter bar UI | `metatv/gui/filter_bar.py` |
| Channel query with filter axes | `metatv/core/repositories/channel.py` → `get_all()` |
| Global Exclusions dialog | `metatv/gui/global_filter_dialog.py` |

---

## Implementation Status

| Feature | Status |
|---------|--------|
| `detected_prefix` column + prefix normalization | ✅ |
| `detected_quality` column (prefix + suffix + API fallback) | ✅ |
| `detected_region` column (parenthetical suffix e.g. `(US)→US`) | ✅ |
| Tier 1 Language filter dropdown | ✅ |
| Tier 1 Quality filter dropdown | ✅ |
| Tier 1 Platform filter dropdown | ✅ |
| Tier 1 "N results filtered" inline bypass button | ✅ |
| Tier 1 locale sub-groups (EN/FR/PT/AR/ES regional variants) | ✅ |
| Tier 2 Global Exclusions modal (blacklist model) | ✅ |
| Global Exclusions applied to search + Discovery | ✅ |
| Grayed-out excluded versions in details pane | ✅ |
| Debounced SQL search (200ms, 5k page cap) | ✅ |
| User Categories (custom discovery shelves, mood signals) | ✅ |
| **Tier 1 filter logic: Language OR Region OR Platform identity pool** | ❌ not yet — currently AND across axes |
| **Tier 1 Region filter dropdown (hierarchical)** | ❌ `BASE_REGIONAL_GROUPS` defined but not wired to UI |
| **Region UI: three-state hierarchical selector** | ❌ not yet built |
| **RAW quality tier in detection + filter bar** | ❌ |
| **Platform split: individual brand groups (no Streaming catchall)** | ❌ |
| **EAR reclassified to Platform/Multi (not Arabic)** | ❌ |
| **Sub/Dub included within Language axis** | ❌ |
| **Compound locale schema** (`detected_language`, `detected_platform` separate columns) | ❌ deferred — current prefix-based OR model is sufficient for now |

---

## Roadmap

- [ ] **Wire BASE_REGIONAL_GROUPS to filter bar** — Region dropdown with hierarchical three-state picker (same model as Global Exclusions dialog)
- [ ] **Implement Language OR Region OR Platform pool logic** — replace current AND-across-axes SQL with the identity pool model
- [ ] **Split BASE_PLATFORM_GROUPS** — individual brand groups: NF, PRIME, D+, VIX, JOYN, TUBI, GOLD, VIP, WOW, SHAHID; remove "Streaming" catchall
- [ ] **Add RAW to quality detection** — scan suffix position in channel names for RAW/ᴿᵃʷ tokens; add RAW tier to BASE_QUALITY_GROUPS
- [ ] **Reclassify EAR** — move from Arabic language group to Platform + Multi/Subtitle groups
- [ ] **Sub/Dub within Language axis** — include DUB/SUB prefixed channels in their target-language group results
- [ ] **Others prefix audit** — add French/Spanish/Arabic country name variants to `_ALIAS_MAP` (MAROC→MAR, ALGÉRIE→DZA, etc.)
- [ ] **User-defined prefix groups** — UI to assign "Other" prefixes to existing groups or new custom groups; backed by `user_prefix_overrides` config
- [ ] **"Copy filters from…" across views** — apply a dialed-in Tier 1 filter from one view to another
- [ ] **"Promote to Global Exclusion"** — convert an active Tier 1 filter set into a permanent Tier 2 exclusion
