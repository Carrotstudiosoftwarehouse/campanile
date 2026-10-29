# DEVELOPED BY CARROTSTUDIO software house
"""The double click: starts Campanile on a laptop and opens the setup page, or the sign.

The window is read by non-technical people: it speaks the computer's language.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import api
import copying
import firewall
import messages
import preparation
import release
import server
import update

PORT = 8080
KIWIX_PORT = 8081  # server.py's default, where kiwix-serve listens on the laptop
WHOLE_NETWORK = "0.0.0.0"  # noqa: S104 (here we do want to be found)
DATA = server.HERE.parent / "data"
PASSWORD_FILE = DATA / "admin-password.txt"
TRUSTED_KEYS = DATA / "trusted-keys.json"  # optional: enables signed notices
LANG = messages.computer_language()
NINE_ONE_ONE = ("US", "CA")  # where people call 911; elsewhere 112, and the admin page changes it


def say(key: str, *values) -> None:
    print("  " + messages.window(key, LANG, *values))


def admin_password() -> str:
    if not PASSWORD_FILE.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        PASSWORD_FILE.write_text(secrets.token_urlsafe(12) + "\n", encoding="utf-8")
        os.chmod(PASSWORD_FILE, 0o600)
    return PASSWORD_FILE.read_text(encoding="utf-8").strip()


FIREWALL_CHECK_EVERY = 60  # Windows' question may still be open: give the person time


def programs_listening() -> list[tuple[str, int]]:
    """Python on its port, and kiwix-serve on Wikipedia's once the setup page installed it."""
    kiwix = preparation.Preparation(DATA, server.HERE.parent / "tools").kiwix_program()
    return [(sys.executable, PORT)] + ([(str(kiwix), KIWIX_PORT)] if kiwix else [])


def watch_firewall() -> None:
    """On Windows: if the firewall blocks the phones, say so and offer to fix it."""
    if firewall.blocks(sys.executable) is None:
        return  # not Windows, or no way to tell
    while True:
        time.sleep(FIREWALL_CHECK_EVERY)
        blocked = [(p, port) for p, port in programs_listening() if firewall.blocks(p)]
        if not blocked:
            continue
        print()
        say("firewall_blocked")
        input()
        say("firewall_fixed" if firewall.allow(blocked) else "firewall_not_fixed")
        print()


# Why nothing starts: this Campanile would start empty while its data sits elsewhere.
STOPPED = ("update_folder_missing", "update_unfinished", "update_data_twice")


def updated(root: Path) -> Path | None:
    """Finishes any update before anything runs. Returns the newer folder to start instead, or
    None; raises UpdateError or OSError when nothing may start."""
    update.adopt(root)
    try:
        return update.resume(root, server.VERSION)
    except release.ReleaseError:
        shutil.rmtree(root / update.STAGING, ignore_errors=True)
        say("update_discarded")
    except update.UpdateError as e:
        if e.args[0] != "update_folder_exists":
            raise
        say("update_folder_exists", e.args[1])
    except OSError:
        if (root / update.MOVED).exists():
            raise  # past the point of no return: only forward, at the next start
        say("update_failed")
    print()
    return None


def server_args() -> list[str]:
    args = ["--host", WHOLE_NETWORK, "--port", str(PORT), "--setup"]
    args += ["--password-file", str(PASSWORD_FILE)]
    if messages.computer_region() in NINE_ONE_ONE:
        args += ["--emergency-number", "911"]
    if TRUSTED_KEYS.exists():
        args += ["--trusted-keys", str(TRUSTED_KEYS)]
    return args


def main() -> int:
    # Flush every line, even when the output goes to a file: "fixed" must never sit in a buffer.
    sys.stdout.reconfigure(line_buffering=True)
    try:
        newer = updated(server.HERE.parent)
    except update.UpdateError as e:
        print()
        say(e.args[0], *e.args[1:])
        print()
        return 1
    except OSError:
        print()
        say("update_locked")
        print()
        return 1
    if newer is not None:
        say("updated", newer.name)
        try:  # the same window, the same Python: only the folder changes
            return subprocess.call([sys.executable, str(newer / "campanile" / "launch.py")])  # noqa: S603
        except KeyboardInterrupt:
            return 0
    if not (server.HERE / "web" / "vendor" / "maplibre-gl.mjs").exists():
        say("not_prepared")
        return 1

    damaged = copying.check(server.HERE.parent)
    if damaged:
        say("damaged", len(damaged), damaged[0])
        print()

    password = admin_password()
    ip = api.lan_address()
    print()
    say("on")
    print()
    if ip:
        say("phones", f"http://{ip}:{PORT}/")
    else:
        say("no_network")
    here = f"http://localhost:{PORT}/"
    lines = [
        ("here", here),
        ("admin", here + "admin.html"),
        ("password", password),
        ("setup", here + "setup.html"),
        ("guide", here + "guide.html"),
    ]
    width = max(len(messages.window(key, LANG)) for key, _ in lines)
    for key, value in lines:
        print(f"  {messages.window(key, LANG):<{width}} {value}")
    print()

    threading.Thread(target=watch_firewall, daemon=True).start()

    # The first time there is nothing to show yet: start from getting it ready.
    first_page = "sign.html" if any((DATA / "maps").glob("*.pmtiles")) else "setup.html"
    threading.Timer(1.0, webbrowser.open, [f"http://localhost:{PORT}/{first_page}"]).start()
    try:
        server.main(server_args())
    except OSError as e:
        print()
        say("port_busy", PORT, e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
