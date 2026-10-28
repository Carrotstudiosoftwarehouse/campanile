# DEVELOPED BY CARROTSTUDIO software house
"""Getting a Campanile ready from the browser, while internet still works.

Laptop only: launch.py turns it on with --setup, the Raspberry never has it. The page picks
from fixed choices and never sends an address: every URL is written here. Programs are
checked against the SHA-256 pinned below, Wikipedia against the one Kiwix publishes, and
nothing lands in data/ until it is complete and checked. Redirects to plain http are refused.
"""

from __future__ import annotations

import contextlib
import filecmp
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import tarfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit

import copying
import release
import sharing
import update

CHUNK = 1 << 20
NETWORK_TIMEOUT = 30  # seconds of silence before a download gives up
TOOL_TIMEOUT = 12 * 3600  # a whole-country extract on a slow line takes hours
RESERVE = 500 * 10**6  # always leave this much disk free
TEXT_LIMIT = 8 * 10**6  # index pages and checksums
PROGRAM_LIMIT = 200 * 10**6
REPLACE_WAIT = 60  # seconds a finished download waits for the old file to be free (Windows)

# The whole world, measured on 24 October 2026: 189 MB up to zoom 7 (countries, cities, main
# roads), 560 MB up to 8. It is also the map the setup page uses to pick the area.
WORLD = (-180.0, -85.0, 180.0, 85.0)
WORLD_ZOOM = 7
AREA_ZOOM = 15
MAX_AREA = 0.25  # square degrees: about 50 x 28 km in Italy, a few hundred MB in a city
# Medical articles. Measured on 24 October 2026: Italian with images is 261 MB; English is
# far larger, so it comes without images (1.0 GB, full text).
WIKI_PACKAGES = {"it": "wikipedia_it_medicine_maxi", "en": "wikipedia_en_medicine_nopic"}
WIKI_LIMIT = 4 * 10**9

# Rough upper bounds, only to warn before starting when the disk is too small.
EXPECTED_BYTES = {"world": 400 * 10**6, "area": 1000 * 10**6}

# Mozilla's certificate authorities (certifi, from scripts/prepare.sh), added to the system's.
# On a Mac, python.org's Python has none; on a fresh Windows it can't fetch a missing root as
# Edge does (measured: build-metadata.protomaps.dev failed there, and worked with this list).
CA_BUNDLE = Path(__file__).resolve().parent / "certs" / "cacert.pem"

PMTILES = "https://github.com/protomaps/go-pmtiles/releases/download/v1.31.2/"
KIWIX = "https://download.kiwix.org/release/kiwix-tools/"


@dataclass(frozen=True)
class Tool:
    url: str
    sha256: str
    members: tuple[str, ...]  # files taken from the archive; the first is the program


TOOLS = {
    "pmtiles": {
        ("Darwin", "arm64"): Tool(
            PMTILES + "go-pmtiles-1.31.2_Darwin_arm64.zip",
            "40528f7f616fcbf91207cd48c8fc023d213f6d86c0cbf1f748732803d1880f3d",
            ("pmtiles",),
        ),
        ("Darwin", "x86_64"): Tool(
            PMTILES + "go-pmtiles-1.31.2_Darwin_x86_64.zip",
            "1f0dc02eee6c58312dd6c509faee1b5c32f0596568af1bf51f1b034e7a88a65b",
            ("pmtiles",),
        ),
        ("Linux", "arm64"): Tool(
            PMTILES + "go-pmtiles_1.31.2_Linux_arm64.tar.gz",
            "f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1",
            ("pmtiles",),
        ),
        ("Linux", "x86_64"): Tool(
            PMTILES + "go-pmtiles_1.31.2_Linux_x86_64.tar.gz",
            "3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f",
            ("pmtiles",),
        ),
        ("Windows", "arm64"): Tool(
            PMTILES + "go-pmtiles_1.31.2_Windows_arm64.zip",
            "8780a17453c63af757917a694cbbb50b943db89cc3f1b07e6fd62c1ff8e6963b",
            ("pmtiles.exe",),
        ),
        ("Windows", "x86_64"): Tool(
            PMTILES + "go-pmtiles_1.31.2_Windows_x86_64.zip",
            "a658baa4d7e55020aef6ca17bd9ff9faa1582671266b36f58c52db0ac8e785a1",
            ("pmtiles.exe",),
        ),
    },
    # Kiwix publishes only MD5: these SHA-256 were taken on 22 October 2026 from files
    # whose MD5 matched the published one.
    "kiwix-serve": {
        ("Darwin", "arm64"): Tool(
            KIWIX + "kiwix-tools_macos-arm64-3.8.1.tar.gz",
            "222e8398ca50ac005a7e92cf0116e0c83e3c44c79cab0bb7f6537943d517e8d3",
            ("kiwix-tools_macos-arm64-3.8.1/kiwix-serve",),
        ),
        ("Darwin", "x86_64"): Tool(
            KIWIX + "kiwix-tools_macos-x86_64-3.8.1.tar.gz",
            "70219e56f7c274e1fc0db8487abdcc91bde9a6f2923958894c0c81ee24b06c01",
            ("kiwix-tools_macos-x86_64-3.8.1/kiwix-serve",),
        ),
        ("Linux", "arm64"): Tool(
            KIWIX + "kiwix-tools_linux-aarch64-3.8.1.tar.gz",
            "7b00940e1f5e4642e4ef6e7262543893e105b20e9e97be5352e129c591fa29da",
            ("kiwix-tools_linux-aarch64-3.8.1/kiwix-serve",),
        ),
        ("Linux", "x86_64"): Tool(
            KIWIX + "kiwix-tools_linux-x86_64-3.8.1.tar.gz",
            "46557f9a3c3eaada2556a957cf5bc662c07dc6286e8924e04fa3a173f83ff6dd",
            ("kiwix-tools_linux-x86_64-3.8.1/kiwix-serve",),
        ),
        ("Windows", "x86_64"): Tool(
            KIWIX + "kiwix-tools_win-x86_64-3.8.1.zip",
            "fcd01ed2b93e9a68632c7863c83b9f66bf64406a66357be1df7b8b75596f3e45",
            (
                "kiwix-serve.exe",
                "icudt74.dll",
                "icuin74.dll",
                "icuio74.dll",
                "icutu74.dll",
                "icuuc74.dll",
            ),
        ),
    },
}
# Kiwix has no build for Windows on ARM, which runs x64 programs emulated (measured on
# Windows 11 ARM64: kiwix-serve 3.8.1 x64 runs and serves).
TOOLS["kiwix-serve"][("Windows", "arm64")] = TOOLS["kiwix-serve"][("Windows", "x86_64")]

# Python's official installers, so a stick can start a Campanile where there is neither Python
# nor internet. Checked on 24 October 2026 against python.org's Sigstore signatures (identity
# hugo@python.org); the Windows ones are also signed by the PSF, the Mac one notarized by Apple.
PYTHON = "https://www.python.org/ftp/python/3.14.9/"
PYTHON_INSTALLERS = (
    Tool(
        PYTHON + "python-3.14.9-amd64.exe",
        "a247a0b612244a803f507b39fb7121e3602e4160d59c3b99d98e735289c53394",
        ("python-3.14.9-amd64.exe",),
    ),
    Tool(
        PYTHON + "python-3.14.9-arm64.exe",
        "4508e6a54c69566b8faec461d84d85eebee65c39a15eb910bc2ad873d09b022b",
        ("python-3.14.9-arm64.exe",),
    ),
    Tool(
        PYTHON + "python-3.14.9-macos11.pkg",
        "08e312f20844b524c2f8c5e5b2e7f49608c22e8c7cb194f5834d385c94383462",
        ("python-3.14.9-macos11.pkg",),
    ),
)


def tool_folder(tool: Tool) -> str:
    """The tool's folder in tools/: its archive's name, without the extension."""
    return re.sub(r"\.(zip|tar\.gz)$", "", Path(urlsplit(tool.url).path).name)


def tool_folders(table: dict | None = None) -> dict[str, tuple[str, ...]]:
    """kiwix-serve for every computer: {folder in tools/: the files it holds}."""
    tools = (table or TOOLS).get("kiwix-serve", {}).values()
    return {tool_folder(t): tuple(Path(m).name for m in t.members) for t in tools}


def installer_names(installers=PYTHON_INSTALLERS) -> tuple[str, ...]:
    return tuple(t.members[0] for t in installers)


@dataclass(frozen=True)
class Sources:
    builds: str = "https://build-metadata.protomaps.dev/builds.json"
    world: str = "https://build.protomaps.com/"
    wikipedia: str = "https://download.kiwix.org/zim/wikipedia/"
    tools: dict = field(default_factory=lambda: TOOLS)
    installers: tuple = PYTHON_INSTALLERS
    https_only: bool = True  # tests serve plain http on localhost


class SetupError(Exception):
    """Ends a job. The key becomes a message on the page (setup.error.<key>)."""

    def __init__(self, key: str, detail: str = ""):
        super().__init__(f"{key}: {detail}" if detail else key)
        self.key = key
        self.detail = detail


class Cancelled(SetupError):
    def __init__(self):
        super().__init__("cancelled")


def tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if CA_BUNDLE.is_file():
        context.load_verify_locations(cafile=str(CA_BUNDLE))
    return context


def this_platform() -> tuple[str, str]:
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    return platform.system(), machine


def valid_area(bbox) -> tuple[float, float, float, float] | None:
    """WEST, SOUTH, EAST, NORTH in degrees, small enough to download a city's detail."""
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox):
        return None
    w, s, e, n = (float(v) for v in bbox)
    if not (-180 <= w < e <= 180 and -85 <= s < n <= 85):  # also false for NaN
        return None
    if (e - w) * (n - s) > MAX_AREA:
        return None
    return w, s, e, n


def replace(source: Path, target: Path) -> None:
    """os.replace, waiting for whoever is still reading the old file.

    Windows refuses to replace an open file (measured on Windows 11: WinError 5), such as a
    map being searched or loaded by a phone. It is free a moment later.
    """
    deadline = time.monotonic() + REPLACE_WAIT
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.25)


def _free(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Another Campanile answers itself: a redirect could only send us somewhere else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SetupError("share_none", f"redirect to {newurl}")


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise SetupError("insecure", newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Preparation:
    def __init__(
        self,
        data: Path,
        tools: Path,
        kiwix_port: int = 0,
        sources: Sources | None = None,
        version: str = "dev",
    ):
        self.data = data
        self.maps = data / "maps"
        self.zim = data / "zim"
        self.tools = tools
        self.program = tools.parent  # the folder with campanile/, data/, tools/
        self.version = version
        self.kiwix_port = kiwix_port
        self.sources = sources = sources or Sources()
        handlers = [_HttpsOnly] if sources.https_only else []
        handlers.append(urllib.request.HTTPSHandler(context=tls_context()))
        self._opener = urllib.request.build_opener(*handlers)
        self._opener.addheaders = [("User-Agent", "Campanile (+offline emergency hub)")]
        # The local network, for another Campanile: plain http, no redirects, no proxy.
        self._lan = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects)
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._job: dict | None = None
        self._thread: threading.Thread | None = None
        self._kiwix: subprocess.Popen | None = None

    # -- what the page sees ------------------------------------------------------------

    def state(self) -> dict:
        system = this_platform()
        with self._lock:
            job = dict(self._job) if self._job else None
        return {
            "maps": sorted(f.stem for f in self.maps.glob("*.pmtiles"))
            if self.maps.is_dir()
            else [],
            "wiki": sorted(f.name for f in self.zim.glob("*.zim")) if self.zim.is_dir() else [],
            "supported": {name: system in table for name, table in self.sources.tools.items()},
            "job": job,
            "free": shutil.disk_usage(self._existing(self.maps)).free,
            "extras": self.extras_ready(),
            "copy_bytes": sum(source.stat().st_size for source, _ in self.copy_plan()),
            "drives": [
                {"path": d.path, "name": d.name, "free": _free(d.path)} for d in copying.drives()
            ],
        }

    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_map(self, name: str, bbox, zoom: int) -> bool:
        return self._start(f"map-{name}", self._map_job, name, bbox, zoom)

    def start_wiki(self, lang: str) -> bool:
        return self._start(f"wiki-{lang}", self._wiki_job, lang)

    def start_receive(self, address: str, code: str) -> bool:
        return self._start("receive", self._receive_job, address, code)

    def start_extras(self) -> bool:
        return self._start("extras", self._extras_job)

    def start_copy(self, drive: copying.Drive) -> bool:
        return self._start("copy", self._copy_job, drive)

    def start_update(self, drive: copying.Drive) -> bool:
        return self._start("update", self._update_job, drive)

    def extras_ready(self) -> bool:
        """kiwix-serve for every computer, and Python's installers: what a stick needs."""
        folders = tool_folders(self.sources.tools)
        installers = installer_names(self.sources.installers)
        return all((self.tools / f / names[0]).is_file() for f, names in folders.items()) and all(
            (self.tools / "python" / name).is_file() for name in installers
        )

    def copy_plan(self) -> list[tuple[Path, str]]:
        return copying.plan(
            self.program,
            self.data,
            self.tools,
            self.data / "trusted-keys.json",
            tool_folders(self.sources.tools),
            installer_names(self.sources.installers),
        )

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    # -- jobs ----------------------------------------------------------------------------

    def _start(self, task: str, job, *args) -> bool:
        with self._lock:
            if self.busy():
                return False
            self._cancel.clear()
            self._job = {
                "task": task,
                "step": "start",
                "done": 0,
                "total": None,
                "error": None,
                "detail": "",
                "finished": False,
            }
            self._thread = threading.Thread(target=self._run, args=(job, *args), daemon=True)
            self._thread.start()
        return True

    def _run(self, job, *args) -> None:
        try:
            job(*args)
        except SetupError as e:
            self._update(error=e.key, detail=e.detail[:300])
        except Exception as e:  # whatever happens, the page must hear about it
            self._update(error="failed", detail=f"{type(e).__name__}: {e}"[:300])
        finally:
            self._update(finished=True)

    def _update(self, **changes) -> None:
        with self._lock:
            if self._job is not None:
                self._job.update(changes)

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    def _map_job(self, name: str, bbox, zoom: int) -> None:
        pmtiles = self._tool("pmtiles")
        self._update(step="source", done=0, total=None)
        builds = json.loads(self._text(self.sources.builds))
        keys = sorted(
            b["key"]
            for b in builds
            if isinstance(b, dict) and re.fullmatch(r"\d{8}\.pmtiles", str(b.get("key", "")))
        )
        if not keys:
            raise SetupError("not_found", "no world map in the Protomaps build list")
        self.maps.mkdir(parents=True, exist_ok=True)
        self._need_space(self.maps, EXPECTED_BYTES.get(name, EXPECTED_BYTES["area"]))
        target = self.maps / f"{name}.pmtiles"
        partial = self.maps / f".{name}.pmtiles.partial"
        partial.unlink(missing_ok=True)
        w, s, e, n = bbox
        self._update(step="map", done=0, total=None)
        try:
            self._program(
                [
                    str(pmtiles),
                    "extract",
                    self.sources.world + keys[-1],
                    str(partial),
                    f"--bbox={w},{s},{e},{n}",
                    f"--maxzoom={zoom}",
                ],
                growing=partial,
            )
            self._update(step="verify")
            self._program([str(pmtiles), "verify", str(partial)])
            replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        self._update(step="done", done=target.stat().st_size)

    def _receive_job(self, address: str, code: str) -> None:
        """Maps and Wikipedia from a Campanile nearby: its list must carry our code's signature,
        and every file the SHA-256 the list gives. Nothing here is ever overwritten."""
        self._update(step="source", done=0, total=None)
        try:
            with self._open(address + "/api/share", lan=True) as response:
                body = response.read(TEXT_LIMIT + 1)
            answer = json.loads(body) if len(body) <= TEXT_LIMIT else None
            manifest, signature = answer["manifest"], answer["tag"]
            seen_as = answer.get("you")  # our address, as the other Campanile sees it
            if not isinstance(manifest, str) or not isinstance(signature, str):
                raise TypeError
        except HTTPError as e:
            e.close()
            raise SetupError("share_none", f"HTTP {e.code}") from None
        except (ValueError, KeyError, TypeError):
            raise SetupError("share_none", "not a Campanile sharing") from None
        if not hmac.compare_digest(sharing.tag(code, manifest.encode()), signature):
            raise SetupError("share_code")
        try:
            session, files = sharing.check(manifest)
        except ValueError as e:
            raise SetupError("share_bad", str(e)) from None
        if not isinstance(seen_as, str) or not 0 < len(seen_as) <= 100 or not seen_as.isascii():
            raise SetupError("share_bad", "no address")
        wanted = []
        for f in files:
            target = self._receive_target(self.maps if f["kind"] == "map" else self.zim, f)
            if target is not None:
                wanted.append((f, target))
        self._need_space(self.data, sum(f["bytes"] for f, _ in wanted))
        headers = {sharing.TOKEN_HEADER: sharing.token(code, session, seen_as)}
        for f, target in wanted:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._update(step="share", done=0, total=f["bytes"], detail=f["name"])
            url = f"{address}/api/share/file/{quote(f['name'])}"
            try:
                self._download(url, target, f["sha256"], f["bytes"], headers=headers, lan=True)
            except SetupError as e:  # not internet: the other Campanile, next door
                if e.key == "network":
                    raise SetupError("share_busy" if "503" in e.detail else "share_lost") from None
                raise
        if any(f["kind"] == "wiki" for f, _ in wanted):
            self.start_kiwix()
        self._update(step="done", detail=f"{len(wanted)}")

    @staticmethod
    def _receive_target(folder: Path, f: dict) -> Path | None:
        """None if the file is already here (same SHA-256), else a name not taken."""
        if folder.is_dir():
            for path in folder.iterdir():
                same_size = path.is_file() and path.stat().st_size == f["bytes"]
                if same_size and sha256_of(path) == f["sha256"]:
                    return None
        stem, suffix = f["name"].rsplit(".", 1)
        target, n = folder / f["name"], 2
        while target.exists():  # someone else's map with the same name: kept, ours gets -2
            target, n = folder / f"{stem}-{n}.{suffix}", n + 1
        return target

    def _extras_job(self) -> None:
        """While internet works: what other computers need to start from a stick."""
        self._need_space(self.tools, 400 * 10**6)
        seen = set()
        for system, tool in sorted(self.sources.tools["kiwix-serve"].items()):
            if tool.url not in seen:  # Windows on ARM uses the x64 one
                seen.add(tool.url)
                self._tool("kiwix-serve", system)
        python = self.tools / "python"
        python.mkdir(parents=True, exist_ok=True)
        for installer in self.sources.installers:
            target = python / installer.members[0]
            if not target.is_file():
                self._update(step="installer", done=0, total=None)
                self._download(installer.url, target, installer.sha256, PROGRAM_LIMIT)
        self._update(step="done")

    def _copy_job(self, drive: copying.Drive) -> None:
        files = self.copy_plan()
        self._update(step="copy", done=0, total=sum(s.stat().st_size for s, _ in files))
        try:
            copying.copy(
                files,
                drive,
                self.version,
                progress=lambda done, total: self._update(done=done, total=total),
                cancelled=self._cancel.is_set,
            )
        except copying.CopyError as e:
            if e.key == "cancelled":
                raise Cancelled() from None
            raise SetupError(e.key, e.detail) from None
        self._update(step="copied")

    def _update_job(self, drive: copying.Drive) -> None:
        """Prepares the update; it is applied at the next start (update.py)."""
        source = update.find_program(Path(drive.path))
        if source is None:
            raise SetupError("update_no_program")
        self._update(step="update_copy", done=0, total=None)
        try:
            _, version = update.stage(
                source,
                self.program / update.STAGING,
                self.version,
                progress=lambda done, total: self._update(done=done, total=total),
                cancelled=self._cancel.is_set,
            )
        except copying.CopyError as e:
            if e.key == "cancelled":
                shutil.rmtree(self.program / update.STAGING, ignore_errors=True)
                raise Cancelled() from None
            raise SetupError(e.key, e.detail) from None
        except release.ReleaseError as e:
            raise SetupError(e.args[0]) from None
        self._update(step="update_ready", detail=version)

    def _wiki_job(self, lang: str) -> None:
        self._tool("kiwix-serve")
        prefix = WIKI_PACKAGES[lang]
        self._update(step="source", done=0, total=None)
        index = self._text(self.sources.wikipedia)
        pattern = r'href="(' + re.escape(prefix) + r'_\d{4}-\d{2}\.zim)"'
        names = sorted(set(re.findall(pattern, index)))
        if not names:
            raise SetupError("not_found", prefix)
        name = names[-1]
        target = self.zim / name
        if not target.exists():
            published = self._text(self.sources.wikipedia + name + ".sha256").split()
            if not published or not re.fullmatch(r"[0-9a-f]{64}", published[0]):
                raise SetupError("checksum", "no SHA-256 published for " + name)
            self.zim.mkdir(parents=True, exist_ok=True)
            self._update(step="wiki")
            self._download(self.sources.wikipedia + name, target, published[0], WIKI_LIMIT)
        older = [f for f in self.zim.glob(prefix + "_*.zim") if f.name != name]
        if older:  # the same package, older: replaced
            self.stop_kiwix()  # Windows can't delete a file kiwix-serve still has open
            for old in older:
                old.unlink(missing_ok=True)
        self._update(step="done", done=target.stat().st_size)
        self.start_kiwix()

    # -- pieces ----------------------------------------------------------------------------

    def _tool(self, name: str, system: tuple[str, str] | None = None) -> Path:
        """The program, downloaded once into tools/ and checked against its pinned SHA-256.

        system: another computer's (for the copies on a stick); by default this one's.
        """
        system = system or this_platform()
        tool = self.sources.tools[name].get(system)
        if tool is None:
            raise SetupError("unsupported", "{} {}".format(*system))
        archive_name = Path(urlsplit(tool.url).path).name
        folder = self.tools / tool_folder(tool)
        program = folder / Path(tool.members[0]).name
        if program.is_file():
            return program
        self._update(step="tool", done=0, total=None)
        downloads = self.tools / ".downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        archive = downloads / archive_name
        self._download(tool.url, archive, tool.sha256, PROGRAM_LIMIT)
        unpacking = folder.with_name(folder.name + ".partial")
        shutil.rmtree(unpacking, ignore_errors=True)
        unpacking.mkdir(parents=True)
        # Only the named files, each written under its own plain name: nothing in the
        # archive decides where a file goes.
        for member in tool.members:
            self._extract(archive, member, unpacking / Path(member).name)
        if os.name != "nt":
            (unpacking / program.name).chmod(0o755)
        shutil.rmtree(folder, ignore_errors=True)
        os.replace(unpacking, folder)
        archive.unlink(missing_ok=True)
        return program

    @staticmethod
    def _extract(archive: Path, member: str, out: Path) -> None:
        with contextlib.ExitStack() as stack:
            if archive.name.endswith(".zip"):
                source = stack.enter_context(
                    stack.enter_context(zipfile.ZipFile(archive)).open(member)
                )
            else:
                tar = stack.enter_context(tarfile.open(archive, "r:gz"))
                info = tar.getmember(member)
                if not info.isfile():
                    raise SetupError("failed", f"{member} is not a file")
                source = stack.enter_context(tar.extractfile(info))
            sink = stack.enter_context(open(out, "wb"))
            copied = 0
            while chunk := source.read(CHUNK):
                copied += len(chunk)
                if copied > PROGRAM_LIMIT:
                    raise SetupError("too_big", member)
                sink.write(chunk)

    def _open(self, url: str, headers: dict | None = None, lan: bool = False):
        internet = ("https",) if self.sources.https_only else ("https", "http")
        # Another Campanile, on the local network: plain http, checked by its signature.
        allowed = ("http",) if lan else internet
        if urlsplit(url).scheme not in allowed:
            raise SetupError("insecure", url)
        request = urllib.request.Request(url, headers=headers or {})  # noqa: S310 (checked above)
        try:
            return (self._lan if lan else self._opener).open(request, timeout=NETWORK_TIMEOUT)
        except HTTPError:
            raise
        except (URLError, OSError) as e:
            raise SetupError("network", str(getattr(e, "reason", e))) from e

    def _text(self, url: str) -> str:
        try:
            with self._open(url) as response:
                body = response.read(TEXT_LIMIT + 1)
        except HTTPError as e:
            raise SetupError("network", f"HTTP {e.code}") from e
        if len(body) > TEXT_LIMIT:
            raise SetupError("too_big", url)
        return body.decode("utf-8", "replace")

    def _download(
        self,
        url: str,
        target: Path,
        sha256: str,
        limit: int,
        headers: dict | None = None,
        lan: bool = False,
    ) -> None:
        """Resumes where a previous attempt stopped; lands only if the SHA-256 matches."""
        partial = target.with_name(f".{target.name}.partial")
        start = partial.stat().st_size if partial.exists() else 0
        sent = dict(headers or {}, **({"Range": f"bytes={start}-"} if start else {}))
        try:
            response = self._open(url, sent, lan=lan)
        except HTTPError as e:
            e.close()
            if e.code != 416 or not start:  # 416: the previous attempt had it all
                raise SetupError("network", f"HTTP {e.code}") from e
            response = None
        if response is not None:
            with response:
                if start and response.status != 206:
                    start = 0  # the server ignored the range: from the beginning
                length = response.headers.get("Content-Length")
                total = start + int(length) if length and length.isdigit() else None
                if total and total > limit:
                    raise SetupError("too_big", f"{total} bytes")
                self._need_space(target.parent, (total or 0) - start)
                done = start
                self._update(done=done, total=total)
                with open(partial, "ab" if start else "wb") as out:
                    while True:
                        self._check_cancel()
                        try:
                            chunk = response.read(CHUNK)
                        except OSError as e:
                            raise SetupError("network", str(e)) from e
                        if not chunk:
                            break
                        done += len(chunk)
                        if done > limit:
                            raise SetupError("too_big", f"more than {limit} bytes")
                        out.write(chunk)
                        self._update(done=done)
                if total and done < total:
                    raise SetupError("network", "interrupted: start again to resume")
        self._update(step="check")
        if sha256_of(partial) != sha256:
            partial.unlink(missing_ok=True)
            raise SetupError("checksum", Path(urlsplit(url).path).name)
        replace(partial, target)

    def _program(self, args: list[str], growing: Path | None = None) -> None:
        """Runs a pinned program (no shell), and stops it if the job is cancelled."""
        log_path = self.tools / ".last-run.log"
        self.tools.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + TOOL_TIMEOUT
        with open(log_path, "wb") as log:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log)  # noqa: S603
            try:
                while process.poll() is None:
                    if self._cancel.is_set() or time.monotonic() > deadline:
                        process.kill()
                        process.wait()
                        self._check_cancel()
                        raise SetupError("failed", "took too long")
                    if growing is not None and growing.exists():
                        self._update(done=growing.stat().st_size)
                    time.sleep(0.5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        if process.returncode != 0:
            tail = log_path.read_bytes()[-300:].decode("utf-8", "replace").strip()
            raise SetupError("failed", tail or f"exit code {process.returncode}")

    def _need_space(self, folder: Path, size: int) -> None:
        free = shutil.disk_usage(self._existing(folder)).free
        if free < size + RESERVE:
            raise SetupError("disk", f"{free // 10**6} MB free")

    @staticmethod
    def _existing(folder: Path) -> Path:
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent
        return folder

    # -- Wikipedia on the laptop -------------------------------------------------------

    def kiwix_program(self) -> Path | None:
        tool = self.sources.tools["kiwix-serve"].get(this_platform())
        if tool is None:
            return None
        program = self.tools / tool_folder(tool) / Path(tool.members[0]).name
        return program if program.is_file() else None

    @staticmethod
    def _runnable(program: Path) -> Path:
        """Linux may not run programs from a stick formatted FAT (it mounts it "showexec"):
        then a copy in the user's own cache folder can run."""
        if os.name == "nt" or os.access(program, os.X_OK):
            return program
        cache = Path.home() / ".cache" / "campanile" / program.parent.name
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        local = cache / program.name
        if not local.is_file() or not filecmp.cmp(program, local, shallow=False):
            partial = cache / f".{program.name}.partial"
            shutil.copyfile(program, partial)
            partial.chmod(0o700)
            os.replace(partial, local)
        return local

    def start_kiwix(self) -> bool:
        """(Re)starts kiwix-serve on the ZIM files in data/zim, if there are any."""
        program = self.kiwix_program()
        zims = sorted(self.zim.glob("*.zim")) if self.zim.is_dir() else []
        if not self.kiwix_port or program is None or not zims:
            return False
        self.stop_kiwix()
        self._kiwix = subprocess.Popen(  # noqa: S603
            [
                str(self._runnable(program)),
                f"--port={self.kiwix_port}",
                "--blockexternal",
                "--skipInvalid",
                "--ipConnectionLimit=16",
                f"--attachToProcess={os.getpid()}",  # it stops if the Campanile dies
                *map(str, zims),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    def stop_kiwix(self) -> None:
        if self._kiwix and self._kiwix.poll() is None:
            self._kiwix.terminate()
            try:
                self._kiwix.wait(5)
            except subprocess.TimeoutExpired:
                self._kiwix.kill()
                self._kiwix.wait()
        self._kiwix = None
