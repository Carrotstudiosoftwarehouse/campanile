#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Downloads offline Wikipedia (Kiwix ZIM files) into data/zim/. Finds the latest
# release by itself, resumes interrupted downloads and checks Kiwix's SHA-256.
set -euo pipefail

usage() {
  cat <<'USAGE'
Downloads offline Wikipedia (Kiwix ZIM) into data/zim/.

  scripts/download-wikipedia.sh PACKAGE [LANGUAGE]

  medicine        medical articles, with images     ~260 MB
  medicine-light  medical articles, no images       ~100 MB
  essential       most-read articles, no images     ~900 MB
  full            all of Wikipedia, no images       ~8.4 GB
  full-images     all of Wikipedia, with images     ~30 GB

LANGUAGE is a Wikipedia code like it, en, de, fr, uk (default: it).
Sizes are for Italian, measured on 22 October 2026. Needs: bash, curl, python3.
USAGE
  exit 1
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIM="${CAMPANILE_DATA:-$ROOT/data}/zim"
INDEX="https://download.kiwix.org/zim/wikipedia/"

[ $# -ge 1 ] && [ $# -le 2 ] || usage
LANGUAGE="${2:-it}"
[[ "$LANGUAGE" =~ ^[a-z]{2,3}$ ]] || { echo "Invalid language code: $LANGUAGE" >&2; exit 1; }
case "$1" in
  medicine)       PREFIX="wikipedia_${LANGUAGE}_medicine_maxi" ;;
  medicine-light) PREFIX="wikipedia_${LANGUAGE}_medicine_nopic" ;;
  essential)      PREFIX="wikipedia_${LANGUAGE}_top_nopic" ;;
  full)           PREFIX="wikipedia_${LANGUAGE}_all_nopic" ;;
  full-images)    PREFIX="wikipedia_${LANGUAGE}_all_maxi" ;;
  *) usage ;;
esac

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

echo "Looking up the latest ${PREFIX}..."
NAME="$(curl -fsSL --proto =https --proto-redir =https --retry 3 "$INDEX" | python3 -I -c '
import re, sys
prefix = sys.argv[1]
names = set(re.findall(r"href=\"(" + re.escape(prefix) + r"_\d{4}-\d{2}\.zim)\"", sys.stdin.read()))
if not names:
    sys.exit("No file found for " + prefix)
print(sorted(names)[-1])
' "$PREFIX")"
echo "Latest: $NAME"

mkdir -p "$ZIM"
TARGET="$ZIM/$NAME"
# On a Raspberry the installer has moved it to /var/lib/campanile.
for HAVE in "$TARGET" "/var/lib/campanile/zim/$NAME"; do
  if [ -f "$HAVE" ]; then
    echo "Already there: $HAVE"
    exit 0
  fi
done

EXPECTED="$(curl -fsSL --proto =https --proto-redir =https --retry 3 "$INDEX$NAME.sha256" | cut -d' ' -f1)"
if ! [[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]]; then
  echo "ERROR: no SHA-256 published for $NAME" >&2
  exit 1
fi

PARTIAL="$ZIM/.$NAME.partial"
echo "Downloading (you can stop and rerun: it resumes where it left off)..."
curl -fL --proto =https --proto-redir =https --retry 5 --retry-delay 5 -C - -o "$PARTIAL" "$INDEX$NAME"

echo "Checking SHA-256 (takes a few minutes on big files)..."
ACTUAL="$(sha256 "$PARTIAL")"
if [ "$ACTUAL" != "$EXPECTED" ]; then
  echo "ERROR: the download doesn't match the published checksum." >&2
  echo "  expected: $EXPECTED" >&2; echo "  actual:   $ACTUAL" >&2
  echo "Deleting the damaged file: run the script again." >&2
  rm -f "$PARTIAL"
  exit 1
fi
mv -f "$PARTIAL" "$TARGET"
echo "Done: $TARGET ($(du -h "$TARGET" | cut -f1))"

OLD="$(find "$ZIM" -maxdepth 1 -name "${PREFIX}_*.zim" ! -name "$NAME" | sort)"
if [ -n "$OLD" ]; then
  echo "Older versions of the same package (safe to delete):"
  echo "$OLD"
fi
