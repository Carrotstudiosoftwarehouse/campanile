# DEVELOPED BY CARROTSTUDIO software house
"""A copy of this Campanile on a USB stick, to start another one without internet.

Only fixed names go: the program, maps, Wikipedia, the trusted public keys and, if downloaded,
kiwix-serve for every computer and Python's installers. Never the database (names, posts,
contacts) or the admin password.

Programs travel only this way, handed over in person: anyone can name a Wi-Fi "Campanile".
The stick itself may be hostile. No link on it is followed, nothing on it is read as
instructions, and we write only inside its Campanile folder, and only into one that holds
nothing but our own files: a file slipped in beforehand would otherwise travel inside a copy
that people start without a second thought.

    python3 campanile/copying.py /media/usb [--data /var/lib/campanile] [--keys FILE]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
FOLDER = "Campanile"  # on the stick
MARKER = ".campanile-copy"  # written first: a folder with it is ours to write into
MANIFEST = "MANIFEST.json"  # written last: without it, the copy is not complete
README = "LEGGIMI - READ ME.txt"
CHUNK = 1 << 20
FAT_LIMIT = 4 * 2**30 - 1  # the largest file FAT32 can hold
MARGIN = 50 * 10**6  # left free on the stick

# The program: these names at the top of its folder, and everything under them.
PROGRAM = (
    "campanile",
    "raspberry",
    "scripts",
    "docs",
    "README.md",
    "README.it.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "ROADMAP.md",
    "pyproject.toml",
    "Avvia Campanile (Windows).bat",
    "Avvia Campanile (Mac).command",
)
ZIM_NAME = re.compile(r"[A-Za-z0-9_.-]+\.zim")
MAP_NAME = re.compile(r"[A-Za-z0-9_-]+\.pmtiles")


class CopyError(Exception):
    """Ends a copy. The key becomes a message on the page (setup.error.<key>)."""

    def __init__(self, key: str, detail: str = ""):
        super().__init__(f"{key}: {detail}" if detail else key)
        self.key = key
        self.detail = detail


@dataclass(frozen=True)
class Drive:
    path: str
    name: str
    filesystem: str


# -- which drives -------------------------------------------------------------------------

LOCAL_FILESYSTEMS = {
    "msdos", "vfat", "fat", "exfat", "ntfs", "ntfs3", "fuseblk", "ext2", "ext3", "ext4",
    "btrfs", "xfs", "hfs", "hfsplus", "apfs",
}  # fmt: skip


def _mac_drives() -> list[Drive]:
    # "/dev/disk4s1 on /Volumes/STICK (msdos, local, nodev, nosuid, ...)"
    out = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=10).stdout
    found = []
    for line in out.splitlines():
        match = re.fullmatch(r"(/dev/\S+) on (/Volumes/.+) \(([^,)]+)(, [^)]*)?\)", line)
        if match and "local" in (match[4] or "") and match[3] in LOCAL_FILESYSTEMS:
            found.append(Drive(match[2], Path(match[2]).name, match[3]))
    return found


def _linux_drives() -> list[Drive]:
    found = []
    with open("/proc/self/mounts", encoding="utf-8", errors="replace") as f:
        for line in f:
            fields = line.split()
            if len(fields) < 3:
                continue
            # Spaces in a mount point are written as \040.
            point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[1])
            if fields[2] in LOCAL_FILESYSTEMS and re.match(r"/(run/)?media/", point):
                found.append(Drive(point, Path(point).name, fields[2]))
    return found


def _windows_drives() -> list[Drive]:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    system = os.environ.get("SYSTEMDRIVE", "C:").upper().rstrip("\\") + "\\"  # in any letter case
    found = []
    mask = kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask >> i & 1:
            continue
        root = f"{chr(65 + i)}:\\"
        kind = kernel32.GetDriveTypeW(root)
        if root == system or kind not in (2, 3):  # removable or fixed; never the network
            continue
        name = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        if kernel32.GetVolumeInformationW(root, name, 261, None, None, None, filesystem, 261):
            found.append(Drive(root, name.value or root, filesystem.value.lower()))
    return found


def _holds(drive: Drive, path: Path) -> bool:
    """Whether path is on that drive."""
    try:
        root, path = Path(drive.path).resolve(), path.resolve()
    except OSError:
        return False
    if os.name == "nt":
        return root.drive.upper() == path.drive.upper()
    return root == path or root in path.parents


def drives() -> list[Drive]:
    """Drives one can copy to: sticks and external disks, never the system, the network, or
    the one this Campanile runs from (a stick is not copied onto itself)."""
    found: list[Drive] = []
    try:
        if sys.platform == "darwin":
            found = _mac_drives()
        elif sys.platform.startswith("linux"):
            found = _linux_drives()
        elif os.name == "nt":
            found = _windows_drives()
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return [drive for drive in found if not _holds(drive, HERE)]


# -- what goes ----------------------------------------------------------------------------


def _regular(path: Path) -> bool:
    """A real file: not a link (to the database, say), not a device or a pipe."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _walk(top: Path):
    """Regular files under top, without ever following a link."""
    if top.is_symlink():
        return
    if _regular(top):
        yield top
        return
    if not top.is_dir():
        return
    for folder, dirs, files in os.walk(top, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        for name in sorted(files):
            path = Path(folder, name)
            if not name.startswith(".") and not name.endswith(".pyc") and _regular(path):
                yield path


def plan(root: Path, data: Path, tools: Path, keys: Path | None, tool_folders, installers):
    """[(source, path on the stick)], from fixed names only.

    tool_folders: {folder name: file names} of the programs to take from tools/;
    installers: file names to take from tools/python/.
    """
    files: list[tuple[Path, str]] = []
    for name in PROGRAM:
        for path in _walk(root / name):
            files.append((path, path.relative_to(root).as_posix()))
    for folder, pattern in (("maps", MAP_NAME), ("zim", ZIM_NAME)):
        source = data / folder
        if source.is_dir() and not source.is_symlink():
            for path in sorted(source.iterdir()):
                if pattern.fullmatch(path.name) and _regular(path):
                    files.append((path, f"data/{folder}/{path.name}"))
    if keys is not None and _regular(keys):
        files.append((keys, "data/trusted-keys.json"))
    for folder, names in sorted(tool_folders.items()):
        for name in names:
            path = tools / folder / name
            if _regular(path) and not (tools / folder).is_symlink():
                files.append((path, f"tools/{folder}/{name}"))
    for name in installers:
        path = tools / "python" / name
        if _regular(path) and not (tools / "python").is_symlink():
            files.append((path, f"tools/python/{name}"))
    return files


# -- writing on the stick -------------------------------------------------------------------


def _is_link(path: Path) -> bool:
    """A symbolic link, or on Windows a junction: anything that leads somewhere else."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    reparse = getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    )
    return stat.S_ISLNK(info.st_mode) or bool(reparse)


def _folder(root: Path, parts: list[str]) -> Path:
    """Creates the folders one by one, refusing any link: a hostile stick can't redirect us."""
    path = root
    for part in parts:
        path = path / part
        if _is_link(path):
            raise CopyError("links", path.name)
        if not path.exists():
            path.mkdir()
        elif not path.is_dir():
            raise CopyError("links", path.name)
    return path


def _target(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if any(p in ("", ".", "..") for p in parts) or relative.startswith("/"):
        raise CopyError("failed", f"bad path {relative}")
    target = _folder(root, parts[:-1]) / parts[-1]
    if _is_link(target):
        raise CopyError("links", target.name)
    return target


def _sha256(path: Path, cancelled=lambda: False) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            if cancelled():
                raise CopyError("cancelled")
            digest.update(chunk)
    return digest.hexdigest()


def _write(source: Path | bytes, target: Path, done=lambda n: None, cancelled=lambda: False):
    """Copies with fsync into a new hidden file, then gives it its name: a half-written file
    never has the real one, and no link is followed. Returns the SHA-256 of what was read."""
    partial = target.with_name(f".{target.name}.partial")
    if _is_link(partial):
        raise CopyError("links", partial.name)
    with contextlib.suppress(FileNotFoundError):
        partial.unlink()
    digest = hashlib.sha256()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        with contextlib.ExitStack() as files:
            out = files.enter_context(os.fdopen(os.open(partial, flags, 0o644), "wb"))
            if isinstance(source, bytes):
                chunks = iter([source])
            else:
                src = files.enter_context(open(source, "rb"))
                chunks = iter(lambda: src.read(CHUNK), b"")
            for chunk in chunks:
                if cancelled():
                    raise CopyError("cancelled")
                digest.update(chunk)
                out.write(chunk)
                done(len(chunk))
            out.flush()
            os.fsync(out.fileno())
        os.replace(partial, target)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise
    return digest.hexdigest()


def _leftover(name: str) -> bool:
    """Files left by us or by the computer, never by a person: half-written copies (ours),
    and what a Mac adds to a folder it has shown (.DS_Store) or to a file it has opened (._)."""
    return (
        name == ".DS_Store"
        or name.startswith("._")
        or (name.startswith(".") and name.endswith(".partial"))
    )


def _survey(root: Path, files: list[tuple[Path, str]]) -> list[Path]:
    """Checks a Campanile folder already on the stick before anything is written; returns the
    leftovers to remove. Anything else that this copy doesn't write stops it: a module, a
    library or a database slipped in there would be used by whoever starts the copy."""
    expected = {MARKER, MANIFEST, README} | {relative for _, relative in files}
    folders = {"/".join(r.split("/")[:k]) for r in expected for k in range(1, r.count("/") + 1)}
    leftovers = []

    def unreadable(error: OSError):  # a folder we can't list could hide anything
        raise error

    for folder, dirs, names in os.walk(root, onerror=unreadable, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(folder, name)
            relative = path.relative_to(root).as_posix()
            if _is_link(path):
                raise CopyError("links", relative)
            mode = os.lstat(path).st_mode
            if stat.S_ISDIR(mode) and relative in folders:
                continue
            if stat.S_ISREG(mode) and relative in expected:
                continue
            if stat.S_ISREG(mode) and _leftover(name):
                leftovers.append(path)
            elif stat.S_ISDIR(mode) and name == "__pycache__" and _only_cache(path):
                leftovers.append(path)  # Python's, if the copy was started from the stick
            else:
                raise CopyError("not_only_ours", relative)
        dirs[:] = [d for d in dirs if Path(folder, d).relative_to(root).as_posix() in folders]
    return leftovers


def _only_cache(folder: Path) -> bool:
    """A __pycache__ with compiled files only: anything else in it is someone's."""
    with os.scandir(folder) as entries:
        return all(
            e.name.endswith(".pyc") and e.is_file(follow_symlinks=False) and not _is_link(Path(e))
            for e in entries
        )


def _remove(leftovers: list[Path]) -> None:
    for path in leftovers:
        if path.name == "__pycache__":
            for compiled in path.iterdir():
                compiled.unlink()
            path.rmdir()
        else:
            path.unlink()


def _explain(error: OSError, name: str) -> CopyError:
    import errno

    if error.errno == errno.ENOSPC:
        return CopyError("stick_full", name)
    if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return CopyError("stick_denied", name)
    if error.errno in (errno.EIO, errno.ENOENT, errno.ENXIO, errno.ENODEV):
        return CopyError("stick_gone", name)
    if error.errno == errno.EFBIG or getattr(error, "winerror", None) == 223:
        return CopyError("fat32", name)
    return CopyError("failed", f"{name}: {error.strerror or error}")


def readme(version: str) -> str:
    return f"""CAMPANILE {version} - copia pronta / ready-made copy

ITALIANO
1. Se il computer non ha Python: apri la cartella tools/python e installalo
   (Windows: python-...-amd64.exe, o -arm64.exe sui computer ARM; spunta
   "Add python.exe to PATH". Mac: il file .pkg).
2. Doppio clic su "Avvia Campanile (Windows)" o "Avvia Campanile (Mac)".
   Su Linux: python3 campanile/launch.py
3. Gli altri si collegano alla stessa Wi-Fi e aprono l'indirizzo che compare.

Questa copia viene dal Campanile di chi te l'ha data: accettala solo di persona.
Non installare mai programmi presi da una rete Wi-Fi: chiunque puo' chiamare
una rete "Campanile".

ENGLISH
1. If the computer has no Python: open the folder tools/python and install it
   (Windows: python-...-amd64.exe, or -arm64.exe on ARM computers; tick
   "Add python.exe to PATH". Mac: the .pkg file).
2. Double-click "Avvia Campanile (Windows)" or "Avvia Campanile (Mac)".
   On Linux: python3 campanile/launch.py
3. The others join the same Wi-Fi and open the address shown.

This copy comes from the Campanile of whoever gave it to you: accept it only in
person. Never install programs taken from a Wi-Fi network: anyone can name a
network "Campanile".
"""


def copy(
    files: list[tuple[Path, str]],
    drive: Drive,
    version: str,
    progress=lambda done, total: None,
    cancelled=lambda: False,
) -> Path:
    """Writes the files into DRIVE/Campanile; returns that folder. Files already there and
    identical are kept. Outside that folder nothing is touched; inside it, only leftovers
    are removed, and a folder holding anything else is refused untouched."""
    total = sum(source.stat().st_size for source, _ in files)
    fat = drive.filesystem in ("msdos", "vfat", "fat", "fat32", "fat16")
    if fat:
        for source, relative in files:
            if source.stat().st_size > FAT_LIMIT:
                raise CopyError("fat32", Path(relative).name)
    base = Path(drive.path)
    root = base / FOLDER
    if _is_link(root):
        raise CopyError("links", FOLDER)
    try:
        ours = root.exists()
        if ours and (not root.is_dir() or _is_link(root / MARKER) or not (root / MARKER).is_file()):
            raise CopyError("not_ours", FOLDER)
        leftovers = _survey(root, files) if ours else []
        needed = total - (_already(files, root) if ours else 0) + MARGIN
        if shutil.disk_usage(base).free < needed:  # before writing anything at all
            raise CopyError("stick_full", f"{needed // 10**6} MB")
        if not ours:
            root.mkdir()
            _write(f"{version}\n".encode(), root / MARKER)
        _remove(leftovers)
        with contextlib.suppress(FileNotFoundError):  # from now on the copy is not complete
            (root / MANIFEST).unlink()
        written = 0
        listed = {}

        def done(n: int) -> None:
            nonlocal written
            written += n
            progress(written, total)

        for source, relative in files:
            target = _target(root, relative)
            size = source.stat().st_size
            if target.is_file() and target.stat().st_size == size:
                digest = _sha256(source, cancelled)
                if _sha256(target, cancelled) == digest:
                    listed[relative] = {"bytes": size, "sha256": digest}
                    done(size)
                    continue
            listed[relative] = {"bytes": size, "sha256": _write(source, target, done, cancelled)}
        _write(readme(version).replace("\n", "\r\n").encode(), root / README)
        manifest = json.dumps(
            {
                "campanile": version,
                "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": listed,
            },
            ensure_ascii=False,
            indent=1,
        )
        _write(manifest.encode(), root / MANIFEST)
    except OSError as e:
        raise _explain(e, getattr(e, "filename", None) or FOLDER) from e
    return root


def _already(files: list[tuple[Path, str]], root: Path) -> int:
    """Bytes already on the stick with the right size: they need no new room."""
    same = 0
    for source, relative in files:
        target = root / relative
        with contextlib.suppress(OSError):
            if not _is_link(target) and target.stat().st_size == source.stat().st_size:
                same += target.stat().st_size
    return same


def check(root: Path) -> list[str]:
    """Program files of a copy that are missing or of the wrong size (fast, at every start).

    Only the program: maps and Wikipedia may rightly change after the copy.
    """
    manifest = root / MANIFEST
    if not manifest.is_file():
        return []
    try:
        files = json.loads(manifest.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return [MANIFEST]
    wrong = []
    for relative, info in files.items():
        if relative.startswith(("data/", "tools/")):
            continue
        path = root / relative
        try:
            if path.stat().st_size != info["bytes"]:
                wrong.append(relative)
        except (OSError, KeyError, TypeError):
            wrong.append(relative)
    return wrong


def main(argv=None) -> int:
    sys.path.insert(0, str(HERE))
    import preparation
    import server

    parser = argparse.ArgumentParser(
        description="Copies this Campanile into DESTINATION/Campanile."
    )
    parser.add_argument("destination", help="the stick, e.g. /media/usb or E:\\")
    parser.add_argument("--data", default=str(HERE.parent / "data"), help="the data folder")
    parser.add_argument("--keys", help="trusted keys file (default: data/trusted-keys.json)")
    a = parser.parse_args(argv)
    data = Path(a.data)
    keys = Path(a.keys) if a.keys else data / "trusted-keys.json"
    tools = HERE.parent / "tools"
    files = plan(
        HERE.parent, data, tools, keys, preparation.tool_folders(), preparation.installer_names()
    )
    destination = Path(a.destination)
    filesystem = next((d.filesystem for d in drives() if Path(d.path) == destination), "")
    last = [0.0]

    def show(done: int, total: int) -> None:
        if time.monotonic() - last[0] > 2 or done == total:
            last[0] = time.monotonic()
            print(
                f"  {done * 100 // max(total, 1)}%  {done // 10**6} of {total // 10**6} MB",
                flush=True,
            )

    try:
        root = copy(
            files, Drive(str(destination), destination.name, filesystem), server.VERSION, show
        )
    except CopyError as e:
        print(f"Not copied: {e}", file=sys.stderr)
        return 1
    print(f"Done: {root} ({len(files)} files). Eject the stick before removing it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
