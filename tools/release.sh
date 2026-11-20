#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
# Publish, or republish, the GitHub release for the version in VERSION.
#   tools/release.sh            build + test, tag vX.Y.Z if needed, create or update the release
#   tools/release.sh --dry-run  build + test and write build/release-notes.md; change nothing on GitHub
#   tools/release.sh --verify   check the published vX.Y.Z files match the local build (no build, any branch)
# Run from WSL in a clone on a Windows drive (the build runs tools\build.bat on Windows).
# Needs the GitHub CLI (gh), signed in with push access. Steps: docs/development.md.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
DRY=0 VERIFY=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY=1 ;;
  --verify) VERIFY=1 ;;
  *) echo "usage: tools/release.sh [--dry-run | --verify]" >&2; exit 2 ;;
esac

die() { echo "release: $*" >&2; exit 1; }
check() {  # a failed check stops a real release; a dry run only warns
  if [ "$DRY" = 1 ]; then echo "release: warning: $*" >&2; else die "$*"; fi
}

VERSION=$(tr -d '[:space:]' < VERSION)
TAG="v$VERSION"
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION must be X.Y.Z, got '$VERSION'."
INSTALLER="build/installer/multiput-setup-$VERSION.exe"
UF2="build/firmware/multiput.uf2"
command -v gh >/dev/null || die "the GitHub CLI (gh) is needed: https://cli.github.com"
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)

# The published files must be exactly the local build. GitHub records each upload's SHA-256
# ("digest"), so compare with that rather than downloading the files again (which can stall).
verify() {
  local assets name want got tries=0
  for f in "$INSTALLER" "$UF2"; do
    [ -f "$f" ] || die "$f is missing: build $VERSION first (tools\\build.bat), or check out the commit it was released from."
  done
  while :; do
    assets=$(gh api "repos/$REPO/releases/tags/$TAG" --jq '.assets[] | .name + " " + (.digest // "")') ||
      die "there's no $TAG release on $REPO."
    # GitHub may take a moment to record a fresh upload's digest.
    if [ "$tries" -lt 10 ] && grep -qE "^($(basename "$INSTALLER")|$(basename "$UF2")) *$" <<< "$assets"; then
      tries=$((tries + 1)); sleep 3; continue
    fi
    break
  done
  for f in "$INSTALLER" "$UF2"; do
    name=$(basename "$f")
    want="sha256:$(sha256sum < "$f" | cut -d' ' -f1)"
    got=$(awk -v n="$name" '$1 == n { print $2 }' <<< "$assets")
    grep -q "^$name " <<< "$assets" || die "$name isn't on the $TAG release."
    [ -n "$got" ] || die "GitHub has no checksum for $name on $TAG yet; try again in a minute."
    [ "$got" = "$want" ] || die "$name on GitHub doesn't match the local build ($got, local $want). Republish with tools/release.sh."
    echo "   $name: matches ($want)"
  done
}

if [ "$VERIFY" = 1 ]; then
  echo "== Verifying the $TAG release on $REPO against the local build"
  verify
  echo "== OK: https://github.com/$REPO/releases/tag/$TAG"
  exit 0
fi

# Releases only ever come from main: branch builds must never publish.
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != main ]; then
  WHERE=${BRANCH:+"branch '$BRANCH'"}
  WHERE=${WHERE:-"a detached HEAD ($(git rev-parse --short HEAD))"}
  [ "$DRY" = 1 ] || die "releases are only made from main, but you're on $WHERE. Switch with 'git switch main' (a --dry-run works on any branch)."
  echo "release: note: dry run on $WHERE; a real release has to run on main." >&2
fi
START=$(git rev-parse HEAD)

grep -q "^## \[$VERSION\]" CHANGELOG.md || die "CHANGELOG.md has no '## [$VERSION]' section. Move the Unreleased entries under it first."
case "$ROOT" in /mnt/*) ;; *) die "clone the repo onto a Windows drive (e.g. /mnt/c/...): the installer builds on Windows." ;; esac
[ -z "$(git status --porcelain)" ] || check "there are uncommitted changes; commit them first."
git fetch -q origin main --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || check "main isn't in sync with origin/main; push (or pull) first."
NEW_TAG=1
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  NEW_TAG=0
  [ "$(git rev-list -n1 "$TAG")" = "$(git rev-parse HEAD)" ] || check "$TAG already exists on a different commit. A published version shouldn't change; bump VERSION instead."
fi

echo "== Building and testing multiput $VERSION"
cmd.exe /c "tools\\build.bat" || die "the build failed; see build/logs/build.log."
[ -f "$INSTALLER" ] && [ -f "$UF2" ] || die "expected $INSTALLER and $UF2 after the build."
NOTES="build/release-notes.md"
python3 tools/release_notes.py "$VERSION" "$INSTALLER" "$UF2" > "$NOTES"

if [ "$DRY" = 1 ]; then
  echo "== Dry run: nothing published. Notes: $NOTES"
  echo "   Would $([ $NEW_TAG = 1 ] && echo "create tag $TAG and the release" || echo "update the existing $TAG release") on $REPO."
  exit 0
fi

# The build takes minutes: make sure the branch and commit didn't change meanwhile.
[ "$(git branch --show-current)" = main ] && [ "$(git rev-parse HEAD)" = "$START" ] ||
  die "the branch or commit changed during the build; nothing was published. Run the release again."

if [ "$NEW_TAG" = 1 ]; then
  echo "== Tagging $TAG"
  git tag -a "$TAG" -m "multiput $VERSION"
  git push origin "$TAG"
fi
if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  echo "== Updating the $TAG release (republish)"
  gh release edit "$TAG" --repo "$REPO" --title "multiput $VERSION" --notes-file "$NOTES"
  gh release upload "$TAG" --repo "$REPO" --clobber "$INSTALLER" "$UF2"
else
  echo "== Creating the $TAG release"
  gh release create "$TAG" --repo "$REPO" --verify-tag --title "multiput $VERSION" --notes-file "$NOTES" "$INSTALLER" "$UF2"
fi

echo "== Verifying the published files"
verify
echo "== Published: https://github.com/$REPO/releases/tag/$TAG"
