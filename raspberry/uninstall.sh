#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Undoes raspberry/install.sh. Keeps data and password unless --purge is given.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  sudo raspberry/uninstall.sh [--purge]

Removes the Campanile services, the hotspot with its firewall and DNS redirect, and
/opt/campanile.
By default the data (/var/lib/campanile) and the admin password (/etc/campanile) are kept,
so a later install picks up where you left off.

  --purge   also delete the data, the password and the 'campanile' user

If you're connected through the Campanile hotspot, you'll be disconnected.
The packages and the Wi-Fi country stay. nginx is stopped if it came with Campanile;
otherwise Debian's default site is back.
USAGE
}

PURGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --purge)   PURGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)         usage; echo "ERROR: unknown option: $1" >&2; exit 1 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "ERROR: needs root: sudo $0" >&2; exit 1; }

step() { echo; echo "== $*"; }

step "Hotspot, DNS redirect and firewall"
bash "$(dirname "$0")/hotspot-off.sh"  # bash: a copy from a stick has no exec bits

step "Services"
systemctl disable --now campanile.service campanile-kiwix.service 2>/dev/null || true
rm -f /etc/systemd/system/campanile.service /etc/systemd/system/campanile-kiwix.service
systemctl daemon-reload

step "Web server (nginx)"
rm -f /etc/nginx/sites-enabled/campanile /etc/nginx/sites-available/campanile
if [ -e /etc/campanile/nginx-default-was-enabled ] && [ -e /etc/nginx/sites-available/default ]; then
  ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
  rm -f /etc/campanile/nginx-default-was-enabled
fi
if [ -e /etc/campanile/nginx-came-with-campanile ]; then
  # Installed for Campanile: no web server is left answering on port 80.
  systemctl disable --now nginx.service 2>/dev/null || true
  echo "nginx came with Campanile: stopped. The package stays (sudo apt purge nginx)."
elif command -v nginx >/dev/null && nginx -t -q 2>/dev/null; then
  # restart, not reload: reload is asynchronous and old workers would keep serving for a moment
  systemctl restart nginx.service 2>/dev/null || true
fi

step "Code"
rm -rf /opt/campanile

if [ "$PURGE" -eq 1 ]; then
  step "Data, password and user"
  rm -rf /var/lib/campanile /etc/campanile
  if id campanile >/dev/null 2>&1; then
    userdel campanile
  fi
  echo "Campanile removed, data and password too."
else
  echo
  echo "Kept: /var/lib/campanile (data) and /etc/campanile (password)."
  echo "To remove them too: sudo raspberry/uninstall.sh --purge"
fi
echo "Not removed: the packages kiwix-tools, nginx, nftables and python3-cryptography, the"
echo "Wi-Fi country, and the folder you installed from."
