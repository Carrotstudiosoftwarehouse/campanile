# DEVELOPED BY CARROTSTUDIO software house
"""Everything Campanile saves: board posts, "I'm safe" names and official notices."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path

import messages

MAX_OPEN_POSTS = 2000
MAX_PENDING_POSTS = 500
MAX_OPEN_POSTS_PER_DEVICE = 5
MAX_SAFE = 5000
MAX_SAFE_PER_DEVICE = 10  # a family registering its members
MAX_NOTICES = 50
MAX_CLOSED_ROADS = 300
# Nothing stays forever: in an emergency a post two weeks old has almost always passed, while
# someone may look for a relative for weeks. The admin can change both when starting.
POST_DAYS = 14
SAFE_DAYS = 60
FORGET_EVERY = 60  # seconds between looks for what has expired
MAX_LOG = 1000  # entries of what the admin did; older ones go
MAX_ADMINS = 50  # people with a password of their own
MAX_OFFSET = 400 * 86400  # seconds the Campanile's clock may be set away from the computer's
EMERGENCY = "112"  # the number to call in danger, until the admin sets this area's
# Digits only: 112, 911, 999, 000. [0-9], not \d, which also takes other scripts' digits.
EMERGENCY_FORMAT = re.compile(r"[0-9]{2,6}")
MAX_ID = 2**63 - 1  # the largest number SQLite can store

CATEGORIES = (
    "water",
    "food",
    "medicine",
    "power",
    "shelter",
    "transport",
    "help",
    "info",
    "other",
)
POST_KINDS = ("offer", "need")

# Outcomes of checking a post's or a name's code.
OK, WRONG, GONE = "ok", "wrong", "gone"

# No 0/O and no 1/I/L: people must be able to read the code out loud without mistakes.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('offer', 'need')),
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    area TEXT NOT NULL,
    contact TEXT NOT NULL,
    created INTEGER NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0,
    code_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS safe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    search_name TEXT NOT NULL,
    message TEXT NOT NULL,
    place TEXT NOT NULL,
    created INTEGER NOT NULL,
    code_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    urgent INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS open_posts ON posts (closed, created);
CREATE TABLE IF NOT EXISTS admin_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at INTEGER NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    key_hash TEXT NOT NULL UNIQUE,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS closed_roads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lon REAL NOT NULL,
    lat REAL NOT NULL,
    name TEXT NOT NULL,
    note TEXT NOT NULL,
    created INTEGER NOT NULL
);
"""

# Columns added after 0.1.0: (table, name, definition). Old databases get them on start.
ADDED_COLUMNS = (
    ("notices", "signer", "TEXT"),
    ("notices", "issued", "INTEGER"),
    ("notices", "expires", "INTEGER"),
    ("notices", "signature_hash", "TEXT"),
    ("notices", "signed", "TEXT"),
    ("notices", "source", "TEXT"),  # who issued an official CAP alert, as the alert says
    ("notices", "cap_key", "TEXT"),  # the alert's sender and identifier: loaded once
    # device: a tag that changes every day, never the phone's address (see devices.DeviceTags)
    ("posts", "device", "TEXT"),
    ("posts", "pending", "INTEGER NOT NULL DEFAULT 0"),
    ("safe", "device", "TEXT"),
    ("admin_log", "who", "TEXT NOT NULL DEFAULT ''"),  # '' is the main password
)


_LIST_POSTS = (
    "SELECT id, kind, category, text, area, contact, created FROM posts"
    " WHERE closed = 0 AND pending = 0"
)
_LIST_POSTS_ADMIN = (
    "SELECT id, kind, category, text, area, contact, created, device FROM posts"
    " WHERE closed = 0 AND pending = 0"
)


class RequestError(Exception):
    """An error for the user: HTTP status plus a message key, translated when sent."""

    def __init__(self, status: int, key: str, **params):
        super().__init__(messages.text(key, **params))
        self.status = status
        self.key = key
        self.params = params

    def text(self, lang: str) -> str:
        return messages.text(self.key, lang, **self.params)


def clean_text(
    value, label: str, max_length: int, *, required: bool = True, multiline: bool = False
) -> str:
    """Validates user text. `label` is a key of messages.FIELDS, shown in the user's language."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise RequestError(400, "field_not_text", field=label)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate: JSON allows it, UTF-8 can't store it
        raise RequestError(400, "field_not_text", field=label) from None
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if not multiline:
        value = value.replace("\n", " ")
    value = _CONTROL_CHARS.sub("", value)
    # Invisible format characters (bidi overrides, zero-width spaces...) can make a post
    # look different from what it says. The zero-width joiner stays: emoji need it.
    value = "".join(c for c in value if c == "\u200d" or unicodedata.category(c) != "Cf")
    value = value.strip()
    if required and not value:
        raise RequestError(400, "field_required", field=label)
    if len(value) > max_length:
        raise RequestError(400, "field_too_long", field=label, max=max_length)
    return value


def reject_duplicate_keys(pairs: list) -> dict:
    """json.loads hook: {"text": "a", "text": "b"} is refused, not silently resolved.

    Different readers pick different duplicates; with signed notices that would let one
    program verify a text and another display a different one.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def strict_json(raw: str):
    return json.loads(raw, object_pairs_hook=reject_duplicate_keys)


def normalize_name(name: str) -> str:
    """So that "Nicolò  Rossi" is also found by searching "nicolo rossi"."""
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def parse_id(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RequestError(400, "bad_number")
    try:
        number = int(value)
    except ValueError:
        raise RequestError(400, "bad_number") from None
    if not 1 <= number <= MAX_ID:
        raise RequestError(400, "bad_number")
    return number


def disk_full(error: Exception) -> bool:
    """SQLite ran out of disk: reading still works, only writing has to wait."""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    # 13 is SQLITE_FULL; the code is there from Python 3.11, the text on every version.
    return getattr(error, "sqlite_errorcode", None) == 13 or "disk is full" in str(error)


def new_code(groups: int = 2) -> str:
    """Like K7M2-QX9P. With the limit on wrong attempts, nobody guesses it."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4 * groups))
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def hash_code(code: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]", "", str(code).upper())
    return hashlib.sha256(cleaned.encode("ascii", "ignore")).hexdigest()


class RateLimiter:
    """Counts how much someone did in the last few minutes: how many times, or how many
    seconds of work (the routes: a few long ones must not keep the navigator from others)."""

    def __init__(self, limit: float, window: float):
        self.limit = limit
        self.window = window
        self._events: dict[str, list[tuple[float, float]]] = {}  # (when, how much)
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[tuple[float, float]]:
        recent = [e for e in self._events.get(key, ()) if now - e[0] < self.window]
        self._events[key] = recent
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return sum(a for _, a in self._recent(key, time.monotonic())) >= self.limit

    def record(self, key: str, amount: float = 1) -> None:
        now = time.monotonic()
        with self._lock:
            self._recent(key, now).append((now, amount))
            if len(self._events) > 10_000:
                self._events = {
                    k: v for k, v in self._events.items() if v and now - v[-1][0] < self.window
                }

    def allow(self, key: str) -> bool:
        """Like record(), but only if there is still room."""
        now = time.monotonic()
        with self._lock:
            recent = self._recent(key, now)
            if sum(a for _, a in recent) >= self.limit:
                return False
            recent.append((now, 1))
            return True


class Store:
    """A single SQLite connection behind a lock: plenty for a neighborhood."""

    def __init__(self, path: Path, post_days: int = POST_DAYS, safe_days: int = SAFE_DAYS):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.keep = {"posts": post_days * 86400, "safe": safe_days * 86400}  # 0: forever
        self._forgot = 0.0
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        os.chmod(path, 0o600)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self.closed_version = 0  # changes with every blocked street added or reopened
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            # FULL: a notice that was accepted survives a sudden power cut.
            self._db.execute("PRAGMA synchronous=FULL")
            # What is deleted is overwritten with zeros, not left in the file for a disk reader.
            self._db.execute("PRAGMA secure_delete=ON")
            self._db.executescript(SCHEMA)
            self._migrate()
            self._db.commit()
            row = self._db.execute("SELECT value FROM settings WHERE name = 'clock'").fetchone()
            self.offset = float(row["value"]) if row else 0.0

    def _migrate(self) -> None:
        for table, name, definition in ADDED_COLUMNS:
            existing = {row["name"] for row in self._db.execute(f"PRAGMA table_info({table})")}
            if name not in existing:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS notice_signature ON notices (signature_hash)"
        )
        self._db.execute("CREATE UNIQUE INDEX IF NOT EXISTS notice_cap ON notices (cap_key)")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- time, and what it takes away ------------------------------------------------------

    def now(self) -> int:
        """The Campanile's clock: the computer's, corrected by the admin when it is wrong (a
        Raspberry has no battery for its clock: without internet it restarts behind)."""
        return int(time.time() + self.offset)

    def set_clock(self, real: float) -> int:
        offset = real - time.time()
        if not abs(offset) <= MAX_OFFSET:  # NaN included
            raise RequestError(400, "bad_time")
        with self._lock:
            self.offset = round(offset)
            self._db.execute(
                "INSERT OR REPLACE INTO settings (name, value) VALUES ('clock', ?)",
                (str(self.offset),),
            )
            self._db.commit()
        return self.now()

    def emergency(self) -> str | None:
        """The number to call in danger, if the admin set one."""
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE name = 'emergency'").fetchone()
        return row["value"] if row else None

    def set_emergency(self, number) -> str:
        if not isinstance(number, str) or not EMERGENCY_FORMAT.fullmatch(number):
            raise RequestError(400, "bad_emergency")
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO settings (name, value) VALUES ('emergency', ?)", (number,)
            )
            self._db.commit()
        return number

    def instance(self) -> str:
        """A random name for this Campanile, made once: records it exports never collide with
        another Campanile's, and say nothing about where it is."""
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE name = 'instance'").fetchone()
            if row:
                return row["value"]
            name = secrets.token_hex(4)
            self._db.execute("INSERT INTO settings (name, value) VALUES ('instance', ?)", (name,))
            self._db.commit()
            return name

    def _forget(self) -> None:
        """Deletes the posts and names older than they may be kept. Under the lock."""
        now = self.now()
        if now - self._forgot < FORGET_EVERY:
            return
        self._forgot = now
        gone = 0
        for table, sql in (
            ("posts", "DELETE FROM posts WHERE created < ?"),
            ("safe", "DELETE FROM safe WHERE created < ?"),
        ):
            if self.keep[table]:
                gone += self._db.execute(sql, (now - self.keep[table],)).rowcount
        self._db.commit()
        if gone:
            self._wipe()

    def _wipe(self) -> None:
        """The journal still holds deleted text in earlier copies of its pages: empty it."""
        self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def log(self, action: str, detail: str = "", who: str = "") -> None:
        """What was done, when and by whom: a person's name, or '' for the main password."""
        with self._lock:
            self._db.execute(
                "INSERT INTO admin_log (at, action, detail, who) VALUES (?, ?, ?, ?)",
                (self.now(), action, detail[:200], who),
            )
            self._db.execute(
                "DELETE FROM admin_log WHERE id <= (SELECT MAX(id) FROM admin_log) - ?",
                (MAX_LOG,),
            )
            self._db.commit()

    def admin_log(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT at, action, detail, who FROM admin_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- the people who run the Campanile --------------------------------------------------

    def add_admin(self, name: str) -> tuple[int, str]:
        """A person with a password of their own. The Campanile makes it, so it is random and
        used nowhere else, and 16 characters (about 79 bits) are out of reach even for someone
        who copies the database: a fast hash is enough, and only the hash is kept."""
        password = new_code(groups=4)
        with self._lock:
            if self._count("SELECT COUNT(*) FROM admins") >= MAX_ADMINS:
                raise RequestError(503, "too_many_admins", max=MAX_ADMINS)
            try:
                cur = self._db.execute(
                    "INSERT INTO admins (name, key_hash, created) VALUES (?, ?, ?)",
                    (name, hash_code(password), self.now()),
                )
            except sqlite3.IntegrityError:
                raise RequestError(409, "admin_name_taken") from None
            self._db.commit()
        return cur.lastrowid, password

    def remove_admin(self, admin_id: int) -> str | None:
        """Their password stops working from the next request. Their name, or None."""
        with self._lock:
            row = self._db.execute("SELECT name FROM admins WHERE id = ?", (admin_id,)).fetchone()
            if row:
                self._db.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
                self._db.commit()
        return row["name"] if row else None

    def admins(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, name, created FROM admins ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def admin_by_password(self, password: str) -> str | None:
        """The name of the person with this password, or None."""
        with self._lock:
            row = self._db.execute(
                "SELECT name FROM admins WHERE key_hash = ?", (hash_code(password),)
            ).fetchone()
        return row["name"] if row else None

    def _count(self, sql: str) -> int:
        return self._db.execute(sql).fetchone()[0]

    def _check_code(self, sql: str, item_id: int, code: str) -> str:
        """OK, WRONG (a guess that counts against the device) or GONE (already closed).

        GONE must not count: a phone retrying its own post, already closed by the admin,
        would otherwise lock itself out. Whether a post is open is public anyway.
        """
        row = self._db.execute(sql, (item_id,)).fetchone()
        if row is None:
            return GONE
        return OK if hmac.compare_digest(row["code_hash"], hash_code(code)) else WRONG

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return (
                self._count("SELECT COUNT(*) FROM posts WHERE closed = 0 AND pending = 0"),
                self._count("SELECT COUNT(*) FROM safe"),
            )

    def add_post(
        self, kind, category, text, area, contact, device: str = "", pending: bool = False
    ) -> tuple[int, str]:
        code = new_code()
        with self._lock:
            self._forget()
            mine = self._db.execute(
                "SELECT COUNT(*) FROM posts WHERE closed = 0 AND device = ?", (device,)
            ).fetchone()[0]
            if device and mine >= MAX_OPEN_POSTS_PER_DEVICE:
                raise RequestError(429, "device_open_posts", count=mine)
            if pending:
                if self._count("SELECT COUNT(*) FROM posts WHERE closed = 0 AND pending = 1") >= (
                    MAX_PENDING_POSTS
                ):
                    raise RequestError(503, "pending_full")
            elif (
                self._count("SELECT COUNT(*) FROM posts WHERE closed = 0 AND pending = 0")
                >= MAX_OPEN_POSTS
            ):
                raise RequestError(503, "board_full")
            cur = self._db.execute(
                "INSERT INTO posts (kind, category, text, area, contact, created, code_hash,"
                " device, pending) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    kind,
                    category,
                    text,
                    area,
                    contact,
                    self.now(),
                    hash_code(code),
                    device,
                    int(pending),
                ),
            )
            self._db.commit()
            return cur.lastrowid, code

    def list_pending(self) -> list[dict]:
        with self._lock:
            self._forget()
            return [
                dict(r)
                for r in self._db.execute(
                    "SELECT id, kind, category, text, area, contact, created, device FROM posts"
                    " WHERE closed = 0 AND pending = 1 ORDER BY created, id LIMIT ?",
                    (MAX_PENDING_POSTS,),
                )
            ]

    def approve_post(self, post_id: int) -> bool:
        with self._lock:
            visible = self._count("SELECT COUNT(*) FROM posts WHERE closed = 0 AND pending = 0")
            if visible >= MAX_OPEN_POSTS:
                raise RequestError(503, "board_full_admin")
            cur = self._db.execute(
                "UPDATE posts SET pending = 0 WHERE id = ? AND closed = 0 AND pending = 1",
                (post_id,),
            )
            self._db.commit()
            return cur.rowcount > 0

    def close_device_posts(self, device: str) -> int:
        """Closes every open or pending post of one device: the cleanup after a flood."""
        if not device:
            return 0
        with self._lock:
            cur = self._db.execute(
                "UPDATE posts SET closed = 1 WHERE device = ? AND closed = 0", (device,)
            )
            self._db.commit()
            return cur.rowcount

    def close_recent_posts(self, minutes: int) -> int:
        with self._lock:
            cur = self._db.execute(
                "UPDATE posts SET closed = 1 WHERE closed = 0 AND created >= ?",
                (self.now() - minutes * 60,),
            )
            self._db.commit()
            return cur.rowcount

    def remove_device_safe(self, device: str) -> int:
        if not device:
            return 0
        with self._lock:
            cur = self._db.execute("DELETE FROM safe WHERE device = ?", (device,))
            self._db.commit()
            self._wipe()
            return cur.rowcount

    def list_posts(self, kind=None, category=None, limit=500, with_device=False) -> list[dict]:
        sql = _LIST_POSTS_ADMIN if with_device else _LIST_POSTS
        params: list = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY created DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            self._forget()
            return [dict(r) for r in self._db.execute(sql, params)]

    def close_post(self, post_id: int, code: str) -> str:
        with self._lock:
            result = self._check_code(
                "SELECT code_hash FROM posts WHERE id = ? AND closed = 0", post_id, code
            )
            if result == OK:
                self._db.execute("UPDATE posts SET closed = 1 WHERE id = ?", (post_id,))
                self._db.commit()
            return result

    def add_safe(self, name, message, place, device: str = "") -> tuple[int, str]:
        code = new_code()
        with self._lock:
            self._forget()
            mine = self._db.execute(
                "SELECT COUNT(*) FROM safe WHERE device = ?", (device,)
            ).fetchone()[0]
            if device and mine >= MAX_SAFE_PER_DEVICE:
                raise RequestError(429, "device_names", count=mine)
            if self._count("SELECT COUNT(*) FROM safe") >= MAX_SAFE:
                raise RequestError(503, "registry_full")
            cur = self._db.execute(
                "INSERT INTO safe (name, search_name, message, place, created, code_hash, device)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    normalize_name(name),
                    message,
                    place,
                    self.now(),
                    hash_code(code),
                    device,
                ),
            )
            self._db.commit()
            return cur.lastrowid, code

    def search_safe(self, query: str, limit=50) -> list[dict]:
        """Searching "rossi giulia" also finds "Giulia Rossi"."""
        sql = "SELECT id, name, message, place, created FROM safe WHERE 1 = 1"
        params: list = []
        for word in normalize_name(query).split():
            sql += " AND instr(search_name, ?) > 0"
            params.append(word)
        sql += " ORDER BY created DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            self._forget()
            return [dict(r) for r in self._db.execute(sql, params)]

    def remove_safe(self, safe_id: int, code: str) -> str:
        with self._lock:
            result = self._check_code("SELECT code_hash FROM safe WHERE id = ?", safe_id, code)
            if result == OK:
                self._db.execute("DELETE FROM safe WHERE id = ?", (safe_id,))
                self._db.commit()
                self._wipe()
            return result

    def add_notice(self, title: str, text: str, urgent: bool) -> int:
        with self._lock:
            if self._count("SELECT COUNT(*) FROM notices") >= MAX_NOTICES:
                raise RequestError(503, "too_many_notices")
            cur = self._db.execute(
                "INSERT INTO notices (title, text, urgent, created) VALUES (?, ?, ?, ?)",
                (title, text, int(urgent), self.now()),
            )
            self._db.commit()
            return cur.lastrowid

    def add_signed_notice(self, notice: dict, signer: str, signature_hash: str, signed: str) -> int:
        with self._lock:
            if self._count("SELECT COUNT(*) FROM notices") >= MAX_NOTICES:
                raise RequestError(503, "too_many_notices")
            try:
                cur = self._db.execute(
                    "INSERT INTO notices (title, text, urgent, created, signer, issued, expires,"
                    " signature_hash, signed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        notice["title"],
                        notice["text"],
                        int(notice["urgent"]),
                        self.now(),
                        signer,
                        notice["issued"],
                        notice["expires"],
                        signature_hash,
                        signed,
                    ),
                )
            except sqlite3.IntegrityError:
                raise RequestError(409, "signed_duplicate") from None
            self._db.commit()
            return cur.lastrowid

    def add_closed_road(self, lon: float, lat: float, name: str, note: str) -> int:
        """A street the admin marks as blocked: every route avoids it from now on."""
        with self._lock:
            if self._count("SELECT COUNT(*) FROM closed_roads") >= MAX_CLOSED_ROADS:
                raise RequestError(503, "too_many_closed")
            cur = self._db.execute(
                "INSERT INTO closed_roads (lon, lat, name, note, created) VALUES (?, ?, ?, ?, ?)",
                (lon, lat, name, note, self.now()),
            )
            self._db.commit()
            self.closed_version += 1
            return cur.lastrowid

    def closed_roads(self) -> tuple[int, list[dict]]:
        """(version, the blocked streets), read together: never a list older than its number."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, lon, lat, name, note, created FROM closed_roads ORDER BY id"
            ).fetchall()
            return self.closed_version, [dict(row) for row in rows]

    def open_road(self, road_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM closed_roads WHERE id = ?", (road_id,))
            self._db.commit()
            self.closed_version += 1
            return cur.rowcount > 0

    def add_cap_notice(self, alert: dict) -> int:
        """An official alert in CAP (see cap.py), already checked and cleaned."""
        with self._lock:
            if self._count("SELECT COUNT(*) FROM notices") >= MAX_NOTICES:
                raise RequestError(503, "too_many_notices")
            try:
                cur = self._db.execute(
                    "INSERT INTO notices (title, text, urgent, created, expires, source, cap_key)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        alert["title"],
                        alert["text"],
                        int(alert["urgent"]),
                        self.now(),
                        alert["expires"],
                        alert["source"],
                        alert["key"],
                    ),
                )
            except sqlite3.IntegrityError:
                raise RequestError(409, "cap_duplicate") from None
            self._db.commit()
            return cur.lastrowid

    def list_notices(self) -> list[dict]:
        """Signed notices disappear by themselves once expired."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, title, text, urgent, created, signer, issued, expires, signed, source"
                " FROM notices WHERE expires IS NULL OR expires > ?"
                " ORDER BY urgent DESC, created DESC, id DESC",
                (self.now(),),
            ).fetchall()
        notices = []
        for r in rows:
            n = {k: r[k] for k in ("id", "title", "text", "created")}
            n["urgent"] = bool(r["urgent"])
            if r["source"]:
                n.update(source=r["source"], expires=r["expires"])
            if r["signer"]:
                # The whole signed document, so anyone can check it independently.
                n.update(
                    signer=r["signer"],
                    issued=r["issued"],
                    expires=r["expires"],
                    signed=json.loads(r["signed"]),
                )
            notices.append(n)
        return notices

    def all_safe(self) -> list[dict]:
        with self._lock:
            self._forget()
            return [
                dict(r)
                for r in self._db.execute(
                    "SELECT id, name, message, place, created, device FROM safe"
                    " ORDER BY created DESC, id DESC LIMIT ?",
                    (MAX_SAFE,),
                )
            ]

    def delete(self, table: str, item_id: int) -> bool:
        sql = {
            "post": "UPDATE posts SET closed = 1 WHERE id = ? AND closed = 0",
            "safe": "DELETE FROM safe WHERE id = ?",
            "notice": "DELETE FROM notices WHERE id = ?",
        }.get(table if isinstance(table, str) else "")
        if sql is None:
            raise RequestError(400, "bad_table")
        with self._lock:
            cur = self._db.execute(sql, (item_id,))
            self._db.commit()
            if table != "post":  # a removed post is only closed, and goes with the others
                self._wipe()
            return cur.rowcount > 0
