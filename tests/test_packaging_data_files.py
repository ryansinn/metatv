"""Every non-.py file under ``metatv/`` must be declared in the Nuitka build.

(History below speaks of the PyInstaller spec it was written for; the build is
Nuitka since 2026-10-20 and follows imports the same way, so the rule holds.)

Why this exists
---------------
PyInstaller follows IMPORTS. A ``.py`` module comes along automatically; a data
file does not — it has to be named in ``datas`` or it simply is not in the
bundle. So the failure mode is silent at build time and total at run time.

It shipped twice. The DTCG palette files (``metatv/gui/tokens/*.tokens.json``)
landed with the theme rewrite and were never added, so on every macOS build from
that release onward::

    FileNotFoundError: .../Contents/Frameworks/metatv/gui/tokens/midnight.tokens.json
      theme.py:53 -> theme_palettes.py:502 -> _derive:498 -> loader.py:157

That read happens at import, so the app died before drawing a window. The whole
suite stayed green, because tests run from a source checkout where the file is
right there on disk — the one environment that cannot reproduce the bug.

``metatv/data/sports_definitions.yaml`` was in the same state and was found by
writing this test rather than by a second crash report.

What this checks, and what it cannot
------------------------------------
This is a STATIC check: it executes the spec with stubbed PyInstaller symbols
and asserts the resulting ``datas`` covers every non-.py file in the package. It
proves the spec NAMES the files. It cannot prove the built app launches — only
running the built app does that, which is what the ``smoke`` job in
``.github/workflows/release.yml`` is for. Both are needed: this one fails fast
and points at the exact missing path; the smoke test catches whatever this
cannot anticipate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD = REPO_ROOT / "packaging" / "build_nuitka.sh"

#: Files that are deliberately NOT shipped. Each entry is a decision.
NOT_SHIPPED = {
    # Developer documentation for the entries directory; the app never reads it.
    # (It rides along anyway inside the whats_new/entries tree — harmless.)
    "metatv/whats_new/entries/README",
}


def _spec_datas() -> list[tuple[str, str]]:
    """The ``(source, destination)`` data entries the Nuitka build passes.

    Read from ``packaging/build_nuitka.sh``: each ``--include-data-dir=SRC=DST``
    and ``--include-data-files=SRC=DST``. The Flatpak copies the same
    directories (``test_the_flatpak_copies_the_same_data``).
    """
    script = BUILD.read_text(encoding="utf-8")
    pairs = re.findall(r"--include-data-(?:dir|files)=([^=\s]+)=([^\s]+)", script)
    assert pairs, "build_nuitka.sh passes no data files at all"
    return [(str(REPO_ROOT / src), dst) for src, dst in pairs]


def test_the_flatpak_copies_the_same_data():
    """The Flatpak compiles in module mode and copies data dirs itself."""
    manifest = (REPO_ROOT / "packaging" / "flatpak"
                / "io.github.ryansinn.MetaTV.yml").read_text(encoding="utf-8")
    for src, _dst in _spec_datas():
        rel = Path(src).relative_to(REPO_ROOT).as_posix()
        if rel.startswith("metatv/"):
            assert rel in manifest, f"the Flatpak does not copy {rel}"


def _data_files() -> list[str]:
    """Repo-relative paths of every non-.py file under ``metatv/``."""
    out = []
    for path in (REPO_ROOT / "metatv").rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".py", ".pyc"} or "__pycache__" in path.parts:
            continue
        out.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(out)


def _is_covered(rel_path: str, datas: list[tuple[str, str]]) -> bool:
    """True when *rel_path* is shipped, either directly or inside a shipped dir."""
    absolute = (REPO_ROOT / rel_path).resolve()
    for src, _dest in datas:
        source = Path(src).resolve()
        if source == absolute:
            return True
        if source.is_dir() and source in absolute.parents:
            return True
    return False


def test_the_spec_declares_every_runtime_data_file():
    """The gate. A new data file fails here, naming the exact path to add."""
    datas = _spec_datas()
    missing = [
        p for p in _data_files()
        if p not in NOT_SHIPPED and not _is_covered(p, datas)
    ]
    assert not missing, (
        "these files are read at runtime but are NOT in the PyInstaller bundle — "
        "add them to `datas` in packaging/metatv.spec (or to NOT_SHIPPED here, "
        "with a reason):\n" + "\n".join(f"  {p}" for p in missing)
    )


@pytest.mark.parametrize("rel_path", [
    "metatv/gui/tokens/midnight.tokens.json",
    "metatv/gui/tokens/graphite.tokens.json",
    "metatv/gui/tokens/daylight.tokens.json",
    "metatv/data/sports_definitions.yaml",
])
def test_the_known_casualties_are_shipped(rel_path):
    """Named individually, not just covered by the sweep above.

    A regression on these two specifically is a crash-before-launch, and a
    test that only reports "1 file missing" is a worse bug report than one that
    says which. Both were genuinely absent from shipped builds.
    """
    assert _is_covered(rel_path, _spec_datas()), f"{rel_path} is not in the bundle"


def test_data_files_are_read_relative_to_the_package():
    """The palette loader must resolve paths from ``__file__``, not the CWD.

    Shipping the files is only half of it: a frozen app's working directory is
    not the bundle, so a CWD-relative read fails even when the file is present.
    """
    from metatv.gui import theme_palettes

    tokens_dir = getattr(theme_palettes, "_TOKENS_DIR", None)
    assert tokens_dir is not None, "theme_palettes must expose its token directory"
    assert Path(tokens_dir).is_absolute(), (
        f"token path {tokens_dir!r} is not absolute — it would resolve against "
        f"the working directory inside a frozen app"
    )
    for palette in ("midnight", "graphite", "daylight"):
        assert (Path(tokens_dir) / f"{palette}.tokens.json").is_file()
