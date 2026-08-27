"""The settings pages line up: one control column, one checkbox edge.

Found by rendering the dialog and measuring it, which is the only way this
class of defect shows up — every widget was individually fine.

On Interface, before this:

    control                                   x
    ---------------------------------------- ---
    "Automatically check for updates"         195
    "Remember last search"                    203
    "Show thumbnails in lists"                297
    Theme: combo                              246
    Row density: combo                        297

Three different left edges for the same kind of control, and a control column
that moved between adjacent groups. The causes were both structural rather than
per-widget:

- ``addRow("", widget)`` leaves an EMPTY label occupying the label column, so
  the widget lands in the FIELD column — indented by however wide that group's
  widest label happens to be. A group with no labelled rows indents by nothing;
  the group below it indents by 94px. Same checkbox, different place.
- Qt sizes each ``QFormLayout``'s label column independently, and a page holds
  several, so the control column tracks each group's longest label.

Both are fixed at a seam rather than per call site, and asserted here on real
geometry — the numbers are RELATIONSHIPS (all equal, fits its rows), never
pinned pixels, so a deliberate density change does not turn these red.
"""

from __future__ import annotations


import pytest
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QListWidget

from metatv.gui import theme as _theme
from metatv.gui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qapp, tmp_path):
    from metatv.core.config import Config

    _theme.apply_theme("Midnight")
    config = Config(
        config_dir=tmp_path / "cfg",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    dlg = SettingsDialog(config, None)
    dlg.resize(1000, 720)
    dlg.show()
    qapp.processEvents()
    yield dlg
    dlg.deleteLater()


def _pages(dialog) -> list:
    """Each section page — alignment is a within-page property."""
    return [
        form.parentWidget()
        for form in dialog.findChildren(QFormLayout)
    ]


def _left_edges(root, kind) -> dict[str, int]:
    """Visible widgets of *kind* under *root*: label text -> page-space x."""
    out = {}
    for w in root.findChildren(kind):
        if not w.isVisible():
            continue
        text = w.currentText() if isinstance(w, QComboBox) else w.text()
        out[text or repr(w)] = w.mapTo(root, w.rect().topLeft()).x()
    return out


def _section(dialog, qapp, label: str):
    dialog.select_section_by_label(label)
    qapp.processEvents()
    return dialog


# ---------------------------------------------------------------------------
# 1. One control column per page
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section", ["Interface", "Playback", "Recommendations"])
def test_every_combo_on_a_page_shares_one_left_edge(dialog, qapp, section):
    """FAILS pre-fix on Interface: Theme at 246, Row density at 297."""
    _section(dialog, qapp, section)
    edges = _left_edges(dialog, QComboBox)
    if len(edges) < 2:
        pytest.skip(f"{section} has fewer than two combos to align")
    assert len(set(edges.values())) == 1, (
        f"{section}: the control column moves between groups — "
        + ", ".join(f"{t!r}@{x}" for t, x in sorted(edges.items(), key=lambda kv: kv[1]))
    )


@pytest.mark.parametrize("section", ["Interface", "Playback"])
def test_every_checkbox_on_a_page_shares_one_left_edge(dialog, qapp, section):
    """FAILS pre-fix on Interface: checkboxes at 195, 203 and 297."""
    _section(dialog, qapp, section)
    edges = _left_edges(dialog, QCheckBox)
    if len(edges) < 2:
        pytest.skip(f"{section} has fewer than two checkboxes")
    assert len(set(edges.values())) == 1, (
        f"{section}: checkboxes sit at {sorted(set(edges.values()))} — an "
        f"unlabelled row must span both columns, not sit in the field column:\n  "
        + "\n  ".join(
            f"{x:4d}  {t}" for t, x in sorted(edges.items(), key=lambda kv: kv[1])
        )
    )


def test_a_checkbox_is_not_indented_past_the_labels(dialog, qapp):
    """A checkbox is a row in its own right, not a value belonging to a label.

    This is the assertion that would still fail if every checkbox were indented
    *consistently* — equal-but-wrong. It pins the relationship to the labels,
    not just agreement between the checkboxes.
    """
    _section(dialog, qapp, "Interface")
    checkboxes = _left_edges(dialog, QCheckBox)
    labels = {
        t: x for t, x in _left_edges(dialog, QLabel).items() if t.endswith(":")
    }
    assert checkboxes and labels
    assert min(checkboxes.values()) <= min(labels.values()), (
        f"checkboxes start at {min(checkboxes.values())}, past the label column "
        f"at {min(labels.values())} — they are being treated as field values"
    )


# ---------------------------------------------------------------------------
# 2. The sidebar list fits what it holds
# ---------------------------------------------------------------------------

def test_the_sidebar_section_list_fits_its_rows(dialog, qapp):
    """FAILS pre-fix: a hardcoded 200px for five rows (~110px of void).

    Both directions are asserted. Only checking "not too tall" would pass a
    clipped list, and only checking "not clipped" would pass the void this
    started as.
    """
    _section(dialog, qapp, "Interface")
    lst = dialog._sidebar_list
    assert lst.count() > 0, "the list is empty — nothing to size to"

    content = lst.sizeHintForRow(0) * lst.count()
    height = lst.height()

    assert height >= content, (
        f"the list is {height}px for {content}px of rows — the last row is clipped"
    )
    # Frame + a row of slack. Generous enough that a padding change is not a
    # red gate, tight enough that the original 200-for-5 could never pass.
    assert height <= content + lst.sizeHintForRow(0) + 8, (
        f"the list reserves {height}px for {content}px of rows "
        f"({lst.count()} sections) — that gap is dead space under the last row"
    )


def test_the_sidebar_list_is_sized_from_its_rows_not_a_constant(dialog, qapp):
    """Re-populating with fewer rows must shrink it.

    A constant that happens to match today's five sections would pass the test
    above and reopen the void the moment a section is added or removed — which
    is exactly what happened when "sources" left this list.
    """
    from metatv.gui.settings_dialog import _fit_list_to_rows

    _section(dialog, qapp, "Interface")
    lst = dialog._sidebar_list
    full = lst.height()

    while lst.count() > 2:
        lst.takeItem(lst.count() - 1)
    _fit_list_to_rows(lst)
    qapp.processEvents()

    assert lst.height() < full, (
        f"height stayed {lst.height()} after dropping to {lst.count()} rows — "
        f"it is a constant, not a fit"
    )


def test_fitting_an_empty_list_is_a_no_op(qapp):
    """Guard the degenerate case rather than raising on an empty model."""
    from metatv.gui.settings_dialog import _fit_list_to_rows

    empty = QListWidget()
    before = empty.height()
    _fit_list_to_rows(empty)
    assert empty.height() == before
