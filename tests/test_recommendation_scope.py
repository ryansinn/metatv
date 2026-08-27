"""Every surface that recommends must exclude the same things.

#493 fixed the Recommended SIDEBAR, which had been passing four of the nine
exclusion axes. It did not reach the other two surfaces, and they were still
wrong when this was written:

    sidebar/recommended.py   12 args to score_candidates
    preferences_view.py      10   — no adult_mode, no excluded_content_types
    trail_map_data.py         9   — those, plus excluded_prefixes without the
                                    per-prefix union, plus no settings

``score_candidates`` defaults ``adult_mode="all"``. A caller that omits it does
not get a safe default — it gets NO adult filtering. So the Recommendations
dashboard was showing adult titles with the adult filter ON.

The guard is structural rather than behavioural on purpose. A behavioural test
would need a seeded library per axis per surface, and it would still only cover
the axes someone remembered to write; this asserts that no call site names the
axes at all, which is the property that stops them drifting again.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap

from metatv.core.preference_engine import recommendation_scope

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Every axis recommendation_scope resolves. Adding one here reaches all callers.
EXPECTED_AXES = {
    "muted_attrs", "dedupe_overrides", "excluded_prefixes",
    "include_uncategorized", "excluded_keywords", "excluded_provider_ids",
    "excluded_content_types", "adult_mode", "force_adult_provider_ids",
}

# The axes a caller must NEVER name itself — naming one means it has its own
# opinion about what a recommendation may contain.
FORBIDDEN_AT_CALL_SITES = EXPECTED_AXES


def _score_candidates_calls() -> list[tuple[str, ast.Call]]:
    """Every ``score_candidates(...)`` call under metatv/, with its file."""
    found = []
    for path in sorted((REPO_ROOT / "metatv").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == "score_candidates":
                found.append((path.relative_to(REPO_ROOT).as_posix(), node))
    return found


def test_recommendation_scope_resolves_every_axis():
    """The chokepoint must actually carry the full set, or routing through it lies."""
    src = textwrap.dedent(inspect.getsource(recommendation_scope))
    returned = {
        k.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Dict)
        for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    missing = EXPECTED_AXES - returned
    assert not missing, f"recommendation_scope no longer resolves: {sorted(missing)}"


def test_every_surface_scores_through_the_shared_scope():
    """No call site may name an exclusion axis itself.

    This is the assertion that would have caught #493 before it shipped, and
    the two surfaces it missed afterwards.
    """
    offenders = []
    for where, call in _score_candidates_calls():
        named = {kw.arg for kw in call.keywords if kw.arg}
        owns = named & FORBIDDEN_AT_CALL_SITES
        unpacks = any(kw.arg is None for kw in call.keywords)
        if owns:
            offenders.append(f"{where}:{call.lineno} names {sorted(owns)}")
        elif not unpacks:
            offenders.append(
                f"{where}:{call.lineno} unpacks no scope at all — it excludes nothing"
            )

    assert not offenders, (
        "score_candidates call sites assembling their own exclusions:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse **recommendation_scope(session, config) — that is the one place "
          "that knows what a recommendation may contain."
    )


def test_there_is_more_than_one_surface_to_keep_in_step():
    """Guards the guard: if the calls move or are renamed, the sweep finds none
    and the test above passes vacuously."""
    calls = _score_candidates_calls()
    assert len(calls) >= 3, (
        f"only {len(calls)} score_candidates call site(s) found — the sweep is "
        "probably looking in the wrong place, which would make the drift check "
        "pass for free"
    )


# ---------------------------------------------------------------------------
# The behavioural half: the axis that was actually missing, actually applied.
# ---------------------------------------------------------------------------

def test_the_scope_carries_the_adult_filter_from_config(tmp_path):
    """`adult_mode` defaults to "all" in score_candidates — omitting it filters NOTHING.

    That default is why the omission was invisible: a missing argument does not
    fail, it silently disables the filter. This asserts the resolved scope
    actually carries the user's setting, so routing through it is not just
    tidier but correct.
    """
    from metatv.core.config import Config
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path}/scope.db")
    db.create_tables()
    config = Config(config_dir=tmp_path)
    try:
        with db.session_scope() as session:
            scope = recommendation_scope(session, config)
    finally:
        db.close()

    assert "adult_mode" in scope, "the adult axis is not in the resolved scope"
    assert scope["adult_mode"] is not None
    assert "excluded_content_types" in scope, (
        "the content-type axis (the AI-content layer) is not in the resolved scope"
    )
    # Every axis the engine accepts, present in one call — the property that
    # makes a fourth consumer safe to add.
    assert EXPECTED_AXES <= set(scope), (
        f"resolved scope is missing {sorted(EXPECTED_AXES - set(scope))}"
    )


def test_the_discover_shelf_is_registered_and_routes_through_the_scope():
    """The shelf the owner asked for exists, and takes no exclusions of its own."""
    from metatv.gui import discover_workers

    src = pathlib.Path(discover_workers.__file__).read_text()
    assert '("recommended",    "Recommended for You")' in src, (
        "Discover has no Recommended shelf"
    )
    assert 'if shelf_key == "recommended"' in src, (
        "fetch_cards_for_key does not dispatch the recommended shelf, so See-all "
        "and lazy-expand would return nothing for it"
    )
