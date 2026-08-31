"""Config → :class:`VisibilityScope`: the one place every exclusion axis is read.

Its own module, and not a helper inside ``filter_utils``, for two reasons.

``filter_utils`` is 1,371 lines and pinned there by the code-health ratchet, so
anything added to it has to earn the increase — and this does not need to be
there. More importantly, burying the resolver in a large utility file is the
exact failure this function exists to fix: the correct path has to be the
findable one. A module named for what it produces is findable; function #74 of
``filter_utils`` is not.

The split it respects is DR-0007. The CONTROL layer decides *what* is excluded
by reading user settings; ``VisibilityScope`` only encodes *how* an
already-decided exclusion is applied and holds no ``Config``. This module is
that control step, in one function, so no surface has to assemble the axes
itself and get a subset.
"""

from __future__ import annotations

def resolve_scope(session, config, *, excluded_provider_ids=(),
                  include_hidden: bool = False):
    """EVERY exclusion axis, resolved from Config in ONE place.

    ``filter_utils.global_exclusion_sets`` resolves four of them; this resolves all
    six, because four was the number that kept leaking. A surface would compose
    the axes it happened to know about and the ones added later never reached
    it — ``channel_lens.apply_global_exclusions`` was written to apply "the same
    blacklist Discover applies" and applied two, so 215 adult/restricted rows
    and 114 content-type-tagged rows could surface in Similar Titles while
    every other surface hid them.

    **The adult gate is not paused-aware; Global Exclusions are.** Pausing is a
    "show me my own curation" gesture, not a request to unhide adult content.

    Args:
        session: Live session — needed only for the ``force_adult`` lookup.
        config: Live ``Config``.
        excluded_provider_ids: Hidden-provider gate, already resolved by the
            caller (not every caller has a repository factory to hand).
        include_hidden: True for a surface that deliberately shows
            per-channel-hidden rows.

    Returns:
        A fully-resolved ``VisibilityScope``.
    """
    from metatv.core.channel_visibility import VisibilityScope
    from metatv.core.discovery_engine import build_adult_filter
    from metatv.core.filter_utils import (
        get_active_category_filter, global_exclusion_sets,
    )

    prefixes, categories, content_types, keywords = global_exclusion_sets(config)
    adult_mode, force_adult_ids = build_adult_filter(session, config)
    # The "Uncategorized" toggle rides WITH the prefix axis — it decides whether
    # an untagged channel passes the prefix exclusion, so resolving one without
    # the other silently changes what the exclusion means.
    _, include_uncategorized = get_active_category_filter(config)
    return VisibilityScope(
        excluded_provider_ids=list(excluded_provider_ids or []),
        include_hidden=include_hidden,
        include_uncategorized=include_uncategorized,
        excluded_prefixes=set(prefixes or []),
        excluded_categories=set(categories or []),
        excluded_content_types=set(content_types or []),
        excluded_keywords=set(keywords or []),
        adult_mode=adult_mode,
        force_adult_provider_ids=force_adult_ids or [],
    )
