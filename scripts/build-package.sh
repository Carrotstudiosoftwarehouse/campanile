#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Builds dist/campanile-VERSION.zip, ready to open with a double click (Windows too), libraries
# included. Only files tracked by git, plus campanile/web/vendor and campanile/certs: never
# local data, databases or passwords.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[ -z "$(git status --porcelain)" ] || { echo "There are uncommitted changes." >&2; exit 1; }
[ -f campanile/web/vendor/maplibre-gl.mjs ] && [ -f campanile/certs/cacert.pem ] || scripts/prepare.sh

VERSION="$(python3 -I -c 'import re; print(re.search(r"VERSION = \"(.+?)\"", open("campanile/server.py").read())[1])')"
NAME="campanile-$VERSION"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git archive --format=tar --prefix="$NAME/" HEAD | tar -x -C "$TMP"
cp -R campanile/web/vendor "$TMP/$NAME/campanile/web/vendor"
cp -R campanile/certs "$TMP/$NAME/campanile/certs"

mkdir -p dist
rm -f "dist/$NAME.zip"
(cd "$TMP" && zip -q -r -X "$ROOT/dist/$NAME.zip" "$NAME")
echo "Done: dist/$NAME.zip ($(du -h "dist/$NAME.zip" | cut -f1))"
