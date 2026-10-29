#!/usr/bin/env python3
# DEVELOPED BY CARROTSTUDIO software house
"""Campanile's server: pages, board, "I'm safe", notices and maps.

Standard library only, so it runs wherever Python does.

    python3 campanile/server.py                  # this computer only
    python3 campanile/server.py --host 0.0.0.0   # the whole local network

Here the parts come together: transport.py takes the requests, files.py serves pages and
maps, api.py answers phones and other Campaniles, admin.py the admin page.
"""

from __future__ import annotations

import argparse
import os
import threading
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import admin
import api
import devices
import files
import places
import preparation
import routes
import sharing
import signing
import store
import transport
from store import RequestError

VERSION = "0.1.1"

HERE = Path(__file__).resolve().parent

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


class Handler(admin.AdminApi, api.PublicApi, files.Files, transport.RequestHandler):
    """Every request, sent to the part that answers it."""

    server_version = "Campanile/" + VERSION
    version = VERSION

    def _get(self):
        url = urlsplit(self.path)
        path = unquote(url.path)
        if not path.startswith("/api/"):
            return self._static(path)  # pages and maps
        if self.command == "HEAD":
            raise RequestError(405, "method_not_allowed")
        return self._api_get(path, parse_qs(url.query))

    def _post(self):
        path = urlsplit(self.path).path
        # Room for a CAP alert only where the admin page works at all (the body is read before
        # the password is checked).
        admin_here = self.cfg.admin_from_network or self._ip in transport.LOCAL_ADDRESSES
        big = path == "/api/admin/cap" and admin_here
        data = self._read_json(admin.CAP_BODY if big else transport.MAX_BODY)
        if path.startswith(("/api/admin/", "/api/setup/")):
            return self._admin(path, data)
        return self._public_post(path, data)


def create_server(host: str, port: int, cfg: Config, **options) -> transport.CampanileServer:
    if cfg.behind_proxy:
        # Every connection comes from nginx, which already caps connections per phone.
        options.setdefault("max_per_ip", options.get("max_connections", transport.MAX_CONNECTIONS))
    handler = type("CampanileHandler", (Handler,), {"cfg": cfg})
    return transport.CampanileServer((host, port), handler, **options)


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
