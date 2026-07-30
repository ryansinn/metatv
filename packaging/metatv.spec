# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds a windowed, unsigned ``MetaTV.app`` for macOS.

Run from the repo root::

    pyinstaller packaging/metatv.spec --noconfirm

Note: mpv is an EXTERNAL binary MetaTV spawns over an IPC socket (not libmpv),
so PyInstaller does NOT bundle it here.  CI vendors a self-contained mpv into
``MetaTV.app/Contents/Resources/mpv/`` after this build (see
``.github/workflows/release.yml``); ``_resolve_mpv_binary()`` finds it there
when frozen and falls back to ``$MPV_BINARY`` / ``PATH`` otherwise.
"""

import os
import re

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Locate the repo root (this spec lives in <root>/packaging) ───────────────
try:
    _SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 - PyInstaller global
except NameError:  # pragma: no cover - fallback when SPEC isn't injected
    _SPEC_DIR = os.path.abspath(os.getcwd())
REPO_ROOT = (
    os.path.dirname(_SPEC_DIR)
    if os.path.basename(_SPEC_DIR) == "packaging"
    else _SPEC_DIR
)


def _read_version() -> str:
    """Read ``__version__`` from ``metatv/__init__.py`` (the version SSOT)."""
    init_path = os.path.join(REPO_ROOT, "metatv", "__init__.py")
    with open(init_path, encoding="utf-8") as handle:
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', handle.read())
    return match.group(1) if match else "0.0.0"


VERSION = _read_version()

# ── Dynamically-imported plugin packages PyInstaller can't see statically ────
# providers / metadata_providers / players are loaded through factories + a
# dynamic import; whats_new entries via pkgutil.iter_modules.  Without collecting
# their submodules the frozen app would silently ship none of them.
hiddenimports: list[str] = []
for _pkg in (
    "metatv.providers",
    "metatv.metadata_providers",
    "metatv.core.players",
    "metatv.whats_new.entries",
):
    hiddenimports += collect_submodules(_pkg)
# Belt-and-suspenders: sweep the whole package so nothing dynamic is missed.
hiddenimports += collect_submodules("metatv")

# ── Data files ───────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files("qtawesome")  # bundled icon fonts / charmaps
# Also ship the What's New entry modules on disk so pkgutil.iter_modules can
# enumerate them inside the frozen app.
datas.append(
    (
        os.path.join(REPO_ROOT, "metatv", "whats_new", "entries"),
        os.path.join("metatv", "whats_new", "entries"),
    )
)

block_cipher = None

a = Analysis(
    [os.path.join(REPO_ROOT, "metatv", "__main__.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MetaTV",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed .app (no attached terminal)
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MetaTV",
)

app = BUNDLE(
    coll,
    name="MetaTV.app",
    icon=None,  # placeholder omitted for the MVP; add packaging/metatv.icns later
    bundle_identifier="com.ryansinn.metatv",
    version=VERSION,
    info_plist={
        "CFBundleName": "MetaTV",
        "CFBundleDisplayName": "MetaTV",
        "CFBundleIdentifier": "com.ryansinn.metatv",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
)
