"""The episode context menu's Mark action names the state, not a raw template.

#953 rewrote these two QAction labels for the icon migration and dropped the
``f`` prefix, so the menu read "Mark as Unwatched{label_suffix}" literally.
These drive the real ``show_series_context_menu`` and read the action text.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QTreeWidget, QTreeWidgetItem, QWidget

from metatv.core.repositories.dtos import EpisodeDTO
from metatv.gui.main_window_series import _SeriesMixin


class _Host(_SeriesMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.config = SimpleNamespace(autoplay_season_episodes=False)
        self.series_tree = QTreeWidget(self)
        self.series_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)


def _episode_item(tree, num, watched):
    ep = EpisodeDTO(
        id=f"e{num}", episode_num=num, season_num=1, title=f"Episode {num}",
        series_name="S", stream_url=None, duration=None, is_watched=watched, rating=None,
    )
    item = QTreeWidgetItem(tree, [ep.title])
    item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": ep})
    return item


def _menu_texts(host, item):
    captured: list[str] = []

    def _fake_exec(menu, *_a, **_k):
        captured.extend(a.text() for a in menu.actions())

    pos = host.series_tree.visualItemRect(item).center()
    with patch.object(QMenu, "exec", _fake_exec), \
            patch.object(host.series_tree, "itemAt", return_value=item):
        host.show_series_context_menu(pos if not pos.isNull() else QPoint(1, 1))
    return [t for t in captured if t.startswith("Mark as")]


def test_single_watched_episode_reads_mark_as_unwatched(qtbot):
    host = _Host()
    qtbot.addWidget(host)
    item = _episode_item(host.series_tree, 7, watched=True)

    assert _menu_texts(host, item) == ["Mark as Unwatched"]


def test_multi_select_names_the_episode_count(qtbot):
    host = _Host()
    qtbot.addWidget(host)
    items = [_episode_item(host.series_tree, n, watched=False) for n in (4, 5, 6)]
    for it in items:
        it.setSelected(True)

    labels = _menu_texts(host, items[0])

    assert labels == ["Mark as Watched (3 episodes)"]
    assert "{" not in labels[0]
