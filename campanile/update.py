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
MOVED = ".campanile-moved"  # in the old folder, written first: the update's point of no return
FROM = ".campanile-from"  # in the new folder until it holds everything: the old folder's name
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


def resume(root: Path, installed: str) -> Path | None:
    """At start, in the old folder, before anything runs: applies a prepared update, or finishes
    one that a power cut stopped. Returns the folder to start instead of this one, or None.

    Like a database journal: the note in the old folder is written first, then everything only
    moves forward, so a Campanile never starts empty while its data sits elsewhere."""
    staged = root / STAGING / copying.FOLDER
    name = _note(root, MOVED)
    checked = False
    if name is None:
        if not staged.is_dir():
            return None
        version = release.check(staged, newer_than=installed)  # again: it sat on the disk
        name, checked = f"Campanile {version}", True
        if (root.parent / name).exists():
            raise UpdateError("update_folder_exists", name)
        _write_note(staged, FROM, root.name)
        _write_note(root, MOVED, name)  # the point of no return
    target = root.parent / name
    if not target.exists() and staged.is_dir():
        if not checked:  # stopped right after the point of no return: once more
            try:
                release.check(staged, newer_than=installed)
            except release.ReleaseError:
                (root / MOVED).unlink()  # nothing has moved yet: as if never started
                raise
        staged.rename(target)
    if not (target / "campanile" / "launch.py").is_file():
        raise UpdateError("update_folder_missing", name)  # the data may be there
    _move_into(root, target)
    return target


def adopt(root: Path) -> None:
    """At start, in the new folder: opened before the old one, it finishes the move itself."""
    old_name = _note(root, FROM)
    if old_name is None:
        return
    old = root.parent / old_name
    if _note(old, MOVED) != root.name:
        raise UpdateError("update_unfinished", old_name)
    _move_into(old, root)


def _move_into(old: Path, new: Path) -> None:
    """Data and tools into the new folder. Run again after a power cut, it finishes the job."""
    for name in CARRIED:
        if (old / name).exists():
            if (new / name).exists():
                raise UpdateError("update_data_twice", old.name, new.name)  # never merged
            (old / name).rename(new / name)
    with contextlib.suppress(FileNotFoundError):
        (new / FROM).unlink()
    shutil.rmtree(old / STAGING, ignore_errors=True)


def _note(folder: Path, note: str) -> str | None:
    """The folder name in a note, only if it is a folder right next to this one."""
    try:
        name = (folder / note).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return name if name not in ("", ".", "..") and Path(name).name == name else None


def _write_note(folder: Path, note: str, name: str) -> None:
    """Whole or not at all, even if the power goes in the middle."""
    part = folder / f"{note}.part"
    with open(part, "w", encoding="utf-8") as f:
        f.write(name + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(part, folder / note)


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
