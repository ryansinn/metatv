"""Every non-.py file under ``metatv/`` must be declared in the PyInstaller spec.

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

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "packaging" / "metatv.spec"

#: Files that are deliberately NOT shipped. Each entry is a decision.
NOT_SHIPPED = {
    # Developer documentation for the entries directory; the app never reads it.
    # (It rides along anyway inside the whats_new/entries tree — harmless.)
    "metatv/whats_new/entries/README",
}


def _spec_datas() -> list[tuple[str, str]]:
    """Run the spec with stubbed PyInstaller symbols and return its ``datas``.

    Executing it (rather than regex-scraping) means the test sees what
    PyInstaller will actually see, including anything built by a loop or a
    helper — a scrape would quietly pass on a spec whose list is computed.
    """
    import sys
    import types

    captured: dict[str, object] = {}

    def _collect_data_files(pkg, **kwargs):
        return []          # third-party payloads are not what this test guards

    def _collect_submodules(pkg, **kwargs):
        return []

    # PyInstaller is a BUILD dependency, installed in CI but not in the dev
    # venv — and this test must run everywhere, since its whole purpose is to
    # fail in the environment that cannot otherwise notice the bug. Stubbing the
    # import is safe: the spec only uses these two helpers, and both are
    # replaced by the no-ops above.
    stub = types.ModuleType("PyInstaller.utils.hooks")
    stub.collect_data_files = _collect_data_files
    stub.collect_submodules = _collect_submodules
    installed = {
        "PyInstaller": types.ModuleType("PyInstaller"),
        "PyInstaller.utils": types.ModuleType("PyInstaller.utils"),
        "PyInstaller.utils.hooks": stub,
    }
    saved = {name: sys.modules.get(name) for name in installed}
    sys.modules.update(installed)

    class _Recorder:
        """Stands in for Analysis/PYZ/EXE/COLLECT/BUNDLE."""

        def __init__(self, *args, **kwargs):
            if "datas" in kwargs:
                captured["datas"] = kwargs["datas"]
            self.pure = self.zipped_data = self.scripts = []
            self.binaries = self.zipfiles = self.datas = []

        def __iter__(self):
            return iter(())

    globs = {
        "__file__": str(SPEC),
        "collect_data_files": _collect_data_files,
        "collect_submodules": _collect_submodules,
        "Analysis": _Recorder,
        "PYZ": _Recorder,
        "EXE": _Recorder,
        "COLLECT": _Recorder,
        "BUNDLE": _Recorder,
        "TOC": list,
        "Tree": lambda *a, **k: [],
        "SPEC": str(SPEC),
        "DISTPATH": str(REPO_ROOT / "dist"),
        "workpath": str(REPO_ROOT / "build"),
        "os": os,
    }
    try:
        exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), globs)
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    datas = captured.get("datas")
    assert datas is not None, "the spec never passed datas= to Analysis()"
    return [(str(src), str(dest)) for src, dest in datas]


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
