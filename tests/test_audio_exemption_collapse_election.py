"""Ledger D69: measured audio outranks an excluded prefix in the collapse election.

A Global Exclusion hides a copy by its prefix, but a copy whose measured audio
contradicts that prefix (``StreamInfoRepository.prefix_exempt_ids``) stays
visible. The channel list's Python pass honoured that; the ``collapse_variants``
election did not, so an exempt copy ranked as "will be dropped" beside a truly
excluded sibling, lost on quality, and the whole title vanished.

Drives the real loaders (``_query_channels`` and its pagination sibling)
against a file-backed ``Database``, and guards the class: every call to the
exclusion predicates must see an exempt set.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.main_window_channels import _ChannelListMixin
from tests.conftest import channel_query_params

_KEY = "digger|movie|2026"


@pytest.fixture
def repos(file_db):
    s = file_db.get_session()
    s.add(ProviderDB(id="p1", name="Test Source", type="xtream", url="http://example",
                     is_active=True, account_status="Active"))
    s.commit()
    yield RepositoryFactory(s)
    s.close()


def _copy(repos, name: str, prefix: str, quality: str) -> str:
    cid = str(uuid.uuid4())
    repos.session.add(ChannelDB(
        id=cid, source_id=str(uuid.uuid4()), provider_id="p1", name=name,
        media_type="movie", is_hidden=False, detected_prefix=prefix,
        detected_quality=quality, detected_title="Digger", content_key=_KEY,
    ))
    repos.session.flush()
    return cid


@pytest.fixture
def title(repos):
    """One title, two copies: A (NL, heard English) and B (GR, unmeasured,
    higher quality so it wins the election on quality alone)."""
    heard = _copy(repos, "NL - DIGGER (2026)", "NL", "HD")
    guess = _copy(repos, "|GR| Digger 4K", "GR", "4K")
    repos.stream_info.upsert(heard, {"audio": [{"lang": "eng"}]}, source="probe")
    repos.session.commit()
    assert repos.stream_info.prefix_exempt_ids({"NL", "GR"}) == {heard}, "fixture: A must be exempt"
    return heard, guess


def _params():
    return channel_query_params(collapse_variants=True, excluded_prefixes={"NL", "GR"})


def test_page_one_elects_the_exempt_copy(repos, title):
    heard, _guess = title
    dtos, _out = _ChannelListMixin._query_channels(repos, _params())
    assert [d.id for d in dtos] == [heard], (
        "the title must show, represented by its English-audio copy — "
        f"got {[d.name for d in dtos]}")


def test_page_n_elects_the_exempt_copy(repos, title):
    heard, _guess = title
    dtos, _has_more, _raw = _ChannelListMixin._query_channels_page(
        repos, _params(), offset=0, page_size=50)
    assert [d.id for d in dtos] == [heard], f"got {[d.name for d in dtos]}"


def test_without_a_measurement_both_copies_stay_excluded(repos, title):
    """Control: the exemption is what keeps the title, not a lifted exclusion."""
    heard, _guess = title
    repos.session.query(ChannelDB).filter_by(id=heard).update({"detected_prefix": "GR"})
    repos.session.commit()
    dtos, _out = _ChannelListMixin._query_channels(repos, _params())
    assert dtos == []


# ── The class guard ──────────────────────────────────────────────────────────
#
# Predicate: a call to ``channel_exclusion_criterion`` without ``keep_ids``, or a
# call to ``is_channel_excluded`` whose enclosing ``and``/``or`` has no operand
# naming an exempt set. Census at D69: five sites, two of them missing it.
# A site that genuinely cannot see stream data goes in ALLOWED with the reason.

_ROOT = Path(__file__).resolve().parent.parent / "metatv"
_EXEMPT_WORDS = ("keep", "exempt")
ALLOWED: dict[str, str] = {}


def _names(node: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _mentions_exempt(node: ast.AST) -> bool:
    return any(w in name.lower() for name in _names(node) for w in _EXEMPT_WORDS)


def _offenders() -> list[str]:
    found = []
    for path in sorted(_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            site = f"{path.relative_to(_ROOT.parent)}:{node.lineno}"
            if fn == "channel_exclusion_criterion":
                if len(node.args) < 3 and not any(k.arg == "keep_ids" for k in node.keywords):
                    found.append(site)
            elif fn == "is_channel_excluded":
                up = parents.get(node)
                while isinstance(up, ast.UnaryOp):
                    up = parents.get(up)
                if not (isinstance(up, ast.BoolOp)
                        and any(_mentions_exempt(v) for v in up.values if v is not node)):
                    found.append(site)
    return [s for s in found if s.rsplit(":", 1)[0] not in ALLOWED]


def test_every_exclusion_predicate_call_sees_the_exempt_set():
    offenders = _offenders()
    assert not offenders, (
        "these Global-Exclusion checks ignore measured audio "
        "(StreamInfoRepository.prefix_exempt_ids) — pass keep_ids= / guard the "
        f"is_channel_excluded call with the exempt set, or list the file in ALLOWED: {offenders}")


def test_guard_sees_the_call_sites():
    """A guard that finds no calls passes vacuously; the census found five."""
    calls = 0
    for path in _ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        calls += text.count("channel_exclusion_criterion(") + text.count("is_channel_excluded(")
    assert calls >= 5
