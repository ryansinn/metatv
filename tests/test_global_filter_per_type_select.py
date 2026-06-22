"""Per-type Select All in the Global Exclusions dialog.

The user's ask: "select all Languages except 2, leave Platforms alone" — instead
of a single master toggle they then have to unpick. Each type (Languages /
Platforms / Content Types / User Categories) gets its own scoped all·none, and
selecting one type must NOT touch the others (DR-0005: types are orthogonal axes).

These drive the scoped handlers directly via ``__new__`` (the real ``__init__``
needs a DB + QApplication; the handlers don't).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from metatv.gui.global_filter_dialog import GlobalFilterDialog


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def seeded_db(tmp_path):
    from metatv.core.database import Database, ChannelDB, ProviderDB
    db = Database(f"sqlite:///{tmp_path / 'gf.db'}")
    db.create_tables()
    s = db.get_session()
    try:
        s.add(ProviderDB(id="p1", name="P", type="xtream",
                         url="http://x.example.com", is_active=True))
        for pre in ["EN", "FR", "NF", "DSNY"]:  # EN/FR → languages, NF/DSNY → platforms
            s.add(ChannelDB(id=str(uuid.uuid4()), source_id=pre, provider_id="p1",
                            name=f"{pre} Channel", detected_prefix=pre, media_type="live"))
        s.commit()
    finally:
        s.close()
    yield db
    db.close()


class _FakeSection:
    def __init__(self):
        self.value = None

    def set_all(self, checked: bool):
        self.value = checked


def _dlg() -> GlobalFilterDialog:
    return GlobalFilterDialog.__new__(GlobalFilterDialog)


def test_select_languages_leaves_platforms_untouched():
    """Selecting all Languages must not change Platform sections (the core ask)."""
    dlg = _dlg()
    langs = [_FakeSection(), _FakeSection()]
    plats = [_FakeSection()]

    dlg._select_sections(langs, True)
    assert all(s.value is True for s in langs), "all language sections selected"
    assert plats[0].value is None, "platform sections must be untouched"

    # And the reverse — clearing Platforms leaves Languages as they were.
    plats[0].value = True
    dlg._select_sections(plats, False)
    assert plats[0].value is False
    assert all(s.value is True for s in langs), "languages unchanged by a platform op"


def test_select_content_types_is_scoped():
    """_select_content_types toggles only the content-type rows (+ its Other section)."""
    dlg = _dlg()
    cb1, cb2 = MagicMock(), MagicMock()
    dlg._content_type_rows = [("Sports", cb1, None), ("News", cb2, None)]
    other = _FakeSection()
    dlg._content_type_other_section = other

    dlg._select_content_types(True)
    cb1.setChecked.assert_called_once_with(True)
    cb2.setChecked.assert_called_once_with(True)
    assert other.value is True


def test_select_user_categories_is_scoped():
    """_select_user_categories toggles only the user-category rows."""
    dlg = _dlg()
    cb1, cb2 = MagicMock(), MagicMock()
    dlg._user_category_rows = [("Faves", cb1, None), ("Kids", cb2, None)]

    dlg._select_user_categories(False)
    cb1.setChecked.assert_called_once_with(False)
    cb2.setChecked.assert_called_once_with(False)


def test_master_select_all_covers_every_type():
    """The bottom master toggle still hits sections + content types + user cats."""
    dlg = _dlg()
    secs = [_FakeSection()]
    dlg._sections = secs
    ct_cb = MagicMock()
    dlg._content_type_rows = [("Sports", ct_cb, None)]
    dlg._content_type_other_section = None
    uc_cb = MagicMock()
    dlg._user_category_rows = [("Faves", uc_cb, None)]

    dlg._select_all(True)
    assert secs[0].value is True
    ct_cb.setChecked.assert_called_once_with(True)
    uc_cb.setChecked.assert_called_once_with(True)  # master now covers user cats too


def test_build_and_per_type_select_end_to_end(qapp, seeded_db):
    """Real dialog build: a Languages 'all' touches only language sections."""
    from metatv.core.config import Config

    dlg = GlobalFilterDialog(seeded_db, Config())
    assert dlg._language_sections, "language sections must be tracked at build"
    assert dlg._platform_sections, "platform sections must be tracked at build"

    dlg._select_sections(dlg._language_sections, True)
    lang_checked = [p for s in dlg._language_sections for p in s.checked_prefixes()]
    plat_checked = [p for s in dlg._platform_sections for p in s.checked_prefixes()]
    assert lang_checked, "languages should be checked after a Languages 'all'"
    assert not plat_checked, "platforms must stay unchecked — the scoped select works"
