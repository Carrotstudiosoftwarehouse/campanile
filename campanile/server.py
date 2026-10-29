#!/usr/bin/env python3
# DEVELOPED BY CARROTSTUDIO software house
"""Campanile's server: pages, board, "I'm safe", notices and maps.

Standard library only, so it runs wherever Python does.

    python3 campanile/server.py                  # this computer only
    python3 campanile/server.py --host 0.0.0.0   # the whole local network
"""

from __future__ import annotations

import _socket
import argparse
import contextlib
import hmac
import ipaddress
import json
import math
import os
import re
import socket
import sys
import threading
import time
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import cap
import copying
import devices
import messages
import pfif
import places
import preparation
import routes
import sharing
import signing
import store
import strictjson
from store import RequestError, clean_text, normalize_name, parse_id

VERSION = "0.1.0"

HERE = Path(__file__).resolve().parent

MAX_BODY = 8 * 1024
MAX_CONNECTIONS = 256
MAX_CONNECTIONS_PER_IP = 16
CONNECTION_TIMEOUT = 30
# Seconds allowed for a whole request, so a client dripping one byte at a time can't hold a
# connection forever (slowloris).
REQUEST_DEADLINE = 10
# When every slot is taken, idle keep-alive connections make room first: browsers reopen them
# silently, while a phone turned away gets a half-loaded page (measured: 300 phones arriving
# within 5 s, 236 without a home page).
EVICT_AFTER = 1.0
# Then answers still being sent, from the device holding the most slots. A phone needs a few,
# so a slow reader on many connections crowds out only himself (measured: 256 slow readers
# held every slot for 90 s, and a phone failed 23 times in 23).
FAIR_SHARE = 4
EVICT_BATCH = 8
SLOT_WAIT = 3.0
# Bounds for draining a body we answered without reading: nobody can hold a slot with it.
LINGER_SECONDS = 2.0
LINGER_BYTES = 64 * 1024
RATE_WINDOW = 600
MAX_WRITES_PER_IP = 10
MAX_WRONG_CODES = 20
# Flood brake: past this many new posts in the window, new ones wait for the admin.
FLOOD_POSTS = 30
FLOOD_WINDOW = 300
SEARCHES = 30  # map searches per device in SEARCH_WINDOW seconds: typing makes a few
SEARCH_WINDOW = 10
ROUTES = 10  # routes per device in SEARCH_WINDOW seconds: each choice of mode makes one
# Seconds of routing per device in SEARCH_WINDOW: on a slow Raspberry or a big map a few
# routes take long, and one phone must not keep the navigator from everyone.
ROUTE_SECONDS = 2.0
SEARCHING = 1  # map searches at the same time: the others wait their turn, briefly
SEARCH_WAIT = 0.25  # a waiting search holds a connection: past this, "try again in a moment"
_DEVICE_TAG = re.compile(r"[0-9a-f]{12}")
CHUNK_SIZE = 64 * 1024

LOCAL_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
# A web page can make the browser call 127.0.0.1 under its own name (DNS rebinding):
# the setup page answers only to the names this computer really has.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
# The same trick works on the whole Campanile, to read the board from internet, but such a
# name always ends in a registered domain. Names nobody can register are fine.
LOCAL_SUFFIXES = (".local", ".localhost", ".home.arpa", ".internal", ".lan", ".home")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".pbf": "application/x-protobuf",
    ".pmtiles": "application/octet-stream",
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; worker-src 'self' blob:; "
        "connect-src 'self'; style-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}

_RANGE = re.compile(r"^bytes=([0-9]{0,15})-([0-9]{0,15})$")  # ASCII digits, a sane length
_MAP_NAME = re.compile(r"[A-Za-z0-9_-]+\.pmtiles")


class Config:
    def __init__(
        self,
        *,
        web: Path,
        data: Path,
        portal: str | None = None,
        hostnames: Iterable[str] = (),
        kiwix_port: int = 0,
        admin_password: str | None = None,
        admin_from_network: bool = False,
        behind_proxy: bool = False,
        arp_table: Path = devices.ARP_TABLE,
        public_url: str | None = None,
        kiwix_url: str | None = None,
        trusted_keys: Path | None = None,
        require_signed: bool = False,
        kiwix_backend_port: int = 0,
        setup: preparation.Preparation | None = None,
        post_days: int = store.POST_DAYS,
        safe_days: int = store.SAFE_DAYS,
        emergency: str = store.EMERGENCY,
    ):
        self.web = web.resolve()
        self.maps = (data / "maps").resolve()
        self.portal = portal or None
        self.hostnames = {h.lower() for h in [*hostnames, portal] if h}
        self.kiwix_port = kiwix_port
        # Behind nginx the phone's port (8081) and kiwix's own port (8082) differ.
        self.kiwix_backend_port = kiwix_backend_port or kiwix_port
        self.admin_password = admin_password
        self.admin_from_network = admin_from_network
        self.behind_proxy = behind_proxy
        self.public_url = public_url or None
        self.kiwix_url = kiwix_url or None
        self.trusted_keys = signing.TrustedKeys.load(trusted_keys)
        self.require_signed = require_signed
        self.emergency = emergency  # until the admin page sets one
        self.store = store.Store(data / "campanile.db", post_days, safe_days)
        self.write_limit = store.RateLimiter(MAX_WRITES_PER_IP, RATE_WINDOW)
        self.wrong_code_limit = store.RateLimiter(MAX_WRONG_CODES, RATE_WINDOW)
        self.post_flow = store.RateLimiter(FLOOD_POSTS, FLOOD_WINDOW)
        self.search_limit = store.RateLimiter(SEARCHES, SEARCH_WINDOW)
        self.safe_search_limit = store.RateLimiter(SEARCHES, SEARCH_WINDOW)
        # Searching is the only real work a phone can ask for: one at a time, so however
        # many phones search, the rest of the Campanile answers as fast as ever.
        self.searching = threading.BoundedSemaphore(SEARCHING)
        self.route_limit = store.RateLimiter(ROUTES, SEARCH_WINDOW)
        self.route_time = store.RateLimiter(ROUTE_SECONDS, SEARCH_WINDOW)
        self.routing = threading.BoundedSemaphore(SEARCHING)
        # The names too: each search goes through every name, under the database's one lock.
        self.safe_searching = threading.BoundedSemaphore(SEARCHING)
        self.device_tags = devices.DeviceTags(arp_table)
        self.setup = setup
        self.places = places.Places(self.maps, data / "places")
        self.routes = routes.Routes(self.maps, data / "routes")
        self.routes.reload_closed(self.store)  # the database decides what is blocked
        self.share = sharing.Share(self.maps, (data / "zim").resolve())


# On Windows "a:b" is the hidden stream b of file a (measured: we served a download's
# Zone.Identifier, which says where it came from), "\\" is a separator, and a trailing dot or
# space is dropped. None of our files has such names, so these paths are treated as missing.
_WINDOWS_TRICKS = re.compile(r"[:\\]|[. ](/|$)")


def safe_path(root: Path, relative: str) -> Path | None:
    """Nobody gets out of the root folder: no ../../etc/passwd tricks."""
    if "\x00" in relative or _WINDOWS_TRICKS.search(relative):
        return None
    candidate = (root / relative.lstrip("/")).resolve()
    return candidate if candidate.is_relative_to(root) else None


def parse_range(value: str, size: int):
    """Reads the Range header the map uses to fetch only the pieces it needs.

    One range at a time: if more are asked for we send the whole file, which is
    allowed. Returns (start, end), None, or "invalid".
    """
    m = _RANGE.match(value.strip())
    if not m or m.group(1) == m.group(2) == "":
        return None
    first, last = m.groups()
    if first == "":
        n = int(last)
        if n == 0 or size == 0:
            return "invalid"
        return max(0, size - n), size - 1
    start = int(first)
    if start >= size:
        return "invalid"
    end = size - 1 if last == "" else min(int(last), size - 1)
    return (start, end) if end >= start else None


def lan_address() -> str | None:
    """The address phones use to reach this computer on the local network.

    The UDP socket sends nothing: it only asks the OS which network card it
    would use. That's why it works without internet.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.254.254.254", 1))
            ip = s.getsockname()[0]
    except OSError:
        return None
    address = ipaddress.ip_address(ip)
    return ip if address.is_private and not address.is_loopback else None


def kiwix_running(port: int) -> bool:
    if port <= 0:
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Campanile/" + VERSION
    sys_version = ""
    timeout = CONNECTION_TIMEOUT
    # Headers and body leave in two writes: with Nagle on, the body waits for the phone's
    # delayed ACK, 40 ms on every answer (measured on Linux).
    disable_nagle_algorithm = True
    cfg: Config

    def log_message(self, format, *args):
        """No access log: we don't want to know who connects."""

    def date_time_string(self, timestamp=None):
        """The Date phones read their clock against: the Campanile's, as corrected."""
        return super().date_time_string(self.cfg.store.now() if timestamp is None else timestamp)

    def log_error(self, format, *args):
        if format.startswith("Request timed out"):
            return  # an idle browser connection timing out: normal, not worth logging
        print("[campanile] " + format % args, flush=True)

    def handle_one_request(self):
        # Behind nginx one connection may carry several phones' requests: nothing per-phone
        # may survive from one request to the next.
        self._device_tag = None
        self._body_left = False
        self.server.watch(self)
        try:
            super().handle_one_request()
        finally:
            self.server.unwatch(self)
            # An unread body would be parsed as the next request, with headers its sender
            # wrote: behind nginx, its own X-Real-IP (measured).
            if self._body_left:
                self.close_connection = True

    def parse_request(self):
        ok = super().parse_request()
        if ok:
            lengths = self.headers.get_all("Content-Length") or ()
            self._body_left = "Transfer-Encoding" in self.headers or any(n != "0" for n in lengths)
        if self.command != "POST":  # POST keeps the clock running until its body is read
            self.server.unwatch(self)
        return ok

    def do_GET(self):
        self._handle(self._get)

    def do_HEAD(self):
        self._handle(self._get)

    def do_POST(self):
        self._handle(self._post)

    def finish(self):
        super().finish()
        if self.close_connection and getattr(self, "_body_left", False):
            linger(self.connection)

    @property
    def _lang(self) -> str:
        return messages.pick_language(self.headers.get("Accept-Language"))

    def _check_framing(self):
        """A body only on POST, measured by a single Content-Length: no chunked, no guessing.

        A proxy and this server must agree on where each request ends; anything else is
        refused rather than interpreted.
        """
        lengths = self.headers.get_all("Content-Length") or ()
        if (
            "Transfer-Encoding" in self.headers
            or len(lengths) > 1
            or (self._body_left and self.command != "POST")
        ):
            self.close_connection = True  # where this request ends is anyone's guess
            raise RequestError(400, "bad_framing")

    def _handle(self, method):
        try:
            self._check_framing()
            if self._should_redirect():
                return self._redirect(f"http://{self.cfg.portal}/")
            if not self._known_host():
                raise RequestError(421, "unknown_host")
            method()
        except RequestError as e:
            if self._body_left:
                self.close_connection = True
            with contextlib.suppress(OSError):  # the client may already be gone
                self._json(e.status, {"error": e.text(self._lang)})
        except OSError:
            self.close_connection = True
        except Exception as e:
            full = store.disk_full(e)
            self.log_error("disk full: %r" if full else "internal error: %r", e)
            self.close_connection = True  # the response may already have started
            with contextlib.suppress(OSError):
                key = "disk_full" if full else "internal"
                self._json(507 if full else 500, {"error": messages.text(key, self._lang)})

    def _headers(
        self, status: int, mime: str | None, length: int, extra: dict[str, str] | None = None
    ):
        self.send_response(status)
        if self.close_connection:  # so the phone or nginx doesn't send another request
            self.send_header("Connection", "close")
        if mime:
            self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        for name, value in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(name, value)
        self.end_headers()

    def _json(self, status: int, data) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self._headers(
            status, "application/json; charset=utf-8", len(body), {"Cache-Control": "no-store"}
        )
        if self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.close_connection = True
        self._headers(302, None, 0, {"Location": location, "Cache-Control": "no-store"})

    def _host(self) -> str:
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):
            return host.split("]")[0] + "]"
        return host.rsplit(":", 1)[0]

    def _should_redirect(self) -> bool:
        return bool(self.cfg.portal) and self._host() not in self.cfg.hostnames

    def _known_host(self) -> bool:
        """An address, a name of this network or one of ours: never a domain of internet."""
        host = self._host().rstrip(".")
        if "." not in host or host in self.cfg.hostnames or host.endswith(LOCAL_SUFFIXES):
            return True  # also no name at all, and the computer's own: "raspberrypi"
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            return False
        return True

    def _get(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        if path.startswith("/api/"):
            if self.command == "HEAD":
                raise RequestError(405, "method_not_allowed")
            return self._api_get(path, parse_qs(url.query))
        if path.startswith("/maps/"):
            name = path.removeprefix("/maps/")
            if not _MAP_NAME.fullmatch(name):
                raise RequestError(404, "map_not_found")
            return self._file(safe_path(self.cfg.maps, name))
        if path.endswith("/"):
            path += "index.html"
        return self._file(safe_path(self.cfg.web, path))

    def _file(self, file: Path | None, rate: int | None = None):
        if file is None or not file.is_file():
            raise RequestError(404, "not_found")
        stat = file.stat()
        size = stat.st_size
        extra = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "ETag": f'"{stat.st_mtime_ns:x}-{size:x}"',
        }

        byte_range = None
        if "Range" in self.headers:
            byte_range = parse_range(self.headers["Range"], size)
            if byte_range == "invalid":
                return self._headers(416, None, 0, {"Content-Range": f"bytes */{size}"})

        if byte_range is None:
            start, end, status = 0, size - 1, 200
        else:
            (start, end), status = byte_range, 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = end - start + 1

        mime = MIME_TYPES.get(file.suffix.lower(), "application/octet-stream")
        self._headers(status, mime, length, extra)
        if self.command == "HEAD":
            return
        self.server.responding(self)
        try:
            with open(file, "rb") as f:
                f.seek(start)
                began, sent = time.monotonic(), 0
                while length > 0 and (chunk := f.read(min(CHUNK_SIZE, length))):
                    self.wfile.write(chunk)
                    length -= len(chunk)
                    sent += len(chunk)
                    if rate and (ahead := sent / rate - (time.monotonic() - began)) > 0:
                        time.sleep(ahead)  # bytes per second, at most
        finally:
            self.server.done_responding(self)

    def _maps(self) -> list[dict]:
        if not self.cfg.maps.is_dir():
            return []
        routable = self.cfg.routes.available()
        return [
            {
                "name": f.stem,
                "file": f.name,
                "bytes": f.stat().st_size,
                "routes": f.stem in routable,
            }
            for f in sorted(self.cfg.maps.glob("*.pmtiles"))
            if f.is_file() and _MAP_NAME.fullmatch(f.name)
        ]

    def _api_get(self, path: str, query: dict):
        db = self.cfg.store

        def param(name: str) -> str:
            return (query.get(name) or [""])[0]

        if path == "/api/status":
            posts, people = db.counts()
            host = self.cfg.portal or lan_address()
            port = self.server.server_address[1]
            address = self.cfg.public_url or (
                host and (f"http://{host}/" if port == 80 else f"http://{host}:{port}/")
            )
            return self._json(
                200,
                {
                    "version": VERSION,
                    "open_posts": posts,
                    "registered_people": people,
                    "kiwix": kiwix_running(self.cfg.kiwix_backend_port),
                    "kiwix_port": self.cfg.kiwix_port,
                    "kiwix_url": self.cfg.kiwix_url,
                    "signed_notices": len(self.cfg.trusted_keys) > 0,
                    "setup": self.cfg.setup is not None,
                    "maps": self._maps(),
                    "address": address,
                    "emergency": db.emergency() or self.cfg.emergency,
                },
            )
        if path == "/api/maps":
            # A map may have arrived since the start (setup page, another Campanile): its
            # streets are built now, and the pages wait while "building" says so. Asked before
            # the list, so a build that ends in between is in the list. Pages ask this once,
            # then every few seconds only while building: looking each time costs little.
            self.cfg.routes.refresh(now=True)
            building = not self.cfg.routes.ready
            return self._json(200, {"maps": self._maps(), "building": building})
        if path == "/api/notices":
            return self._json(200, {"notices": db.list_notices()})
        if path == "/api/posts":
            kind, category = param("kind"), param("category")
            if kind and kind not in store.POST_KINDS:
                raise RequestError(400, "bad_kind")
            if category and category not in store.CATEGORIES:
                raise RequestError(400, "bad_category")
            return self._json(200, {"posts": db.list_posts(kind, category)})
        if path == "/api/safe":
            if not self.cfg.safe_search_limit.allow(self._device):
                raise RequestError(429, "too_many_searches")
            q = clean_text(param("q"), "name", 80, required=False)
            if len(normalize_name(q)) < 2:
                raise RequestError(400, "search_too_short")
            with _turn(self.cfg.safe_searching, "search_busy"):
                found = db.search_safe(q)
            return self._json(200, {"results": found})
        if path == "/api/share":  # another Campanile asking what is shared, if anything
            found = self.cfg.share.published()
            if found is None:
                raise RequestError(404, "unknown_api")
            # "you": the address we see, the only one its download permission will work from
            return self._json(200, {"manifest": found[0], "tag": found[1], "you": self._ip})
        if path.startswith("/api/share/file/"):
            name = path.removeprefix("/api/share/file/")
            file = self.cfg.share.file(name, self.headers.get(sharing.TOKEN_HEADER), self._ip)
            if file is None:
                raise RequestError(404, "not_found")
            with self.cfg.share.sending() as allowed:
                if not allowed:  # whoever sniffed the token can't open twenty downloads
                    raise RequestError(503, "share_busy")
                return self._file(file, rate=sharing.RATE)
        if path == "/api/places":
            if not self.cfg.search_limit.allow(self._device):
                raise RequestError(429, "too_many_searches")
            q = clean_text(param("q"), "search", 80, required=False)
            if len(places.normalize(q)) < 2:
                raise RequestError(400, "search_too_short")
            with _turn(self.cfg.searching, "search_busy"):
                found = self.cfg.places.search(q, _near(param("near")), self._lang)
            return self._json(200, found)
        if path == "/api/route":
            if self.cfg.route_time.blocked(self._device):
                raise RequestError(429, "too_many_routes")
            if not self.cfg.route_limit.allow(self._device):
                raise RequestError(429, "too_many_routes")
            start, end, mode = _near(param("from")), _near(param("to")), param("by")
            if start is None or end is None or mode not in ("foot", "car"):
                raise RequestError(400, "bad_route")
            with _turn(self.cfg.routing, "route_busy"):
                began = time.monotonic()
                try:
                    found = self.cfg.routes.route(start, end, mode)
                except routes.RouteError as e:
                    busy = e.key in ("route_wait", "route_long")
                    raise RequestError(503 if busy else 404, e.key) from None
                finally:
                    self.cfg.route_time.record(self._device, time.monotonic() - began)
            return self._json(200, found)
        if path == "/api/roads/closed":
            return self._json(200, {"closed": self.cfg.routes.closed()})
        raise RequestError(404, "unknown_api")

    def _read_json(self, most: int = MAX_BODY) -> dict:
        mime = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if mime != "application/json":
            raise RequestError(415, "need_json")
        length = self.headers.get("Content-Length") or ""
        if not re.fullmatch(r"[0-9]{1,9}", length):  # isdigit() would also take "²"
            raise RequestError(411, "need_length")
        if int(length) > most:
            raise RequestError(413, "too_large")
        raw = self.rfile.read(int(length))
        if len(raw) < int(length):  # dropped by the deadline, or the client gave up
            raise RequestError(400, "incomplete")
        self._body_left = False
        self.server.unwatch(self)
        try:
            data = strictjson.loads(raw.decode())
        except (UnicodeDecodeError, ValueError, RecursionError):  # JSONDecodeError is a ValueError
            raise RequestError(400, "bad_json") from None
        if not isinstance(data, dict):
            raise RequestError(400, "need_object")
        return data

    @property
    def _ip(self) -> str:
        peer = self.client_address[0]
        if not self.cfg.behind_proxy or peer not in LOCAL_ADDRESSES:
            return peer
        # nginx puts the phone's address in X-Real-IP, overwriting whatever the phone sent.
        # Missing or malformed means "unknown", never "local": that would open the admin page.
        try:
            return str(ipaddress.ip_address((self.headers.get("X-Real-IP") or "").strip()))
        except ValueError:
            return "unknown"

    @property
    def _device(self) -> str:
        """Per-day tag of the phone; computed once per request."""
        if self._device_tag is None:
            self._device_tag = self.cfg.device_tags.tag(self._ip)
        return self._device_tag

    def _check_write_limit(self):
        if not self.cfg.write_limit.allow(self._device):
            raise RequestError(429, "too_many_writes")

    def _check_code(self, verify, item_id: int, code: str):
        """Only wrong attempts count, so closing your own posts never locks you out."""
        if self.cfg.wrong_code_limit.blocked(self._device):
            raise RequestError(429, "too_many_wrong")
        result = verify(item_id, code)
        if result == store.GONE:
            raise RequestError(404, "already_closed")
        if result == store.WRONG:
            self.cfg.wrong_code_limit.record(self._device)
            raise RequestError(403, "wrong_code")

    def _post(self):
        path = urlsplit(self.path).path
        # A CAP alert is bigger than anything else: room for it, escaped in JSON, but only where
        # the admin page works at all (the body is read before the password is checked).
        admin_here = self.cfg.admin_from_network or self._ip in LOCAL_ADDRESSES
        big = path == "/api/admin/cap" and admin_here
        data = self._read_json(2 * cap.MAX_BYTES + 1024 if big else MAX_BODY)
        db = self.cfg.store

        if path == "/api/posts":
            kind, category = data.get("kind"), data.get("category")
            if kind not in store.POST_KINDS:
                raise RequestError(400, "choose_kind")
            if category not in store.CATEGORIES:
                raise RequestError(400, "bad_category")
            text = clean_text(data.get("text"), "description", 500, multiline=True)
            area = clean_text(data.get("area"), "area", 80)
            contact = clean_text(data.get("contact"), "contact", 120)
            self._check_write_limit()
            # During a flood the board stays readable: new posts wait for the admin.
            pending = not self.cfg.post_flow.allow("all")
            post_id, code = db.add_post(
                kind, category, text, area, contact, device=self._device, pending=pending
            )
            return self._json(201, {"id": post_id, "code": code, "pending": pending})

        if path == "/api/posts/close":
            self._check_code(
                db.close_post,
                parse_id(data.get("id")),
                clean_text(data.get("code"), "code", 20),
            )
            return self._json(200, {"ok": True})

        if path == "/api/safe":
            name = clean_text(data.get("name"), "name", 80)
            if len(normalize_name(name)) < 2:
                raise RequestError(400, "name_too_short")
            message = clean_text(
                data.get("message"), "message", 300, required=False, multiline=True
            )
            place = clean_text(data.get("place"), "place", 80, required=False)
            self._check_write_limit()
            safe_id, code = db.add_safe(name, message, place, device=self._device)
            return self._json(201, {"id": safe_id, "code": code})

        if path == "/api/safe/remove":
            self._check_code(
                db.remove_safe,
                parse_id(data.get("id")),
                clean_text(data.get("code"), "code", 20),
            )
            return self._json(200, {"ok": True})

        if path.startswith(("/api/admin/", "/api/setup/")):
            return self._admin(path, data)

        raise RequestError(404, "unknown_api")

    def _publish_signed(self, signed):
        try:
            notice, signer = self.cfg.trusted_keys.verify(signed, now=self.cfg.store.now())
            sig_hash = signing.signature_hash(signed)
        except signing.SignatureError as e:
            raise RequestError(400, e.args[0]) from None
        _unchanged(notice["title"], "title", 120, multiline=False)
        _unchanged(notice["text"], "text", 1000, multiline=True)
        # Stored re-serialized from what was verified, never as received.
        document = json.dumps(
            {
                "format": signing.FORMAT,
                "notice": notice,
                "signature": signing.signature_b64(signed),
            },
            ensure_ascii=False,
        )
        notice_id = self.cfg.store.add_signed_notice(notice, signer, sig_hash, document)
        self._log("signed_notice", f"{signer}: {notice['title']}")
        return self._json(201, {"id": notice_id, "signer": signer})

    def _publish_cap(self, document):
        if self.cfg.require_signed:  # a CAP alert's signature is not checked here
            raise RequestError(403, "signed_required")
        if not isinstance(document, str):
            raise RequestError(400, "cap_bad")
        try:
            alert = cap.read(document, [self._lang, *messages.LANGUAGES], self.cfg.store.now())
        except cap.CapError as e:
            raise RequestError(400, e.key, **e.params) from None
        alert.update(
            title=clean_text(alert["title"], "title", cap.TITLE_MAX),
            text=clean_text(alert["text"], "text", cap.TEXT_MAX, multiline=True),
            source=clean_text(alert["source"], "source", 120),
        )
        notice_id = self.cfg.store.add_cap_notice(alert)
        self._log("cap_notice", f"{alert['source']}: {alert['title']}")
        return self._json(
            201, {"id": notice_id, "title": alert["title"], "source": alert["source"]}
        )

    def _admin(self, path: str, data: dict):
        cfg = self.cfg
        if not cfg.admin_password:
            raise RequestError(403, "admin_off")
        if path.startswith("/api/setup/"):
            if cfg.setup is None:
                raise RequestError(404, "unknown_api")
            # It downloads from internet onto this computer: never from the network,
            # whatever --admin-from-network says.
            if self._ip not in LOCAL_ADDRESSES or self._host() not in LOCAL_HOSTS:
                raise RequestError(403, "admin_local_only")
        # On the open Wi-Fi the password would travel in clear text, so admin
        # only works from the Campanile itself: its own screen or an SSH tunnel.
        if not cfg.admin_from_network and self._ip not in LOCAL_ADDRESSES:
            raise RequestError(403, "admin_local_only")
        key = "admin:" + self._ip
        if cfg.wrong_code_limit.blocked(key):
            raise RequestError(429, "too_many_wrong")
        who = self._admin_name(data.get("password"))
        if who is None:
            cfg.wrong_code_limit.record(key)
            raise RequestError(403, "wrong_password")
        self._who = who

        if path.startswith("/api/setup/"):
            return self._setup(path, data)
        if path == "/api/admin/me":
            return self._json(200, {"name": who})
        if path.startswith("/api/admin/people"):
            return self._people(path, data)
        if path == "/api/admin/roads/close":
            lon, lat = _coordinate(data.get("lon"), 180), _coordinate(data.get("lat"), 90)
            note = clean_text(data.get("note"), "note", 120, required=False)
            street = cfg.routes.street_at(lon, lat)
            if street is None:
                raise RequestError(404, "no_street_here")
            road = cfg.store.add_closed_road(lon, lat, street["name"], note)
            cfg.routes.reload_closed(cfg.store)
            self._log("road_closed", street["name"])
            reply = {"id": road, **{k: street[k] for k in ("name", "lines", "open")}}
            return self._json(201, reply)
        if path == "/api/admin/roads/open":
            road = parse_id(data.get("id"))
            if not cfg.store.open_road(road):
                raise RequestError(404, "item_not_found")
            cfg.routes.reload_closed(cfg.store)
            self._log("road_opened", f"#{road}")
            return self._json(200, {"ok": True})
        if path == "/api/admin/share/start":
            cfg.share.start()
            self._log("share_started")
            return self._json(200, cfg.share.state())
        if path == "/api/admin/share/stop":
            cfg.share.stop()
            self._log("share_stopped")
            return self._json(200, cfg.share.state())
        if path == "/api/admin/log":
            days = {k: v // 86400 for k, v in cfg.store.keep.items()}
            log = cfg.store.admin_log()
            return self._json(200, {"log": log, "now": cfg.store.now(), "keep": days})
        if path == "/api/admin/clock":
            real = data.get("now")
            if isinstance(real, bool) or not isinstance(real, (int, float)):
                raise RequestError(400, "bad_time")
            before = cfg.store.now()
            now = cfg.store.set_clock(real)
            self._log("clock_set", f"{now - before:+d}")  # seconds: the page says them
            return self._json(200, {"now": now})
        if path == "/api/admin/emergency":
            number = cfg.store.set_emergency(data.get("number"))
            self._log("emergency_set", number)
            return self._json(200, {"emergency": number})
        if path == "/api/admin/share/state":
            return self._json(200, cfg.share.state())
        if path == "/api/admin/list":
            return self._json(
                200,
                {
                    "posts": cfg.store.list_posts(limit=store.MAX_OPEN_POSTS, with_device=True),
                    "pending": cfg.store.list_pending(),
                    "safe": cfg.store.all_safe(),
                },
            )
        if path == "/api/admin/notices/signed":
            return self._publish_signed(data.get("signed"))
        if path == "/api/admin/notices":
            if cfg.require_signed:
                raise RequestError(403, "signed_required")
            title = clean_text(data.get("title"), "title", 120)
            text = clean_text(data.get("text"), "text", 1000, multiline=True)
            notice_id = cfg.store.add_notice(title, text, data.get("urgent") is True)
            self._log("notice", title)
            return self._json(201, {"id": notice_id})
        if path == "/api/admin/cap":
            return self._publish_cap(data.get("cap"))
        if path == "/api/admin/pfif":
            people = cfg.store.all_safe()
            domain = f"campanile-{cfg.store.instance()}.invalid"  # .invalid: never a real site
            document = pfif.export(people, domain, cfg.store.now(), cfg.store.keep["safe"])
            self._log("pfif_export", str(len(people)))
            return self._json(200, {"pfif": document.decode(), "count": len(people)})
        if path == "/api/admin/approve":
            post = parse_id(data.get("id"))
            if not cfg.store.approve_post(post):
                raise RequestError(404, "pending_not_found")
            self._log("approved", f"#{post}")
            return self._json(200, {"ok": True})
        if path in ("/api/admin/close-device", "/api/admin/remove-device-safe"):
            device = data.get("device")
            if not isinstance(device, str) or not _DEVICE_TAG.fullmatch(device):
                raise RequestError(400, "bad_device")
            if path == "/api/admin/close-device":
                closed = cfg.store.close_device_posts(device)
                self._log("device_closed", f"{device}: {closed}")
                return self._json(200, {"closed": closed})
            removed = cfg.store.remove_device_safe(device)
            self._log("device_safe_removed", f"{device}: {removed}")
            return self._json(200, {"removed": removed})
        if path == "/api/admin/close-recent":
            minutes = data.get("minutes")
            if (
                isinstance(minutes, bool)
                or not isinstance(minutes, int)
                or not 1 <= minutes <= 1440
            ):
                raise RequestError(400, "bad_minutes")
            closed = cfg.store.close_recent_posts(minutes)
            self._log("recent_closed", f"{minutes} min: {closed}")
            return self._json(200, {"closed": closed})
        if path == "/api/admin/delete":
            table, item = data.get("table"), parse_id(data.get("id"))
            if not cfg.store.delete(table, item):
                raise RequestError(404, "item_not_found")
            self._log("deleted", f"{table} #{item}")
            return self._json(200, {"ok": True})
        raise RequestError(404, "unknown_api")

    def _admin_name(self, password) -> str | None:
        """'' for the main password, a person's name for theirs, None for anything else."""
        if not isinstance(password, str):
            return None
        # surrogatepass: a lone surrogate must be a wrong password, not a crash
        if hmac.compare_digest(
            password.encode("utf-8", "surrogatepass"), self.cfg.admin_password.encode()
        ):
            return ""
        return self.cfg.store.admin_by_password(password)

    def _people(self, path: str, data: dict):
        """Only the main password adds or removes the people who run the Campanile."""
        if self._who:
            raise RequestError(403, "main_password_only")
        db = self.cfg.store
        if path == "/api/admin/people":
            return self._json(200, {"people": db.admins()})
        if path == "/api/admin/people/add":
            name = clean_text(data.get("name"), "name", 40)
            person, password = db.add_admin(name)
            self._log("person_added", name)
            return self._json(201, {"id": person, "name": name, "password": password})
        if path == "/api/admin/people/remove":
            name = db.remove_admin(parse_id(data.get("id")))
            if name is None:
                raise RequestError(404, "item_not_found")
            self._log("person_removed", name)
            return self._json(200, {"ok": True})
        raise RequestError(404, "unknown_api")

    def _log(self, action: str, detail: str = "") -> None:
        self.cfg.store.log(action, detail, who=self._who)

    def _setup(self, path: str, data: dict):
        setup = self.cfg.setup
        if path == "/api/setup/state":
            return self._json(200, setup.state())
        if path == "/api/setup/cancel":
            setup.cancel()
            return self._json(200, {"ok": True})
        if path != "/api/setup/start":
            raise RequestError(404, "unknown_api")
        task = data.get("task")
        if task == "map-world":
            started = setup.start_map("world", preparation.WORLD, preparation.WORLD_ZOOM)
        elif task == "map-area":
            area = preparation.valid_area(data.get("bbox"))
            if area is None:
                raise RequestError(400, "bad_area")
            started = setup.start_map("area", area, preparation.AREA_ZOOM)
        elif task == "wiki":
            lang = data.get("lang")
            if not isinstance(lang, str) or lang not in preparation.WIKI_PACKAGES:
                raise RequestError(400, "bad_language")
            started = setup.start_wiki(lang)
        elif task == "receive":
            address = sharing.lan_address(data.get("address"))
            if address is None:
                raise RequestError(400, "bad_address")
            code = sharing.normalize(data.get("code"))
            if code is None:
                raise RequestError(400, "bad_code")
            started = setup.start_receive(address, code)
        elif task == "extras":
            started = setup.start_extras()
        elif task in ("copy", "update"):
            # Only a drive the computer itself lists: the page never names a path.
            drive = next((d for d in copying.drives() if d.path == data.get("drive")), None)
            if drive is None:
                raise RequestError(400, "bad_drive")
            started = setup.start_copy(drive) if task == "copy" else setup.start_update(drive)
        else:
            raise RequestError(400, "bad_task")
        if not started:
            raise RequestError(409, "setup_busy")
        return self._json(202, {"ok": True})


@contextlib.contextmanager
def _turn(semaphore: threading.BoundedSemaphore, busy: str):
    """One at a time: whoever waits past SEARCH_WAIT hears "try again in a moment", so a crowd
    of costly requests never piles up on the rest of the Campanile."""
    if not semaphore.acquire(timeout=SEARCH_WAIT):
        raise RequestError(503, busy)
    try:
        yield
    finally:
        semaphore.release()


def _near(value: str) -> tuple[float, float] | None:
    """'lon,lat' of the middle of the phone's map: what is close comes first."""
    if not value:
        return None
    try:
        lon, lat = (float(v) for v in value.split(","))
    except ValueError:
        raise RequestError(400, "bad_number") from None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):  # also false for NaN
        raise RequestError(400, "bad_number")
    return lon, lat


def _coordinate(value, limit: float) -> float:
    """A longitude or latitude from JSON, which also takes NaN, Infinity and 10**400."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RequestError(400, "bad_number")
    try:
        value = float(value)
    except OverflowError:
        raise RequestError(400, "bad_number") from None
    if not math.isfinite(value) or abs(value) > limit:
        raise RequestError(400, "bad_number")
    return value


def _unchanged(value, label: str, max_length: int, *, multiline: bool) -> str:
    """Signed text can't be cleaned up: it must already be clean, or the signature breaks."""
    if clean_text(value, label, max_length, multiline=multiline) != value:
        raise RequestError(400, "signed_field_invalid", field=label)
    return value


class CampanileServer(ThreadingHTTPServer):
    """One thread per connection, capped in total and per device, so one phone can't take
    every slot."""

    daemon_threads = True
    request_queue_size = 1024  # socketserver's default of 5 refuses a crowd arriving at once

    def __init__(
        self,
        address,
        handler,
        max_connections: int = MAX_CONNECTIONS,
        max_per_ip: int = MAX_CONNECTIONS_PER_IP,
        request_deadline: float = REQUEST_DEADLINE,
    ):
        # Everything ready before binding: if the port is taken, socketserver calls
        # server_close() at once, and it must find what it closes.
        self._slots = threading.BoundedSemaphore(max_connections)
        self._max_per_ip = max_per_ip
        self._per_ip: dict[str, int] = {}
        self._per_ip_lock = threading.Lock()
        self.request_deadline = request_deadline
        # One watchdog for every connection, instead of a timer thread per request
        # (measured: the timers cost about a quarter of the throughput).
        self._watched: dict[int, tuple[float, socket.socket]] = {}
        self._watched_lock = threading.Lock()
        self._answering: dict[int, tuple[float, socket.socket]] = {}  # same lock
        self._stopping = threading.Event()
        threading.Thread(target=self._watchdog, daemon=True).start()
        super().__init__(address, handler)

    def watch(self, handler) -> None:
        with self._watched_lock:
            self._watched[id(handler)] = (
                time.monotonic() + self.request_deadline,
                handler.connection,
            )

    def unwatch(self, handler) -> None:
        with self._watched_lock:
            self._watched.pop(id(handler), None)

    def responding(self, handler) -> None:
        with self._watched_lock:
            self._answering[id(handler)] = (
                time.monotonic(),
                handler.connection,
                handler.client_address[0],
            )

    def done_responding(self, handler) -> None:
        with self._watched_lock:
            self._answering.pop(id(handler), None)

    def _watchdog(self) -> None:
        while not self._stopping.wait(0.25):
            now = time.monotonic()
            with self._watched_lock:
                late = [k for k, (deadline, _) in self._watched.items() if deadline <= now]
                sockets = [self._watched.pop(k)[1] for k in late]
            for s in sockets:
                hang_up(s)

    def server_close(self):
        self._stopping.set()
        super().server_close()

    def _take(self, ip: str) -> bool:
        # Only the accept loop calls this, so the per-device count can't grow meanwhile.
        with self._per_ip_lock:
            if self._per_ip.get(ip, 0) >= self._max_per_ip:
                return False
        if not self._slots.acquire(blocking=False):
            self._make_room(EVICT_BATCH)
            if not self._slots.acquire(timeout=SLOT_WAIT):
                return False
        with self._per_ip_lock:
            self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
        return True

    def _make_room(self, count: int) -> None:
        """Frees slots when all are taken: first the connections waiting longest for a request,
        then answers from whichever device holds the most slots, its oldest first."""
        now = time.monotonic()
        with self._per_ip_lock:
            held = dict(self._per_ip)
        with self._watched_lock:
            waiting = sorted(
                (deadline, key)
                for key, (deadline, _) in self._watched.items()
                if deadline - self.request_deadline <= now - EVICT_AFTER
            )
            sockets = [self._watched.pop(key)[1] for _, key in waiting[:count]]
            greedy = sorted(
                (-held.get(ip, 0), started, key)
                for key, (started, _, ip) in self._answering.items()
                if held.get(ip, 0) > FAIR_SHARE
            )
            sockets += [self._answering.pop(key)[1] for *_, key in greedy[: count - len(sockets)]]
        for s in sockets:
            hang_up(s)

    def _give_back(self, ip: str) -> None:
        with self._per_ip_lock:
            left = self._per_ip[ip] - 1
            if left:
                self._per_ip[ip] = left
            else:
                del self._per_ip[ip]
            self._slots.release()

    def process_request(self, request, client_address):
        if not self._take(client_address[0]):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._give_back(client_address[0])
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._give_back(client_address[0])

    def handle_error(self, request, client_address):
        # A phone gone mid-request, or a connection the watchdog closed (only Windows raises
        # for that, WinError 10058): network noise, so no traceback in the window people see.
        if isinstance(sys.exc_info()[1], OSError):
            return
        super().handle_error(request, client_address)


def linger(sock: socket.socket) -> None:
    """Closes gently on a phone that may still be sending a body we didn't read.

    Closing with unread data sends a reset, and on Windows a reset can discard the answer
    already sent (measured: 1 redirected post in 20 lost it). So we stop writing, drain for
    a moment, then close (RFC 9112, 9.6).
    """
    deadline = time.monotonic() + LINGER_SECONDS
    drained = 0
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_WR)
        while drained < LINGER_BYTES and (left := deadline - time.monotonic()) > 0:
            sock.settimeout(left)
            chunk = sock.recv(4096)
            if not chunk:
                break
            drained += len(chunk)


def hang_up(sock: socket.socket) -> None:
    """Ends a connection whose handler thread is blocked reading it.

    On macOS and Linux shutdown() wakes the read (on Linux close() would not). On Windows only
    closing the handle does (measured: after shutdown() the thread waited for its timeout).
    CPython marks the socket closed first, so the thread can't touch a reused handle.
    """
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)
    if os.name == "nt":
        with contextlib.suppress(OSError):
            _socket.socket.close(sock)  # the handle itself, past makefile()'s reference count


def create_server(host: str, port: int, cfg: Config, **options) -> CampanileServer:
    if cfg.behind_proxy:
        # Every connection comes from nginx, which already caps connections per phone.
        options.setdefault("max_per_ip", options.get("max_connections", MAX_CONNECTIONS))
    handler = type("CampanileHandler", (Handler,), {"cfg": cfg})
    return CampanileServer((host, port), handler, **options)


def emergency_number(text: str) -> str:
    if not store.EMERGENCY_FORMAT.fullmatch(text):
        raise argparse.ArgumentTypeError("digits only, 2 to 6 of them")
    return text


def read_password(file: str | None) -> str | None:
    if os.environ.get("CAMPANILE_ADMIN_PASSWORD"):
        return os.environ["CAMPANILE_ADMIN_PASSWORD"]
    if file:
        return Path(file).read_text(encoding="utf-8").strip() or None
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description="Campanile: offline emergency hub for a neighborhood.")
    p.add_argument(
        "--host", default="127.0.0.1", help="address to listen on; 0.0.0.0 for the whole network"
    )
    p.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")
    p.add_argument("--web", type=Path, default=HERE / "web", help="folder with the pages")
    p.add_argument(
        "--data", type=Path, default=HERE.parent / "data", help="folder with database and maps"
    )
    p.add_argument(
        "--portal",
        default="",
        help="Campanile's address on the hotspot (e.g. 10.42.0.1): any other hostname is "
        "redirected here, so phones open the portal by themselves",
    )
    p.add_argument(
        "--hostname",
        action="append",
        default=[],
        help="extra hostname accepted without redirecting (repeatable)",
    )
    p.add_argument(
        "--kiwix-port",
        type=int,
        default=8081,
        help="kiwix-serve port, 0 to disable (default: 8081)",
    )
    p.add_argument(
        "--password-file",
        default=None,
        help="file holding the admin password (or env CAMPANILE_ADMIN_PASSWORD)",
    )
    p.add_argument(
        "--admin-from-network",
        action="store_true",
        help="allow admin from other devices (the password travels in clear text)",
    )
    p.add_argument(
        "--behind-proxy",
        action="store_true",
        help="running behind nginx on this machine: take the phone's address from X-Real-IP",
    )
    p.add_argument(
        "--public-url", default="", help="address printed on the sign, e.g. http://10.42.0.1/"
    )
    p.add_argument("--kiwix-url", default="", help="link to Wikipedia, if not on --kiwix-port")
    p.add_argument(
        "--kiwix-backend-port",
        type=int,
        default=0,
        help="port kiwix-serve really listens on, when nginx publishes it on --kiwix-port",
    )
    p.add_argument(
        "--trusted-keys",
        type=Path,
        default=None,
        help="JSON file with the authorities' public keys, for signed notices",
    )
    p.add_argument(
        "--setup",
        action="store_true",
        help="laptop only: the setup page can download maps and Wikipedia, and kiwix-serve "
        "is started from tools/",
    )
    p.add_argument(
        "--require-signed",
        action="store_true",
        help="refuse official notices that aren't signed by a trusted key",
    )
    p.add_argument(
        "--post-days",
        type=int,
        default=store.POST_DAYS,
        help=f"posts are deleted after this many days, 0 never (default: {store.POST_DAYS})",
    )
    p.add_argument(
        "--safe-days",
        type=int,
        default=store.SAFE_DAYS,
        help=f"'I'm safe' names are deleted after this many days, 0 never "
        f"(default: {store.SAFE_DAYS})",
    )
    p.add_argument(
        "--emergency-number",
        type=emergency_number,
        default=store.EMERGENCY,
        help=f"the number to call in danger, until the admin page sets one "
        f"(default: {store.EMERGENCY})",
    )
    a = p.parse_args(argv)

    cfg = Config(
        web=a.web,
        data=a.data,
        portal=a.portal,
        hostnames=[*a.hostname, "localhost", "127.0.0.1"],
        kiwix_port=a.kiwix_port,
        admin_password=read_password(a.password_file),
        admin_from_network=a.admin_from_network,
        behind_proxy=a.behind_proxy,
        public_url=a.public_url,
        kiwix_url=a.kiwix_url,
        trusted_keys=a.trusted_keys,
        require_signed=a.require_signed,
        kiwix_backend_port=a.kiwix_backend_port,
        setup=preparation.Preparation(a.data, HERE.parent / "tools", a.kiwix_port, version=VERSION)
        if a.setup
        else None,
        post_days=max(0, a.post_days),
        safe_days=max(0, a.safe_days),
        emergency=a.emergency_number,
    )
    server = create_server(a.host, a.port, cfg)
    cfg.places.refresh(now=True)  # the maps are read in the background, once
    cfg.routes.refresh(now=True)  # and their streets, for the routes
    if cfg.setup:
        cfg.setup.start_kiwix()
    print(f"[campanile] {VERSION} on http://{a.host}:{a.port}/", flush=True)
    if not cfg.admin_password:
        print("[campanile] admin disabled: no password set", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if cfg.setup:
            cfg.setup.cancel()
            cfg.setup.stop_kiwix()
        cfg.store.close()


if __name__ == "__main__":
    main()
