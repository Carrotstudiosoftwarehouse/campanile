# DEVELOPED BY CARROTSTUDIO software house
"""What phones, and other Campaniles, can ask for: status, board, "I'm safe", notices, map
search, routes and sharing."""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import threading
import time

import files
import places
import routes
import sharing
import store
from store import RequestError, clean_text, normalize_name, parse_id

SEARCH_WAIT = 0.25  # a waiting search holds a connection: past this, "try again in a moment"


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


class PublicApi:
    """Anyone on the network: the request handler's part for phones and other Campaniles."""

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
            if f.is_file() and files.MAP_NAME.fullmatch(f.name)
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
                    "version": self.version,
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
            # A map may have arrived since the start: its streets are built now, and pages wait
            # while "building". Asked before the list, so a build ending meanwhile is in it.
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

    def _public_post(self, path: str, data: dict):
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

        raise RequestError(404, "unknown_api")

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
