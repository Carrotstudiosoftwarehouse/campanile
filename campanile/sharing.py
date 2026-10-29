# DEVELOPED BY CARROTSTUDIO software house
"""Maps and Wikipedia from one Campanile to another over Wi-Fi, without internet.

Only data travels this way, never programs: those go on a USB stick, handed over in person.
The Campanile that shares shows a code on its own screen, and whoever receives types it. The
list of files, with their SHA-256, is signed with that code (HMAC): a fake Campanile with the
same network name doesn't know it, so neither its list nor any file it swaps gets accepted.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import strictjson

FORMAT = "campanile-share-1"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford's: no I, L, O, U to misread
CODE_LENGTH = 16  # 80 bits: guessing it, even offline, is out of reach
LASTS = 2 * 3600  # seconds: a share ends by itself
RATE = 2 * 2**20  # bytes per second for each download: the Wi-Fi stays usable for the phones
MAX_FILES = 200
MAX_DOWNLOADS = 2  # at the same time: the receiver takes one file at a time
MAX_BYTES = 64 * 10**9  # a whole Wikipedia with images is about 30 GB
MAP_NAME = re.compile(r"[A-Za-z0-9_-]{1,60}\.pmtiles")
ZIM_NAME = re.compile(r"[A-Za-z0-9_.-]{1,120}\.zim")
TOKEN_HEADER = "X-Campanile-Token"  # noqa: S105 (a header's name, not a secret)


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def show(code: str) -> str:
    """'K7QF2M9XR4TA8WHN' -> 'K7QF-2M9X-R4TA-8WHN': easier to read out and to type."""
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))


def normalize(text) -> str | None:
    """The code as typed, forgiving dashes, spaces, lower case, and I/L/O for 1/1/0."""
    if not isinstance(text, str):
        return None
    code = re.sub(r"[\s-]", "", text.upper()).translate(str.maketrans("ILO", "110"))
    return code if len(code) == CODE_LENGTH and all(c in ALPHABET for c in code) else None


def tag(code: str, manifest: bytes) -> str:
    return hmac.new(code.encode(), FORMAT.encode() + b" list\n" + manifest, "sha256").hexdigest()


def token(code: str, session: str, address: str) -> str:
    """The permission to download, valid only from the receiver's address: whoever overhears
    it on the Wi-Fi can't use it from another one to hold the few downloads allowed."""
    message = FORMAT.encode() + b" download\n" + session.encode() + b"\n" + address.encode()
    return hmac.new(code.encode(), message, "sha256").hexdigest()


def lan_address(text) -> str | None:
    """'10.42.0.1' -> 'http://10.42.0.1:80'; 'campanile.local:8080' works too.

    Only addresses of the local network: the other Campanile is next door, not on internet.
    """
    if not isinstance(text, str) or len(text) > 200:
        return None
    text = text.strip()
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        port = parts.port or 80
    except ValueError:
        return None
    host = parts.hostname or ""
    if parts.scheme != "http" or parts.username or parts.password or parts.query:
        return None
    if parts.fragment or parts.path not in ("", "/"):
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63})*\.local", host):
            return None
        return f"http://{host}:{port}"
    if not (ip.is_private or ip.is_loopback or ip.is_link_local) or ip.is_multicast:
        return None
    return f"http://[{ip}]:{port}" if ip.version == 6 else f"http://{ip}:{port}"


def check(manifest: str) -> tuple[str, list[dict]]:
    """The session and the files of a list received from another Campanile. Its signature is
    checked before this is called; this checks that what it says is something we accept."""
    data = strictjson.loads(manifest)
    if not isinstance(data, dict) or set(data) != {"format", "session", "files"}:
        raise ValueError("not a share list")
    if data["format"] != FORMAT:
        raise ValueError("unknown format")
    session, files = data["session"], data["files"]
    if not isinstance(session, str) or not re.fullmatch(r"[0-9a-f]{32}", session):
        raise ValueError("bad session")
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ValueError("bad file list")
    names = set()
    for f in files:
        if not isinstance(f, dict) or set(f) != {"name", "kind", "bytes", "sha256"}:
            raise ValueError("bad file")
        pattern = {"map": MAP_NAME, "wiki": ZIM_NAME}.get(f["kind"])
        if pattern is None or not isinstance(f["name"], str) or not pattern.fullmatch(f["name"]):
            raise ValueError("bad name")
        size = f["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_BYTES:
            raise ValueError("bad size")
        if not isinstance(f["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", f["sha256"]):
            raise ValueError("bad sha256")
        if f["name"] in names:
            raise ValueError("duplicate name")
        names.add(f["name"])
    return session, files


def sha256_file(path: Path, stop=lambda: False) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            if stop():
                raise InterruptedError
            digest.update(chunk)
    return digest.hexdigest()


class Share:
    """The sharing side: one session at a time, started and stopped from the admin page."""

    def __init__(self, maps: Path, zim: Path):
        self.maps, self.zim = maps, zim
        self._lock = threading.Lock()
        self._session: dict | None = None
        self._hashes: dict[tuple, str] = {}  # (path, size, mtime): sha256, so a restart is quick
        self._sending = 0

    def _files(self) -> list[tuple[str, str, Path]]:
        found = []
        for kind, folder, pattern in (("map", self.maps, MAP_NAME), ("wiki", self.zim, ZIM_NAME)):
            if folder.is_dir() and not folder.is_symlink():
                for path in sorted(folder.iterdir()):
                    if pattern.fullmatch(path.name) and path.is_file() and not path.is_symlink():
                        found.append((kind, path.name, path))
        return found

    def start(self) -> None:
        files = self._files()
        session = {
            "code": new_code(),
            "id": secrets.token_hex(16),
            "ends": time.monotonic() + LASTS,
            "files": {name: path for _, name, path in files},
            "done": 0,
            "total": sum(path.stat().st_size for _, _, path in files),
            "published": None,  # (list, tag) once every file is hashed
        }
        with self._lock:
            self._session = session
        threading.Thread(target=self._hash, args=(session, files), daemon=True).start()

    def _hash(self, session: dict, files) -> None:
        listed = []
        try:
            for kind, name, path in files:
                st = path.stat()
                key = (str(path), st.st_size, st.st_mtime_ns)
                if key not in self._hashes:
                    self._hashes[key] = sha256_file(path, lambda: self._session is not session)
                listed.append(
                    {"name": name, "kind": kind, "bytes": st.st_size, "sha256": self._hashes[key]}
                )
                session["done"] += st.st_size
        except (OSError, InterruptedError):
            return
        manifest = json.dumps(
            {"format": FORMAT, "session": session["id"], "files": listed},
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock:
            if self._session is session:
                session["published"] = (manifest, tag(session["code"], manifest.encode()))

    def stop(self) -> None:
        with self._lock:
            self._session = None

    def _live(self) -> dict | None:
        with self._lock:
            if self._session and time.monotonic() > self._session["ends"]:
                self._session = None
            return self._session

    def state(self) -> dict:
        """For the admin page, on the Campanile itself: the code is shown only there."""
        session = self._live()
        if session is None:
            return {"active": False}
        return {
            "active": True,
            "ready": session["published"] is not None,
            "code": show(session["code"]),
            "files": len(session["files"]),
            "bytes": session["total"],
            "done": session["done"],
            "minutes": max(0, round((session["ends"] - time.monotonic()) / 60)),
        }

    def published(self) -> tuple[str, str] | None:
        """(list, signature), for anyone on the Wi-Fi: it holds no secret."""
        session = self._live()
        return session["published"] if session else None

    @contextlib.contextmanager
    def sending(self):
        """True while one of the few downloads allowed at once is ours."""
        with self._lock:
            allowed = self._sending < MAX_DOWNLOADS
            self._sending += allowed
        try:
            yield allowed
        finally:
            if allowed:
                with self._lock:
                    self._sending -= 1

    def file(self, name: str, given: str | None, address: str) -> Path | None:
        """The file to send, if the name is in the list and the download token is right."""
        session = self._live()
        if session is None or session["published"] is None or not isinstance(given, str):
            return None
        right = token(session["code"], session["id"], address)
        if not given.isascii() or not hmac.compare_digest(right, given):
            return None
        return session["files"].get(name)
