"""Every catalogue field the provider parses must actually be written.

`epg_channel_id` was parsed by the Xtream provider (`xtream.py:357`) and
dropped by the bulk-insert column list. Measured on the owner's library:

    channels                                        785,163
      with a stored epg_channel_id                        0
    live channels whose raw_data DOES carry one      20,506

So EPG tier-1 matching — the path the code calls "highest confidence" — could
never fire, on any install, ever. The consumer had tests; three of them set the
column **by hand**, which is exactly why nobody noticed the producer never did.

This is the defect class, not the instance: a hand-written list of N things
where the real population is M > N. The guard therefore compares the list to
what the ``Channel`` model actually provides rather than to another list, so
the next field added to the model cannot be silently discarded here.

The exclusions are named and reasoned individually. A blanket "these are fine"
set would recreate the very problem — a second hand-written list nobody
revisits.
"""

from __future__ import annotations

import dataclasses

import pytest

from metatv.core.models import Channel
from metatv.core.provider_loader import _CATALOG_COLS, _CATALOG_UPDATE_COLS

#: Channel fields that are deliberately NOT catalogue columns, each with the
#: reason. These are user/derived state that a refresh must never overwrite.
_NOT_CATALOGUE = {
    "is_favorite":  "user state — a refresh must not clear a favourite",
    "is_hidden":    "user state",
    "play_count":   "user state, accumulated locally",
    "last_played":  "user state",
    "added_at":     "row bookkeeping, set once on insert",
    "updated_at":   "row bookkeeping, set by the write itself",
    "metadata_id":  "link owned by the metadata layer, not the provider",
    "language":     "not populated by the Xtream provider",
}


def test_every_channel_field_is_either_written_or_explicitly_excluded():
    """THE assertion. Derived from the model, so a new field must be decided on.

    A field that is neither in ``_CATALOG_COLS`` nor in the exclusion map above
    is one somebody added to ``Channel`` and forgot to persist — which is
    precisely what happened to ``epg_channel_id``.
    """
    fields = {f.name for f in dataclasses.fields(Channel)}
    written = set(_CATALOG_COLS)
    unaccounted = sorted(fields - written - set(_NOT_CATALOGUE))

    assert not unaccounted, (
        f"{unaccounted} are parsed into Channel but never written to the "
        "database, and nothing says they should not be. Either add them to "
        "_CATALOG_COLS (and to the batch dict) or name them in _NOT_CATALOGUE "
        "with the reason."
    )


def test_epg_channel_id_is_written():
    """The specific regression, kept as a named anchor.

    20,506 live channels carry one and none of them reached the column.
    """
    assert "epg_channel_id" in _CATALOG_COLS


def test_the_batch_dict_supplies_every_declared_column():
    """Declaring a column and not filling it fails at the INSERT, not here —
    so check the two halves agree while it is cheap to fix."""
    import ast
    import pathlib

    src = pathlib.Path("metatv/core/provider_loader.py").read_text()
    tree = ast.parse(src)
    # The batch row is the dict literal whose keys include "stream_url".
    rows = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Dict)
        and any(isinstance(k, ast.Constant) and k.value == "stream_url" for k in n.keys)
    ]
    assert rows, "could not find the batch row dict"
    supplied = {k.value for k in rows[0].keys if isinstance(k, ast.Constant)}
    missing = sorted(set(_CATALOG_COLS) - supplied)

    assert not missing, (
        f"_CATALOG_COLS declares {missing} but the batch row never sets them"
    )


def test_no_user_or_derived_column_is_overwritten_by_a_refresh():
    """The exclusions must stay excluded — this is the expensive direction.

    Writing `is_favorite` on refresh would clear favourites on every catalogue
    update, which is worse than the bug this file exists for.
    """
    leaked = sorted(set(_NOT_CATALOGUE) & set(_CATALOG_UPDATE_COLS))

    assert not leaked, f"a refresh would overwrite user/derived state: {leaked}"


@pytest.mark.parametrize("field,reason", sorted(_NOT_CATALOGUE.items()))
def test_each_exclusion_names_a_real_field(field, reason):
    """An exclusion for a field that no longer exists is stale bookkeeping."""
    fields = {f.name for f in dataclasses.fields(Channel)}
    assert field in fields, (
        f"_NOT_CATALOGUE excludes {field!r} ({reason}) but Channel has no such "
        "field — the exclusion list has drifted from the model"
    )


def test_the_primary_key_is_not_updated_on_conflict():
    """`id` is the conflict target; updating it would be nonsense."""
    assert "id" in _CATALOG_COLS
    assert "id" not in _CATALOG_UPDATE_COLS
