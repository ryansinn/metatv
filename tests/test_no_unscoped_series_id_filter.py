"""``SeasonDB``/``EpisodeDB.series_id`` may never be filtered without ``provider_id``.

The class of bug, not one location. ``series_id`` on both tables holds the
PROVIDER's own series id (``ChannelDB.source_id``), never ``ChannelDB.id`` — and
that id **collides across providers** (2 confirmed cases in the owner's real
library, SERIES-2). So a query is only safe when it pairs ``series_id`` with
``provider_id``; the id alone is wrong even when it is the right KIND of id.

This has now been found and fixed twice as one location apiece instead of once
as a class:

* SERIES-2 (#822) fixed ``series_monitor.py``'s baseline fast path and logged
  ledger row D52 for a second site — but D52 recorded a *location*
  (``channel_pruning.py``'s delete cascade), not the predicate.
* D52's own fix (#826) then found a THIRD site nobody had recorded, in
  ``prune_provider_content``'s Step 4 "kept series are spared" check — and that
  one was actively dangerous: because the check could never match, deleting a
  provider stripped seasons/episodes from a favorited series that SURVIVED the
  delete. Real loss of engaged content, only found because that brief happened
  to ask for a census.

GUARD-6 closes the class instead of waiting for the next location. Running this
guard's census over the current tree found a fourth, previously-unrecorded
site — ``metatv/scripts/inspect_series.py`` filtered ``SeasonDB.series_id ==
ch.id`` with no ``provider_id`` at all — fixed in the same change as this file,
which is why ``ALLOWLIST`` below is empty: there was no legitimate exception to
seed it with, only a bug to fix.

**The checkable form, not the general one.** "Does this variable hold a
provider-scoped id" is not statically decidable, so this does not attempt it.
What IS decidable: any query that filters ``SeasonDB.series_id`` or
``EpisodeDB.series_id`` must also filter ``provider_id`` *in the same query*.
That single predicate catches both failure directions — the wrong-key bug (no
provider scoping at all) and the collision bug (the id is even the right kind,
but two providers can still share it).

**An AST walk, not a line regex** — same shape as the ``setStyleSheet`` drift
guard and the ``UrlCycler``/``PointingHandCursor`` guards: a regex over source
text fires on every *mention* in a comment or docstring (this file's own
prose above would trip one), and CLAUDE.md already records that the regex the
style guard replaced knew one shape and eleven real sites sailed past it.

**What "same query" means here, and what this does not cover.** Every real
call site in this codebase builds and executes a query as ONE fluent
expression per Python statement (``return self.session.query(X).filter(...)
.order_by(...).first()``, or ``foo = (session.query(X).filter(...).all())``) —
never by reassigning a query variable across multiple statements before
executing it. "Same query" is therefore approximated as "the nearest enclosing
statement", which is exact for every site this guard has ever seen and is
cheap to reason about. A query assembled by mutating a variable across several
statements would defeat this approximation; nothing in ``metatv/`` does that
today. This is a documented limitation, not a silent gap — same spirit as
declining to trace "does this variable hold a channel id" in general.

Both ``.filter(Model.series_id == x, Model.provider_id == y)`` (single call,
several conditions) and ``.filter(Model.series_id == x).filter(Model.provider_id
== y)`` (split across chained calls) are treated identically, and so is
``.filter_by(series_id=x, provider_id=y)``. ``series_id`` is only ever a column
on ``SeasonDB``/``EpisodeDB`` (see ``ORIGINAL_COLUMNS`` in
``tests/test_schema_upgrade_adds_every_column.py``), so a bare
``filter_by(series_id=...)`` needs no ``.query(Model)`` confirmation to know
which table it means. The ``provider_id`` side is intentionally NOT restricted
to the same class — a join-style pairing (``SeasonDB.series_id == ...,
ChannelDB.provider_id == ...``) is exactly as safe as pairing on the same
model, and restricting it would only manufacture false positives.

``metatv/core/repositories/channel_pruning.py``'s ``_series_channel_exists``
chokepoint (the correlated-EXISTS helper both D52 fixes now route through) is
invisible to this guard by construction, not by allowlisting: it reads
``model.series_id``/``model.provider_id`` off a passed-in parameter, never the
literal ``SeasonDB.series_id``/``EpisodeDB.series_id`` this guard looks for.
That is fine — it already pairs (source_id, provider_id) correctly, and a
guard for the general "does this dynamic attribute hold a channel id" question
is exactly the undecidable form this file declines to attempt.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = REPO_ROOT / "metatv"

#: The only two ORM classes that carry a ``series_id`` column.
_SERIES_MODELS = frozenset({"SeasonDB", "EpisodeDB"})

#: Shrink-only. Every finding this guard has produced so far was a real bug
#: (fixed in the same change that added the guard — see module docstring), so
#: there is currently no legitimate exception and this stays empty. A future
#: entry would be ``"path/to/file.py:<lineno>"`` with the reason inline here.
ALLOWLIST: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _filter_calls(stmt: ast.AST):
    """Yield every ``.filter(...)``/``.filter_by(...)`` ``Call`` node in *stmt*."""
    for node in ast.walk(stmt):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("filter", "filter_by")
        ):
            yield node


def _filters_attr(stmt: ast.AST, class_names: frozenset[str] | None, attr: str) -> bool:
    """True if some ``.filter(...)``/``.filter_by(...)`` call in *stmt* filters
    *attr* — ``<Class>.<attr>`` inside ``.filter(...)`` args (class restricted
    to *class_names* when given, any class when ``None``), or an ``<attr>=``
    keyword inside ``.filter_by(...)``.

    Only ``.filter(...)``'s ARGS are walked (never the whole call, never the
    rest of the chain) so an unrelated same-named attribute elsewhere in the
    statement — e.g. ``.order_by(Model.provider_id)`` — cannot satisfy this by
    accident. That is what makes "in the same query" mean something precise
    rather than "mentioned somewhere nearby".
    """
    for call in _filter_calls(stmt):
        if call.func.attr == "filter_by":
            if any(kw.arg == attr for kw in call.keywords):
                return True
            continue
        for arg in call.args:
            for node in ast.walk(arg):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == attr
                    and (
                        class_names is None
                        or (isinstance(node.value, ast.Name) and node.value.id in class_names)
                    )
                ):
                    return True
    return False


def _has_series_id_filter(stmt: ast.AST) -> bool:
    return _filters_attr(stmt, _SERIES_MODELS, "series_id")


def _has_provider_id_filter(stmt: ast.AST) -> bool:
    return _filters_attr(stmt, None, "provider_id")


def _build_parent_map(tree: ast.AST) -> dict:
    parent_of: dict = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_of[id(child)] = parent
    return parent_of


def _enclosing_statement(node: ast.AST, parent_of: dict) -> ast.AST:
    """Climb to the nearest enclosing statement — see module docstring for why
    a Python statement is the unit "the same query" is checked against."""
    current = node
    while not isinstance(current, ast.stmt):
        parent = parent_of.get(id(current))
        if parent is None:
            return current
        current = parent
    return current


def _series_id_filter_sites(path: pathlib.Path) -> tuple[int, list[int]]:
    """Returns ``(total_series_id_filter_sites, [offending_lineno, ...])`` for
    one file. A "site" is one distinct statement that filters
    ``SeasonDB.series_id``/``EpisodeDB.series_id``; it is offending when that
    same statement never also filters ``provider_id``.
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:  # pragma: no cover - not our concern here
        return 0, []
    parent_of = _build_parent_map(tree)

    checked_stmt_ids: set = set()
    total = 0
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("filter", "filter_by")
        ):
            continue
        stmt = _enclosing_statement(node, parent_of)
        if id(stmt) in checked_stmt_ids:
            continue
        checked_stmt_ids.add(id(stmt))
        if not _has_series_id_filter(stmt):
            continue
        total += 1
        if not _has_provider_id_filter(stmt):
            offenders.append(getattr(stmt, "lineno", node.lineno))
    return total, offenders


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def test_no_unscoped_series_id_filter():
    """Every ``SeasonDB``/``EpisodeDB.series_id`` filter in ``metatv/`` must
    also filter ``provider_id`` in the same statement, or be named in
    ``ALLOWLIST`` with a reason recorded in this file's docstring.

    Fails loudly (rather than passing vacuously) if the census itself came
    back empty — a runner that ran nothing exits 0, and that reads as "no bugs"
    instead of "the detector broke". There are at least the six known-good
    sites in ``episode.py``, ``season.py``, ``series_monitor.py`` and
    ``queue.py`` alone, so zero is never a legitimate result.
    """
    total_sites = 0
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        site_count, offending_linenos = _series_id_filter_sites(path)
        total_sites += site_count
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno in offending_linenos:
            entry = f"{rel}:{lineno}"
            if entry in ALLOWLIST:
                continue
            offenders.append(entry)

    assert total_sites > 0, (
        "censused ZERO SeasonDB/EpisodeDB.series_id filter sites across "
        f"{PACKAGE} — the detector broke (known real sites: "
        "core/repositories/episode.py, core/repositories/season.py, "
        "core/series_monitor.py, core/repositories/queue.py)."
    )

    assert not offenders, (
        f"{len(offenders)} SeasonDB/EpisodeDB.series_id filter(s) with no "
        "provider_id filter in the same query:\n  "
        + "\n  ".join(offenders)
        + "\n\nseries_id holds the PROVIDER's own series id and collides across "
          "providers (SERIES-2) — pair it with a provider_id filter in the "
          "same statement, or route through "
          "channel_pruning._ChannelPruningMixin._series_channel_exists()."
    )

    assert ALLOWLIST == frozenset(), (
        "ALLOWLIST is meant to stay empty (see module docstring) — if a "
        "legitimate exception was just added, this assertion documents that "
        "the decision was deliberate; update this message rather than "
        "deleting the check."
    )


# ---------------------------------------------------------------------------
# Proof the detector actually distinguishes match from mismatch
# ---------------------------------------------------------------------------

def _scan_source(src: str) -> tuple[int, list[int]]:
    """``_series_id_filter_sites`` for a literal source snippet, not a file —
    used so the proof tests below exercise exactly the same machinery the
    real sweep uses."""
    tree = ast.parse(src)
    parent_of = _build_parent_map(tree)
    checked_stmt_ids: set = set()
    total = 0
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("filter", "filter_by")
        ):
            continue
        stmt = _enclosing_statement(node, parent_of)
        if id(stmt) in checked_stmt_ids:
            continue
        checked_stmt_ids.add(id(stmt))
        if not _has_series_id_filter(stmt):
            continue
        total += 1
        if not _has_provider_id_filter(stmt):
            offenders.append(getattr(stmt, "lineno", node.lineno))
    return total, offenders


def test_the_guard_fires_on_the_wrong_key_shape():
    """The exact shape ``inspect_series.py`` shipped: ``SeasonDB.series_id``
    filtered alone, no ``provider_id`` anywhere in the statement."""
    src = (
        "seasons = (\n"
        "    session.query(SeasonDB)\n"
        "    .filter(SeasonDB.series_id == ch.id)\n"
        "    .order_by(SeasonDB.season_number)\n"
        "    .all()\n"
        ")\n"
    )
    total, offenders = _scan_source(src)
    assert total == 1
    assert offenders, "must flag a series_id filter with no provider_id pairing"


def test_the_guard_fires_on_the_collision_shape_too():
    """Even when the id IS the right kind (``source_id``, not ``id``), an
    unpaired ``series_id`` is still wrong because it collides across
    providers — the guard must not be satisfied by the id being correct."""
    src = (
        "return self.session.query(EpisodeDB).filter(\n"
        "    EpisodeDB.series_id == ch.source_id\n"
        ").all()\n"
    )
    total, offenders = _scan_source(src)
    assert total == 1
    assert offenders, "a correct id with no provider_id pairing is still a violation"


def test_the_guard_accepts_paired_filter_in_one_call():
    src = (
        "return self.session.query(EpisodeDB).filter(\n"
        "    EpisodeDB.series_id == series_id,\n"
        "    EpisodeDB.provider_id == provider_id,\n"
        ").first()\n"
    )
    total, offenders = _scan_source(src)
    assert total == 1
    assert offenders == []


def test_the_guard_accepts_paired_filter_split_across_chained_calls():
    src = (
        "return (\n"
        "    self.session.query(SeasonDB)\n"
        "    .filter(SeasonDB.series_id == source_id)\n"
        "    .filter(SeasonDB.provider_id == provider_id)\n"
        "    .all()\n"
        ")\n"
    )
    total, offenders = _scan_source(src)
    assert total == 1
    assert offenders == []


def test_the_guard_accepts_paired_filter_by_keywords():
    src = (
        "return self.session.query(EpisodeDB).filter_by(\n"
        "    series_id=series_id, provider_id=provider_id\n"
        ").all()\n"
    )
    total, offenders = _scan_source(src)
    assert total == 1
    assert offenders == []


def test_the_guard_fires_on_unpaired_filter_by():
    src = (
        "return self.session.query(EpisodeDB).filter_by(series_id=series_id).all()\n"
    )
    total, offenders = _scan_source(src)
    assert total == 1
    assert offenders, "filter_by(series_id=...) with no provider_id keyword must fire"


def test_a_provider_id_reference_outside_the_filter_call_does_not_count():
    """A ``provider_id`` mentioned only in ``.order_by(...)`` (never actually
    filtered) must not be read as pairing — this is what keeps the detector
    from being fooled by an unrelated same-named attribute nearby."""
    src = (
        "return (\n"
        "    self.session.query(EpisodeDB)\n"
        "    .filter(EpisodeDB.series_id == series_id)\n"
        "    .order_by(EpisodeDB.provider_id)\n"
        "    .all()\n"
        ")\n"
    )
    total, offenders = _scan_source(src)
    assert total == 1
    assert offenders, "a provider_id reference outside .filter()/.filter_by() must not pair"


def test_two_separate_statements_are_scanned_independently():
    """A paired statement followed by an unpaired one must flag only the
    second — proves statements are not accidentally merged."""
    src = (
        "def f(self):\n"
        "    good = self.session.query(EpisodeDB).filter(\n"
        "        EpisodeDB.series_id == a, EpisodeDB.provider_id == b\n"
        "    ).all()\n"
        "    bad = self.session.query(SeasonDB).filter(\n"
        "        SeasonDB.series_id == c\n"
        "    ).all()\n"
        "    return good, bad\n"
    )
    total, offenders = _scan_source(src)
    assert total == 2
    assert len(offenders) == 1


def test_a_run_that_finds_no_filter_calls_at_all_censuses_zero():
    """Sanity: a file with no query code at all produces total == 0 — the
    zero-census guard in test_no_unscoped_series_id_filter exists precisely
    so THIS shape, hit across the whole tree, fails loudly instead of passing."""
    total, offenders = _scan_source("x = 1\n")
    assert total == 0
    assert offenders == []


@pytest.mark.parametrize("rel_path", [
    "metatv/core/repositories/episode.py",
    "metatv/core/repositories/season.py",
    "metatv/core/series_monitor.py",
    "metatv/core/repositories/queue.py",
])
def test_known_call_sites_are_paired_on_the_real_tree(rel_path):
    """The real files this guard's docstring cites as "known-good" must stay
    that way — proves the sweep runs cleanly against production code, not
    only against synthetic snippets."""
    path = REPO_ROOT / rel_path
    total, offenders = _series_id_filter_sites(path)
    assert total > 0, f"{rel_path}: expected at least one series_id filter site"
    assert offenders == [], f"{rel_path}: {offenders}"
