# Context Filter Chips — Design Pattern & Implementation Guide

Context filter chips are temporary, isolated filters that activate when the user clicks
a metadata value in the **details pane** (genre, cast member, director, etc.). They appear
inline in the search bar row, can coexist with text search, and are dismissed by the user
with a single ✕ click.

This document is the canonical reference for adding new context filter chips. Follow it
exactly so all chip filters are consistent in behaviour, UI, and code structure.

---

## Concept

The details pane surfaces metadata about a specific piece of content. A context filter
chip lets the user say **"show me more content like this attribute"** — clicking "Drama"
shows Drama movies/series; clicking "Tom Hanks" shows content featuring Tom Hanks.

### What makes a context filter chip different from the filter panel

| | Filter panel | Context filter chip |
|---|---|---|
| **Scope** | Inclusive/opt-out — channels with no data always pass through | Strict — only channels that explicitly match |
| **Lifetime** | Persisted to config; survives restarts | Ephemeral; cleared on dismiss or new chip |
| **Entry point** | User opens the panel and selects | User clicks a metadata value in the details pane |
| **Coexists with search** | Yes | Yes — text search narrows *within* the chip filter |
| **Multiple active** | All filter panel sections active simultaneously | At most one chip active at a time |

**Do not route details-pane clicks through the filter panel.** The filter panel's
inclusive passthrough semantics are correct for browsing but wrong for this use case.

---

## Architecture: the five layers

Every context filter chip touches exactly these five files:

```
metatv/core/repositories/channel.py   ← 1. SQL filter parameter
metatv/gui/details_sections.py        ← 2. Clickable widget + signal
metatv/gui/details_pane.py            ← 3. Signal bubble
metatv/gui/main_window.py             ← 4. State, chip label, handler, pass-through
metatv/gui/theme.py                   ← (no changes needed — chip styles already exist)
```

The chip widget itself (`_context_filter_chip`) already exists in `main_window.py` and
is reused for all chip types. You do not create a new widget.

---

## Step-by-step implementation

### Step 1 — SQL filter in `channel.py`

Add an `Optional[str]` parameter to `ChannelRepository.get_all()` after `strict_genre_filter`.

Write a filter that is **strict by default** — no passthrough for channels with missing data.

**Pattern A — field on `ChannelDB` (e.g. `sport_type`):**
```python
if my_filter:
    query = query.filter(ChannelDB.some_field.ilike(f"%{my_filter}%"))
```

**Pattern B — JSON field in `raw_data` (e.g. genre):**
```python
if my_filter:
    from sqlalchemy import text as _text
    query = query.filter(
        ChannelDB.media_type.in_(["movie", "series"]),   # restrict if appropriate
        _text("json_extract(raw_data, '$.field') LIKE :_val").bindparams(
            _val=f"%{my_filter}%"
        ),
    )
```

**Pattern C — field on `MetadataDB` (e.g. cast/director):**
```python
if my_filter:
    from metatv.core.database import MetadataDB as _MetaDB
    query = query.join(
        _MetaDB, ChannelDB.metadata_id == _MetaDB.id
    ).filter(
        or_(
            _MetaDB.field_a.ilike(f"%{my_filter}%"),
            _MetaDB.field_b.ilike(f"%{my_filter}%"),
        )
    )
```

The MetadataDB JOIN is an inner join — channels with no metadata are excluded, which is
correct for person/credit searches.

### Step 2 — Clickable widget in `details_sections.py`

Add a `pyqtSignal(str)` to the relevant section class:

```python
class _MySection(QWidget):
    my_filter_clicked = pyqtSignal(str)   # emits the filter value
```

In `_setup()`, enable `linkActivated` on the relevant label:

```python
self._my_label.setTextFormat(Qt.TextFormat.RichText)
self._my_label.setOpenExternalLinks(False)
self._my_label.linkActivated.connect(lambda url: self.my_filter_clicked.emit(url))
```

In `load()`, render values as HTML links using `html.escape()` on both the href and
display text. Use `_theme.COLOR_ACCENT_BLUE_2` for the link colour:

```python
import html
link_col = _theme.COLOR_ACCENT_BLUE_2
links = []
for value in values:
    href = html.escape(value, quote=True)
    links.append(
        f'<a href="{href}" style="color:{link_col}; text-decoration:none;">'
        f'{html.escape(value)}</a>'
    )
self._my_label.setText(" • ".join(links))
```

Always `html.escape()` both the `href` attribute (with `quote=True`) and the display
text to handle names/genres with `&`, `<`, `>`, or `"`.

### Step 3 — Signal bubble in `details_pane.py`

Add the public signal to `DetailsPaneWidget`:

```python
my_filter_requested = pyqtSignal(str)
```

Wire it in `_connect_sections()`:

```python
self._my_section.my_filter_clicked.connect(self.my_filter_requested)
```

### Step 4 — Main window wiring in `main_window.py`

**4a. State variable** — add next to `_details_genre_filter`:

```python
self._details_my_filter: str | None = None
```

**4b. Connect the signal** in the signal-wiring block (near line 354):

```python
self.details_pane.my_filter_requested.connect(self._on_my_filter_requested)
```

**4c. Handler** — add near `_on_genre_filter_requested`:

```python
def _on_my_filter_requested(self, value: str) -> None:
    # Clear all other context filters — only one active at a time
    self._details_genre_filter = None
    self._details_person_filter = None
    # ... clear any others ...
    self._details_my_filter = value
    self._context_filter_label.setText(f"Label: {value}")
    self._context_filter_chip.show()
    self.switch_to_list_view()
    self.load_channels()
```

**4d. Clear in `_clear_context_filter()`:**

```python
def _clear_context_filter(self) -> None:
    self._details_genre_filter = None
    self._details_person_filter = None
    self._details_my_filter = None      # ← add this
    self._context_filter_chip.hide()
    self.load_channels()
```

**4e. Pass through `load_channels()` params dict:**

```python
my_filter=self._details_my_filter,
```

**4f. Pass through `_bg_load_channels()` into `get_all()`:**

```python
my_filter=params.get('my_filter'),
```

---

## Chip label conventions

| Filter type | Label text |
|---|---|
| Genre | `Genre: Drama` |
| Cast / Director / Crew | `Cast/Crew: Tom Hanks` |
| Sport type | `Sport: Soccer` |
| Country | `Country: France` |
| Year | `Year: 1994` |

Keep it short. The chip must fit in the search bar row alongside the tab buttons and
the search input. `"Label: Value"` is the standard form.

---

## Mutual exclusion rule

Context filters are **mutually exclusive**. Activating a new chip clears all others.
Each handler must null out every `_details_*_filter` variable before setting its own.
This is enforced by convention, not code — update `_clear_context_filter()` and every
handler whenever a new filter is added.

---

## Search bar coexistence rule

**Do not dismiss the chip when the user types in the search box.** The text search
and the context filter apply together — text narrows *within* the active filter.
The chip is only dismissed by its own ✕ button.

This was a deliberate decision made after initially dismissing on typing felt wrong.

---

## Existing chip filters

| Filter | State variable | `get_all()` param | Section / signal | Chip label |
|---|---|---|---|---|
| Genre | `_details_genre_filter` | `strict_genre_filter` | `_MetadataSection.genre_clicked` | `Genre: X` |
| Cast / Crew / Director | `_details_person_filter` | `person_filter` | `_CastSection.person_clicked` | `Cast/Crew: X` |

---

## Checklist for a new chip filter

- [ ] `get_all()` — new `Optional[str]` parameter with strict SQL (no passthrough)
- [ ] Section class — new `pyqtSignal(str)`, `linkActivated` wired, HTML links rendered with `html.escape()`
- [ ] `DetailsPaneWidget` — new public signal, wired in `_connect_sections()`
- [ ] `main_window` — state variable, signal connected, handler added, handler clears all other `_details_*` vars, `_clear_context_filter` updated, passed through params and `get_all()` call
- [ ] No inline hex/rgba/px literals — styles from `theme.py` only
- [ ] Tests pass (`venv/bin/python -m pytest tests/ -x -q`)
- [ ] Committed as its own commit (isolates for potential revert)
