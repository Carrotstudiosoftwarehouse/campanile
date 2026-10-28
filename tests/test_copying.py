# DEVELOPED BY CARROTSTUDIO software house
"""Copies on a USB stick: what goes, what never goes, and sticks prepared by someone hostile."""

import errno
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import copying

TOOLS = {"kiwix-tools_test": ("kiwix-serve", "helper.dll")}
INSTALLERS = ("python-9.9.9-amd64.exe",)
SECRETS = ("campanile.db", "campanile.db-wal", "admin-password.txt", "places/area.json")
LINKS = os.name != "nt"  # creating links on Windows needs a privilege the CI may not have


def write(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class CopyCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.root, self.outside = tmp / "program", tmp / "outside"
        self.data, self.tools = self.root / "data", self.root / "tools"
        self.outside.mkdir()
        r = self.root
        for name in (
            "campanile/server.py",
            "campanile/web/index.html",
            "campanile/web/vendor/m.js",
            "scripts/prepare.sh",
            "raspberry/install.sh",
            "docs/PROVE.md",
            "README.md",
            "LICENSE",
            "Avvia Campanile (Windows).bat",
            "Avvia Campanile (Mac).command",
        ):
            write(r / name, f"content of {name}".encode())
        # Never part of a copy:
        for name in (
            "campanile/__pycache__/server.cpython-313.pyc",
            "campanile/.hidden",
            "tests/test_x.py",
            ".git/config",
            "dist/old.zip",
            "campanile/web/x.pyc",
        ):
            write(r / name)
        write(self.data / "maps" / "area.pmtiles", os.urandom(300_000))
        write(self.data / "maps" / ".area.pmtiles.partial")
        write(self.data / "maps" / "notes.txt")
        write(self.data / "zim" / "wikipedia_it_medicine_maxi_2026-10.zim", os.urandom(200_000))
        write(self.data / "zim" / ".wikipedia_en.zim.partial")
        write(self.data / "trusted-keys.json", b'{"keys": []}')
        for secret in SECRETS:
            write(self.data / secret, b"SECRET")
        write(self.tools / "kiwix-tools_test" / "kiwix-serve", b"program")
        write(self.tools / "kiwix-tools_test" / "helper.dll", b"library")
        write(self.tools / "kiwix-tools_test" / "unexpected.exe", b"not in the table")
        write(self.tools / "go-pmtiles_test" / "pmtiles", b"not needed offline")
        write(self.tools / "python" / INSTALLERS[0], b"installer")
        write(self.tools / "python" / "evil.exe", b"not in the table")
        self.stick = tmp / "stick"
        self.stick.mkdir()
        self.drive = copying.Drive(str(self.stick), "STICK", "exfat")

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self):
        keys = self.data / "trusted-keys.json"
        return copying.plan(self.root, self.data, self.tools, keys, TOOLS, INSTALLERS)

    def copy(self, **options):
        return copying.copy(self.plan(), self.drive, "9.9", **options)

    def link(self, link: Path, target: Path):
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)


class TestWhatGoes(CopyCase):
    def test_exactly_the_program_maps_wikipedia_keys_and_tools(self):
        self.assertEqual(
            sorted(relative for _, relative in self.plan()),
            sorted([
                "Avvia Campanile (Mac).command", "Avvia Campanile (Windows).bat", "LICENSE",
                "README.md", "campanile/server.py", "campanile/web/index.html",
                "campanile/web/vendor/m.js", "data/maps/area.pmtiles",
                "data/trusted-keys.json", "data/zim/wikipedia_it_medicine_maxi_2026-10.zim",
                "docs/PROVE.md", "raspberry/install.sh", "scripts/prepare.sh",
                "tools/kiwix-tools_test/helper.dll", "tools/kiwix-tools_test/kiwix-serve",
                f"tools/python/{INSTALLERS[0]}",
            ]),
        )  # fmt: skip

    def test_the_database_and_the_password_never_reach_the_stick(self):
        root = self.copy()
        for path in root.rglob("*"):
            if path.is_file():
                self.assertNotEqual(path.read_bytes(), b"SECRET", path)

    @unittest.skipUnless(LINKS, "links")
    def test_links_are_never_followed(self):
        # A "map" that is really the database, and a page that is really a system file.
        self.link(self.data / "maps" / "stolen.pmtiles", self.data / "campanile.db")
        self.link(self.root / "campanile" / "web" / "passwd.js", Path("/etc/passwd"))
        self.link(self.root / "docs" / "secrets", self.data)  # a whole folder
        self.link(self.tools / "python" / "python-9.9.9-arm64.exe", self.data / "campanile.db")
        names = [relative for _, relative in self.plan()]
        for name in names:
            self.assertNotIn("stolen", name)
            self.assertNotIn("passwd", name)
            self.assertNotIn("secrets", name)
        root = self.copy()
        self.assertFalse(any(p.read_bytes() == b"SECRET" for p in root.rglob("*") if p.is_file()))


class TestCopy(CopyCase):
    def test_complete_and_identical(self):
        root = self.copy()
        self.assertEqual(root, self.stick / "Campanile")
        manifest = json.loads((root / copying.MANIFEST).read_text(encoding="utf-8"))
        self.assertEqual(manifest["campanile"], "9.9")
        for source, relative in self.plan():
            copied = root / relative
            self.assertEqual(copied.read_bytes(), source.read_bytes(), relative)
            sha = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(
                manifest["files"][relative], {"bytes": source.stat().st_size, "sha256": sha}
            )
        self.assertEqual(sorted(manifest["files"]), sorted(r for _, r in self.plan()))
        readme = (root / copying.README).read_bytes()
        self.assertIn(b"\r\n", readme)  # Notepad on an old Windows shows it right
        self.assertIn(b"tools/python", readme)
        self.assertFalse(list(root.rglob("*.partial")))

    def test_copying_again_rewrites_only_what_changed(self):
        root = self.copy()
        kept, changed = root / "LICENSE", root / "README.md"
        old = 1_000_000_000 * 10**9  # whole seconds: every filesystem keeps it exactly
        os.utime(kept, ns=(old, old))
        changed.write_bytes(b"x" * changed.stat().st_size)  # same size, other content
        self.copy()
        self.assertEqual(kept.stat().st_mtime_ns, old)  # not written again
        self.assertEqual(changed.read_bytes(), (self.root / "README.md").read_bytes())

    def test_an_interrupted_copy_is_incomplete_and_resumes(self):
        calls = 0

        def cancelled():
            nonlocal calls
            calls += 1
            return calls > 6

        with self.assertRaises(copying.CopyError) as e:
            self.copy(cancelled=cancelled)
        self.assertEqual(e.exception.key, "cancelled")
        root = self.stick / "Campanile"
        self.assertFalse((root / copying.MANIFEST).exists())  # not complete: nothing claims it is
        self.assertFalse(list(root.rglob("*.partial")))
        self.copy()
        self.assertTrue((root / copying.MANIFEST).exists())

    def test_a_folder_with_files_that_arent_ours_is_refused_untouched(self):
        root = self.copy()
        mine = write(root / "data" / "maps" / "mine.pmtiles", b"someone's own map")
        notes = write(root / "notes.txt", b"notes")
        with self.assertRaises(copying.CopyError) as e:
            self.copy()
        self.assertEqual(e.exception.key, "not_only_ours")
        self.assertEqual((mine.read_bytes(), notes.read_bytes()), (b"someone's own map", b"notes"))
        self.assertTrue((root / copying.MANIFEST).exists())  # the copy there stays as it was

    def test_a_campanile_folder_that_isnt_ours_is_left_alone(self):
        theirs = write(self.stick / "Campanile" / "README.md", b"their own file")
        with self.assertRaises(copying.CopyError) as e:
            self.copy()
        self.assertEqual(e.exception.key, "not_ours")
        self.assertEqual(theirs.read_bytes(), b"their own file")

    def test_a_full_stick_is_said_before_writing_anything(self):
        with mock.patch.object(copying.shutil, "disk_usage") as usage:
            usage.return_value.free = 10
            with self.assertRaises(copying.CopyError) as e:
                self.copy()
        self.assertEqual(e.exception.key, "stick_full")
        self.assertEqual(list(self.stick.iterdir()), [])

    def test_fat32_cannot_hold_a_file_over_4_gb(self):
        fat = copying.Drive(str(self.stick), "STICK", "msdos")
        with (
            mock.patch.object(copying, "FAT_LIMIT", 250_000),
            self.assertRaises(copying.CopyError) as e,
        ):
            copying.copy(self.plan(), fat, "9.9")
        self.assertEqual((e.exception.key, e.exception.detail), ("fat32", "area.pmtiles"))
        self.assertEqual(list(self.stick.iterdir()), [])

    def test_errors_are_said_in_words(self):
        cases = {
            errno.ENOSPC: "stick_full", errno.EACCES: "stick_denied", errno.EROFS: "stick_denied",
            errno.EIO: "stick_gone", errno.ENOENT: "stick_gone", errno.EFBIG: "fat32",
        }  # fmt: skip
        for number, key in cases.items():
            self.assertEqual(copying._explain(OSError(number, "x"), "f").key, key)
        windows_too_big = OSError(22, "x")
        windows_too_big.winerror = 223
        self.assertEqual(copying._explain(windows_too_big, "f").key, "fat32")


@unittest.skipUnless(LINKS, "links")
class TestHostileStick(CopyCase):
    """A stick can be prepared by someone hostile: it must not make us write anywhere else."""

    def victim(self) -> Path:
        return write(self.outside / "victim.txt", b"untouched")

    def assert_refused(self):
        with self.assertRaises(copying.CopyError) as e:
            self.copy()
        self.assertEqual(e.exception.key, "links")
        self.assertEqual((self.outside / "victim.txt").read_bytes(), b"untouched")
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["victim.txt"])

    def test_the_campanile_folder_is_a_link(self):
        self.victim()
        self.link(self.stick / "Campanile", self.outside)
        self.assert_refused()

    def test_a_folder_inside_is_a_link(self):
        self.victim()
        self.copy()  # a real copy, then a folder in it replaced by a link
        root = self.stick / "Campanile"
        for path in sorted((root / "campanile").rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        (root / "campanile").rmdir()
        self.link(root / "campanile", self.outside)
        self.assert_refused()

    def test_a_file_is_a_link(self):
        self.victim()
        self.copy()
        root = self.stick / "Campanile"
        (root / "LICENSE").unlink()
        self.link(root / "LICENSE", self.outside / "victim.txt")
        self.assert_refused()

    def test_a_half_written_file_is_a_link(self):
        self.victim()
        self.copy()
        root = self.stick / "Campanile"
        (root / "README.md").write_bytes(b"changed")  # so it is written again
        self.link(root / ".README.md.partial", self.outside / "victim.txt")
        self.assert_refused()

    def test_the_readme_is_a_link(self):
        self.victim()
        self.copy()
        root = self.stick / "Campanile"
        (root / copying.README).unlink()
        self.link(root / copying.README, self.outside / "victim.txt")
        self.assert_refused()

    def test_the_half_written_manifest_is_a_link(self):
        self.victim()
        self.copy()
        self.link(
            self.stick / "Campanile" / f".{copying.MANIFEST}.partial",
            Path("../../outside/victim.txt"),
        )
        self.assert_refused()

    def test_the_manifest_is_a_link(self):
        self.victim()
        self.copy()
        root = self.stick / "Campanile"
        (root / copying.MANIFEST).unlink()
        self.link(root / copying.MANIFEST, self.outside / "victim.txt")
        self.assert_refused()


class TestPreparedStick(CopyCase):
    """A stick prepared by someone hostile, with a Campanile folder already on it: whatever
    was slipped in must not travel inside a copy that people start without a second thought."""

    SLIPPED_IN: ClassVar = {  # what was slipped in: what the refusal names
        "campanile/secrets.py": "campanile/secrets.py",  # imported by launch.py, not Python's
        "secrets.py": "secrets.py",  # by the "python3 -c" of install.sh, as root, from here
        "urllib/__init__.py": "urllib",
        "py.bat": "py.bat",  # Windows runs it instead of py.exe, from the folder of the .bat
        "tools/kiwix-tools_test/version.dll": "tools/kiwix-tools_test/version.dll",
        "tools/python/python-3.14.9-amd64 (1).exe": "tools/python/python-3.14.9-amd64 (1).exe",
        "data/admin-password.txt": "data/admin-password.txt",  # known to whoever prepared it
        "data/campanile.db": "data/campanile.db",
        "data/zim/other.zim": "data/zim/other.zim",
        "campanile/__pycache__/readme.txt": "campanile/__pycache__",
    }

    def prepared(self, *slipped: str) -> Path:
        root = self.stick / "Campanile"
        write(root / copying.MARKER, b"9.9\n")
        for name in slipped:
            write(root / name, b"from whoever prepared the stick")
        return root

    def test_anything_slipped_in_stops_the_copy_untouched(self):
        for name, named in self.SLIPPED_IN.items():
            with self.subTest(name):
                root = self.prepared(name)
                before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
                with self.assertRaises(copying.CopyError) as e:
                    self.copy()
                self.assertEqual((e.exception.key, e.exception.detail), ("not_only_ours", named))
                after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
                self.assertEqual(after, before)  # nothing written, nothing removed
                self.assertEqual((root / name).read_bytes(), b"from whoever prepared the stick")
                for path in sorted(root.rglob("*"), reverse=True):
                    path.unlink() if path.is_file() else path.rmdir()

    def test_a_folder_slipped_in_stops_it_too(self):
        root = self.prepared()
        (root / "campanile" / "web" / "extra").mkdir(parents=True)
        with self.assertRaises(copying.CopyError) as e:
            self.copy()
        self.assertEqual(
            (e.exception.key, e.exception.detail), ("not_only_ours", "campanile/web/extra")
        )

    def test_leftovers_are_removed_and_the_copy_goes_on(self):
        root = self.copy()
        leftovers = [
            write(root / ".DS_Store"),  # a Mac showed the folder
            write(root / "._LICENSE"),  # a Mac opened the file
            write(root / "campanile" / ".server.py.partial"),  # a copy cut short
            write(root / f".{copying.MANIFEST}.partial"),
            # Started from the stick: Python's cache. A compiled file in there can even run
            # without its source being checked, so it never travels.
            write(root / "campanile" / "__pycache__" / "server.cpython-314.pyc"),
            write(root / "campanile" / "__pycache__" / "secrets.cpython-314.pyc"),
        ]
        self.copy()
        self.assertEqual([p for p in leftovers if p.exists()], [])
        self.assertFalse((root / "campanile" / "__pycache__").exists())
        for source, relative in self.plan():
            self.assertEqual((root / relative).read_bytes(), source.read_bytes(), relative)

    @unittest.skipUnless(LINKS and os.geteuid() != 0, "permissions")
    def test_a_folder_that_cant_be_listed_stops_it(self):
        # Writable and crossable, but not listable: whatever is inside can't be checked.
        root = self.prepared()
        hidden = write(root / "campanile" / "secrets.py", b"from whoever prepared the stick")
        (root / "campanile").chmod(0o333)
        try:
            with self.assertRaises(copying.CopyError) as e:
                self.copy()
        finally:
            (root / "campanile").chmod(0o755)
        self.assertEqual(e.exception.key, "stick_denied")
        self.assertEqual(hidden.read_bytes(), b"from whoever prepared the stick")
        self.assertFalse((root / "campanile" / "server.py").exists())

    @unittest.skipUnless(LINKS, "pipes")
    def test_a_pipe_stops_it(self):
        root = self.prepared()
        (root / "campanile").mkdir()
        os.mkfifo(root / "campanile" / "server.py")  # reading it would wait forever
        with self.assertRaises(copying.CopyError) as e:
            self.copy()
        self.assertEqual(
            (e.exception.key, e.exception.detail), ("not_only_ours", "campanile/server.py")
        )


class TestCheck(CopyCase):
    def test_a_damaged_program_is_noticed_and_changed_maps_are_not(self):
        root = self.copy()
        self.assertEqual(copying.check(root), [])
        (root / "campanile" / "server.py").write_bytes(b"cut")
        (root / "data" / "maps" / "area.pmtiles").write_bytes(b"a newer map")
        (root / "LICENSE").unlink()
        self.assertEqual(sorted(copying.check(root)), ["LICENSE", "campanile/server.py"])

    def test_not_a_copy_nothing_to_check(self):
        self.assertEqual(copying.check(self.root), [])

    # From an outside review (27 Oct 2026): each of these passed, or crashed, before the fix.
    def test_the_same_size_with_other_content_is_noticed(self):
        root = self.copy()
        server = root / "campanile" / "server.py"
        server.write_bytes(b"x" * server.stat().st_size)
        self.assertEqual(copying.check(root), ["campanile/server.py"])

    def test_a_copy_cut_short_before_its_manifest_is_noticed(self):
        root = self.copy()
        (root / copying.MANIFEST).unlink()  # the marker, written first, is still there
        self.assertEqual(copying.check(root), [copying.MANIFEST])

    def test_a_manifest_of_the_wrong_shape_is_damage_not_a_crash(self):
        root = self.copy()
        for body in ('{"files": []}', '{"files": {"campanile/server.py": 7}}', "[]"):
            with self.subTest(body=body):
                (root / copying.MANIFEST).write_text(body)
                self.assertTrue(copying.check(root))

    def test_a_name_outside_the_copy_is_damage_and_never_read(self):
        root = self.copy()
        # The right size: only the guard keeps it from being read.
        (root.parent / "outside.txt").write_bytes(b"not ours")
        manifest = json.loads((root / copying.MANIFEST).read_text())
        manifest["files"]["../outside.txt"] = {"bytes": 8, "sha256": "0" * 64}
        (root / copying.MANIFEST).write_text(json.dumps(manifest))
        with mock.patch.object(copying, "file_sha256", wraps=copying.file_sha256) as hashed:
            self.assertEqual(copying.check(root), ["../outside.txt"])
        self.assertNotIn(root / "../outside.txt", [c.args[0] for c in hashed.call_args_list])


class TestDrives(unittest.TestCase):
    def test_mac_lists_local_volumes_only(self):
        mount = (
            "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
            "/dev/disk3s5 on /System/Volumes/Data (apfs, local, journaled, nobrowse)\n"
            "/dev/disk4s1 on /Volumes/NO NAME (msdos, local, nodev, nosuid, noowners)\n"
            "/dev/disk5s1 on /Volumes/Backup (2) (exfat, local, nodev, nosuid)\n"
            "//user@nas/share on /Volumes/share (smbfs, nodev, nosuid, mounted by user)\n"
            "map auto_home on /System/Volumes/Data/home (autofs, automounted, nobrowse)\n"
        )
        with mock.patch.object(copying.subprocess, "run") as run:
            run.return_value.stdout = mount
            found = copying._mac_drives()
        self.assertEqual(
            [(d.path, d.name, d.filesystem) for d in found],
            [
                ("/Volumes/NO NAME", "NO NAME", "msdos"),
                ("/Volumes/Backup (2)", "Backup (2)", "exfat"),
            ],
        )

    def test_linux_lists_media_mounts_only(self):
        mounts = (
            "/dev/mmcblk0p2 / ext4 rw 0 0\n"
            "/dev/sda1 /media/pi/MY\\040STICK vfat rw,showexec 0 0\n"
            "/dev/sdb1 /run/media/anna/DATA exfat rw 0 0\n"
            "//nas/share /media/pi/share cifs rw 0 0\n"
            "tmpfs /media/pi/ram tmpfs rw 0 0\n"
        )
        with mock.patch("builtins.open", mock.mock_open(read_data=mounts)):
            found = copying._linux_drives()
        self.assertEqual(
            [(d.path, d.filesystem) for d in found],
            [("/media/pi/MY STICK", "vfat"), ("/run/media/anna/DATA", "exfat")],
        )

    def test_never_the_system(self):
        for drive in copying.drives():
            self.assertNotEqual(drive.path.upper()[:2], os.environ.get("SYSTEMDRIVE", "C:").upper())

    def test_never_the_drive_this_campanile_runs_from(self):
        # On GitHub's Windows machines the code is on D:, a fixed disk like an external one.
        own = copying.Drive(copying.HERE.anchor, "OWN", "ntfs")
        other = copying.Drive("Q:\\" if os.name == "nt" else "/Volumes/OTHER", "OTHER", "exfat")
        with (
            mock.patch.object(copying, "_mac_drives", return_value=[own, other]),
            mock.patch.object(copying, "_linux_drives", return_value=[own, other]),
            mock.patch.object(copying, "_windows_drives", return_value=[own, other]),
        ):
            self.assertEqual(copying.drives(), [other])
        for drive in copying.drives():  # and the real ones of this computer
            self.assertFalse(copying._holds(drive, copying.HERE), drive)


class TestCommandLine(CopyCase):
    def test_copies_this_campanile(self):
        here = Path(__file__).resolve().parent.parent
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(here / "campanile" / "copying.py"),
                str(self.stick),
                "--data",
                str(self.data),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        root = self.stick / "Campanile"
        manifest = json.loads((root / copying.MANIFEST).read_text(encoding="utf-8"))["files"]
        self.assertIn("campanile/copying.py", manifest)
        self.assertIn("data/maps/area.pmtiles", manifest)
        self.assertNotIn("tests/test_copying.py", manifest)
        self.assertFalse(any(p.read_bytes() == b"SECRET" for p in root.rglob("*") if p.is_file()))


if __name__ == "__main__":
    unittest.main()
