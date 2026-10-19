#!/usr/bin/env bash
# Attach one build artifact to the `rolling` release, replacing the old copy (D64).
#
#   scripts/upload_to_rolling.sh <asset-file>
#
# release.yml creates and moves the release itself (tag, title, notes); the
# Windows and Flatpak jobs only add their own asset under a stable name. They
# can finish first, so this waits up to ten minutes for the release to exist.
# Needs GITHUB_TOKEN and GITHUB_REPOSITORY (both set in Actions).
set -euo pipefail
asset="${1:?usage: upload_to_rolling.sh <asset-file>}"

for _ in $(seq 1 30); do
  gh release view rolling --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1 && break
  echo "rolling release not there yet — waiting for release.yml"; sleep 20
done
gh release upload rolling "$asset" --clobber --repo "$GITHUB_REPOSITORY"
