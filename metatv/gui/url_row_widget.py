"""URLRowWidget — single URL row for the provider editor URL list."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QToolTip, QVBoxLayout, QWidget,
)

from metatv.core.models import ProviderURL
from metatv.gui import cursor_affordance
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


#: At or above this reads as healthy.
#:
#: Bands, not a gradient: the useful question is "is this address fine, flaky,
#: or broken", and three answers are readable at a glance where a continuous
#: ramp is not.
_HEALTHY_AT = 0.80

#: Below this reads as failing rather than merely flaky.
_FAILING_BELOW = 0.40


def reliability_tint_token(pu: ProviderURL) -> "str | None":
    """Name of the overlay TOKEN tinting a URL row, or ``None`` for no tint.

    Reads ``reliability_score`` — THE NUMBER PRINTED ON THE ROW.

    The first version of this read ``health_score`` instead, reasoning that the
    tint should follow whatever ``ordered_urls`` sorts by. That produced a
    screen contradicting itself: on the owner's TREX source every host's recent
    attempts had failed, so health was 0.00 for all six while the printed
    figures ranged 0% to 86% — and an 86% row was tinted identically to a 0%
    one. Owner: *"86% and 68% should not have the same as 0% and 1%."*

    A colour must never disagree with the number beside it. If the row ever
    starts PRINTING the recency-weighted score, this should read that instead —
    the rule is that they match, not which one wins.

    A token rather than three dedicated theme roles. Three roles differing only
    in which colour they name is a near-twin cluster, and the role-duplication
    guard is right to reject it — the shape is one thing parameterised by
    state, so it is expressed that way and composed with ``style_fn``.

    Uses ``health_score`` — the recency-weighted score ``ordered_urls`` SORTS
    on — not ``reliability_score``. Tinting on the lifetime ratio would put a
    green row at the bottom of the list and an amber one at the top, because
    the two disagree the moment a long-good host starts failing.

    An untested URL is deliberately left UNTINTED. ``reliability_score``
    returns 100.0 for one ("untested, assume good") and ``health_score`` falls
    back to it, so tinting on the number alone would paint an address nobody
    has ever reached in confident green. "Untested" is what the row's own text
    already says, and no tint is the honest visual for it.

    Args:
        pu: The URL row's model.

    Returns:
        A ``theme`` role name, or None when there is nothing to say.
    """
    if pu.success_count + pu.failure_count == 0:
        return None

    health = pu.reliability_score / 100.0
    if health >= _HEALTHY_AT:
        return "OVERLAY_GREEN_15"
    if health < _FAILING_BELOW:
        return "OVERLAY_ERR_15"
    return "OVERLAY_ORANGE_10"


class _ClickToCopyLabel(QLabel):
    """A ``QLabel`` whose full text copies to the clipboard on left-click.

    Replaces the old ``TextSelectableByMouse`` flag (select + manual Ctrl+C)
    with a single click — the URL row has no dedicated copy button, so the
    text itself is the affordance.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        cursor_affordance.set_clickable(self)
        self.setToolTip("Click to copy URL")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            QApplication.clipboard().setText(self.text())
            QToolTip.showText(QCursor.pos(), "Copied ✓", self)
            return
        super().mousePressEvent(event)


class URLRowWidget(QWidget):
    """Single URL row: try-first boost, click-to-copy URL, live test result, remove.

    ``pending_remove=True`` renders the row in "ghost" mode — dimmed +
    struck-through URL text, an Undo button in place of the remove button, and
    the try-first button hidden — for a URL the user has removed but not yet
    saved (``ProviderEditorView._pending_url_removals``). The mode is fixed at
    construction; the list is rebuilt (a fresh widget per row) whenever it
    changes, same as every other list mutation in this editor.
    """

    tryFirstToggled = pyqtSignal()
    removed = pyqtSignal()
    restored = pyqtSignal()

    def __init__(self, provider_url: ProviderURL, index: int, total: int, parent=None,
                 pending_remove: bool = False):
        super().__init__(parent)
        self.provider_url = provider_url
        self._pending_remove = pending_remove

        # Reinforcement for the reliability text already on this row, never a
        # replacement for it. Untested rows stay untinted — see the helper.
        # Ghost rows skip the tint entirely: the row is leaving, and a colour
        # wash would compete with the muted/strikethrough treatment that is
        # now the row's actual message.
        tint_token = None if pending_remove else reliability_tint_token(provider_url)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Try-first column (replaces the old up/down reorder arrows — a
        # placebo, since manual order landed in `priority`, the LAST tiebreak,
        # so evidence always overrode it).
        order_col = QVBoxLayout()
        order_col.setSpacing(1)
        self._try_first_btn = QPushButton(_icons.try_first_icon)
        self._try_first_btn.setFixedSize(24, 24)
        self._try_first_btn.setCheckable(True)
        self._try_first_btn.setChecked(provider_url.try_first)
        self._try_first_btn.setToolTip("Try this URL first on the next connection")
        _theme.style(self._try_first_btn, "URL_TRY_FIRST_BTN")
        self._try_first_btn.clicked.connect(self.tryFirstToggled)
        if pending_remove:
            self._try_first_btn.hide()
        order_col.addWidget(self._try_first_btn)
        layout.addLayout(order_col)

        # Priority badge
        badge = QLabel(f"#{index + 1}")
        badge.setFixedWidth(24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _theme.style(badge, "META_HINT")
        layout.addWidget(badge)

        # URL + stats column.
        #
        # The tint goes on THIS block, not on the row. Tinting the row put a
        # colour wash behind the reorder arrows, the #N badge and the remove
        # button — controls whose appearance has nothing to do with how well
        # the address works. Owner: "both lines don't need to be tinted
        # either. just the url and # fields."
        self._info_widget = QWidget()
        info_col = QVBoxLayout(self._info_widget)
        info_col.setContentsMargins(6, 3, 6, 3)
        info_col.setSpacing(2)

        url_label = _ClickToCopyLabel(provider_url.url)
        if pending_remove:
            _theme.style(url_label, "URL_ROW_GHOST")
        else:
            _theme.style(url_label, "FIELD_LABEL")
        info_col.addWidget(url_label)

        stats_text = "removed — will be deleted on Save" if pending_remove else self._build_stats(provider_url)
        self._stats_label = QLabel(stats_text)
        _theme.style(self._stats_label, "META_HINT")
        info_col.addWidget(self._stats_label)
        if tint_token:
            # style_fn, so the tint is re-read on a theme switch rather than
            # baked in at construction (CLAUDE.md's theme-registry rule).
            _theme.style_fn(self._info_widget, lambda t=tint_token: (
                f"background-color: {getattr(_theme, t)}; border-radius: 3px;"
            ))
        layout.addWidget(self._info_widget, 1)

        # Live test result badge (hidden until a test runs)
        self._result_badge = QLabel("")
        self._result_badge.setFixedWidth(110)
        self._result_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        _theme.style(self._result_badge, "URL_BADGE")
        self._result_badge.hide()
        layout.addWidget(self._result_badge)

        # Remove / Undo button
        if pending_remove:
            undo_btn = QPushButton(f"{_icons.undo_icon} undo")
            undo_btn.setToolTip("Keep this URL")
            _theme.style(undo_btn, "LINK_BTN_SM")
            cursor_affordance.set_clickable(undo_btn)
            undo_btn.clicked.connect(self.restored)
            layout.addWidget(undo_btn)
        else:
            rm_btn = QPushButton(_icons.close_icon)
            rm_btn.setFixedSize(24, 24)
            rm_btn.setToolTip("Remove this URL")
            _theme.style(rm_btn, "URL_REMOVE_BTN")
            rm_btn.clicked.connect(self.removed)
            layout.addWidget(rm_btn)

    def show_testing(self):
        """Show a 'Testing…' spinner while waiting for result. No-op in ghost mode."""
        if self._pending_remove:
            return
        self._result_badge.setText(f"{_icons.loading_icon} Testing…")
        _theme.style(self._result_badge, "URL_BADGE_TESTING")
        self._result_badge.show()

    def show_test_result(self, success: bool, message: str):
        """Update badge with pass/fail result. No-op in ghost mode."""
        if self._pending_remove:
            return
        if success:
            self._result_badge.setText(f"{_icons.notification_success_icon}  {message}")
            _theme.style(self._result_badge, "URL_BADGE_OK")
        else:
            self._result_badge.setText(f"{_icons.notification_error_icon}  {message}")
            _theme.style(self._result_badge, "URL_BADGE_ERR")
        self._result_badge.show()

    def clear_test_result(self):
        self._result_badge.hide()
        self._result_badge.setText("")

    @staticmethod
    def _build_stats(pu: ProviderURL) -> str:
        total = pu.success_count + pu.failure_count
        if total == 0:
            return "Untested"
        ok = _icons.notification_success_icon
        err = _icons.notification_error_icon
        rel = f"{pu.reliability_score:.0f}% reliability"
        parts = [rel, f"{ok}{pu.success_count}", f"{err}{pu.failure_count}"]
        if pu.last_success:
            parts.append(f"last ok {pu.last_success.strftime('%m/%d')}")
        return "  ·  ".join(parts)
