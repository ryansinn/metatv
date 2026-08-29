"""URLRowWidget — single URL row for the provider editor URL list."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from metatv.core.models import ProviderURL
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


class URLRowWidget(QWidget):
    """Single URL row: move up/down, live test result badge, stats, remove."""

    moveUp = pyqtSignal()
    moveDown = pyqtSignal()
    removed = pyqtSignal()

    def __init__(self, provider_url: ProviderURL, index: int, total: int, parent=None):
        super().__init__(parent)
        self.provider_url = provider_url

        # Reinforcement for the reliability text already on this row, never a
        # replacement for it. Untested rows stay untinted — see the helper.
        tint_token = reliability_tint_token(provider_url)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Order controls
        order_col = QVBoxLayout()
        order_col.setSpacing(1)
        self._up_btn = QPushButton(_icons.move_up_icon)
        self._up_btn.setFixedSize(22, 18)
        self._up_btn.setToolTip("Try this URL earlier (raise its priority)")
        self._up_btn.setEnabled(index > 0)
        self._up_btn.clicked.connect(self.moveUp)
        self._down_btn = QPushButton(_icons.move_down_icon)
        self._down_btn.setFixedSize(22, 18)
        self._down_btn.setToolTip("Try this URL later (lower its priority)")
        self._down_btn.setEnabled(index < total - 1)
        self._down_btn.clicked.connect(self.moveDown)
        order_col.addWidget(self._up_btn)
        order_col.addWidget(self._down_btn)
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

        url_label = QLabel(provider_url.url)
        _theme.style(url_label, "FIELD_LABEL")
        url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_col.addWidget(url_label)

        self._stats_label = QLabel(self._build_stats(provider_url))
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

        # Remove button
        rm_btn = QPushButton(_icons.close_icon)
        rm_btn.setFixedSize(24, 24)
        rm_btn.setToolTip("Remove this URL")
        _theme.style(rm_btn, "URL_REMOVE_BTN")
        rm_btn.clicked.connect(self.removed)
        layout.addWidget(rm_btn)

    def show_testing(self):
        """Show a 'Testing…' spinner while waiting for result."""
        self._result_badge.setText(f"{_icons.loading_icon} Testing…")
        _theme.style(self._result_badge, "URL_BADGE_TESTING")
        self._result_badge.show()

    def show_test_result(self, success: bool, message: str):
        """Update badge with pass/fail result."""
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
