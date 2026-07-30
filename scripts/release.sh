#!/usr/bin/env bash
# release.sh — cut a MetaTV release: bump the version, tag it, push → CI builds.
#
# Host-agnostic (fits the dev-tooling spin-off): nothing but the version-file
# path is project-specific, and that is overridable via .devscripts.conf.
#
#   scripts/release.sh 0.11.0        Bump __version__, commit, tag v0.11.0, push.
#   scripts/release.sh 0.11.0-rc1    Pre-release: tags v0.11.0-rc1 (base must
#                                    match the bumped __version__ = 0.11.0).
#   scripts/release.sh 0.11.0 --dry-run   Print every action; change nothing.
#
# On push of the tag, .github/workflows/release.yml builds the unsigned .app/.dmg
# and (for a v* tag) attaches it to the GitHub Release. -rc* tags → prerelease.
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
[ -f "$REPO_ROOT/.devscripts.conf" ] && source "$REPO_ROOT/.devscripts.conf"
VERSION_FILE="${VERSION_FILE:-$REPO_ROOT/metatv/__init__.py}"

DRY_RUN=0
VERSION=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "Unknown flag: $arg" >&2; exit 2 ;;
    *) VERSION="$arg" ;;
  esac
done

if [ -z "$VERSION" ]; then
  echo "usage: scripts/release.sh <version> [--dry-run]" >&2
  exit 2
fi

# Accept X.Y.Z with an optional -rcN / -betaN / -alphaN pre-release suffix.
if ! echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$'; then
  echo "Invalid version '$VERSION' (want X.Y.Z or X.Y.Z-rc1)" >&2
  exit 2
fi

# The __version__ SSOT holds the base X.Y.Z; the tag may carry a pre-release
# suffix (the CI guard strips it before comparing).
BASE_VERSION="${VERSION%%-*}"
TAG="v${VERSION}"

run() {
  echo "+ $*"
  [ "$DRY_RUN" -eq 1 ] || "$@"
}

# ── Preconditions ────────────────────────────────────────────────────────────
if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "Working tree not clean — commit or stash first." >&2
  exit 1
fi

if git -C "$REPO_ROOT" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "Tag $TAG already exists." >&2
  exit 1
fi

# ── Bump __version__ ─────────────────────────────────────────────────────────
CURRENT="$(python3 -c "import re,pathlib;print(re.search(r'__version__\s*=\s*[\"\x27]([^\"\x27]+)', pathlib.Path('$VERSION_FILE').read_text()).group(1))")"
echo "Current __version__: $CURRENT  →  $BASE_VERSION   (tag $TAG)"

if [ "$DRY_RUN" -eq 0 ]; then
  python3 - "$VERSION_FILE" "$BASE_VERSION" <<'PY'
import re, sys, pathlib
path, new = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
text = p.read_text()
text = re.sub(r'(__version__\s*=\s*["\'])([^"\']+)(["\'])', rf'\g<1>{new}\g<3>', text, count=1)
p.write_text(text)
print(f"Wrote __version__ = {new} to {path}")
PY
fi

# ── Commit, tag, push ────────────────────────────────────────────────────────
run git -C "$REPO_ROOT" add "$VERSION_FILE"
run git -C "$REPO_ROOT" commit -m "chore(release): $BASE_VERSION ($TAG)"
run git -C "$REPO_ROOT" tag -a "$TAG" -m "MetaTV $TAG"
run git -C "$REPO_ROOT" push origin HEAD
run git -C "$REPO_ROOT" push origin "$TAG"

echo
echo "Pushed $TAG. Watch the build: Actions → 'Release (macOS)'."
[ "$DRY_RUN" -eq 1 ] && echo "(dry-run — nothing was changed)"
