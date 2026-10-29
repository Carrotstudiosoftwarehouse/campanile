#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Cuts the area you need out of Protomaps' daily world map (OpenStreetMap data)
# and saves it as an offline PMTiles file in data/maps/. Only that area is downloaded.
set -euo pipefail

usage() {
  cat <<'USAGE'
Downloads an offline map (PMTiles) into data/maps/.

  scripts/download-map.sh world          the world, zoom 0-7        ~190 MB
  scripts/download-map.sh italy          Italy, zoom 0-15 (full)    ~4.5 GB
  scripts/download-map.sh italy-light    Italy, zoom 0-12           ~580 MB
  scripts/download-map.sh custom NAME WEST,SOUTH,EAST,NORTH [MAX_ZOOM]
      e.g. scripts/download-map.sh custom turin 7.64,45.04,7.71,45.09

Sizes measured on 22-24 October 2026. Needs: bash, curl, python3, tar or unzip.
USAGE
  exit 1
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAPS="${CAMPANILE_DATA:-$ROOT/data}/maps"
TOOLS="$ROOT/tools"

PMTILES_VER="1.31.2"
BUILDS_URL="https://build-metadata.protomaps.dev/builds.json"
BUILD_BASE="https://build.protomaps.com"

[ $# -ge 1 ] || usage
case "$1" in
  world)       NAME="world";       BBOX="-180,-85,180,85";    ZOOM="7"  ;;
  italy)       NAME="italy";       BBOX="6.6,35.4,18.6,47.1"; ZOOM="15" ;;
  italy-light) NAME="italy-light"; BBOX="6.6,35.4,18.6,47.1"; ZOOM="12" ;;
  custom)
    [ $# -ge 3 ] || usage
    NAME="$2"; BBOX="$3"; ZOOM="${4:-15}"
    ;;
  *) usage ;;
esac

if ! [[ "$NAME" =~ ^[A-Za-z0-9_-]{1,60}$ ]]; then
  echo "Invalid name: use only letters, digits, - and _" >&2; exit 1
fi
if ! [[ "$ZOOM" =~ ^[0-9]{1,2}$ ]] || [ "$ZOOM" -gt 15 ]; then
  echo "Invalid max zoom (0-15): $ZOOM" >&2; exit 1
fi
NUM='-?[0-9]+(\.[0-9]+)?'
if ! [[ "$BBOX" =~ ^$NUM,$NUM,$NUM,$NUM$ ]]; then
  echo "Invalid box: expected WEST,SOUTH,EAST,NORTH in degrees, e.g. 7.64,45.04,7.71,45.09" >&2
  exit 1
fi
python3 -I - "$BBOX" <<'PY'
import sys
w, s, e, n = map(float, sys.argv[1].split(","))
if not (-180 <= w < e <= 180 and -85 <= s < n <= 85):
    sys.exit("Invalid box: WEST must be < EAST and SOUTH < NORTH.")
PY

TARGET="$MAPS/$NAME.pmtiles"
# Like download-wikipedia.sh: running the guide again downloads nothing twice, even offline.
if [ -f "$TARGET" ]; then
  echo "Already there: $TARGET (delete it to download a newer one)"
  exit 0
fi

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# The pmtiles tool is downloaded once and its checksum verified.
PMTILES="$TOOLS/pmtiles"
if ! [ -x "$PMTILES" ] || ! grep -q "pmtiles $PMTILES_VER" <<< "$("$PMTILES" version 2>/dev/null)"; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)   ARCHIVE="go-pmtiles-${PMTILES_VER}_Darwin_arm64.zip"
                    EXPECTED="40528f7f616fcbf91207cd48c8fc023d213f6d86c0cbf1f748732803d1880f3d" ;;
    Darwin-x86_64)  ARCHIVE="go-pmtiles-${PMTILES_VER}_Darwin_x86_64.zip"
                    EXPECTED="1f0dc02eee6c58312dd6c509faee1b5c32f0596568af1bf51f1b034e7a88a65b" ;;
    Linux-aarch64|Linux-arm64)
                    ARCHIVE="go-pmtiles_${PMTILES_VER}_Linux_arm64.tar.gz"
                    EXPECTED="f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1" ;;
    Linux-x86_64)   ARCHIVE="go-pmtiles_${PMTILES_VER}_Linux_x86_64.tar.gz"
                    EXPECTED="3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f" ;;
    *) echo "Unsupported system: $(uname -s) $(uname -m). Download the map on another computer and copy it into data/maps/." >&2
       exit 1 ;;
  esac
  echo "Downloading the pmtiles tool ${PMTILES_VER}..."
  mkdir -p "$TOOLS"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL --proto =https --proto-redir =https --retry 3 -o "$TMP/$ARCHIVE" \
    "https://github.com/protomaps/go-pmtiles/releases/download/v$PMTILES_VER/$ARCHIVE"
  ACTUAL="$(sha256 "$TMP/$ARCHIVE")"
  if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "ERROR: SHA-256 mismatch for the pmtiles tool." >&2
    echo "  expected: $EXPECTED" >&2; echo "  actual:   $ACTUAL" >&2
    exit 1
  fi
  case "$ARCHIVE" in
    *.zip)    unzip -q -o "$TMP/$ARCHIVE" pmtiles -d "$TMP" ;;
    *.tar.gz) tar xzf "$TMP/$ARCHIVE" -C "$TMP" pmtiles ;;
  esac
  install -m 755 "$TMP/pmtiles" "$PMTILES"
fi

echo "Looking up Protomaps' latest world map..."
LATEST="$(curl -fsSL --proto =https --proto-redir =https --retry 3 "$BUILDS_URL" | python3 -I -c '
import json, sys
builds = [b["key"] for b in json.load(sys.stdin) if b.get("key", "").endswith(".pmtiles")]
if not builds:
    sys.exit("No map found in the Protomaps build list.")
print(sorted(builds)[-1])
')"
echo "Source map: $BUILD_BASE/$LATEST"

mkdir -p "$MAPS"
PARTIAL="$MAPS/.$NAME.pmtiles.partial"
rm -f "$PARTIAL"
echo "Extracting '$NAME' (box $BBOX, zoom 0-$ZOOM)..."
"$PMTILES" extract "$BUILD_BASE/$LATEST" "$PARTIAL" --bbox="$BBOX" --maxzoom="$ZOOM"
"$PMTILES" verify "$PARTIAL" >/dev/null
mv -f "$PARTIAL" "$TARGET"
echo "Done: $TARGET ($(du -h "$TARGET" | cut -f1))"
