"""Exclusions dialog: Channel Categories, Genres, collapsible sections (WIP-3).

(a) Engine — the tag exclusion predicate: a category hides its channels; a
    genre in "only" mode hides a title whose genres are ALL excluded, in "any"
    mode a title carrying any of them; the SQL clause and the id-set twin agree.
(b) Config — the retired hand-typed Content Types carry over onto categories.
(c) Dialog — the rendered grid places cells side by side, the long genre tail
    folds behind "Show N more", compound genres read "Sci-Fi & Fantasy",
    Languages starts collapsed and remembers a toggle, CL/CHL share one row,
    and Save writes categories, genres and the genre mode.

Real ``Database`` on a ``tmp_path`` file, per the tests rule.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.config import Config
from metatv.core.database import ChannelDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.tag_exclusions import (
    excluded_channel_ids,
    excluded_tag_content_types,
    tag_content_type_exclusion_criterion,
)


def _add(session, name, tags, media_type="movie", prefix=None):
    cid = str(uuid.uuid4())
    session.add(ChannelDB(id=cid, source_id=str(uuid.uuid4()), provider_id="p1", name=name,
                          media_type=media_type, detected_prefix=prefix))
    session.flush()
    RepositoryFactory(session).tags.set_content_tags(cid, [(t, v, "test") for t, v in tags])
    return cid


@pytest.fixture
def seeded(file_db):
    with file_db.session_scope() as s:
        ids = {
            "horror": _add(s, "Pure Horror", [("genre", "Horror")]),
            "horror_comedy": _add(s, "Horror Comedy", [("genre", "Horror"), ("genre", "Comedy")]),
            "comedy": _add(s, "Comedy", [("genre", "Comedy")]),
            "scifi": _add(s, "Space", [("genre", "Sci-Fi_Fantasy")]),
            "kids_live": _add(s, "Kids TV", [("category", "Kids")], media_type="live"),
            "news_live": _add(s, "News TV", [("category", "News")], media_type="live"),
        }
        for code in ("CL", "CHL", "AR", "XXX"):
            _add(s, f"{code} channel", [], media_type="live", prefix=code)
    return ids, file_db


def _visible_ids(db, slugs) -> set[str]:
    with db.session_scope() as s:
        q = s.query(ChannelDB.id).filter(tag_content_type_exclusion_criterion(slugs, ChannelDB.channel_key))
        return {cid for (cid,) in q.all()}


def _cfg(**kw) -> Config:
    return Config(**kw)


# ── (a) Engine ────────────────────────────────────────────────────────────────


def test_genre_only_mode_hides_only_titles_that_are_entirely_excluded(seeded):
    ids, db = seeded
    slugs = excluded_tag_content_types(_cfg(global_filter_excluded_genres=["Horror"]))
    visible = _visible_ids(db, slugs)
    assert ids["horror"] not in visible
    assert ids["horror_comedy"] in visible, "a Horror-Comedy stays in 'only' mode"
    assert ids["comedy"] in visible


def test_genre_any_mode_hides_every_title_carrying_the_genre(seeded):
    ids, db = seeded
    slugs = excluded_tag_content_types(
        _cfg(global_filter_excluded_genres=["Horror"], global_filter_genre_mode="any"))
    visible = _visible_ids(db, slugs)
    assert ids["horror"] not in visible and ids["horror_comedy"] not in visible
    assert ids["comedy"] in visible


def test_genre_only_with_every_genre_of_a_title_excluded_hides_it(seeded):
    ids, db = seeded
    slugs = excluded_tag_content_types(_cfg(global_filter_excluded_genres=["Horror", "Comedy"]))
    visible = _visible_ids(db, slugs)
    assert ids["horror_comedy"] not in visible
    assert ids["scifi"] in visible, "an untouched genre is never hidden"


def test_channel_category_hides_its_channels(seeded):
    ids, db = seeded
    slugs = excluded_tag_content_types(_cfg(global_filter_excluded_channel_categories=["Kids"]))
    visible = _visible_ids(db, slugs)
    assert ids["kids_live"] not in visible
    assert ids["news_live"] in visible


@pytest.mark.parametrize("mode", ["only", "any"])
def test_id_set_twin_agrees_with_the_sql_clause(seeded, mode):
    ids, db = seeded
    slugs = excluded_tag_content_types(_cfg(
        global_filter_excluded_genres=["Horror"], global_filter_genre_mode=mode,
        global_filter_excluded_channel_categories=["Kids"]))
    with db.session_scope() as s:
        all_ids = {cid for (cid,) in s.query(ChannelDB.id).all()}
        hidden = excluded_channel_ids(s, slugs)
    assert hidden == all_ids - _visible_ids(db, slugs)
    assert ids["kids_live"] in hidden


def test_paused_exclusions_hide_nothing():
    cfg = _cfg(global_filter_excluded_genres=["Horror"], global_filter_paused=True)
    assert excluded_tag_content_types(cfg) == set()


# ── (b) Config carry-over ─────────────────────────────────────────────────────


def test_retired_content_types_carry_over_to_categories():
    cfg = _cfg(global_filter_excluded_content_types=["Kids", "Religious", "Movies"],
               global_filter_excluded_source_categories=["SOME HEADER"])
    assert cfg.global_filter_excluded_channel_categories == ["Kids", "Religious"]
    assert cfg.global_filter_excluded_content_types == []
    assert cfg.global_filter_excluded_source_categories == []
    cfg._apply_value_migrations()  # runs again after the profile store attaches
    assert cfg.global_filter_excluded_channel_categories == ["Kids", "Religious"]


# ── (c) Dialog ────────────────────────────────────────────────────────────────


@pytest.fixture
def dialog(seeded, qtbot):
    from metatv.gui.global_filter_dialog import GlobalFilterDialog

    _ids, db = seeded
    cfg = _cfg(global_filter_excluded_channel_categories=["Kids"])
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)
    dlg.resize(900, 900)
    dlg.show()
    qtbot.waitExposed(dlg)
    return dlg, cfg


def test_category_grid_renders_cells_side_by_side(dialog):
    dlg, _cfg_ = dialog
    boxes = dlg._tag_sections["category"]._checkboxes
    a, b = boxes["Kids"].parentWidget(), boxes["News"].parentWidget()
    assert a.isVisible() and b.isVisible(), "grid cells are shown (an unparented cell once read as hidden)"
    ga, gb = a.geometry(), b.geometry()
    assert ga.top() == gb.top(), "cells of one row share a baseline"
    assert ga.left() != gb.left() and ga.width() > 0, "cells sit in separate columns"
    assert boxes["Kids"].isChecked(), "saved exclusion shows checked"


def test_genre_tail_folds_behind_show_more(dialog):
    dlg, _cfg_ = dialog
    sec = dlg._tag_sections["genre"]
    # Every seeded genre has under 100 titles, so all fold.
    assert not any(cb.parentWidget().isVisible() for cb in sec._checkboxes.values())
    assert sec._fold_link.isVisible() and "Show 3 more" in sec._fold_link.text()
    sec._toggle_fold()
    assert all(cb.parentWidget().isVisible() for cb in sec._checkboxes.values())


def test_compound_genre_label_reads_with_an_ampersand(dialog):
    dlg, _cfg_ = dialog
    cb = dlg._tag_sections["genre"]._checkboxes["Sci-Fi_Fantasy"]
    assert cb.text() == "Sci-Fi && Fantasy", "escaped, so Qt draws '&' not a shortcut underline"


def test_languages_start_collapsed_and_remember_the_toggle(dialog):
    dlg, cfg = dialog
    lang = dlg._collapsers["Languages"]
    assert lang.collapsed
    assert all(not s.isVisible() for s in dlg._language_sections)
    assert "groups" in lang.summary_label.text()
    lang.toggle()
    assert all(s.isVisible() for s in dlg._language_sections)
    assert "Languages" not in cfg.global_exclusions_collapsed


def test_one_row_per_country(dialog):
    dlg, _cfg_ = dialog
    section = next(s for s in dlg._sections if "CL" in s.all_prefixes())
    section._set_expanded(True)
    rows = [k for k in section._checkboxes if section._row_codes[k] == ["CL", "CHL"]
            or section._row_codes[k] == ["CHL", "CL"]]
    assert len(rows) == 1, "Chile's two codes share one checkbox"
    section._checkboxes[rows[0]].setChecked(True)
    assert set(section.checked_prefixes()) >= {"CL", "CHL"}


def test_save_writes_categories_genres_and_mode(dialog):
    dlg, cfg = dialog
    dlg._tag_sections["genre"]._checkboxes["Horror"].setChecked(True)
    dlg._tag_sections["category"]._checkboxes["News"].setChecked(True)
    dlg._genre_mode_group.button(1).setChecked(True)
    dlg._save_and_accept()
    assert cfg.global_filter_excluded_genres == ["Horror"]
    assert set(cfg.global_filter_excluded_channel_categories) == {"Kids", "News"}
    assert cfg.global_filter_genre_mode == "any"


def test_adult_is_listed_with_platforms_not_languages(dialog):
    dlg, _cfg_ = dialog
    lang = {s._group_name for s in dlg._language_sections}
    plat = {s._group_name for s in dlg._platform_sections}
    assert "Adult" not in lang, "a content descriptor is not a language"
    assert "Adult" in plat
    assert "Arabic" in lang, "real languages stay put"


def test_dialog_opens_large_and_remembers_its_size(seeded, qtbot):
    from metatv.gui.global_filter_dialog import GlobalFilterDialog

    _ids, db = seeded
    cfg = _cfg()
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)
    assert dlg.width() >= 700 and dlg.height() >= 540, "fits the grids, not the 420px minimum"
    dlg.resize(1000, 700)
    dlg.reject()
    assert cfg.global_exclusions_dialog_size == [1000, 700]
    again = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(again)
    screen = again.screen().availableGeometry()
    assert again.width() == min(1000, screen.width() - 40), "reopens at the saved width (screen permitting)"
    assert again.height() == min(700, screen.height() - 40)


# ── Finished fixture slots ("Hide finished events") ─────────────────────────


@pytest.fixture
def slots(file_db):
    from datetime import timedelta

    from metatv.core.epg_utils import now_utc

    now = now_utc()
    rows = {
        "ended_no_stop": (now - timedelta(hours=5), None),      # past the 4h default
        "on_now_no_stop": (now - timedelta(hours=1), None),
        "upcoming": (now + timedelta(hours=2), None),
        "ended_by_stop": (now - timedelta(hours=2), now - timedelta(minutes=5)),
        "rack": (None, None),                                   # 24/7 feed, never "ended"
    }
    ids = {}
    with file_db.session_scope() as s:
        for key, (start, stop) in rows.items():
            cid = str(uuid.uuid4())
            s.add(ChannelDB(id=cid, source_id=cid, provider_id="p1", name=key, media_type="live",
                            event_start_time=start, event_stop_time=stop))
            ids[key] = cid
    return ids, file_db


def test_finished_events_hide_passed_fixture_slots(slots):
    ids, db = slots
    visible = _visible_ids(db, excluded_tag_content_types(_cfg()))   # default: hide finished
    assert ids["ended_no_stop"] not in visible, "a slot past its window is finished"
    assert ids["ended_by_stop"] not in visible, "a provider stop time in the past is finished"
    assert {ids["on_now_no_stop"], ids["upcoming"], ids["rack"]} <= visible


def test_showing_finished_events_keeps_every_slot(slots):
    ids, db = slots
    visible = _visible_ids(db, excluded_tag_content_types(_cfg(show_ended_events=True)))
    assert set(ids.values()) <= visible


def test_finished_slots_id_twin_agrees(slots):
    ids, db = slots
    slugs = excluded_tag_content_types(_cfg())
    with db.session_scope() as s:
        hidden = excluded_channel_ids(s, slugs)
    assert hidden == {ids["ended_no_stop"], ids["ended_by_stop"]}
