#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Starts kiwix-serve with every ZIM file found. With none it exits cleanly:
# after adding one, `sudo systemctl restart campanile-kiwix`.
set -euo pipefail
shopt -s nullglob

FOLDER="${CAMPANILE_ZIM:-/var/lib/campanile/zim}"
FILES=("$FOLDER"/*.zim)

if [ ${#FILES[@]} -eq 0 ]; then
  echo "No ZIM files in $FOLDER: offline Wikipedia is off."
  exit 0
fi

# Only nginx talks to it; phones reach it on port 8081.
exec kiwix-serve --address 127.0.0.1 --port 8082 --blockexternal "${FILES[@]}"
