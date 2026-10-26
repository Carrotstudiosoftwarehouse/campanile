# DEVELOPED BY CARROTSTUDIO software house
"""The setup page's downloads, against a stand-in for GitHub, Kiwix and Protomaps on localhost.

The real programs are replaced by small scripts with the same command line, so every path
runs here: tools checked and unpacked, maps cut out, Wikipedia resumed and checked, and
every way it can go wrong.
"""

import hashlib
import io
import json
import os
import ssl
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import zipfile
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import copying
import preparation
from preparation import Preparation, SetupError, Sources, Tool
from test_server import PASSWORD, CampanileTestCase

POSIX = os.name != "nt"
ZIM = "wikipedia_it_medicine_maxi_2026-10.zim"
ZIM_BYTES = os.urandom(300_000)


class Origin:
    """Files, Range requests and redirects, like the real servers."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.redirects: dict[str, str] = {}
        self.requests: list[tuple[str, str | None]] = []
        self.hold = threading.Event()  # set: the next download stops after its first piece
        self.release = threading.Event()
        origin = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                origin.requests.append((self.path, self.headers.get("Range")))
                if self.path in origin.redirects:
                    self.send_response(302)
                    self.send_header("Location", origin.redirects[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = origin.files.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                start = 0
                wanted = self.headers.get("Range", "")
                if wanted.startswith("bytes="):
                    start = int(wanted[6:].rstrip("-"))
                    if start >= len(body):
                        self.send_response(416)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                else:
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body) - start))
                self.end_headers()
                piece = 64 * 1024
                for offset in range(start, len(body), piece):
                    try:
                        self.wfile.write(body[offset : offset + piece])
                        self.wfile.flush()
                    except OSError:
                        return
                    if origin.hold.is_set():
                        origin.release.wait(10)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


def script(body: str) -> bytes:
    """A stand-in program: a Python script with the real program's command line."""
    return f"#!{sys.executable}\nimport json, os, pathlib, sys, time\n{body}\n".encode()


FAKE_PMTILES = """
args = sys.argv[1:]
here = pathlib.Path(__file__).parent
with open(here / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "extract":
    pathlib.Path(args[2]).write_bytes(b"PMTiles" + b"x" * 5000)
    sys.exit(0)
if args[0] == "verify":
    sys.exit(VERIFY_EXIT)
sys.exit(2)
"""

FAKE_KIWIX = """
(pathlib.Path(__file__).parent / "args.json").write_text(json.dumps(sys.argv[1:]))
time.sleep(60)
"""


def tar_gz(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644  # not executable: the Campanile has to set it
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def zip_file(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PreparationCase(unittest.TestCase):
    verify_exit = 0

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.data, self.tools = root / "data", root / "tools"
        self.origin = Origin()
        self.addCleanup(self.origin.close)
        o = self.origin
        pmtiles = tar_gz(
            {"pmtiles": script(FAKE_PMTILES.replace("VERIFY_EXIT", str(self.verify_exit)))}
        )
        kiwix = tar_gz({"kiwix-tools_test/kiwix-serve": script(FAKE_KIWIX)})
        o.files["/tools/pmtiles_test.tar.gz"] = pmtiles
        o.files["/tools/kiwix-tools_test.tar.gz"] = kiwix
        o.files["/builds.json"] = json.dumps(
            [
                {"key": "20260101.pmtiles"},
                {"key": "20261020.pmtiles"},
                {"key": "../../etc/passwd.pmtiles"},  # not a build name: ignored
                {"key": "99999999.zip"},
                "garbage",
            ]
        ).encode()
        o.files["/zim/"] = (
            f'<a href="wikipedia_it_medicine_maxi_2026-07.zim">old</a>'
            f'<a href="{ZIM}">new</a>'
            f'<a href="wikipedia_it_medicine_nopic_2026-11.zim">other package</a>'
        ).encode()
        o.files[f"/zim/{ZIM}"] = ZIM_BYTES
        o.files[f"/zim/{ZIM}.sha256"] = f"{sha(ZIM_BYTES)}  {ZIM}\n".encode()
        here = preparation.this_platform()
        self.tool_table = {
            "pmtiles": {
                here: Tool(o.url + "/tools/pmtiles_test.tar.gz", sha(pmtiles), ("pmtiles",))
            },
            "kiwix-serve": {
                here: Tool(
                    o.url + "/tools/kiwix-tools_test.tar.gz",
                    sha(kiwix),
                    ("kiwix-tools_test/kiwix-serve",),
                )
            },
        }
        self.prep = self.make()

    def tearDown(self):
        self.prep.cancel()
        self.prep.wait(10)
        self.prep.stop_kiwix()
        self._tmp.cleanup()

    def make(self, **sources):
        o = self.origin
        defaults = {
            "builds": o.url + "/builds.json",
            "world": o.url + "/world/",
            "wikipedia": o.url + "/zim/",
            "tools": self.tool_table,
            "https_only": False,
        }
        return Preparation(
            self.data, self.tools, kiwix_port=18999, sources=Sources(**{**defaults, **sources})
        )

    def run_job(self, start):
        self.assertTrue(start())
        self.prep.wait(30)
        job = self.prep.state()["job"]
        self.assertTrue(job["finished"])
        return job


@unittest.skipUnless(POSIX, "the stand-in programs are scripts")
class TestWikipedia(PreparationCase):
    def test_downloads_checks_and_starts_kiwix(self):
        (self.data / "zim").mkdir(parents=True)
        (self.data / "zim" / "wikipedia_it_medicine_maxi_2026-07.zim").write_bytes(b"old")
        (self.data / "zim" / "someone-elses.zim").write_bytes(b"keep")

        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertIsNone(job["error"], job)
        self.assertEqual((self.data / "zim" / ZIM).read_bytes(), ZIM_BYTES)
        zims = sorted(p.name for p in (self.data / "zim").iterdir())
        self.assertEqual(zims, sorted([ZIM, "someone-elses.zim"]))  # older same package: gone

        program = self.tools / "kiwix-tools_test" / "kiwix-serve"
        self.assertTrue(os.access(program, os.X_OK))
        self.assertFalse(any(self.tools.glob("*.partial")))
        deadline = time.time() + 10
        args_file = program.with_name("args.json")
        while not args_file.exists() and time.time() < deadline:
            time.sleep(0.05)
        args = json.loads(args_file.read_text())
        self.assertIn("--port=18999", args)
        self.assertIn("--blockexternal", args)
        self.assertIn(f"--attachToProcess={os.getpid()}", args)
        self.assertIn(str(self.data / "zim" / ZIM), args)
        self.prep.stop_kiwix()
        self.assertIsNone(self.prep._kiwix)

    def test_kiwix_lets_go_of_the_old_version_before_it_is_deleted(self):
        # On Windows a file kiwix-serve has open can't be deleted: it is stopped first.
        old = self.data / "zim" / "wikipedia_it_medicine_maxi_2026-07.zim"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old")
        stopped_with_old_there = []
        stop = self.prep.stop_kiwix

        def watched_stop():
            stopped_with_old_there.append(old.exists())
            stop()

        self.prep.stop_kiwix = watched_stop
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertIsNone(job["error"], job)
        self.assertTrue(stopped_with_old_there[0])
        self.assertFalse(old.exists())

    def test_resumes_an_interrupted_download(self):
        (self.data / "zim").mkdir(parents=True)
        (self.data / "zim" / f".{ZIM}.partial").write_bytes(ZIM_BYTES[:100_000])
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertIsNone(job["error"], job)
        self.assertIn((f"/zim/{ZIM}", "bytes=100000-"), self.origin.requests)
        self.assertEqual((self.data / "zim" / ZIM).read_bytes(), ZIM_BYTES)

    def test_a_complete_leftover_is_checked_not_downloaded_again(self):
        (self.data / "zim").mkdir(parents=True)
        (self.data / "zim" / f".{ZIM}.partial").write_bytes(ZIM_BYTES)
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertIsNone(job["error"], job)
        self.assertEqual((self.data / "zim" / ZIM).read_bytes(), ZIM_BYTES)

    def test_a_wrong_checksum_lands_nothing(self):
        self.origin.files[f"/zim/{ZIM}.sha256"] = f"{'0' * 64}  {ZIM}\n".encode()
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertEqual(job["error"], "checksum")
        self.assertEqual(list((self.data / "zim").iterdir()), [])  # no file, no partial

    def test_no_published_checksum_no_download(self):
        self.origin.files[f"/zim/{ZIM}.sha256"] = b"<html>not found</html>"
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertEqual(job["error"], "checksum")
        self.assertFalse(any(r[0] == f"/zim/{ZIM}" for r in self.origin.requests))

    def test_too_big_stops(self):
        original = preparation.WIKI_LIMIT
        preparation.WIKI_LIMIT = 1000
        self.addCleanup(setattr, preparation, "WIKI_LIMIT", original)
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertEqual(job["error"], "too_big")
        self.assertFalse((self.data / "zim" / ZIM).exists())

    def test_cancel_keeps_the_partial_for_later(self):
        self.origin.hold.set()
        self.assertTrue(self.prep.start_wiki("it"))
        deadline = time.time() + 10
        partial = self.data / "zim" / f".{ZIM}.partial"
        while not partial.exists() and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.prep.start_map("world", preparation.WORLD, 7))  # one at a time
        self.prep.cancel()
        self.origin.release.set()
        self.prep.wait(10)
        self.assertEqual(self.prep.state()["job"]["error"], "cancelled")
        self.assertFalse((self.data / "zim" / ZIM).exists())
        self.assertTrue(partial.exists())

    def test_nothing_published_for_the_package(self):
        self.origin.files["/zim/"] = b"<html>nothing here</html>"
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertEqual(job["error"], "not_found")


@unittest.skipUnless(POSIX, "the stand-in programs are scripts")
class TestMaps(PreparationCase):
    def test_cuts_the_area_from_the_latest_world_map(self):
        job = self.run_job(lambda: self.prep.start_map("area", (7.64, 45.04, 7.71, 45.09), 15))
        self.assertIsNone(job["error"], job)
        self.assertTrue((self.data / "maps" / "area.pmtiles").read_bytes().startswith(b"PMTiles"))
        self.assertEqual(list((self.data / "maps").glob(".*")), [])
        calls = [
            json.loads(x)
            for x in (self.tools / "pmtiles_test" / "calls.jsonl").read_text().splitlines()
        ]
        extract, verify = calls
        self.assertEqual(extract[:2], ["extract", self.origin.url + "/world/20261020.pmtiles"])
        self.assertIn("--bbox=7.64,45.04,7.71,45.09", extract)
        self.assertIn("--maxzoom=15", extract)
        self.assertEqual(verify[0], "verify")
        self.assertEqual(self.prep.state()["maps"], ["area"])

    def test_the_tool_is_downloaded_once(self):
        self.run_job(lambda: self.prep.start_map("world", preparation.WORLD, 7))
        self.run_job(lambda: self.prep.start_map("area", (7.6, 45.0, 7.7, 45.1), 15))
        downloads = [r for r in self.origin.requests if r[0].startswith("/tools/")]
        self.assertEqual(len(downloads), 1)

    def test_a_tampered_tool_is_refused(self):
        self.origin.files["/tools/pmtiles_test.tar.gz"] += b"tampered"
        job = self.run_job(lambda: self.prep.start_map("world", preparation.WORLD, 7))
        self.assertEqual(job["error"], "checksum")
        self.assertFalse((self.tools / "pmtiles_test").exists())
        self.assertFalse((self.data / "maps" / "world.pmtiles").exists())

    def test_tools_packed_as_zip_like_on_windows(self):
        program = script(FAKE_PMTILES.replace("VERIFY_EXIT", "0"))
        archive = zip_file({"LICENSE": b"MIT", "pmtiles": program, "helper.dll": b"dll"})
        self.origin.files["/tools/pmtiles_zip.zip"] = archive
        here = preparation.this_platform()
        url = self.origin.url + "/tools/pmtiles_zip.zip"
        self.tool_table["pmtiles"] = {here: Tool(url, sha(archive), ("pmtiles", "helper.dll"))}
        job = self.run_job(lambda: self.prep.start_map("world", preparation.WORLD, 7))
        self.assertIsNone(job["error"], job)
        folder = self.tools / "pmtiles_zip"
        self.assertEqual(
            sorted(p.name for p in folder.iterdir() if p.suffix != ".jsonl"),
            ["helper.dll", "pmtiles"],
        )  # only the named files, not LICENSE
        self.assertEqual((folder / "pmtiles").read_bytes(), program)

    def test_unsupported_computer(self):
        self.prep = self.make(tools={"pmtiles": {}, "kiwix-serve": {}})
        job = self.run_job(lambda: self.prep.start_map("world", preparation.WORLD, 7))
        self.assertEqual(job["error"], "unsupported")
        self.assertEqual(self.prep.state()["supported"], {"pmtiles": False, "kiwix-serve": False})


@unittest.skipUnless(POSIX, "the stand-in programs are scripts")
class TestOtherCampaniles(PreparationCase):
    """What a USB stick needs, and the copy itself."""

    def setUp(self):
        super().setUp()
        o = self.origin
        windows = zip_file({"kiwix-serve.exe": b"MZ program", "icudt74.dll": b"dll"})
        o.files["/tools/kiwix-win_test.zip"] = windows
        self.tool_table["kiwix-serve"][("Windows", "x86_64")] = Tool(
            o.url + "/tools/kiwix-win_test.zip", sha(windows), ("kiwix-serve.exe", "icudt74.dll")
        )
        self.installer = os.urandom(50_000)
        o.files["/python/python-9.9.9-amd64.exe"] = self.installer
        self.prep = self.make(
            installers=(
                Tool(
                    o.url + "/python/python-9.9.9-amd64.exe",
                    sha(self.installer),
                    ("python-9.9.9-amd64.exe",),
                ),
            )
        )

    def test_kiwix_for_every_computer_and_python_s_installer(self):
        self.assertFalse(self.prep.extras_ready())
        job = self.run_job(self.prep.start_extras)
        self.assertIsNone(job["error"], job)
        self.assertEqual(
            (self.tools / "kiwix-win_test" / "kiwix-serve.exe").read_bytes(), b"MZ program"
        )
        self.assertTrue((self.tools / "kiwix-tools_test" / "kiwix-serve").is_file())
        self.assertEqual(
            (self.tools / "python" / "python-9.9.9-amd64.exe").read_bytes(), self.installer
        )
        self.assertTrue(self.prep.extras_ready())
        self.assertTrue(self.prep.state()["extras"])

    def test_a_tampered_installer_is_refused(self):
        self.origin.files["/python/python-9.9.9-amd64.exe"] = b"something else"
        job = self.run_job(self.prep.start_extras)
        self.assertEqual(job["error"], "checksum")
        self.assertFalse((self.tools / "python" / "python-9.9.9-amd64.exe").exists())

    def test_the_copy_lands_on_the_stick_without_the_database(self):
        (self.data / "maps").mkdir(parents=True)
        (self.data / "maps" / "area.pmtiles").write_bytes(b"map")
        (self.data / "campanile.db").write_bytes(b"SECRET")
        (self.data / "admin-password.txt").write_bytes(b"SECRET")
        stick = Path(self._tmp.name) / "stick"
        stick.mkdir()
        job = self.run_job(lambda: self.prep.start_copy(copying.Drive(str(stick), "S", "exfat")))
        self.assertIsNone(job["error"], job)
        self.assertEqual(job["step"], "copied")
        root = stick / "Campanile"
        self.assertEqual((root / "data" / "maps" / "area.pmtiles").read_bytes(), b"map")
        self.assertTrue((root / copying.MANIFEST).is_file())
        self.assertFalse(any(f.read_bytes() == b"SECRET" for f in root.rglob("*") if f.is_file()))

    def test_a_full_stick_is_reported_by_name(self):
        stick = Path(self._tmp.name) / "stick"
        stick.mkdir()
        with mock.patch.object(copying.shutil, "disk_usage") as usage:
            usage.return_value.free = 0
            job = self.run_job(
                lambda: self.prep.start_copy(copying.Drive(str(stick), "S", "exfat"))
            )
        self.assertEqual(job["error"], "stick_full")


@unittest.skipUnless(POSIX, "file permissions")
class TestRunnable(unittest.TestCase):
    """Linux mounts a FAT stick "showexec": kiwix-serve on it is not executable."""

    def test_a_program_that_cannot_run_from_the_stick_runs_from_a_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            stick = Path(folder, "stick", "kiwix-tools_linux")
            stick.mkdir(parents=True)
            program = stick / "kiwix-serve"
            program.write_bytes(b"#!/bin/sh\necho ok\n")
            program.chmod(0o644)  # as showexec leaves it
            with mock.patch.object(Path, "home", return_value=Path(folder, "home")):
                runnable = Preparation._runnable(program)
                self.assertNotEqual(runnable, program)
                self.assertTrue(os.access(runnable, os.X_OK))
                self.assertEqual(runnable.read_bytes(), program.read_bytes())
                self.assertEqual(runnable.stat().st_mode & 0o077, 0)  # only for this user
                runnable.write_bytes(b"#!/bin/sh\necho no\n")  # same size, another program
                self.assertEqual(Preparation._runnable(program).read_bytes(), program.read_bytes())
                program.chmod(0o755)
                self.assertEqual(Preparation._runnable(program), program)  # runnable: as it is


class TestReplace(unittest.TestCase):
    """A finished download replaces the old file even while someone is still reading it."""

    def test_waits_for_a_reader_to_let_go(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder, "area.pmtiles"), Path(folder, ".area.pmtiles.partial")
            old.write_bytes(b"old map")
            new.write_bytes(b"new map")
            reader = open(old, "rb")  # noqa: SIM115 (closed by the timer: on Windows this blocks)
            threading.Timer(1.0, reader.close).start()
            preparation.replace(new, old)
            self.assertEqual(old.read_bytes(), b"new map")
            reader.close()

    @mock.patch.object(preparation, "REPLACE_WAIT", 0.6)
    def test_gives_up_in_the_end(self):
        busy = PermissionError(13, "in use")
        with mock.patch.object(preparation.os, "replace", side_effect=busy) as replace:
            self.assertRaises(PermissionError, preparation.replace, Path("new"), Path("old"))
        self.assertGreater(replace.call_count, 1)


@unittest.skipUnless(POSIX, "the stand-in programs are scripts")
class TestMapThatFailsVerification(PreparationCase):
    verify_exit = 1

    def test_a_broken_map_never_replaces_a_good_one(self):
        (self.data / "maps").mkdir(parents=True)
        (self.data / "maps" / "world.pmtiles").write_bytes(b"the good one")
        job = self.run_job(lambda: self.prep.start_map("world", preparation.WORLD, 7))
        self.assertEqual(job["error"], "failed")
        self.assertEqual((self.data / "maps" / "world.pmtiles").read_bytes(), b"the good one")
        self.assertEqual(list((self.data / "maps").glob(".*")), [])


class TestSafety(PreparationCase):
    def test_only_https_unless_testing(self):
        self.prep = self.make(https_only=True)
        job = self.run_job(lambda: self.prep.start_wiki("it"))
        self.assertEqual(job["error"], "insecure")
        self.assertEqual(self.origin.requests, [])  # refused before connecting

    def test_a_redirect_to_plain_http_is_refused(self):
        handler = preparation._HttpsOnly()
        with self.assertRaises(SetupError) as e:
            handler.redirect_request(None, None, 302, "Found", {}, "http://mirror.example/f.zim")
        self.assertEqual(e.exception.key, "insecure")

    def test_other_schemes_are_refused_even_when_testing(self):
        for url in ("file:///etc/passwd", "ftp://example.org/x", "data:,x"):
            with self.assertRaises(SetupError, msg=url):
                self.prep._open(url)

    def test_mozillas_authorities_are_added_to_the_systems(self):
        if not preparation.CA_BUNDLE.is_file():
            self.skipTest("scripts/prepare.sh not run: no campanile/certs/cacert.pem")
        system = ssl.create_default_context().cert_store_stats()["x509_ca"]
        both = preparation.tls_context().cert_store_stats()["x509_ca"]
        self.assertGreater(both, system)  # added, not replaced
        self.assertEqual(preparation.tls_context().verify_mode, ssl.CERT_REQUIRED)

    def test_valid_area(self):
        ok = preparation.valid_area
        self.assertEqual(ok([7.64, 45.04, 7.71, 45.09]), (7.64, 45.04, 7.71, 45.09))
        for bad in (
            [7.7, 45.0, 7.6, 45.1],  # west east of east
            [0, 0, 10, 10],  # far too large
            [float("nan"), 45, 7.7, 45.1],
            [float("-inf"), 45, 7.7, 45.1],
            [7.6, 45.0, 7.7, 99],
            [True, 45.0, 7.7, 45.1],
            ["7.6", 45.0, 7.7, 45.1],
            [7.6, 45.0, 7.7],
            None,
            {"w": 1},
        ):
            self.assertIsNone(ok(bad), bad)


class TestSetupEndpoints(CampanileTestCase):
    def setUp(self):
        super().setUp()
        self._tools = tempfile.TemporaryDirectory()
        self.addCleanup(self._tools.cleanup)
        self.started = []
        prep = Preparation(
            self.data, Path(self._tools.name), sources=Sources(tools={"pmtiles": {}})
        )
        prep.start_map = lambda *a: self.started.append(("map", *a)) or len(self.started) < 2
        prep.start_wiki = lambda *a: self.started.append(("wiki", *a)) or True
        prep.start_extras = lambda: self.started.append(("extras",)) or True
        prep.start_receive = lambda *a: self.started.append(("receive", *a)) or True
        prep.start_copy = lambda drive: self.started.append(("copy", drive.path)) or True
        self.cfg.setup = prep
        self.stick = copying.Drive(str(Path(self._tools.name) / "stick"), "STICK", "exfat")
        patcher = mock.patch.object(copying, "drives", return_value=[self.stick])
        patcher.start()
        self.addCleanup(patcher.stop)

    def setup_call(self, path, headers=None, **body):
        return self.json("POST", path, {"password": PASSWORD, **body}, headers)

    def test_state(self):
        status, state = self.setup_call("/api/setup/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["maps"], ["test"])
        self.assertEqual(state["supported"], {"pmtiles": False})
        self.assertIsNone(state["job"])
        self.assertTrue(self.json("GET", "/api/status")[1]["setup"])

    def test_start_tasks_and_one_at_a_time(self):
        status, _ = self.setup_call("/api/setup/start", task="map-world")
        self.assertEqual(status, 202)
        self.assertEqual(self.started[0], ("map", "world", preparation.WORLD, 7))
        status, _ = self.setup_call(
            "/api/setup/start", task="map-area", bbox=[7.6, 45.0, 7.7, 45.1]
        )
        self.assertEqual(status, 409)  # the stand-in says it is busy
        self.assertEqual(self.setup_call("/api/setup/start", task="wiki", lang="en")[0], 202)
        self.assertEqual(self.started[-1], ("wiki", "en"))

    def test_a_copy_only_to_a_drive_the_computer_lists(self):
        status, state = self.setup_call("/api/setup/state")
        self.assertEqual(state["drives"][0]["path"], self.stick.path)
        self.assertIn("copy_bytes", state)
        self.assertFalse(state["extras"])
        self.assertEqual(self.setup_call("/api/setup/start", task="extras")[0], 202)
        self.assertEqual(
            self.setup_call("/api/setup/start", task="copy", drive=self.stick.path)[0], 202
        )
        self.assertEqual(self.started, [("extras",), ("copy", self.stick.path)])
        for drive in (
            "/",
            "/etc",
            self.stick.path + "/..",
            self.stick.path + "/",
            "C:\\",
            None,
            ["x"],
            1,
        ):
            with self.subTest(drive=drive):
                status, r = self.setup_call("/api/setup/start", task="copy", drive=drive)
                self.assertEqual(status, 400)
                self.assertIn("error", r)
        self.assertEqual(len(self.started), 2)

    def test_receiving_only_from_the_local_network_with_a_real_code(self):
        good = {"task": "receive", "address": "10.42.0.1", "code": "k7qf-2m9x-r4ta-8whn"}
        self.assertEqual(self.setup_call("/api/setup/start", **good)[0], 202)
        self.assertEqual(self.started[-1], ("receive", "http://10.42.0.1:80", "K7QF2M9XR4TA8WHN"))
        for address in (
            "8.8.8.8",
            "http://example.com",
            "file:///etc/passwd",
            "10.42.0.1/x",
            None,
            7,
        ):
            status, r = self.setup_call("/api/setup/start", **{**good, "address": address})
            self.assertEqual((status, "error" in r), (400, True), address)
        for code in ("", "1234", "K7QF-2M9X-R4TA-8WH!", None, ["x"]):
            status, r = self.setup_call("/api/setup/start", **{**good, "code": code})
            self.assertEqual((status, "error" in r), (400, True), code)
        self.assertEqual(len(self.started), 1)

    def test_bad_input_is_a_clear_400_never_a_500(self):
        for body in (
            {"task": "rm -rf /"},
            {"task": ["map-world"]},
            {"task": "map-area", "bbox": [0, 0, 50, 50]},
            {"task": "map-area", "bbox": "7.6,45,7.7,45.1"},
            {"task": "wiki", "lang": "de"},
            {"task": "wiki", "lang": ["it"]},
            {"task": "wiki", "lang": {"it": 1}},
        ):
            status, r = self.setup_call("/api/setup/start", **body)
            self.assertEqual(status, 400, body)
            self.assertIn("error", r)
        self.assertEqual(self.started, [])

    def test_password_and_this_computer_only(self):
        self.assertEqual(self.json("POST", "/api/setup/state", {"password": "wrong"})[0], 403)
        # DNS rebinding: a web page reaching 127.0.0.1 under its own name.
        status, _ = self.setup_call("/api/setup/state", {"Host": "evil.example:8080"})
        self.assertEqual(status, 421)
        # A name of the network is fine for the board, not for the setup page.
        status, _ = self.setup_call("/api/setup/state", {"Host": "laptop.local:8080"})
        self.assertEqual(status, 403)
        self.assertEqual(self.setup_call("/api/setup/state", {"Host": "localhost:8080"})[0], 200)

    def test_never_from_the_network_even_with_admin_from_network(self):
        self.cfg.behind_proxy = True
        self.cfg.admin_from_network = True
        phone = {"X-Real-IP": "10.42.0.7"}
        self.assertEqual(self.setup_call("/api/setup/state", phone)[0], 403)
        self.assertEqual(
            self.json("POST", "/api/admin/list", {"password": PASSWORD}, phone)[0], 200
        )

    def test_off_unless_enabled(self):
        self.cfg.setup = None
        self.assertEqual(self.setup_call("/api/setup/state")[0], 404)
        self.assertFalse(self.json("GET", "/api/status")[1]["setup"])


if __name__ == "__main__":
    unittest.main()
