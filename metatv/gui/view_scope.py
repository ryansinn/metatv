"""Resolving a :class:`VisibilityScope` for a content view.

Its own module because TWO views need it — Sports and Events — and a helper
shared by two callers is not private to either. It was ``sports_view``'s
``_visibility_scope`` for about an hour.

The split it encodes is DR-0007: the CONTROL layer decides *what* is excluded by
reading user settings, and the scope only encodes *how* an already-decided
exclusion is applied. That is why this reads ``config`` here and hands the
repository a resolved bag of ids and codes rather than a ``Config``.
"""

from __future__ import annotations

def resolve_visibility_scope(repos, config):
    """Resolve every exclusion axis, in the worker, from already-read settings.

    Call it from inside a ``_run_query`` worker: it touches the repository
    (for the hidden-provider ids) and must not run on the UI thread.

    Args:
        repos: A ``RepositoryFactory`` bound to the worker's session.
        config: Live ``Config``.

    Returns:
        A fully-resolved ``VisibilityScope``.
    """
    from metatv.core.filter_utils import resolve_scope

    # Delegates rather than composing the axes itself. It used to build the
    # scope here from four sets, and quietly omitted the adult gate and the
    # "Uncategorized" toggle — the same two-of-six shape that let adult content
    # into Similar Titles. One resolver means an axis added later reaches Sports
    # and Events without anyone editing this file.
    return resolve_scope(
        repos.session, config,
        excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
    )
