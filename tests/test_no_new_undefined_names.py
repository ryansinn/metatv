"""F821 is ignored project-wide, so nothing was stopping an undefined name.

``pyproject.toml`` ignores F821 with a comment that says, in so many words, that
the ignore is dangerous and someone should run the check by hand::

    "F821",  # 20 — undefined name. Mostly quoted annotations (latent, not
             #      ... the ignore is a real risk, not a formality, so
             #      run `ruff check --select F821` before trusting a clean

That is a prose rule, and prose rules are what this project keeps discovering it
does not follow. On 2026-09-02 it cost a full CI cycle: a worker function
referenced ``search_query`` and ``session``, neither of which was in scope, and
the tree was green through ruff, through the changed-file tests, and through the
launch smoke — because Python does not evaluate a name until the line runs, and
no local test ran that line. Six of ten CI checks came back red with
``NameError: name 'search_query' is not defined``, on a path that would have
crashed the app the first time anybody typed in the search box.

Why the ignore is nonetheless correct, and why this is a RATCHET rather than a
clean-up: of the 22 findings, 21 are names used only inside quoted annotations
(``PlayableEpisodeDTO``, ``datetime``, ``Qt``). Those never execute and turning
the rule on outright would mean 21 changes with no behavioural value. What is
worth catching is the twenty-second kind — a name that a running line reaches.

So the count may fall and may never rise. Lowering ``BASELINE`` is free and
encouraged; raising it should not happen without a reason written down here.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import sys
from pathlib import Path

#: Findings in the tree when this guard was written (2026-09-02), all of them
#: quoted annotations. Shrink-only: never raise this to make a red run green.
BASELINE = 22

ROOT = Path(__file__).resolve().parents[1]


def _ruff(*paths: str) -> list[dict]:
    """Run ruff's F821 check over ``paths`` and return its findings as data.

    **JSON, not text.** The first version of this parsed ``--output-format
    concise`` by testing each line for ``": F821 "``, and matched nothing: ruff
    writes ANSI colour codes between the colon and the code, so every line reads
    ``\x1b[36m:\x1b[0m ... \x1b[31mF821\x1b[0m``. The guard reported zero
    findings against a tree ruff had just flagged 23 times.

    That is the same defect CLAUDE.md records twice already, both times about
    grepping pytest output — ``^FAILED`` never matches a line pytest has
    coloured. Reproducing it inside the guard written to stop guard failures is
    the argument for parsing structured output instead of scraping text.
    """
    ruff = ROOT / "venv" / "bin" / "ruff"
    proc = subprocess.run(
        [str(ruff) if ruff.exists() else "ruff",
         "check", "--select", "F821", "--output-format", "json",
         "--no-cache", *paths],
        cwd=ROOT, capture_output=True, text=True,
    )
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:  # pragma: no cover - a broken toolchain
        raise AssertionError(
            f"could not parse ruff output ({exc}); this guard measures nothing.\n"
            f"stdout: {proc.stdout[:400]!r}\nstderr: {proc.stderr[:400]!r}"
        ) from None


def _findings() -> list[str]:
    """Every F821 in the tree as ``path:line message``, for a readable failure."""
    return [f"{f['filename']}:{f['location']['row']} {f['message']}"
            for f in _ruff("metatv/", "tests/")]


def test_no_new_undefined_names() -> None:
    """The count may fall and may never rise."""
    found = _findings()
    assert len(found) <= BASELINE, (
        f"{len(found)} undefined names, baseline {BASELINE}. A NEW one is here "
        "— and unlike the existing ones, which live in quoted annotations that "
        "never execute, a new one may well be on a line that runs.\n\n"
        + "\n".join(found)
    )


def test_the_ratchet_is_actually_measuring_something() -> None:
    """A guard that silently measures nothing is the failure mode it guards.

    ``ruff`` missing, a bad flag, a moved venv, an output format that stopped
    parsing — each makes the count zero, which passes the test above forever.

    This proof goes through the SAME parser as the real check, which the first
    version did not: it asserted ``"F821" in proc.stdout``, and that substring
    survives the colour codes that were breaking the real parse. So the
    self-proof passed while the thing it was proving was inert — a guard's proof
    has to exercise the guard's own path, or it is just a second thing to trust.
    """
    with tempfile.TemporaryDirectory(dir=ROOT / "tests") as tmp:
        probe = Path(tmp) / "probe_undefined.py"
        probe.write_text("def f():\n    return definitely_not_defined\n")
        found = _ruff(str(probe.relative_to(ROOT)))

    assert found, (
        "the F821 check found nothing in a file that is nothing BUT an "
        f"undefined name — this guard is inert. python: {sys.executable}"
    )
    assert found[0]["code"] == "F821"
