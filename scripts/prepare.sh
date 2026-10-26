#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Run once, with internet: fetches what the pages use offline (map, fonts, icons, QR code)
# into campanile/web/vendor, and the certificate authorities the setup page trusts into
# campanile/certs. Every file is checked against its SHA-256. Needs: bash, curl, tar, git, python3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/campanile/web/vendor"
CERTS="$ROOT/campanile/certs"

MAPLIBRE_VER="6.15.0"
MAPLIBRE_SHA="6af2cfe94668c05057533265253ce7ab5aa6a96355ddfb0977175dc2bfb1f5ce"
PMTILES_VER="4.5.0"
PMTILES_SHA="23ae7c575578ad24cd579377d69c46550631da219e6f179997ec2cf3b8c937e5"
BASEMAPS_VER="5.7.2"
BASEMAPS_SHA="2d5d41b29cdd2364f7092ad439bd9d170b4f38cbec8858cefbe84d0f98125ce6"
QRCODE_VER="2.0.4"
QRCODE_SHA="02e2e18a99a90b02dad940851f59b7c3c5fd1ab79cbdece8595cb06328878159"
# Mozilla's certificate authorities, as packaged by certifi (the list requests and pip use).
# Not the newest: a release some months old has had time to be looked at.
CERTIFI_VER="2026.7.22"
CERTIFI_SHA="62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775"
ASSETS_REPO="https://github.com/protomaps/basemaps-assets.git"
ASSETS_COMMIT="028c18f713baecad011301ff7a69acc39bcc2ae7"
# The pmtiles and basemaps npm packages ship without a license file: taken from their repos.
LIC_PMTILES_URL="https://raw.githubusercontent.com/protomaps/PMTiles/aec8fa1341222fdddb3318e9ffa8e18e19b312f7/LICENSE"
LIC_PMTILES_SHA="0371c38f338835f7fc13ed71176f3d92144e22c8b736a31cced57adbbeb647b3"
LIC_BASEMAPS_URL="https://raw.githubusercontent.com/protomaps/basemaps/42ffaaa4a85a41bfcb23e43cc0f5b492a5eca123/LICENSE.md"
LIC_BASEMAPS_SHA="74f975cfedd168098c43b5cfd6e587e40604684c4ffcec3e90d24b3b09c061b0"
LIC_DATA_URL="https://raw.githubusercontent.com/protomaps/basemaps/42ffaaa4a85a41bfcb23e43cc0f5b492a5eca123/LICENSE_DATA.md"
LIC_DATA_SHA="9d9064bc0004a507ce105b92552538dd1484cd704afe42da02a9a74c3bd4a293"

for cmd in curl tar git python3; do
  command -v "$cmd" >/dev/null || { echo "Missing command: $cmd" >&2; exit 1; }
done

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# fetch URL FILE SHA256
fetch() {
  echo "  downloading $(basename "$2")"
  curl -fsSL --proto =https --proto-redir =https --retry 3 -o "$2" "$1"
  local actual
  actual="$(sha256 "$2")"
  if [ "$actual" != "$3" ]; then
    echo "ERROR: SHA-256 mismatch for $(basename "$2")" >&2
    echo "  expected: $3" >&2
    echo "  actual:   $actual" >&2
    exit 1
  fi
}

echo "1/4 JavaScript libraries"
fetch "https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-$MAPLIBRE_VER.tgz" \
  "$TMP/maplibre.tgz" "$MAPLIBRE_SHA"
fetch "https://registry.npmjs.org/pmtiles/-/pmtiles-$PMTILES_VER.tgz" \
  "$TMP/pmtiles.tgz" "$PMTILES_SHA"
fetch "https://registry.npmjs.org/@protomaps/basemaps/-/basemaps-$BASEMAPS_VER.tgz" \
  "$TMP/basemaps.tgz" "$BASEMAPS_SHA"
fetch "https://registry.npmjs.org/qrcode-generator/-/qrcode-generator-$QRCODE_VER.tgz" \
  "$TMP/qrcode.tgz" "$QRCODE_SHA"

for name in maplibre pmtiles basemaps qrcode; do
  mkdir -p "$TMP/$name"
  tar xzf "$TMP/$name.tgz" -C "$TMP/$name"
done

echo "2/4 Fonts and icons (commit ${ASSETS_COMMIT:0:12})"
git -c init.defaultBranch=main init -q "$TMP/assets"
git -C "$TMP/assets" remote add origin "$ASSETS_REPO"
git -C "$TMP/assets" fetch -q --depth 1 origin "$ASSETS_COMMIT"
git -C "$TMP/assets" -c advice.detachedHead=false checkout -q FETCH_HEAD
if [ "$(git -C "$TMP/assets" rev-parse HEAD)" != "$ASSETS_COMMIT" ]; then
  echo "ERROR: basemaps-assets commit is not the expected one" >&2
  exit 1
fi

echo "3/4 Copying into campanile/web/vendor"
NEW="$TMP/vendor"
mkdir -p "$NEW/licenses" "$NEW/sprites"
cp "$TMP/maplibre/package/dist/maplibre-gl.mjs" \
   "$TMP/maplibre/package/dist/maplibre-gl-worker.mjs" \
   "$TMP/maplibre/package/dist/maplibre-gl.css" "$NEW/"
cp "$TMP/pmtiles/package/dist/pmtiles.js" "$NEW/"
cp "$TMP/basemaps/package/dist/basemaps.js" "$NEW/"
cp "$TMP/qrcode/package/dist/qrcode.mjs" "$NEW/"
cp -R "$TMP/assets/fonts" "$NEW/fonts"
cp -R "$TMP/assets/sprites/v4" "$NEW/sprites/v4"
cp "$TMP/maplibre/package/LICENSE.txt" "$NEW/licenses/maplibre-gl.txt"
fetch "$LIC_PMTILES_URL" "$NEW/licenses/pmtiles.txt" "$LIC_PMTILES_SHA"
fetch "$LIC_BASEMAPS_URL" "$NEW/licenses/protomaps-basemaps.md" "$LIC_BASEMAPS_SHA"
fetch "$LIC_DATA_URL" "$NEW/licenses/map-data.md" "$LIC_DATA_SHA"
cp "$TMP/assets/fonts/OFL.txt" "$NEW/licenses/noto-fonts-OFL.txt"
cp "$TMP/assets/README.md" "$NEW/licenses/basemaps-assets-README.md"
cat > "$NEW/VERSIONS.txt" <<VERSIONS
maplibre-gl          $MAPLIBRE_VER   sha256 $MAPLIBRE_SHA
pmtiles              $PMTILES_VER    sha256 $PMTILES_SHA
@protomaps/basemaps  $BASEMAPS_VER    sha256 $BASEMAPS_SHA
qrcode-generator     $QRCODE_VER    sha256 $QRCODE_SHA
basemaps-assets      commit $ASSETS_COMMIT
VERSIONS

# Build the new folder first, then swap: never a half-broken state.
rm -rf "$VENDOR.old"
[ -d "$VENDOR" ] && mv "$VENDOR" "$VENDOR.old"
mv "$NEW" "$VENDOR"
rm -rf "$VENDOR.old"
echo "Done: $(du -sh "$VENDOR" | cut -f1) in $VENDOR"

echo "4/4 Certificate authorities (certifi $CERTIFI_VER) into campanile/certs"
fetch "https://files.pythonhosted.org/packages/0b/a7/71ac2cff56fec219ed242bb11b8efb69fcc4bec75db06fb7bfe35de520e6/certifi-$CERTIFI_VER-py3-none-any.whl" \
  "$TMP/certifi.whl" "$CERTIFI_SHA"
mkdir -p "$TMP/certs"
python3 -I - "$TMP/certifi.whl" "$TMP/certs" "$CERTIFI_VER" <<'PY'
import sys, zipfile
wheel, out, version = sys.argv[1:]
with zipfile.ZipFile(wheel) as z:  # only the two files we need, under names we choose
    open(f"{out}/cacert.pem", "wb").write(z.read("certifi/cacert.pem"))
    open(f"{out}/LICENSE-certifi.txt", "wb").write(
        z.read(f"certifi-{version}.dist-info/licenses/LICENSE"))
PY
grep -q "BEGIN CERTIFICATE" "$TMP/certs/cacert.pem" || { echo "ERROR: empty certificate list" >&2; exit 1; }
echo "certifi $CERTIFI_VER  sha256 $CERTIFI_SHA" > "$TMP/certs/VERSION.txt"
rm -rf "$CERTS.old"
[ -d "$CERTS" ] && mv "$CERTS" "$CERTS.old"
mv "$TMP/certs" "$CERTS"
rm -rf "$CERTS.old"
echo "Done: $(grep -c "BEGIN CERTIFICATE" "$CERTS/cacert.pem") authorities in $CERTS"
