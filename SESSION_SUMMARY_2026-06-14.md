# MetaTV Session Summary — 2026-06-14
## Issues Diagnosed, Fixed, and Architectural Gaps Identified

---

## Overview
This session addressed three distinct issues around the details pane and data visibility:
1. Missing star ratings in details panel
2. Unexplained German language content with no indicator
3. Category metadata underutilization

Each revealed gaps in the data architecture and metadata pipeline.

---

## Issue #1: Missing Star Ratings in Details Panel

### Problem
- Discover cards showed ratings (e.g., ★ 8.5/10)
- Details pane showed nothing
- Both should use the same data

### Root Cause Analysis

**Initial diagnosis:** The metadata provider was intentionally filtering out Xtream API's top-level `rating` field (lines 85-86 in `provider_metadata.py`), considering it placeholder data (always "10" or "5"). The code tried to fall back to `raw_rating`, but:

1. **Flat vs. nested raw_data structures:** Xtream providers return either:
   - **Flat:** `{num, name, stream_type, stream_id, stream_icon, rating, ...}` 
   - **Nested:** `{info: {rating, cast, plot, ...}, ...}`

2. **Issue:** For flat structures, the `rating` field is popped before use, so the fallback never triggers.

3. **Secondary issue:** Even when fallback worked, ratings only displayed in `load_metadata()` (async), not in `load_basic()` (immediate).

### Test Results
Checked 4 channels WITHOUT ratings and 4 WITH:
```
WITHOUT ratings showing:
- Mortal Kombat II (2026): rating=7.884 in raw_data
- Michael (2026): rating=8.388 in raw_data
- EN - Michael (MULTI SUB): rating=7.6 in raw_data
- Masal Şatosu: rating=9.8 in raw_data

WITH ratings showing:
- EN - The Yellow Tie (2025): rating=8.5
- EN - Iron Maiden Burning Ambition (2026): rating=6.9
```

**Key insight:** All channels HAD rating data in raw_data. The ones not showing had simpler flat structures.

### Fixes Implemented

**Fix 1 (metadata_manager.py):**
```python
# Preserve raw_data rating before filtering
raw_rating = channel.raw_data.get('rating') if channel.raw_data else None
# Later:
rating=self._parse_rating(info.get('rating')) or self._parse_rating(raw_rating)
```

**Fix 2 (details_sections.py) — PRIMARY FIX:**
Show rating immediately from raw_data in `load_basic()`, don't wait for metadata:
```python
# In load_basic() - runs instantly
if channel.raw_data:
    raw_rating = channel.raw_data.get("rating")
    if raw_rating:
        rating_val = float(raw_rating)
        rating_val = max(0.0, min(10.0, rating_val))
        stars = self.config.rating_star_icon * int(rating_val / 2)
        self.rating_label.setText(f"{stars} {rating_val:.1f} of 10")
        self._rating_row.show()
```

### Architectural Insight
**Ratings should not be async-dependent.** The raw_data is available immediately; the details pane should show it without waiting for metadata enrichment. External providers (TMDb/IMDb) can override later if they have better data, but initial display shouldn't block on async operations.

---

## Issue #2: German Channel with No Language Indicator

### Problem
- Channel: `4814008b-38ab-4db1-b790-0e22aaec89e1_2093486` ("Michael (2026)")
- User confirmed it's German (heard German audio in MPV stream)
- No "DE" badge visible in UI
- No indication in channel name or metadata

### Raw Data Analysis
```json
{
  "num": 66645,
  "name": "Michael (2026)",
  "stream_type": "movie",
  "stream_id": 2093486,
  "category_id": 100,
  "rating": "8.388",
  "tmdb": 936075,
  // ... no language field
}
```

**Key discovery:** 
- `detected_region`: NULL
- `detected_prefix`: NULL
- Channel name has NO language prefix (unlike "EN -", "DE -", "LAT -" prefixes on other channels)
- **BUT** `category_id: 100` is present

### Category Analysis
Queried all channels by category_id to understand the mapping:

```
Category 100: 3,128 channels
  Sample: "DE - Sword of Vengeance (2025)"  ← All category 100 samples start with "DE -"

Category 865: 6,192 channels
  Sample: "DE - Die Mumie..." ← Also German

Category 961: 3,115 channels
  Sample: "EN - 5th Ward (2018)" ← English

Category 343: 5,323 channels
  Sample: "Yeraltı 14. Bölüm" ← Turkish

Category 597: 3,597 channels
  Sample: "SE - Avig Maria" ← Swedish (SE)
```

**CRITICAL FINDING:** The Xtream provider organizes channels by language via `category_id`. Each category_id maps to a specific language/region, inferrable from the dominant language prefix in channel names within that category.

### Why This Matters
The language information IS in the database—it's encoded in `category_id`. The "Michael (2026)" channel's lack of prefix doesn't mean it's language-agnostic; it means the PROVIDER didn't include a prefix in the channel name. The category_id tells us it's German.

### Architectural Gap
**Language metadata is implicit, not explicit:**
- `category_id` is available but not interpreted
- `detected_region` is NULL (because the channel name has no prefix to parse)
- `source_category` field exists but is NULL (never populated from provider category mapping)
- No language lookup table exists to map category_id → ISO language codes

---

## Issue #3: Categories Section Loading Indicator

### Problem
When details pane loads, categories section appeared empty until metadata loaded.

### Fix Implemented
Added loading indicator in `load_basic()`:
```python
self.genres_label.setText(f"{_icons.loading_icon} Loading categories...")
self.genres_label.show()
```

Clears on metadata load (shows genres if available, hides if none).

**Minor issue:** This created false dependency—categories shouldn't block ratings display. **Now fixed:** ratings show immediately from raw_data.

---

## Additional Fixes in This Session

### 1. Inactive Provider Filtering (Early Session)
- **Issue:** Disabling a provider didn't remove its channels from results
- **Fix:** Calculate `inactive_provider_ids` and pass to `excluded_provider_ids` in queries
- **Commit:** `c133377`

### 2. Button Styling (Early Session)
- Individual refresh buttons: Blue (action color) ✓
- Header "Refresh All": Gray (neutral) ✓
- Edit button: Teal (distinguish from refresh) ✓

### 3. Channel ID Identification
- Added click-to-copy source label showing channel ID in tooltip
- Enables debugging and channel-specific reference
- **Commit:** `d5a8bd7`

### 4. Detected Region Display
- `detected_region` now shows as category chip if present
- Fixes cases where region info was parsed but not displayed

---

## Architectural Gaps & Opportunities

### Gap 1: Language Metadata Not Explicit
**Current state:**
- `category_id` encodes language but is never interpreted
- `source_category` field exists but never populated
- `detected_region` only populated from channel name prefixes

**Opportunity:**
Build a `category_id → language` mapping by:
1. On provider load, scan all channels by category_id
2. Extract dominant `detected_prefix`/`detected_region` per category
3. Store or cache the mapping (e.g., category 100 → "DE")
4. Use mapping to display language for channels like "Michael (2026)" that lack explicit prefix

### Gap 2: Async Dependency Chain
**Current pattern:**
- `load_basic()` → immediate UI display
- `load_metadata()` → async, updates UI later
- Problem: Some data (ratings) was blocked on metadata

**Fix applied:** Ratings now show from raw_data in `load_basic()`, metadata enriches later.

**General principle:** Move all immediately-available data (from channel/raw_data) into `load_basic()`. Reserve `load_metadata()` for enrichment only.

### Gap 3: Raw Data Interpretation Inconsistent
**Examples:**
- `rating` field: recognized and displayed
- `category_id`: present but ignored
- Language info: only from channel name prefix parsing, not from category
- Quality/region fields: parsed from name, not read from raw_data fields if present

**Opportunity:** Audit raw_data schema and create systematic extraction for:
- Language/region (from category_id or explicit fields)
- Ratings (already fixed)
- Subtitles/audio tracks (if present)
- Content warnings/ratings (MPAA, etc.)

---

## Summary of Commits This Session

| Commit | Message | Impact |
|--------|---------|--------|
| `c133377` | Fix: exclude inactive providers | Views update when provider disabled |
| `a7390f4` | Fix: show rating via raw_data fallback | Ratings appear when metadata loads |
| `b4417c5` | Fix: individual refresh buttons blue | UI consistency |
| `42c5678` | Feat: show detected_region chip | German channels now show "DE" badge |
| `d5a8bd7` | Feat: click source to copy channel ID | Debugging aid |
| `46a1ac8` | Feat: categories loading indicator | UX feedback |
| `49d2834` | Fix: show rating immediately from raw_data | **PRIMARY FIX** — ratings don't wait for metadata |
| `1968194` | Refactor: debug logging for rating | Diagnostic aid |

---

## Recommended Architectural Direction

### Phase 1 (Immediate)
✅ **Completed this session:**
- Ratings display immediately from raw_data
- Inactive providers filtered out
- Channel ID discoverable

### Phase 2 (High Value)
**Build language metadata extraction:**
- Map `category_id` to language by analyzing channel names in each category
- Populate `source_category` or add explicit `source_language` field
- Display language for all channels, including those without prefix

**Effort estimate:** 2-3 hours
- SQL to group channels by category_id and extract dominant prefix
- Storage strategy (ephemeral mapping vs. db field)
- UI integration (show language chip next to existing region chips)

### Phase 3 (Architectural Cleanup)
**Audit and systematize raw_data extraction:**
- Document what data each provider includes in raw_data
- Build extraction layer that populates detected_* fields comprehensively
- Eliminate async dependency chains where immediate data exists

### Phase 4 (Future)
**Consider metadata provider enrichment:**
- Current fallback: Xtream raw_data → metadata enrichment layer (TMDb/IMDb)
- Opportunity: Add language confidence scoring if multiple sources conflict
- Store language assertions with source provenance

---

## Questions for Opus Analysis

1. **Category ID mapping:** Should this be computed at ingestion time (in provider_loader), cached in DB, or computed on-demand?

2. **Language field strategy:** Add explicit `detected_language` column to ChannelDB, or use calculated property from category_id?

3. **Async dependency removal:** Beyond ratings, what other immediate data is currently blocked on async metadata? Should we audit all raw_data fields?

4. **Raw data schema evolution:** Should we maintain a provider-specific schema registry to document what each provider includes?

---

## Files Modified
- `metatv/metadata_providers/provider_metadata.py` — Rating fallback + logging
- `metatv/gui/details_sections.py` — Show rating immediately + detected_region + loading indicator + channel ID tooltip
- `metatv/core/repositories/channel.py` — Add excluded_provider_ids to get_hidden_channels
- `metatv/gui/main_window.py` — Calculate inactive_provider_ids
- `metatv/gui/sidebar/sources.py` — Button styling (minor)

## Test Status
✅ All 400 tests pass
