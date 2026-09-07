"""One button row for every dialog.

Fifteen ``QDialog`` subclasses, and the row of buttons at the bottom was built
fifteen ways: twelve hand-assembled a ``QDialogButtonBox`` with their own
standard-button flags, their own ``accepted``/``rejected`` wiring and their own
idea of which button is default; two (About, Diagnostics — three dialogs
between them) skipped the box entirely and laid a ``QHBoxLayout`` of
``QPushButton``s out by hand, so their Close button sat wherever that layout
put it rather than where the platform puts a Close button; and one
(``WatchForDialog``) constructed a ``QDialogButtonBox``, never added it to any
layout, and hand-rolled a row beside it.

The differences were never decisions. A dialog's default button — the one Enter
presses — was set on some and left to Qt's guess on others; a Close button
called ``accept()`` in one file and ``reject()`` in the next for no reason that
survives reading both.

So there is one builder. It takes what genuinely varies (the primary button's
label, whether there is a Cancel, what an Apply does, extra action buttons) and
owns what does not (the box, the wiring, the default button, the order the
platform wants). Everything the callers actually did differently is a keyword;
nothing they did differently *by accident* survived.

**No theme role is applied and none should be.** A ``QDialogButtonBox`` carries
no stylesheet anywhere in this app — it is themed by the ``QPalette`` floor
(``theme.qt_palette()`` pushed onto the whole ``QApplication``), which is the
documented mechanism for exactly this: a widget with no stylesheet that no
enumeration sweep could find. A dialog that wants a *coloured* primary button
styles the button this returns (``box.button(StandardButton.Ok)``), the way
``WatchForDialog`` does.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QPushButton

_OK = QDialogButtonBox.StandardButton.Ok
_CANCEL = QDialogButtonBox.StandardButton.Cancel
_APPLY = QDialogButtonBox.StandardButton.Apply


def dialog_buttons(
    dialog: QDialog,
    *,
    ok: str | None = "OK",
    cancel: bool = True,
    on_ok: Callable[[], None] | None = None,
    apply: Callable[[], None] | None = None,
    extra: tuple[tuple[str, Callable[[], None]], ...] = (),
) -> QDialogButtonBox:
    """Build this dialog's button row, wired and with a default button.

    Args:
        dialog: The dialog. ``accepted``/``rejected`` are wired to it, so the
            caller never re-wires them.
        ok: Label for the PRIMARY button — "OK", "Apply", "Add to Category",
            "Close". It is always ``StandardButton.Ok`` underneath, so a caller
            that needs it later looks it up with
            ``box.button(QDialogButtonBox.StandardButton.Ok)`` and gets the
            same handle whatever the label says. ``None`` for no primary
            button at all.
        cancel: Add a Cancel button. It is ``StandardButton.Cancel``, so a
            caller may relabel it (``"Include all"``) and still find it.
        on_ok: What the primary button does. Defaults to ``dialog.accept``.
            Passed explicitly by a dialog that validates first
            (``_try_accept``), saves first (``_save_and_accept``), or whose
            Close historically *rejected* rather than accepted — parity there
            is deliberate: it is the dialog's own exit code, and Escape calls
            ``reject()`` either way, which is why Escape needs no keyword.
        apply: What an Apply button does, or ``None`` for no Apply. A real
            ``StandardButton.Apply`` rather than an ``extra``: ApplyRole sits
            with OK/Cancel while ActionRole sits away from them, so passing
            Apply as an action would MOVE the button. Only Settings has one.
        extra: ``(label, callback)`` pairs added with ``ActionRole`` — the
            buttons that act without closing ("Test Connection", "Copy
            details", "Un-dismiss selected"). Look one up again with
            :func:`action_button`.

    Returns:
        The box. The caller adds it to its own layout — where the row goes is
        the dialog's business; how it is built is not.
    """
    box = QDialogButtonBox(dialog)

    for label, callback in extra:
        button = box.addButton(label, QDialogButtonBox.ButtonRole.ActionRole)
        # The label IS the handle: ``buttons()`` order is not part of Qt's
        # contract, so a positional lookup is a bug waiting for a style change.
        button.setObjectName(label)
        button.clicked.connect(callback)

    if ok is not None:
        box.addButton(_OK)
        primary = box.button(_OK)
        primary.setText(ok)
        # Enter presses THIS. Left to Qt, the guess depends on focus order and
        # differed between dialogs that look identical.
        primary.setDefault(True)
        primary.setAutoDefault(True)

    if cancel:
        box.addButton(_CANCEL)

    if apply is not None:
        box.addButton(_APPLY)
        box.button(_APPLY).clicked.connect(apply)

    box.accepted.connect(on_ok or dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def action_button(box: QDialogButtonBox, label: str) -> QPushButton | None:
    """The ``extra`` button that was added under ``label``.

    By object name, not by position: ``QDialogButtonBox.buttons()`` returns
    them in whatever order the current style lays the row out.
    """
    return box.findChild(QPushButton, label)
