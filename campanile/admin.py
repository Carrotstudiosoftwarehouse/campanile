# DEVELOPED BY CARROTSTUDIO software house
"""The admin page, from the Campanile itself only: notices (written, signed or CAP),
moderation, closed roads, people, the clock and the setup page."""

from __future__ import annotations

import hmac
import json
import math
import re

import cap
import copying
import messages
import pfif
import preparation
import sharing
import signing
import store
import transport
from store import RequestError, clean_text, parse_id

# One CAP alert escaped in JSON (IT-alert's pass 100 kB). Admin page only; nginx-site.sh too.
CAP_BODY = 2 * cap.MAX_BYTES + 1024
_DEVICE_TAG = re.compile(r"[0-9a-f]{12}")  # a phone's tag for the day, as devices.py makes it
# A web page can make the browser call 127.0.0.1 under its own name (DNS rebinding):
# the setup page answers only to the names this computer really has.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class AdminApi:
    """The request handler's part for the admin page and the setup page."""

    def _admin(self, path: str, data: dict):
        cfg = self.cfg
        if not cfg.admin_password:
            raise RequestError(403, "admin_off")
        if path.startswith("/api/setup/"):
            if cfg.setup is None:
                raise RequestError(404, "unknown_api")
            # It downloads from internet onto this computer: never from the network,
            # whatever --admin-from-network says.
            if self._ip not in transport.LOCAL_ADDRESSES or self._host() not in LOCAL_HOSTS:
                raise RequestError(403, "admin_local_only")
        # On the open Wi-Fi the password would travel in clear text, so admin
        # only works from the Campanile itself: its own screen or an SSH tunnel.
        if not cfg.admin_from_network and self._ip not in transport.LOCAL_ADDRESSES:
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
