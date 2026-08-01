"""Realtime search box in the Global Exclusions dialog.

The owner's ask: "the Global Exclusions management interface should have a
search box that allows the realtime filtering of the exclusion list to allow
users to quickly locate a specific prefix or language or region they want to
filter." Proves the actual filtering behavior on a real ``GlobalFilterDialog``
built against a real ``Database`` (never :memory:, per the tests rule):

(a) Typing narrows to matching entries, including a FULL-NAME match — "french"
    finds the FR prefix via the French language group's own name (FR's own
    REGION_FULL_NAMES entry is "France", not "French"), and "germany" finds
    the DE prefix via the REGION_FULL_NAMES lookup directly (DE's group is
    named "German", not "Germany" — so this path can only pass through the
    per-item full-name match, not the group-name shortcut).
(b) A type header (Languages) and a group section (German) hide once nothing
    under them matches; they don't come back until the query clears or a
    fresh query matches again.
(c) Clearing the box restores the full list.
(d) A nonsense query shows the muted empty-state label and hides every group.
(e) The filter also reaches the flat "Content Types" leaf rows, not just the
    prefix groups — the Content Types header hides when the query doesn't hit
    the one item under it, and reappears when it does.

Widgets are never shown/exec()'d (headless dialog), so visibility is asserted
via ``isHidden()`` (an explicit hide/show flag) rather than ``isVisible()``
(which also depends on the top-level window actually being shown).
"""

from __future__ import annotations

import uuid

import pytest

from metatv.gui.global_filter_dialog import GlobalFilterDialog


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def seeded_db(tmp_path):
    from metatv.core.database import ChannelDB, Database, ProviderDB
    db = Database(f"sqlite:///{tmp_path / 'gf_search.db'}")
    db.create_tables()
    s = db.get_session()
    try:
        s.add(ProviderDB(id="p1", name="P", type="xtream",
                         url="http://x.example.com", is_active=True))
        # FR -> French language group; DE -> German language group.
        for pre in ["FR", "DE", "NF"]:
            s.add(ChannelDB(id=str(uuid.uuid4()), source_id=pre, provider_id="p1",
                            name=f"{pre} Channel", detected_prefix=pre, media_type="live"))
        # A live channel with a source_category that won't match any configured
        # Content Types group -> lands in the expandable "Other" section.
        s.add(ChannelDB(
            id=str(uuid.uuid4()), source_id="oth1", provider_id="p1",
            name="Other Channel", media_type="live",
            source_category="WEIRDPROVIDERLABEL",
        ))
        s.commit()
    finally:
        s.close()
    yield db
    db.close()


def _group(dlg, name):
    return next(s for s in dlg._sections if s._group_name == name)


# ---------------------------------------------------------------------------
# (a) Matching — group-name path and full-name-lookup path
# ---------------------------------------------------------------------------


def test_search_french_finds_fr_via_group_name(qapp, seeded_db):
    """"french" must find the FR entry — via the French language GROUP's own
    name (FR's REGION_FULL_NAMES value is "France", not "French"), proving the
    group-name matching path."""
    from metatv.core.config import Config

    dlg = GlobalFilterDialog(seeded_db, Config())
    french = _group(dlg, "French")
    german = _group(dlg, "German")

    dlg._search_box.setText("french")

    assert not french.isHidden(), "French group must be visible for query 'french'"
    fr_row = french._checkboxes["FR"].parentWidget()
    assert not fr_row.isHidden(), "FR row must be visible — the concrete owner example"
    assert german.isHidden(), "German group has no match for 'french' and must hide"
    assert not dlg._lang_header_widgets[0].isHidden(), (
        "Languages type header stays visible — it still has a match (French)"
    )


def test_search_germany_finds_de_via_full_name_lookup(qapp, seeded_db):
    """"germany" only matches through REGION_FULL_NAMES (DE -> "Germany") since
    the enclosing group is named "German", not "Germany" — proving the
    per-item full-name matching path independently of the group-name path."""
    from metatv.core.config import Config

    dlg = GlobalFilterDialog(seeded_db, Config())
    german = _group(dlg, "German")

    dlg._search_box.setText("germany")

    assert not german.isHidden(), "German group must show — DE's full name is 'Germany'"
    de_row = german._checkboxes["DE"].parentWidget()
    assert not de_row.isHidden(), "DE row must be visible via the full-name match"


# ---------------------------------------------------------------------------
# (c) Clearing restores everything
# ---------------------------------------------------------------------------


def test_clearing_search_restores_full_list(qapp, seeded_db):
    from metatv.core.config import Config

    dlg = GlobalFilterDialog(seeded_db, Config())
    french = _group(dlg, "French")
    german = _group(dlg, "German")

    dlg._search_box.setText("french")
    assert german.isHidden(), "sanity: German hidden while filtering for 'french'"

    dlg._search_box.setText("")

    assert not french.isHidden(), "French restored after clearing"
    assert not german.isHidden(), "German restored after clearing"
    for cb in german._checkboxes.values():
        assert not cb.parentWidget().isHidden(), "every row in German restored"
    assert dlg._empty_state_label.isHidden(), "empty-state hidden once query is cleared"


# ---------------------------------------------------------------------------
# (d) Empty state for a nonsense query
# ---------------------------------------------------------------------------


def test_nonsense_query_shows_empty_state_and_hides_everything(qapp, seeded_db):
    from metatv.core.config import Config

    dlg = GlobalFilterDialog(seeded_db, Config())

    dlg._search_box.setText("zzzz_totally_not_a_real_token_zzzz")

    assert not dlg._empty_state_label.isHidden(), "empty-state label must appear"
    assert "zzzz_totally_not_a_real_token_zzzz" in dlg._empty_state_label.text()
    assert all(s.isHidden() for s in dlg._sections), "every prefix group hides"


# ---------------------------------------------------------------------------
# (e) The filter reaches flat leaf rows too, not just prefix groups
# ---------------------------------------------------------------------------


def test_search_reaches_content_types_leaf_rows(qapp, seeded_db):
    """The Content Types header + its 'Other' container hide/show together as a
    single type block, driven by a match on the raw source_category label."""
    from metatv.core.config import Config

    dlg = GlobalFilterDialog(seeded_db, Config())
    assert dlg._content_type_other_section is not None, "Other section must exist (seeded)"
    header_widgets = dlg._content_types_only_header_widgets
    assert header_widgets, "Content Types header widgets must be tracked"

    dlg._search_box.setText("weirdprovider")
    assert not dlg._content_type_other_section.isHidden(), "Other section matches"
    assert not header_widgets[0].isHidden(), "Content Types header stays visible on match"

    dlg._search_box.setText("no_such_category_at_all")
    assert dlg._content_type_other_section.isHidden(), "Other section hides on no match"
    assert header_widgets[0].isHidden(), "Content Types header hides once nothing matches"

    dlg._search_box.setText("")
    assert not dlg._content_type_other_section.isHidden(), "restored after clearing"
    assert not header_widgets[0].isHidden(), "header restored after clearing"
