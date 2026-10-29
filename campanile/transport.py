# DEVELOPED BY CARROTSTUDIO software house
"""How Campanile takes requests: connections, deadlines and HTTP framing.

Nothing here knows what a request is for: files.py, api.py and admin.py do, and server.py
puts them together.
"""

from __future__ import annotations

import _socket
import contextlib
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import messages
import store
import strictjson
from store import RequestError

if TYPE_CHECKING:
    from server import Config

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

LOCAL_ADDRESSES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
# A web page can make a browser call the Campanile under its own name (DNS rebinding), to
# read the board from internet; but such a name always ends in a registered domain. Names
# nobody can register are fine.
LOCAL_SUFFIXES = (".local", ".localhost", ".home.arpa", ".internal", ".lan", ".home")

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


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP as Campanile speaks it: framing, answers, and who is asking."""

    protocol_version = "HTTP/1.1"
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

    # What each request does is decided in server.Handler.
    def _get(self):
        raise NotImplementedError

    def _post(self):
        raise NotImplementedError


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
