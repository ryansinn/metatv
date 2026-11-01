"""The window is released before interpreter exit, never inside PyQt's walk (GUARD-7)."""

from __future__ import annotations


def test_release_deletes_the_window_and_its_children_and_is_idempotent(qapp):
    from PyQt6 import sip
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

    from metatv.gui.app_exit import release_before_exit
    window = QWidget()
    box = QVBoxLayout(window)
    labels = [QLabel(str(i)) for i in range(20)]
    for label in labels:
        box.addWidget(label)
    release_before_exit(window)
    assert sip.isdeleted(window) and all(sip.isdeleted(lbl) for lbl in labels)
    release_before_exit(window)          # a second call is a no-op, not a crash


def test_the_app_exits_through_the_release():
    """main() releases the window after exec() — the path the window-booting
    tests (search gap, EPG header, nav track) also end through."""
    import inspect

    import metatv.__main__ as entry
    source = inspect.getsource(entry.main)
    assert source.index("app.exec()") < source.index("release_before_exit(window)") < source.index("sys.exit(code)")
