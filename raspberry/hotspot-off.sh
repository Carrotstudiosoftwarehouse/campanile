#!/usr/bin/env bash
# DEVELOPED BY CARROTSTUDIO software house
# Takes Campanile's hotspot off: the open Wi-Fi first, then its DNS redirect, then its firewall,
# so the Wi-Fi is never up without the firewall. Used by install.sh --no-hotspot and uninstall.sh.
set -euo pipefail

CONNECTION=campanile-hotspot

if command -v nmcli >/dev/null; then
  nmcli connection delete "$CONNECTION" >/dev/null 2>&1 || true
fi
# Also when NetworkManager isn't running: it would bring the Wi-Fi back at the next start.
rm -f "/etc/NetworkManager/system-connections/$CONNECTION.nmconnection"
if command -v nmcli >/dev/null && nmcli -t -f NAME connection show 2>/dev/null | grep -qx "$CONNECTION"; then
  echo "ERROR: the Wi-Fi '$CONNECTION' is still there, so its firewall stays." >&2
  exit 1
fi
rm -f /etc/NetworkManager/dnsmasq-shared.d/campanile.conf

systemctl disable --now campanile-firewall.service 2>/dev/null || true
rm -f /etc/systemd/system/campanile-firewall.service /etc/campanile/firewall.nft
systemctl daemon-reload
