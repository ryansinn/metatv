"""Regression: 'Remove filter on <X> content' must un-filter across BOTH exclusion axes.

A version chip is flagged *filtered* when its ``detected_prefix`` is in
``global_filter_excluded_categories`` OR ``global_filter_excluded_prefixes``
(``_fetch_channel_versions._is_filtered``).  The old ``_on_prefix_unblock`` only
removed from ``global_filter_excluded_prefixes``, so a token excluded via Content
Categories (e.g. an FR locale filter) silently no-oped — "Remove filter on FR content"
did nothing, no refresh, no toast, and the variant stayed filtered across reopen.

These call the real ``_MetadataMixin._on_prefix_unblock`` with a stub ``self`` so the
changed branch actually executes and we assert the outcome that would break.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.config import Config
from metatv.gui.main_window_metadata import _MetadataMixin


def _stub(config):
    """A minimal stand-in for MainWindow carrying only what _on_prefix_unblock touches."""
    return SimpleNamespace(
        config=config,
        _update_filter_btn_state=MagicMock(),
        load_channels=MagicMock(),
        details_pane=SimpleNamespace(current_channel=None),  # None → skip version refetch
        notification_manager=SimpleNamespace(show=MagicMock()),
    )


def test_unblock_clears_category_axis(tmp_path):
    """FR filtered via Content Categories: unblock must remove it and refresh — the bug."""
    cfg = Config()
    cfg.global_filter_excluded_categories = ["FR"]
    cfg.global_filter_excluded_prefixes = []
    stub = _stub(cfg)

    _MetadataMixin._on_prefix_unblock(stub, "FR")

    assert "FR" not in cfg.global_filter_excluded_categories, (
        "unblock must clear the category axis (this was the silent no-op bug)"
    )
    stub.load_channels.assert_called_once()          # refresh happened
    stub.notification_manager.show.assert_called_once()  # user got feedback


def test_unblock_clears_prefix_axis(tmp_path):
    """FR filtered via the prefix axis still works (the original supported path)."""
    cfg = Config()
    cfg.global_filter_excluded_categories = []
    cfg.global_filter_excluded_prefixes = ["FR"]
    stub = _stub(cfg)

    _MetadataMixin._on_prefix_unblock(stub, "FR")

    assert "FR" not in cfg.global_filter_excluded_prefixes
    stub.load_channels.assert_called_once()


def test_unblock_noop_when_not_excluded_anywhere(tmp_path):
    """If the token isn't excluded on any axis, do nothing (no spurious refresh/toast)."""
    cfg = Config()
    cfg.global_filter_excluded_categories = []
    cfg.global_filter_excluded_prefixes = []
    stub = _stub(cfg)

    _MetadataMixin._on_prefix_unblock(stub, "FR")

    stub.load_channels.assert_not_called()
    stub.notification_manager.show.assert_not_called()
