"""Channel-list QListView with a middle-click signal.

The only behavioural addition over a plain ``QListView`` is ``middle_clicked`` —
emitted with the row's ``QModelIndex`` on a middle mouse-button press over a valid
item.  MainWindow wires this to play the OPPOSITE of the bare double-click default
(resume vs. start-from-beginning), so the two mouse gestures cover both actions
without a context menu.
"""
from PyQt6.QtCore import Qt, QModelIndex, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QListView


class ChannelListView(QListView):
    """``QListView`` that emits ``middle_clicked(index)`` on a middle-button press."""

    middle_clicked = pyqtSignal(QModelIndex)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.middle_clicked.emit(index)
                event.accept()
                return
        super().mousePressEvent(event)
