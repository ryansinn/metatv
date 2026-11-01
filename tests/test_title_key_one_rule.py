"""The title-identity key has one definition (ledger F65).

``COALESCE(content_key, 'id:' || id)`` was rebuilt at six sites in SQL and
Python. ``content_identity.title_key`` / ``title_key_expr`` are the rule; this
guard fails the moment a new site builds the key by hand.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "metatv"
HOME = ROOT / "core" / "content_identity.py"


def test_title_key():
    from metatv.core.content_identity import title_key
    assert title_key("tmdb:1|movie", "c1") == "tmdb:1|movie"
    assert title_key(None, "c1") == "id:c1"
    assert title_key("", "c1") == "id:c1"


def test_title_key_expr_groups_like_title_key(db):
    from sqlalchemy import func

    from metatv.core.content_identity import title_key_expr
    from metatv.core.database import ChannelDB
    with db.session_scope() as s:
        for cid, key in (("a", "k1"), ("b", "k1"), ("c", None), ("d", None)):
            s.add(ChannelDB(id=cid, source_id=cid, provider_id="p", name=cid, content_key=key))
    with db.session_scope() as s:
        n = s.query(func.count(func.distinct(title_key_expr(ChannelDB.content_key, ChannelDB.id)))).scalar()
    assert n == 3, "k1 is one title; each un-keyed row is its own"


def _hand_built_keys(path: Path) -> list[int]:
    lines: set[int] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and node.value == "id:":
            lines.add(node.lineno)             # concat("id:", …)
        elif isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant) \
                and node.values[0].value == "id:" and len(node.values) == 2:
            lines.add(node.lineno)             # f"id:{…}"
    return sorted(lines)


def test_no_site_builds_the_title_key_by_hand():
    offenders = {str(p.relative_to(ROOT)): ln for p in ROOT.rglob("*.py")
                 if p != HOME and (ln := _hand_built_keys(p))}
    assert offenders == {}, f"build the title key with content_identity.title_key(_expr): {offenders}"


def test_the_guard_can_fail(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('k = row.content_key or f"id:{row.id}"\nx = func.concat("id:", c.id)\n')
    assert _hand_built_keys(bad) == [1, 2]
