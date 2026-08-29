"""Every EPG loop over providers applies the hidden gate, not just the first.

#536 fixed the fetch scan: ``is_active`` alone still admits an EXPIRED
subscription, because expired sources stay active until the user removes them.
It applied the gate at **one** call site. Two others in the same file kept
querying ``filter_by(is_active=True)`` on their own:

    _relink_worker                    re-links EPG rows
    _check_watchlist_notifications    raises watch alerts

The second is the one a user would SEE — a notification about a programme on a
source whose content is hidden everywhere else, which is the "disabled/expired
is an absolute gate" rule failing in the most visible way it can.

And the regression test for #536 could not see them. It located the fix with
``str.index()`` on a string that occurs three times and only ever inspected the
first, so two identical mistakes sat one page below a passing guard.

This test is therefore DERIVED: it walks the module's AST and requires every
provider query to be gated, so a fourth loop written later fails without anyone
remembering this file exists.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

MODULE = pathlib.Path("metatv/core/epg_manager.py")


def _provider_query_functions() -> "list[tuple[str, int]]":
    """Functions that loop over ALL providers via ``is_active``.

    The distinction matters and the first version of this helper missed it. It
    flagged every ``query(ProviderDB)``, which swept in single-provider lookups
    by id — ``get_status_text``, ``force_refresh_provider``,
    ``purge_provider_epg``, ``_remember_good_epg_host``. Those must NOT be
    gated: reporting the status of a hidden source, or purging its stale guide,
    or honouring an explicit "refresh this one" is exactly right.

    What must be gated is the shape that walks EVERY provider and treats
    ``is_active`` as the whole answer, because an expired subscription stays
    active until the user removes it.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    found = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            if getattr(call.func, "attr", None) != "filter_by":
                continue
            kw = {k.arg for k in call.keywords}
            # is_active present and NOT narrowed to one provider.
            if "is_active" in kw and "id" not in kw:
                found.append((fn.name, fn.lineno))
                break
    return found


def test_the_scan_finds_the_provider_loops():
    """Guards the guard: a broken walk would pass every test below."""
    fns = _provider_query_functions()
    names = {n for n, _ in fns}
    assert len(fns) >= 2, f"expected the all-provider loops, found {names}"


@pytest.mark.parametrize(
    "fn_name,lineno",
    _provider_query_functions(),
    ids=[n for n, _ in _provider_query_functions()],
)
def test_a_provider_loop_applies_the_hidden_gate(fn_name, lineno):
    """THE assertion. is_active alone admits expired subscriptions.

    Checked per function, so a failure names WHICH loop is unguarded rather
    than reporting that "the module" is wrong.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == fn_name and n.lineno == lineno
    )
    body = ast.unparse(fn)

    assert "get_hidden_provider_ids" in body, (
        f"{fn_name}() queries ProviderDB but never asks for the hidden set. "
        "is_active alone still admits an EXPIRED source — that is #536, and "
        "this is one of the sites it missed."
    )


def test_the_gate_uses_the_canonical_helper_not_a_local_rule():
    """One definition of 'hidden', per the project's scoping rule."""
    body = MODULE.read_text(encoding="utf-8")
    assert "account_status" not in body, (
        "epg_manager appears to re-derive expiry itself instead of asking "
        "get_hidden_provider_ids — that is a second definition of hidden"
    )


def test_every_gate_actually_filters_with_what_it_fetched():
    """Fetching the hidden set and not using it would pass the check above."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        body = ast.unparse(fn)
        if "get_hidden_provider_ids" not in body:
            continue
        assert "hidden" in body and ("not in hidden" in body or "in hidden" in body), (
            f"{fn.name}() fetches the hidden set but never tests membership"
        )
