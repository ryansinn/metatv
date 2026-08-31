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
    from metatv.core.channel_visibility import VisibilityScope
    from metatv.core.filter_utils import global_exclusion_sets

    prefixes, categories, content_types, keywords = global_exclusion_sets(config)
    return VisibilityScope(
        excluded_provider_ids=repos.providers.get_hidden_provider_ids(),
        excluded_prefixes=set(prefixes or []),
        excluded_categories=set(categories or []),
        excluded_content_types=set(content_types or []),
        excluded_keywords=set(keywords or []),
    )
