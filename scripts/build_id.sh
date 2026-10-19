#!/usr/bin/env bash
# The rolling build identifier, defined once for every release workflow (D64).
#
#   scripts/build_id.sh              print <version>+<UTC date>.<short sha>
#   scripts/build_id.sh --stamp [ID] write ID (default: the above) into the
#                                    gitignored metatv/_build_id.py, so a
#                                    packaged app's title bar names its commit
#
# release.yml (.dmg), windows-rolling.yml (.zip) and flatpak-build.yml each
# derived this by hand, and two of them read the SHA differently; one builder
# means a .dmg, .zip and .flatpak from one commit name it identically.
set -euo pipefail
cd "$(dirname "$0")/.."

version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' metatv/__init__.py)"
if [ -z "$version" ]; then
  echo "build_id.sh: no __version__ in metatv/__init__.py" >&2
  exit 1
fi
# GITHUB_SHA when CI provides it (the Flatpak container has no usable git).
sha="${GITHUB_SHA:-$(git rev-parse HEAD)}"
build_id="${version}+$(date -u +%Y%m%d).${sha:0:7}"

if [ "${1:-}" = "--stamp" ]; then
  stamp="${2:-$build_id}"
  printf 'BUILD_ID = "%s"\n' "$stamp" > metatv/_build_id.py
  echo "Stamped build id: $stamp"
else
  echo "$build_id"
fi
