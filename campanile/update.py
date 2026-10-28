# DEVELOPED BY CARROTSTUDIO software house
"""Updating this Campanile from a USB stick, only to a newer version signed by CarrotStudio.

The stick's program is first copied next to this Campanile and checked there, not on the
stick, which can still change after the check.

Laptop: the setup page prepares the update. At the next start, before anything runs, it is
checked again and becomes a folder of its own, "Campanile 0.2.0", with maps, Wikipedia, the
database and the tools moved into it: moved, not copied, so it is instant and nothing is left
half-written. The old double click hands over to the new folder.

Raspberry, from the installed code (never the stick's):
    sudo python3 /opt/campanile/campanile/update.py /media/USER/STICK
The stick is checked the same way, then the new version's own installer runs.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import copying
import messages
import release

STAGING = ".campanile-update"  # inside this Campanile's folder
MOVED = ".campanile-moved"  # left in the old folder: the name of the one that replaced it
CARRIED = ("data", "tools")  # what the new version takes over
INSTALL_OPTIONS = Path("/etc/campanile/install-options")  # saved by raspberry/install.sh
PLACE = Path("/opt")  # Raspberry: the update is checked here, owned by root, before installing


class UpdateError(Exception):
    """args[0] is a key of messages.MESSAGES."""


def find_program(drive: Path) -> Path | None:
    """The Campanile on a stick: our own copy, or one unzipped release package."""
    found = [drive / copying.FOLDER, *sorted(drive.glob("campanile-*"))]
    found = [f for f in found if not f.is_symlink() and (f / "campanile" / "server.py").is_file()]
    return found[0] if len(found) == 1 or (found and found[0].name == copying.FOLDER) else None


def stage(
    source: Path,
    place: Path,
    installed: str,
    progress=lambda done, total: None,
    cancelled=lambda: False,
) -> tuple[Path, str]:
    """Copies the program in source into place/Campanile and checks it there.

    Returns (that folder, its version); a copy that fails the check is removed."""
    place.mkdir(exist_ok=True)
    folder = copying.copy(
        copying.program_files(source),
        copying.Drive(str(place), "update", ""),
        _declared_version(source) or installed,  # only for the read-me: the signature decides
        progress,
        cancelled,
    )
    try:
        return folder, release.check(folder, newer_than=installed)
    except release.ReleaseError:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _declared_version(source: Path) -> str | None:
    try:
        text = (source / "campanile" / "server.py").read_text(encoding="utf-8")
        version = re.search(r'^VERSION = "(.+?)"', text, re.M)[1]
        release.version_number(version)
    except (OSError, UnicodeDecodeError, TypeError, release.ReleaseError):
        return None
    return version


def apply_pending(root: Path, installed: str) -> Path | None:
    """At start, before anything runs: a prepared update becomes its own folder, and takes
    over data and tools. Returns that folder, or None if nothing was prepared."""
    staged = root / STAGING / copying.FOLDER
    if not staged.is_dir():
        return None
    version = release.check(staged, newer_than=installed)  # again: it sat on the disk meanwhile
    target = root.parent / f"Campanile {version}"
    if target.exists():
        raise UpdateError("update_folder_exists")
    staged.rename(target)
    moved = []
    try:
        for name in CARRIED:
            if (root / name).exists():
                (root / name).rename(target / name)
                moved.append(name)
        (root / MOVED).write_text(target.name + "\n", encoding="utf-8")
    except OSError:
        for name in reversed(moved):  # put everything back as it was
            (target / name).rename(root / name)
        target.rename(staged)
        raise
    shutil.rmtree(root / STAGING, ignore_errors=True)
    return target


def successor(root: Path) -> Path | None:
    """The folder that replaced this Campanile, if it was updated."""
    try:
        name = (root / MOVED).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    folder = root.parent / name
    if Path(name).name != name or name in ("", ".", ".."):
        return None  # only a folder right next to this one
    return folder if (folder / "campanile" / "launch.py").is_file() else None


def main(argv=None) -> int:
    """Raspberry: checks a stick, then runs its installer, with the options of last time."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: sudo python3 /opt/campanile/campanile/update.py STICK")
        return 2
    if getattr(os, "geteuid", lambda: -1)() != 0:  # and never on Windows: Raspberry only
        print("Needs root: sudo python3 /opt/campanile/campanile/update.py STICK")
        return 1
    import server  # only here: the version of the installed code

    source = find_program(Path(args[0]))
    if source is None:
        print(messages.text("update_no_program"))
        return 1
    options = []
    with contextlib.suppress(OSError):
        options = INSTALL_OPTIONS.read_text(encoding="utf-8").splitlines()
    with tempfile.TemporaryDirectory(dir=PLACE, prefix=".campanile-update.") as place:
        try:
            folder, version = stage(source, Path(place), server.VERSION)
        except release.ReleaseError as e:
            print(messages.text(e.args[0]))
            return 1
        except copying.CopyError as e:
            print(f"{e.key}: {e.detail}")
            return 1
        print(f"Campanile {version}, firmato da CarrotStudio: lo installo.")
        installer = ["bash", str(folder / "raspberry" / "install.sh"), *options]
        return subprocess.call(installer)  # noqa: S603 (the signed installer just checked)


if __name__ == "__main__":
    sys.exit(main())
