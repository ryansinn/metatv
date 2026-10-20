#!/usr/bin/env bash
# Build MetaTV with Nuitka: the app is compiled to C and then to native code,
# so the bundle carries no Python source and no .pyc bytecode to decompile
# (PyInstaller shipped bytecode that a free extractor turns back into source).
#
#   packaging/build_nuitka.sh [version]
#
# macOS   -> dist/MetaTV.app      (release.yml vendors mpv, signs, makes the .dmg)
# Windows -> dist/MetaTV/MetaTV.exe (windows-rolling.yml vendors mpv, zips)
#
# The Flatpak compiles the same package in module mode instead
# (packaging/flatpak/io.github.ryansinn.MetaTV.yml), because it runs on the
# runtime's own Python.
#
# Data files: Nuitka follows imports, not open() calls. Every non-.py file the
# app reads at runtime is listed here, at the same relative path the source
# tree uses (code finds them next to its own __file__).
# tests/test_packaging_data_files.py names the directories that must be listed.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' metatv/__init__.py)}"
OUT=build/nuitka

args=(
  --standalone
  --assume-yes-for-downloads
  --output-dir="$OUT"
  --output-filename=MetaTV
  --enable-plugins=pyqt6
  --include-package=metatv
  --include-package-data=qtawesome
  --include-data-dir=metatv/gui/tokens=metatv/gui/tokens
  --include-data-dir=metatv/data=metatv/data
  --include-data-dir=metatv/assets/fonts=metatv/assets/fonts
  --include-data-files=packaging/icon/metatv-256.png=packaging/icon/metatv-256.png
  --product-name=MetaTV
  --company-name=MetaTV
  --product-version="$VERSION"
  --file-version="$VERSION"
)

case "$(uname -s)" in
  Darwin)
    args+=(
      --macos-create-app-bundle
      --macos-app-name=MetaTV
      --macos-app-version="$VERSION"
      --macos-signed-app-name=com.ryansinn.metatv
    )
    [ -f packaging/icon/metatv.icns ] && args+=(--macos-app-icon=packaging/icon/metatv.icns)
    ;;
  MINGW*|MSYS*|CYGWIN*)
    args+=(
      --windows-console-mode=disable
      --windows-icon-from-ico=packaging/icon/metatv-256.png
    )
    ;;
esac

python -m nuitka "${args[@]}" packaging/metatv_launcher.py

rm -rf dist && mkdir -p dist
case "$(uname -s)" in
  Darwin) mv "$OUT/metatv_launcher.app" dist/MetaTV.app ;;
  *)      mv "$OUT/metatv_launcher.dist" dist/MetaTV ;;
esac
ls -la dist
