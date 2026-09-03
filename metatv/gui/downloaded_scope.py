"""The Downloaded channel-list scope (DL-5) — glue for the channel-list mixins.

Downloaded is a record/engaged view (DR-0007), same family as History/
Favorites/Queue: it lists titles with at least one COMPLETED download
regardless of the source's active state or Global Exclusions — a file
already saved to disk is the definition of engaged content, and it stays
playable even when its source is disabled. Recordings are deliberately NOT
part of this scope (a future library view).

Split out of ``main_window_channels.py`` rather than grown in place: that
file is pinned at its code-health ratchet ceiling, and CLAUDE.md's size rule
is explicit — "a pinned file at its ceiling means extract to a cohesive new
module, not rebaseline". This module holds the genuinely NEW glue (scope
derivation, button sync, the query-branch call); the surrounding methods stay
in place and call it.
"""

from __future__ import annotations


def scope_from_host(host) -> str:
    """The host's current scope: ``_list_scope`` if set, else derived from ``_hidden_mode``.

    ``host.__dict__.get`` (not ``getattr``): a bare host built via
    ``MainWindow.__new__`` raises ``RuntimeError``, not ``AttributeError``, on
    a missing attribute (CLAUDE.md's documented bare-host trap), which a
    ``getattr`` default cannot catch.
    """
    return host.__dict__.get('_list_scope') or (
        'hidden' if getattr(host, '_hidden_mode', False) else 'all')


def scope_from_state(state: dict) -> tuple[str, bool, bool]:
    """``(scope, hidden_mode, downloaded_mode)`` from a saved search-state dict.

    ``"list_scope"`` is the source of truth; a pre-DL-5 config only carries
    the legacy ``"hidden_mode"`` bool, mapped here to ``"hidden"``/``"all"``.
    """
    scope = state.get("list_scope")
    if scope not in ("all", "downloaded", "hidden"):
        scope = "hidden" if bool(state.get("hidden_mode", False)) else "all"
    return scope, scope == "hidden", scope == "downloaded"


def sync_scope_buttons(host, scope: str, hidden_mode: bool, downloaded_mode: bool) -> None:
    """Check/uncheck the three scope-tab buttons without retriggering their signals.

    ``host.__dict__.get`` — same bare-host reasoning as :func:`scope_from_host`.
    """
    for name, checked in (("_tab_all_btn", scope == "all"),
                          ("_tab_hidden_btn", hidden_mode),
                          ("_tab_downloaded_btn", downloaded_mode)):
        btn = host.__dict__.get(name)
        if btn is not None:
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.blockSignals(False)


def load(repos, params: dict, force_adult_ids, page_size):
    """The ``downloaded_only`` branch of ``_query_channels``'s page-1 fetch.

    No ``media_types``/``tag_includes`` (filter-panel facets don't apply,
    same omission as ``get_hidden_channels``); no
    ``excluded_provider_ids``/``excluded_keywords`` (``get_all``'s
    ``downloaded_only`` forces those empty at the engine regardless of what
    is passed here). ``adult_mode`` stays as configured — unlike
    ``hidden_only``, this scope does not bypass the adult gate.
    """
    return repos.channels.get_all(
        downloaded_only=True,
        provider_id=params['provider_id'],
        search_query=params.get('search_query'),
        adult_mode=params['adult_mode'],
        force_adult_provider_ids=force_adult_ids or None,
        limit=page_size,
    )


def count_text(shown: int) -> str:
    """"N downloaded title(s)" — shared by the status bar and the stats label."""
    return f"{shown:,} downloaded title{'s' if shown != 1 else ''}"


def show_empty(status_bar, stats_label) -> None:
    """Zero-results text for the Downloaded scope."""
    status_bar.showMessage("No downloaded titles yet")
    stats_label.setText("No downloads")
