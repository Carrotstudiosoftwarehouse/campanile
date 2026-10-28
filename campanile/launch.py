# DEVELOPED BY CARROTSTUDIO software house
"""The double click: starts Campanile on a laptop and opens the setup page, or the sign.

The window is read by non-technical people, so its messages stay in Italian.
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

import copying
import firewall
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
        print("  ATTENZIONE: Windows sta bloccando i telefoni, che non possono collegarsi.")
        print("  (Succede se alla domanda di Windows sulle reti si e' premuto Annulla.)")
        print("  Premi INVIO per sistemarlo: Windows ti chiedera' il permesso.")
        input()
        if firewall.allow(blocked):
            print("  Sistemato: ora i telefoni possono collegarsi.")
        else:
            print("  Non e' stato sistemato. Riprova chiudendo e riaprendo il Campanile,")
            print("  e a Windows rispondi Si'.")
        print()


# Why nothing starts: this Campanile would start empty while its data sits elsewhere.
STOPPED = {
    "update_folder_missing": "Questo Campanile e' stato aggiornato: mappe, Wikipedia e annunci\n"
    "  sono nella cartella \"{0}\", che qui accanto non c'e' piu'. Rimettila accanto e riapri.",
    "update_unfinished": "Questo e' un aggiornamento non finito: apri il Campanile dalla cartella\n"
    '  "{0}", che lo finisce da sola.',
    "update_data_twice": 'Ci sono dati sia in "{0}" sia in "{1}": per non perdere niente il\n'
    "  Campanile non parte. Tieni la cartella giusta e sposta altrove l'altra.",
}


def updated(root: Path) -> Path | None:
    """Finishes any update before anything runs. Returns the newer folder to start instead, or
    None; raises UpdateError or OSError when nothing may start."""
    update.adopt(root)
    try:
        return update.resume(root, server.VERSION)
    except release.ReleaseError:
        shutil.rmtree(root / update.STAGING, ignore_errors=True)
        print("  ATTENZIONE: l'aggiornamento preparato non e' piu' quello firmato da CarrotStudio:")
        print("  e' stato scartato. Parte la versione di prima.")
    except update.UpdateError as e:
        if e.args[0] != "update_folder_exists":
            raise
        print(
            f"  L'aggiornamento e' pronto, ma qui accanto c'e' gia' una cartella \"{e.args[1]}\":"
        )
        print("  spostala altrove e riapri il Campanile. Intanto parte la versione di prima.")
    except OSError:
        if (root / update.MOVED).exists():
            raise  # past the point of no return: only forward, at the next start
        print("  L'aggiornamento non e' riuscito: parte la versione di prima.")
    print()
    return None


def main() -> int:
    # Flush every line, even when the output goes to a file: "fixed" must never sit in a buffer.
    sys.stdout.reconfigure(line_buffering=True)
    try:
        newer = updated(server.HERE.parent)
    except update.UpdateError as e:
        print("\n  " + STOPPED[e.args[0]].format(*e.args[1:]) + "\n")
        return 1
    except OSError:
        print("\n  L'aggiornamento non e' finito (un file in uso?). Chiudi le altre finestre e")
        print("  riapri il Campanile: riparte da dove si era fermato. Niente e' perso.\n")
        return 1
    if newer is not None:
        print(f'  Campanile aggiornato: parte dalla cartella "{newer.name}".')
        try:  # the same window, the same Python: only the folder changes
            return subprocess.call([sys.executable, str(newer / "campanile" / "launch.py")])  # noqa: S603
        except KeyboardInterrupt:
            return 0
    if not (server.HERE / "web" / "vendor" / "maplibre-gl.mjs").exists():
        print(
            "Manca la preparazione iniziale. Con internet, esegui una volta:\n"
            "    scripts/prepare.sh"
        )
        return 1

    damaged = copying.check(server.HERE.parent)
    if damaged:
        print("  ATTENZIONE: questa copia del Campanile e' incompleta o danneggiata")
        print(f"  ({len(damaged)} file, per esempio {damaged[0]}).")
        print("  Rifalla dalla chiavetta originale, o chiedi una chiavetta nuova.")
        print()

    password = admin_password()
    ip = server.lan_address()
    print()
    print("  CAMPANILE ACCESO. Lascia aperta questa finestra: chiudendola si spegne.")
    print()
    if ip:
        print(f"  Dagli altri telefoni, collegati alla stessa Wi-Fi:  http://{ip}:{PORT}/")
    else:
        print("  Questo computer non e' collegato a nessuna rete Wi-Fi o via cavo:")
        print("  gli altri dispositivi non possono ancora raggiungerlo.")
    print(f"  Da questo computer:   http://localhost:{PORT}/")
    print(f"  Gestione e avvisi:    http://localhost:{PORT}/admin.html")
    print(f"  Password di gestione: {password}")
    print(f"  Preparazione:         http://localhost:{PORT}/setup.html")
    print(f"  Guida da stampare:    http://localhost:{PORT}/guide.html")
    print()

    threading.Thread(target=watch_firewall, daemon=True).start()

    # The first time there is nothing to show yet: start from getting it ready.
    first_page = "sign.html" if any((DATA / "maps").glob("*.pmtiles")) else "setup.html"
    threading.Timer(1.0, webbrowser.open, [f"http://localhost:{PORT}/{first_page}"]).start()
    try:
        args = ["--host", WHOLE_NETWORK, "--port", str(PORT), "--setup"]
        args += ["--password-file", str(PASSWORD_FILE)]
        if TRUSTED_KEYS.exists():
            args += ["--trusted-keys", str(TRUSTED_KEYS)]
        server.main(args)
    except OSError as e:
        print(f"\n  Impossibile usare la porta {PORT}: forse il Campanile e' gia' acceso. ({e})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
