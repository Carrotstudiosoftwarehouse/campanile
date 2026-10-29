#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Turns a Raspberry Pi (Raspberry Pi OS Bookworm or Trixie) into a Campanile:
# open Wi-Fi hotspot, a portal that opens by itself, services started at boot.
# Safe to run again: it updates without losing data.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage, from the project folder:
  sudo raspberry/install.sh [--ssid NAME] [--country IT] [--no-hotspot]

  --ssid NAME     Wi-Fi network name (default: Campanile)
  --country CC    two-letter country code for the Wi-Fi rules (default: IT)
  --no-hotspot    stay on the existing network, no hotspot and no redirect

Run scripts/prepare.sh first. Maps and Wikipedia in data/ are copied too.
USAGE
}

SSID="Campanile"
COUNTRY="IT"
HOTSPOT=1
ADDRESS="10.42.0.1"
CONNECTION="campanile-hotspot"
INTERFACE="wlan0"

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODE="/opt/campanile"
DATA="/var/lib/campanile"
CONFIG="/etc/campanile"

fail() { echo "ERROR: $*" >&2; exit 1; }
step() { echo; echo "== $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --ssid)       SSID="${2:?missing network name}"; shift 2 ;;
    --country)    COUNTRY="${2:?missing country code}"; shift 2 ;;
    --no-hotspot) HOTSPOT=0; shift ;;
    -h|--help)    usage; exit 0 ;;
    *)            usage; fail "unknown option: $1" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || fail "needs root: sudo $0 $*"
[[ "$SSID" =~ ^[A-Za-z0-9\ _.-]{1,32}$ ]] || fail "invalid network name (1-32 chars: letters, digits, space, . _ -)"
[[ "$COUNTRY" =~ ^[A-Z]{2}$ ]] || fail "invalid country code (two capital letters, e.g. IT)"
[ -f "$SOURCE/campanile/server.py" ] || fail "run this from the Campanile project folder"

if [ "$HOTSPOT" -eq 1 ]; then
  systemctl is-active --quiet NetworkManager \
    || fail "NetworkManager is required (default since Raspberry Pi OS Bookworm). Or use --no-hotspot"
  ip link show "$INTERFACE" >/dev/null 2>&1 || fail "Wi-Fi interface $INTERFACE not found"
  # If you're in over SSH through Wi-Fi, the hotspot would kick you out halfway.
  if [ -n "${SSH_CONNECTION:-}" ]; then
    CLIENT="${SSH_CONNECTION%% *}"
    if grep -q "dev $INTERFACE" <<< "$(ip route get "$CLIENT" 2>/dev/null)"; then
      fail "you're connected over SSH through Wi-Fi: the hotspot would cut you off. Use a cable or the console, then run again."
    fi
  fi
fi

# The map libraries, the first time only: one command less in the guide. As whoever cloned
# the folder, so its files stay theirs, not root's.
if [ ! -f "$SOURCE/campanile/web/vendor/maplibre-gl.mjs" ]; then
  step "Map libraries (first time only)"
  as=()
  [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ] && as=(sudo -u "$SUDO_USER")
  "${as[@]}" "$SOURCE/scripts/prepare.sh" || fail "map libraries not downloaded (the reason is just above)"
fi

step "Packages"
export DEBIAN_FRONTEND=noninteractive
# A Pi just switched on often updates itself for a few minutes: wait for apt, don't fail.
WAIT=(-o DPkg::Lock::Timeout=600)
apt-get "${WAIT[@]}" update -q
apt-get "${WAIT[@]}" install -y -q python3 python3-cryptography kiwix-tools nginx nftables

step "Service user 'campanile'"
if ! id campanile >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin campanile
fi

step "Code in $CODE"
NEW="$(mktemp -d /opt/.campanile-new.XXXXXX)"
trap 'rm -rf "$NEW"' EXIT
cp -R "$SOURCE/campanile" "$SOURCE/raspberry" "$SOURCE/scripts" "$NEW/"
cp "$SOURCE/LICENSE" "$SOURCE/README.md" "$SOURCE/README.it.md" "$NEW/" 2>/dev/null || true
find "$NEW" -name '__pycache__' -prune -exec rm -rf {} +
chown -R root:root "$NEW"
chmod -R u=rwX,go=rX "$NEW"
chmod 755 "$NEW/raspberry/start-kiwix.sh" "$NEW/raspberry/nginx-site.sh"
rm -rf "$CODE.old"
[ -d "$CODE" ] && mv "$CODE" "$CODE.old"
mv "$NEW" "$CODE"
rm -rf "$CODE.old"
trap - EXIT

step "Data in $DATA"
# nginx (www-data) reads the maps, which are public anyway; it can cross the data
# folder but not list it, and the database stays readable by campanile only.
install -d -o campanile -g campanile -m 711 "$DATA"
install -d -o campanile -g campanile -m 755 "$DATA/maps"
install -d -o campanile -g campanile -m 750 "$DATA/zim"
shopt -s nullglob
for f in "$SOURCE"/data/maps/*.pmtiles; do
  [ -e "$DATA/maps/$(basename "$f")" ] || install -o campanile -g campanile -m 644 "$f" "$DATA/maps/"
done
chmod 644 "$DATA"/maps/*.pmtiles 2>/dev/null || true
for f in "$SOURCE"/data/zim/*.zim; do
  [ -e "$DATA/zim/$(basename "$f")" ] || install -o campanile -g campanile -m 640 "$f" "$DATA/zim/"
done
shopt -u nullglob

step "Configuration in $CONFIG"
install -d -o root -g campanile -m 750 "$CONFIG"
# The next update (campanile/update.py) runs this again with the same choices.
{ printf -- '--ssid\n%s\n--country\n%s\n' "$SSID" "$COUNTRY"; [ "$HOTSPOT" -eq 1 ] || echo --no-hotspot; } \
  > "$CONFIG/install-options"
chmod 600 "$CONFIG/install-options"
HOSTNAME_LOCAL="$(hostname).local"
# Without a hotspot we're guests on someone else's network: no redirects.
PORTAL=""
[ "$HOTSPOT" -eq 1 ] && PORTAL="$ADDRESS"
PUBLIC_URL="http://${PORTAL:-$HOSTNAME_LOCAL}/"
cat > "$CONFIG/campanile.env" <<ENV
CAMPANILE_PUBLIC_URL=$PUBLIC_URL
CAMPANILE_HOSTNAME=$HOSTNAME_LOCAL
ENV
chmod 640 "$CONFIG/campanile.env"
chgrp campanile "$CONFIG/campanile.env"
NEW_PASSWORD=""
if [ ! -s "$CONFIG/password" ]; then
  # -I: Python's own modules only, never a secrets.py in the folder this runs from.
  NEW_PASSWORD="$(python3 -I -c 'import secrets; print(secrets.token_urlsafe(12))')"
  ( umask 027; printf '%s\n' "$NEW_PASSWORD" > "$CONFIG/password" )
  chgrp campanile "$CONFIG/password"
fi

# Public keys of the authorities allowed to sign notices. Empty until you add one (docs/ADMIN.md).
if [ ! -f "$CONFIG/trusted-keys.json" ]; then
  printf '{"keys": []}\n' > "$CONFIG/trusted-keys.json"
fi
chmod 640 "$CONFIG/trusted-keys.json"
chgrp campanile "$CONFIG/trusted-keys.json"

step "Web server (nginx)"
"$CODE/raspberry/nginx-site.sh" "$PORTAL" "$HOSTNAME_LOCAL" > /etc/nginx/sites-available/campanile
ln -sf /etc/nginx/sites-available/campanile /etc/nginx/sites-enabled/campanile
# Debian's default site also wants port 80. Remember we turned it off, to restore it on uninstall.
if [ -e /etc/nginx/sites-enabled/default ]; then
  rm /etc/nginx/sites-enabled/default
  touch "$CONFIG/nginx-default-was-enabled"
fi
nginx -t -q || fail "the nginx configuration is not valid"
systemctl enable nginx.service >/dev/null
systemctl reload-or-restart nginx.service

step "Services"
install -m 644 "$CODE/raspberry/campanile.service" /etc/systemd/system/campanile.service
install -m 644 "$CODE/raspberry/campanile-kiwix.service" /etc/systemd/system/campanile-kiwix.service
systemctl daemon-reload
systemctl enable campanile.service campanile-kiwix.service
systemctl restart campanile.service campanile-kiwix.service
python3 -I - <<'WAIT' || fail "Campanile isn't answering. To see why: journalctl -u campanile"
import time, urllib.request
for _ in range(40):
    try:
        urllib.request.urlopen("http://127.0.0.1/api/status", timeout=1)
        raise SystemExit(0)
    except OSError:
        time.sleep(0.5)
raise SystemExit(1)
WAIT
echo "Campanile is answering."

step "Firewall"
if [ "$HOTSPOT" -eq 1 ]; then
  sed "s/@IFACE@/$INTERFACE/g" "$CODE/raspberry/firewall.nft" > "$CONFIG/firewall.nft"
  install -m 644 "$CODE/raspberry/campanile-firewall.service" /etc/systemd/system/campanile-firewall.service
  systemctl daemon-reload
  systemctl enable campanile-firewall.service >/dev/null
  systemctl restart campanile-firewall.service
  echo "Phones on the hotspot reach only DHCP, DNS and Campanile."
else
  # Switching from hotspot to --no-hotspot: our firewall would only get in the way.
  systemctl disable --now campanile-firewall.service 2>/dev/null || true
  rm -f /etc/systemd/system/campanile-firewall.service "$CONFIG/firewall.nft"
  echo "No hotspot: no firewall changes."
fi

if [ "$HOTSPOT" -eq 1 ]; then
  step "Wi-Fi hotspot '$SSID' on $ADDRESS"
  if command -v raspi-config >/dev/null; then
    raspi-config nonint do_wifi_country "$COUNTRY"
  fi
  rfkill unblock wifi 2>/dev/null || true

  # Whatever site a phone looks up, Campanile answers: that's how phones
  # open the portal by themselves as soon as they connect.
  install -d -m 755 /etc/NetworkManager/dnsmasq-shared.d
  cat > /etc/NetworkManager/dnsmasq-shared.d/campanile.conf <<DNS
address=/#/$ADDRESS
dhcp-option=114,http://$ADDRESS/
DNS

  # ap-isolation: phones can't talk to each other directly, so one can't pose as the
  # router or the DNS server for the others. They still all reach the Campanile.
  nmcli connection delete "$CONNECTION" >/dev/null 2>&1 || true
  nmcli connection add type wifi ifname "$INTERFACE" con-name "$CONNECTION" \
    autoconnect yes connection.autoconnect-priority 100 ssid "$SSID" \
    802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
    ipv4.method shared ipv4.addresses "$ADDRESS/24" ipv6.method disabled \
    802-11-wireless.ap-isolation yes
  nmcli connection up "$CONNECTION"
fi

step "Done"
if [ "$HOTSPOT" -eq 1 ]; then
  echo "Portal:  http://$ADDRESS/   (or http://$HOSTNAME_LOCAL/)"
  echo "Open Wi-Fi network: $SSID"
else
  echo "Portal:  http://$HOSTNAME_LOCAL/"
fi
if [ -n "$NEW_PASSWORD" ]; then
  echo
  echo "Admin password (page /admin.html). Write it down now:"
  echo "    $NEW_PASSWORD"
  echo "Stored in $CONFIG/password (readable by root and the campanile service)."
fi
echo
echo "Service status:  systemctl status campanile campanile-kiwix"
