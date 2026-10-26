#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Builds dist/demo/: the online demo, a static site. The pages are the real ones; a service
# worker (demo/sw.js) answers in place of the server, inside each visitor's browser.
# It must be served from the root of a domain (the pages use paths like /common.js).
set -euo pipefail

usage() {
  cat <<'USAGE'
Builds the static online demo into dist/demo/.

  scripts/build-demo.sh MAP.pmtiles      e.g. scripts/build-demo.sh data/maps/area.pmtiles

The map is copied into the demo (keep it small: a city is a few MB).
USAGE
  exit 1
}

[ $# -eq 1 ] && [ -f "$1" ] || usage
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAP="$1"
NAME="$(basename "$MAP" .pmtiles)"
[[ "$NAME" =~ ^[A-Za-z0-9_-]{1,60}$ ]] || { echo "Invalid map name: $NAME" >&2; exit 1; }
[ -f "$ROOT/campanile/web/vendor/maplibre-gl.mjs" ] || "$ROOT/scripts/prepare.sh"

OUT="$ROOT/dist/demo"
rm -rf "$OUT"
mkdir -p "$OUT/maps"
cp -R "$ROOT/campanile/web/." "$OUT/"
# Admin and setup only make sense on a real Campanile.
rm -f "$OUT"/admin.* "$OUT"/setup.*
cp "$ROOT/demo/sw.js" "$OUT/demo-sw.js"
cp "$ROOT/demo/start.js" "$OUT/demo-start.js"
cp "$MAP" "$OUT/maps/$NAME.pmtiles"
python3 -I - "$OUT" "$NAME" "$ROOT" <<'PY'
import json, pathlib, sys
out, name, root = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
size = (out / "maps" / f"{name}.pmtiles").stat().st_size
(out / "maps" / "index.json").write_text(json.dumps([{"name": name, "file": f"{name}.pmtiles", "bytes": size}]))
# The map search, read by the Campanile's own code: the demo only searches what it gives.
sys.path.insert(0, str(root / "campanile"))
import places
content = places.read_map(out / "maps" / f"{name}.pmtiles")
index = {
    "synonyms": {word: sorted(kinds) for word, kinds in places.SYNONYMS.items()},
    "maps": [{"map": name, "max_zoom": content["max_zoom"], "rows": content["rows"]}],
}
(out / "maps" / "places.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
tag = '<meta charset="utf-8">'
for page in out.glob("*.html"):
    html = page.read_text(encoding="utf-8")
    if html.count(tag) != 1:
        sys.exit(f"{page.name}: expected one {tag}")
    page.write_text(html.replace(tag, tag + '\n  <script src="/demo-start.js"></script>'), encoding="utf-8")
PY
echo "Done: $OUT ($(du -sh "$OUT" | cut -f1)). Serve it from the root of a domain."
