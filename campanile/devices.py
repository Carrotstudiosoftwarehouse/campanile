# DEVELOPED BY CARROTSTUDIO software house
"""Telling phones apart without recording who they are.

Per-IP limits are easy to dodge: on the hotspot anyone can take dozens of addresses. Changing
the MAC address means leaving and rejoining the Wi-Fi, and the Raspberry reads it from the
kernel's neighbour table.

Posts carry only a short tag, made with a random key that lives in memory and changes every
day: it groups one attacker's posts for cleanup, but can't be traced back to a phone or
linked to the previous day's tags.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

ARP_TABLE = Path("/proc/net/arp")
_COMPLETE = 0x2
_NO_MAC = "00:00:00:00:00:00"


def mac_for(ip: str, table: Path = ARP_TABLE) -> str | None:
    """The MAC address of a neighbour, or None (not Linux, not on the same Wi-Fi, incomplete)."""
    try:
        lines = table.read_text(encoding="ascii", errors="replace").splitlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) < 4 or fields[0] != ip:
            continue
        try:
            complete = int(fields[2], 16) & _COMPLETE
        except ValueError:
            continue
        if complete and fields[3] != _NO_MAC:
            return fields[3].lower()
    return None


class DeviceTags:
    def __init__(self, arp_table: Path = ARP_TABLE, today: Callable[[], str] | None = None):
        self.arp_table = arp_table
        self._today = today or (lambda: time.strftime("%Y-%m-%d"))
        self._day: str | None = None
        self._key = b""
        self._lock = threading.Lock()

    def tag(self, ip: str) -> str:
        identity = mac_for(ip, self.arp_table) or ip
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._key = day, secrets.token_bytes(32)
            key = self._key
        return hmac.new(key, identity.encode(), hashlib.sha256).hexdigest()[:12]
