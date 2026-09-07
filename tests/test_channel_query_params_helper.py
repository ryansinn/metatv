"""``channel_query_params()`` must supply every key ``_query_channels`` reads.

Four test files each hand-copied the ~30-key ``params`` dict
``MainWindow.load_channels`` builds, under a local ``_params()`` helper
(``test_hidden_accounting_dead_streams.py``,
``test_dead_gate_comparison_skipped_when_empty.py``,
``test_filter_transparency.py``, ``test_get_all_include_raw.py``). All four
claimed to be "a full params dict shaped like load_channels builds", but none
of them actually carried every key ``_ChannelListMixin._query_channels``
reads — the gap never showed because every read went through ``params.get()``
and defaulted to ``None``/falsy rather than raising ``KeyError``.

``tests/conftest.py``'s ``channel_query_params()`` replaces all four copies.
This test is the guard TESTS-1 was asked for: it AST-walks the real
``_query_channels`` method for every key read via ``params[...]`` (Load
context) or ``params.get(...)``, and asserts each one is present in
``channel_query_params()``'s output — so a new key added to production fails
HERE, once, instead of silently defaulting to ``None`` in four copies (or
wherever the next copy gets written).
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from metatv.gui import main_window_channels
from tests.conftest import channel_query_params


def _find_query_channels(tree: ast.Module) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_query_channels":
            return node
    raise AssertionError("_query_channels not found in main_window_channels.py")


def _params_reads(fn: ast.FunctionDef) -> set[str]:
    """Every string key read off a local named ``params`` via ``params[...]``
    (Load context — a ``Store`` is a write, not a read the caller must supply)
    or ``params.get(...)``."""
    reads: set[str] = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "params"
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.slice, ast.Constant)
        ):
            reads.add(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            reads.add(node.args[0].value)
    return reads


def test_channel_query_params_covers_every_key_query_channels_reads():
    tree = ast.parse(Path(inspect.getfile(main_window_channels)).read_text(encoding="utf-8"))
    fn = _find_query_channels(tree)
    reads = _params_reads(fn)

    # A real function body reads a real params dict — if this collected zero
    # keys, the AST walk broke silently rather than the guard being trivially
    # satisfied.
    assert len(reads) > 20, f"AST walk only found {len(reads)} reads — did the shape change?"

    supplied = set(channel_query_params().keys())
    missing = reads - supplied
    assert not missing, (
        f"_query_channels reads {sorted(missing)} but channel_query_params() "
        "doesn't supply them — add them to the base dict in tests/conftest.py "
        "with the production default from load_channels."
    )


def test_channel_query_params_overrides_win():
    """Sanity: ``**overrides`` actually reaches the returned dict."""
    params = channel_query_params(provider_id="p1", hide_watched=True)
    assert params["provider_id"] == "p1"
    assert params["hide_watched"] is True


def test_channel_query_params_returns_a_fresh_dict_each_call():
    """Two calls must not share mutable defaults (``force_adult_ids``, etc.)."""
    a = channel_query_params()
    b = channel_query_params()
    a["force_adult_ids"].append("x")
    assert b["force_adult_ids"] == [], "mutable default was shared between calls"
