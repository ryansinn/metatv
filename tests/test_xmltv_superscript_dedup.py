"""``xmltv_parser`` composes ``channel_name_utils._is_superscript_char`` (R11,
docs/REFACTOR_PLAN.md) rather than carrying its own byte-identical copy.

CLAUDE.md: curated character/lookup data lives only in
``core/channel_name_utils.py``. ``channel_name_utils.py`` already exercises the
predicate's behaviour end-to-end via ``parse_channel_name``
(``tests/test_parser_decoration_attributes.py``); this file pins that
``xmltv_parser`` genuinely reuses that one definition rather than a parallel
copy, and that its own title-badge stripping still behaves the same.
"""
from __future__ import annotations

from metatv.core.channel_name_utils import _is_superscript_char
from metatv.core.xmltv_parser import _drop_superscript_runs, _is_superscript_char as xmltv_predicate


def test_xmltv_parser_imports_the_shared_predicate_not_a_copy():
    """Identity, not just equal behaviour — proves there is one definition."""
    assert xmltv_predicate is _is_superscript_char


def test_drop_superscript_runs_removes_whole_superscript_tokens():
    # ᴴᴰ is entirely superscript/modifier letters; "News" is not.
    assert _drop_superscript_runs("ESPN News ᴴᴰ") == "ESPN News"


def test_drop_superscript_runs_leaves_mixed_tokens_alone():
    """A token that merely CONTAINS a decorated char is not half-erased."""
    assert _drop_superscript_runs("Café") == "Café"  # é is an accent, not superscript


def test_drop_superscript_runs_noop_when_nothing_decorated():
    assert _drop_superscript_runs("BBC One HD") == "BBC One HD"
