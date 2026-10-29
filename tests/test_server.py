# DEVELOPED BY CARROTSTUDIO software house
"""Campanile server tests. Run: python3 -m unittest discover -s tests -v"""

import argparse
import base64
import contextlib
import email.utils
import http.client
import importlib.util
import io
import json
import os
import plistlib
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import devices
import server as campanile
import signing
import store
from test_places import town

import mapfixture

PASSWORD = "test-password"
# The tests sign with `cryptography`; Campanile checks without it too (ed25519.py).
CAN_SIGN = importlib.util.find_spec("cryptography") is not None


class CampanileTestCase(unittest.TestCase):
    portal = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.web = root / "web"
        self.data = root / "data"
        (self.web / "sub").mkdir(parents=True)
        (self.data / "maps").mkdir(parents=True)
        (self.web / "index.html").write_text("<h1>Campanile</h1>", encoding="utf-8")
        (self.web / "sub" / "a.js").write_text("export {};", encoding="utf-8")
        (root / "secret.txt").write_text("MUST NOT LEAK", encoding="utf-8")
        self.map_bytes = bytes(range(256)) * 40  # 10240 known bytes
        (self.data / "maps" / "test.pmtiles").write_bytes(self.map_bytes)
        self.cfg = campanile.Config(
            web=self.web,
            data=self.data,
            portal=self.portal,
            hostnames=["localhost", "127.0.0.1"],
            admin_password=PASSWORD,
        )
        self.server = campanile.create_server("127.0.0.1", 0, self.cfg)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.cfg.store.close()
        self._tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = dict(headers or {})
        payload = None
        if body is not None:
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=h)
        r = conn.getresponse()
        content = r.read()
        conn.close()
        return r, content

    def json(self, method, path, body=None, headers=None):
        r, content = self.request(method, path, body, headers)
        return r.status, (json.loads(content) if content else None)

    def post(self, **overrides):
        data = {
            "kind": "offer",
            "category": "water",
            "text": "20 litres",
            "area": "square",
            "contact": "Marco",
        }
        data.update(overrides)
        return self.json("POST", "/api/posts", data)

    def admin(self, path, **body):
        return self.json("POST", path, {"password": PASSWORD, **body})


class TestBoard(CampanileTestCase):
    def test_publish_list_close(self):
        status, r = self.post()
        self.assertEqual(status, 201)
        self.assertRegex(r["code"], r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        status, listing = self.json("GET", "/api/posts")
        self.assertEqual(status, 200)
        self.assertEqual(len(listing["posts"]), 1)
        p = listing["posts"][0]
        self.assertEqual((p["text"], p["area"], p["contact"]), ("20 litres", "square", "Marco"))
        self.assertNotIn("code_hash", p)  # the code's hash never leaves the server

        # wrong code: refused, post still open
        status, _ = self.json("POST", "/api/posts/close", {"id": r["id"], "code": "AAAA-AAAA"})
        self.assertEqual(status, 403)
        self.assertEqual(len(self.json("GET", "/api/posts")[1]["posts"]), 1)

        # right code, even lowercase and without the dash
        code = r["code"].replace("-", "").lower()
        status, _ = self.json("POST", "/api/posts/close", {"id": r["id"], "code": code})
        self.assertEqual(status, 200)
        self.assertEqual(self.json("GET", "/api/posts")[1]["posts"], [])
        # closing twice: "already closed", which is not a wrong guess
        status, _ = self.json("POST", "/api/posts/close", {"id": r["id"], "code": code})
        self.assertEqual(status, 404)

    def test_filters(self):
        self.post(kind="offer", category="water")
        self.post(kind="need", category="medicine")
        _, r = self.json("GET", "/api/posts?kind=need")
        self.assertEqual([p["category"] for p in r["posts"]], ["medicine"])
        _, r = self.json("GET", "/api/posts?category=water")
        self.assertEqual([p["kind"] for p in r["posts"]], ["offer"])
        self.assertEqual(self.json("GET", "/api/posts?kind=sell")[0], 400)
        self.assertEqual(self.json("GET", "/api/posts?category=weapons")[0], 400)

    def test_validation(self):
        self.assertEqual(self.post(kind="sell")[0], 400)
        self.assertEqual(self.post(category="x")[0], 400)
        self.assertEqual(self.post(text="   ")[0], 400)
        self.assertEqual(self.post(text="x" * 501)[0], 400)
        self.assertEqual(self.post(text="x" * 500)[0], 201)
        self.assertEqual(self.post(area=["list"])[0], 400)
        self.assertEqual(self.post(contact=None)[0], 400)

    def test_errors_name_the_field_in_italian(self):
        _, r = self.post(text="")
        self.assertEqual(r["error"], "Il campo 'descrizione' è obbligatorio.")

    def test_hostile_text_stays_text(self):
        hostile = "<script>alert(1)</script>\x00\x07 line1\nline2"
        status, _ = self.post(text=hostile, area="<b>z</b>\nx")
        self.assertEqual(status, 201)
        p = self.json("GET", "/api/posts")[1]["posts"][0]
        # Stored as text (the browser shows it with textContent), without control
        # characters; line breaks allowed only in the description.
        self.assertEqual(p["text"], "<script>alert(1)</script> line1\nline2")
        self.assertEqual(p["area"], "<b>z</b> x")

    def test_duplicate_keys_are_refused(self):
        body = (
            b'{"kind":"offer","category":"water","text":"real","text":"FAKE",'
            b'"area":"a","contact":"c"}'
        )
        self.assertEqual(self.request("POST", "/api/posts", body, {})[0].status, 400)

    def test_deep_nesting_is_a_clean_400(self):
        r, _ = self.request("POST", "/api/posts", b"[" * 4000 + b"]" * 4000, {})
        self.assertEqual(r.status, 400)

    def test_invisible_format_characters_are_removed(self):
        status, _ = self.post(
            text="Acqua \u202egnirps\u202c", area="zona\u200b", contact="Marco\u2066x\u2069"
        )
        self.assertEqual(status, 201)
        p = self.json("GET", "/api/posts")[1]["posts"][0]
        self.assertEqual((p["text"], p["area"], p["contact"]), ("Acqua gnirps", "zona", "Marcox"))

    def test_emoji_joiner_is_kept(self):
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
        self.assertEqual(self.post(text=f"Famiglia {family}")[0], 201)
        self.assertIn(family, self.json("GET", "/api/posts")[1]["posts"][0]["text"])

    def test_rate_limit_per_ip(self):
        for _ in range(campanile.MAX_WRITES_PER_IP):
            status, r = self.post()
            self.assertEqual(status, 201)
            # close it, so the cap on open posts doesn't kick in first
            self.json("POST", "/api/posts/close", {"id": r["id"], "code": r["code"]})
        status, r = self.post()
        self.assertEqual(status, 429)
        self.assertIn("Troppe", r["error"])

    def test_invalid_requests_dont_use_up_the_limit(self):
        for _ in range(campanile.MAX_WRITES_PER_IP * 2):
            self.assertEqual(self.post(kind="x")[0], 400)
        self.assertEqual(self.post()[0], 201)

    def test_board_full(self):
        old = store.MAX_OPEN_POSTS
        store.MAX_OPEN_POSTS = 2
        try:
            self.assertEqual(self.post()[0], 201)
            self.assertEqual(self.post()[0], 201)
            self.assertEqual(self.post()[0], 503)
        finally:
            store.MAX_OPEN_POSTS = old

    def test_wrong_codes_are_limited(self):
        _, r = self.post()
        for _ in range(campanile.MAX_WRONG_CODES):
            status, _ = self.json("POST", "/api/posts/close", {"id": r["id"], "code": "XXXX-XXXX"})
            self.assertEqual(status, 403)
        # now even the right code is refused: the window is used up
        status, _ = self.json("POST", "/api/posts/close", {"id": r["id"], "code": r["code"]})
        self.assertEqual(status, 429)

    def test_retrying_closed_posts_never_locks_the_owner_out(self):
        # A phone remembering posts that the admin already closed keeps retrying them.
        _, old = self.post()
        self.admin("/api/admin/delete", table="post", id=old["id"])
        for _ in range(campanile.MAX_WRONG_CODES + 5):
            status, _ = self.json(
                "POST", "/api/posts/close", {"id": old["id"], "code": old["code"]}
            )
            self.assertEqual(status, 404)
        _, new = self.post()
        self.assertEqual(
            self.json("POST", "/api/posts/close", {"id": new["id"], "code": new["code"]})[0], 200
        )

    def test_unknown_id_is_not_a_wrong_guess_but_wrong_codes_still_count(self):
        _, r = self.post()
        for _ in range(campanile.MAX_WRONG_CODES):
            self.assertEqual(
                self.json("POST", "/api/posts/close", {"id": 999, "code": "AAAA-AAAA"})[0], 404
            )
        for _ in range(campanile.MAX_WRONG_CODES):
            self.assertEqual(
                self.json("POST", "/api/posts/close", {"id": r["id"], "code": "AAAA-AAAA"})[0], 403
            )
        self.assertEqual(
            self.json("POST", "/api/posts/close", {"id": r["id"], "code": r["code"]})[0], 429
        )

    def test_invalid_id(self):
        for item_id in (0, -1, "abc", True, None, [1], 1.5):
            status, _ = self.json("POST", "/api/posts/close", {"id": item_id, "code": "AAAA-AAAA"})
            self.assertEqual(status, 400, item_id)


class TestSafe(CampanileTestCase):
    def test_register_search_remove(self):
        status, r = self.json(
            "POST",
            "/api/safe",
            {"name": "Nicolò Bianchi", "message": "Sto bene", "place": "Scuola"},
        )
        self.assertEqual(status, 201)
        # no accents, different case, swapped words
        for q in ("nicolo", "BIANCHI", "bianchi nicolò", "COL"):
            _, t = self.json("GET", "/api/safe?q=" + quote(q))
            self.assertEqual([p["name"] for p in t["results"]], ["Nicolò Bianchi"], q)
        _, t = self.json("GET", "/api/safe?q=rossi")
        self.assertEqual(t["results"], [])
        self.assertEqual(self.json("GET", "/api/safe?q=a")[0], 400)
        self.assertEqual(self.json("GET", "/api/safe")[0], 400)
        wrong = {"id": r["id"], "code": "AAAA-AAAA"}
        self.assertEqual(self.json("POST", "/api/safe/remove", wrong)[0], 403)
        right = {"id": r["id"], "code": r["code"]}
        self.assertEqual(self.json("POST", "/api/safe/remove", right)[0], 200)
        _, t = self.json("GET", "/api/safe?q=nicolo")
        self.assertEqual(t["results"], [])

    def test_optional_fields_and_validation(self):
        self.assertEqual(self.json("POST", "/api/safe", {"name": "Anna"})[0], 201)
        self.assertEqual(self.json("POST", "/api/safe", {"name": "A"})[0], 400)
        self.assertEqual(self.json("POST", "/api/safe", {"name": "x" * 81})[0], 400)
        too_long = {"name": "Anna", "message": "m" * 301}
        self.assertEqual(self.json("POST", "/api/safe", too_long)[0], 400)


class TestRequests(CampanileTestCase):
    def test_a_lone_surrogate_password_is_wrong_not_a_crash(self):
        # Found by fuzzing: the password check encoded it and crashed.
        status, r = self.json("POST", "/api/admin/list", {"password": "\ud800"})
        self.assertEqual(status, 403)
        self.assertIn("error", r)

    def answer_to_unread_body(self, host="localhost", size=200_000):
        """A request answered before its body is read: the answer must still arrive.

        Closing a socket with unread data sends a reset, and on Windows a reset discards an
        answer already sent; the phone would show "Campanile not answering" instead.
        """
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        head = (
            f"POST /api/posts HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {size}\r\nAccept-Language: en\r\n\r\n"
        )
        s.sendall(head.encode())

        def send_body():
            with contextlib.suppress(OSError):
                s.sendall(b"x" * size)

        sender = threading.Thread(target=send_body)
        sender.start()
        reply = b""
        with contextlib.suppress(OSError):
            while chunk := s.recv(4096):
                reply += chunk
        sender.join(10)
        s.close()
        return reply

    def test_text_utf8_cannot_store_is_a_clear_400(self):
        # json.dumps writes the lone surrogate as the escape \ud800, as a hostile phone would.
        status, r = self.post(text="\ud800")
        self.assertEqual(status, 400)
        self.assertIn("error", r)
        self.assertEqual(self.post()[0], 201)  # and it didn't cost the phone a post

    def test_huge_numbers_are_a_clear_400(self):
        for value in (2**63, 10**30, "9" * 5000):
            status, _ = self.json("POST", "/api/posts/close", {"id": value, "code": "AAAA-AAAA"})
            self.assertEqual(status, 400, value)
        status, _ = self.json("POST", "/api/posts/close", {"id": 2**63 - 1, "code": "AAAA-AAAA"})
        self.assertEqual(status, 404)  # the largest id SQLite stores: valid, just not there

    def test_a_length_that_isnt_ascii_digits_is_refused(self):
        for length in (b"\xb2", b"1e3", b"-1", b"9999999999"):
            s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            s.sendall(
                b"POST /api/posts HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + length + b"\r\n\r\n"
            )
            status = s.recv(64).split(b"\r\n")[0]
            s.close()
            self.assertIn(
                status, (b"HTTP/1.1 411 Length Required", b"HTTP/1.1 413 Payload Too Large"), length
            )

    def test_an_absurd_range_is_ignored(self):
        r, body = self.request(
            "GET", "/maps/test.pmtiles", headers={"Range": "bytes=" + "9" * 5000 + "-"}
        )
        self.assertEqual(r.status, 200)
        self.assertEqual(body, self.map_bytes)

    def test_too_large_answer_reaches_the_phone(self):
        reply = self.answer_to_unread_body()
        self.assertTrue(reply.startswith(b"HTTP/1.1 413"), reply[:60])
        self.assertIn(b"Request too large", reply)

    def test_a_full_disk_says_so_and_reading_still_works(self):
        def full(*args, **kwargs):
            raise sqlite3.OperationalError("database or disk is full")

        self.cfg.store.add_post = full
        status, r = self.json(
            "POST",
            "/api/posts",
            {"kind": "offer", "category": "water", "text": "t", "area": "a", "contact": "c"},
            {"Accept-Language": "en"},
        )
        self.assertEqual(status, 507)
        self.assertIn("out of disk space", r["error"])
        self.assertEqual(self.json("GET", "/api/posts")[0], 200)

    def test_other_database_errors_stay_internal(self):
        def broken(*args, **kwargs):
            raise sqlite3.OperationalError("no such table: posts")

        self.cfg.store.add_post = broken
        self.assertEqual(self.post()[0], 500)

    def test_requires_json_and_length(self):
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        r, _ = self.request("POST", "/api/posts", b"kind=offer", form)
        self.assertEqual(r.status, 415)
        for body in (b"{", b"[1, 2]", b"\xff\xfe"):
            r, _ = self.request("POST", "/api/posts", body, {})
            self.assertEqual(r.status, 400, body)

    def test_body_too_large(self):
        r, _ = self.request("POST", "/api/posts", b"x" * (campanile.MAX_BODY + 1), {})
        self.assertEqual(r.status, 413)

    def test_connection_safe_after_error(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/posts", body=b"x" * 100, headers={"Content-Type": "text/plain"})
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 415)
        # The server either closed the connection (body unread) or answers properly:
        # it must never read the leftover body as a new request.
        try:
            conn.request("GET", "/api/status")
            r2 = conn.getresponse()
            self.assertEqual(r2.status, 200)
            r2.read()
        except (http.client.RemoteDisconnected, ConnectionError, BrokenPipeError):
            pass
        conn.close()

    def test_a_body_is_never_read_as_the_next_request(self):
        # Found through nginx: a GET whose body was a whole POST had that POST run, with
        # the X-Real-IP its sender wrote. Each request below hides a post that must not run.
        def hidden(marker):
            body = json.dumps(
                {"kind": "offer", "category": "water", "text": marker, "area": "a", "contact": "c"}
            )
            return (
                "POST /api/posts HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json"
                f"\r\nContent-Length: {len(body)}\r\n\r\n{body}"
            )

        post = "POST /api/posts HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
        cases = {
            "GET-BODY": lambda h: (
                f"GET /api/status HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(h)}"
                f"\r\n\r\n{h}"
            ),
            "HEAD-BODY": lambda h: (
                f"HEAD / HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(h)}\r\n\r\n{h}"
            ),
            "TWO-LENGTHS": lambda h: (
                post + f"Content-Length: 0\r\nContent-Length: {len(h)}\r\n\r\n{h}"
            ),
            "CHUNKED": lambda h: (
                post + f"Content-Length: {len(f'{len(h):x}') + 2}\r\n"
                f"Transfer-Encoding: chunked\r\n\r\n{len(h):x}\r\n{h}\r\n0\r\n\r\n"
            ),
        }
        for marker, request in cases.items():
            with self.subTest(marker):
                s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
                s.sendall(request(hidden(marker)).encode())
                reply = b""
                with contextlib.suppress(OSError):  # a timeout here means "kept open"
                    while chunk := s.recv(4096):
                        reply += chunk
                s.close()
                self.assertTrue(reply.startswith(b"HTTP/1.1 400"), reply[:60])
                self.assertEqual(reply.count(b"HTTP/1.1 "), 1)
                self.assertIn(b"Connection: close", reply)
        texts = [p["text"] for p in self.json("GET", "/api/posts")[1]["posts"]]
        self.assertEqual([t for t in texts if t in cases], [])

    def test_an_empty_length_on_a_get_keeps_the_connection(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/status", headers={"Content-Length": "0"})
        r = conn.getresponse()
        r.read()
        first = conn.sock
        conn.request("GET", "/api/status", headers={"Content-Length": "0"})
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 200)
        self.assertIs(conn.sock, first)  # the same connection, still open
        conn.close()

    def test_unknown_api(self):
        self.assertEqual(self.json("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.json("POST", "/api/nothing", {})[0], 404)

    def test_security_headers(self):
        r, _ = self.request("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn("default-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        r, _ = self.request("GET", "/api/status")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_database_is_private(self):
        self.assertEqual((self.data / "campanile.db").stat().st_mode & 0o777, 0o600)

    def test_status(self):
        status, r = self.json("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(r["version"], campanile.VERSION)
        self.assertFalse(r["kiwix"])
        self.assertEqual([m["file"] for m in r["maps"]], ["test.pmtiles"])
        self.assertEqual(r["maps"][0]["bytes"], len(self.map_bytes))


class TestFiles(CampanileTestCase):
    def test_windows_path_tricks_are_not_files(self):
        # On Windows these reach a file's hidden stream, or the file under another name.
        # Elsewhere they are ordinary names: create them, so the test means something there too.
        for name in ("index.html:Zone.Identifier", "index.html.", "index.html ", "sub\\a.js"):
            with contextlib.suppress(OSError):  # Windows refuses such names
                (self.web / name).write_text("HostUrl=secret", encoding="utf-8")
        (self.web / "sub" / "with space.js").write_text("export {};", encoding="utf-8")
        for path in (
            "/index.html:Zone.Identifier",
            "/index.html%3AZone.Identifier",
            "/index.html::$DATA",
            "/index.html.",
            "/index.html%20",
            "/sub%5Ca.js",
        ):
            self.assertEqual(self.request("GET", path)[0].status, 404, path)
        self.assertEqual(self.request("GET", "/sub/with%20space.js")[0].status, 200)

    def test_index_and_mime_types(self):
        r, c = self.request("GET", "/")
        self.assertEqual((r.status, c), (200, b"<h1>Campanile</h1>"))
        self.assertEqual(r.getheader("Content-Type"), "text/html; charset=utf-8")
        r, _ = self.request("GET", "/sub/a.js")
        self.assertEqual(r.getheader("Content-Type"), "text/javascript; charset=utf-8")

    def test_path_traversal(self):
        for p in (
            "/../secret.txt",
            "/%2e%2e/secret.txt",
            "/sub/../../secret.txt",
            "/maps/../../secret.txt",
            "/maps/%2e%2e%2fsecret.txt",
            "/%00",
            "/maps/..%2f..%2fsecret.txt",
        ):
            r, c = self.request("GET", p)
            self.assertNotEqual(r.status, 200, p)
            self.assertNotIn(b"MUST NOT LEAK", c, p)

    def test_full_and_partial_ranges(self):
        m = self.map_bytes
        n = len(m)
        r, c = self.request("GET", "/maps/test.pmtiles")
        self.assertEqual((r.status, c), (200, m))
        self.assertEqual(r.getheader("Accept-Ranges"), "bytes")
        cases = {
            "bytes=0-126": (0, 126),
            "bytes=100-": (100, n - 1),
            "bytes=-50": (n - 50, n - 1),
            "bytes=10000-99999": (10000, n - 1),
            "bytes=-99999": (0, n - 1),
        }
        for value, (a, b) in cases.items():
            r, c = self.request("GET", "/maps/test.pmtiles", headers={"Range": value})
            self.assertEqual(r.status, 206, value)
            self.assertEqual(c, m[a : b + 1], value)
            self.assertEqual(r.getheader("Content-Range"), f"bytes {a}-{b}/{n}", value)
            self.assertEqual(int(r.getheader("Content-Length")), b - a + 1, value)

    def test_unsatisfiable_or_ignored_ranges(self):
        n = len(self.map_bytes)
        r, c = self.request("GET", "/maps/test.pmtiles", headers={"Range": f"bytes={n}-"})
        self.assertEqual(r.status, 416)
        self.assertEqual(r.getheader("Content-Range"), f"bytes */{n}")
        for ignored in ("bytes=5-1", "bytes=0-1,5-6", "lines=0-5", "bytes=-"):
            r, c = self.request("GET", "/maps/test.pmtiles", headers={"Range": ignored})
            self.assertEqual((r.status, len(c)), (200, n), ignored)

    def test_head(self):
        r, c = self.request("HEAD", "/maps/test.pmtiles")
        self.assertEqual(r.status, 200)
        self.assertEqual(c, b"")
        self.assertEqual(int(r.getheader("Content-Length")), len(self.map_bytes))

    def test_only_pmtiles_in_the_maps_folder(self):
        (self.data / "campanile.db.copy").write_text("x")
        self.assertEqual(self.request("GET", "/maps/campanile.db")[0].status, 404)
        self.assertEqual(self.request("GET", "/maps/")[0].status, 404)


class TestAdmin(CampanileTestCase):
    def test_password(self):
        self.assertEqual(self.json("POST", "/api/admin/list", {"password": "no"})[0], 403)
        self.assertEqual(self.json("POST", "/api/admin/list", {})[0], 403)
        status, r = self.admin("/api/admin/list")
        self.assertEqual(status, 200)
        self.assertEqual((r["posts"], r["safe"]), ([], []))

    def test_delete(self):
        _, p = self.post()
        _, s = self.json("POST", "/api/safe", {"name": "Anna"})
        self.assertEqual(self.admin("/api/admin/delete", table="post", id=p["id"])[0], 200)
        self.assertEqual(self.admin("/api/admin/delete", table="safe", id=s["id"])[0], 200)
        self.assertEqual(self.admin("/api/admin/delete", table="safe", id=s["id"])[0], 404)
        self.assertEqual(self.admin("/api/admin/delete", table="users", id=1)[0], 400)
        _, r = self.admin("/api/admin/list")
        self.assertEqual((r["posts"], r["safe"]), ([], []))

    def test_the_first_notice_is_the_urgent_one_else_the_newest(self):
        # The home page shows only the first, the rest behind a button: it must be this one.
        for title, urgent in (("Prima", False), ("Urgente", True), ("Ultima", False)):
            self.admin("/api/admin/notices", title=title, text="Testo", urgent=urgent)
        titles = [n["title"] for n in self.json("GET", "/api/notices")[1]["notices"]]
        self.assertEqual(titles, ["Urgente", "Ultima", "Prima"])

    def test_notices(self):
        self.assertEqual(self.json("GET", "/api/notices")[1], {"notices": []})
        no_password = {"title": "x", "text": "y"}
        self.assertEqual(self.json("POST", "/api/admin/notices", no_password)[0], 403)
        self.assertEqual(self.admin("/api/admin/notices", title="", text="y")[0], 400)
        _, normal = self.admin(
            "/api/admin/notices", title="Acqua", text="Distribuzione alle 16 in piazza"
        )
        _, urgent = self.admin(
            "/api/admin/notices",
            title="Non bere",
            text="Acqua del rubinetto non potabile",
            urgent=True,
        )
        self.admin("/api/admin/notices", title="String", text="z", urgent="true")
        _, r = self.json("GET", "/api/notices")
        self.assertEqual(
            [(n["title"], n["urgent"]) for n in r["notices"]],
            [("Non bere", True), ("String", False), ("Acqua", False)],
        )
        self.assertEqual(self.admin("/api/admin/delete", table="notice", id=urgent["id"])[0], 200)
        _, r = self.json("GET", "/api/notices")
        self.assertNotIn("Non bere", [n["title"] for n in r["notices"]])
        self.assertIn(normal["id"], [n["id"] for n in r["notices"]])

    def test_many_successes_dont_lock_out(self):
        for _ in range(campanile.MAX_WRONG_CODES + 5):
            self.assertEqual(self.admin("/api/admin/list")[0], 200)

    def test_wrong_passwords_lock_out(self):
        for _ in range(campanile.MAX_WRONG_CODES):
            self.assertEqual(self.json("POST", "/api/admin/list", {"password": "no"})[0], 403)
        self.assertEqual(self.admin("/api/admin/list")[0], 429)

    def test_only_from_the_campanile_itself(self):
        old = campanile.LOCAL_ADDRESSES
        campanile.LOCAL_ADDRESSES = set()  # the test client now looks like it's on the network
        try:
            status, r = self.admin("/api/admin/list")
            self.assertEqual(status, 403)
            self.assertIn("dal Campanile stesso", r["error"])
            self.cfg.admin_from_network = True
            self.assertEqual(self.admin("/api/admin/list")[0], 200)
        finally:
            campanile.LOCAL_ADDRESSES = old

    def test_no_password_means_admin_off(self):
        self.cfg.admin_password = None
        status, r = self.json("POST", "/api/admin/list", {"password": ""})
        self.assertEqual(status, 403)
        self.assertIn("disattivata", r["error"])


class TestPeople(CampanileTestCase):
    def add(self, name):
        return self.admin("/api/admin/people/add", name=name)

    def as_person(self, password, path, **body):
        return self.json("POST", path, {"password": password, **body})

    def test_a_person_signs_in_with_their_password_and_the_log_names_them(self):
        status, maria = self.add("Maria")
        self.assertEqual(status, 201)
        # 16 characters, about 79 bits: safe even if someone copies the database
        self.assertRegex(maria["password"], r"^([A-Z2-9]{4}-){3}[A-Z2-9]{4}$")
        typed = maria["password"].lower().replace("-", " ")  # as someone might type it
        self.assertEqual(self.as_person(typed, "/api/admin/me"), (200, {"name": "Maria"}))
        status, _ = self.as_person(typed, "/api/admin/notices", title="Acqua", text="In piazza")
        self.assertEqual(status, 201)
        self.assertEqual(self.admin("/api/admin/me"), (200, {"name": ""}))
        _, r = self.admin("/api/admin/log")
        latest = [(e["who"], e["action"]) for e in r["log"][:2]]
        self.assertEqual(latest, [("Maria", "notice"), ("", "person_added")])

    def test_a_removed_person_is_out_from_the_next_request(self):
        _, maria = self.add("Maria")
        self.assertEqual(self.as_person(maria["password"], "/api/admin/list")[0], 200)
        self.assertEqual(self.admin("/api/admin/people/remove", id=maria["id"])[0], 200)
        self.assertEqual(self.as_person(maria["password"], "/api/admin/list")[0], 403)
        self.assertEqual(self.admin("/api/admin/people/remove", id=maria["id"])[0], 404)

    def test_only_the_main_password_manages_people(self):
        _, maria = self.add("Maria")
        for path, body in (
            ("/api/admin/people", {}),
            ("/api/admin/people/add", {"name": "Luca"}),
            ("/api/admin/people/remove", {"id": maria["id"]}),
        ):
            self.assertEqual(self.as_person(maria["password"], path, **body)[0], 403, path)
        _, r = self.admin("/api/admin/people")
        self.assertEqual([p["name"] for p in r["people"]], ["Maria"])

    def test_names_are_unique_and_people_are_limited(self):
        self.add("Maria")
        self.assertEqual(self.add("maria")[0], 409)
        self.assertEqual(self.add("")[0], 400)
        for i in range(store.MAX_ADMINS - 1):
            self.add(f"Volontario {i}")
        self.assertEqual(self.add("Uno di troppo")[0], 503)

    def test_only_a_hash_of_the_password_is_kept(self):
        _, maria = self.add("Maria")
        kept = b"".join(path.read_bytes() for path in self.data.glob("*.db*"))
        self.assertIn(b"Maria", kept)  # we are reading the right files
        self.assertNotIn(maria["password"].encode(), kept)
        self.assertNotIn(maria["password"].replace("-", "").encode(), kept)


class TestPortal(CampanileTestCase):
    portal = "10.42.0.1"

    def test_redirects_foreign_hostnames(self):
        for host in (
            "connectivitycheck.gstatic.com",
            "captive.apple.com",
            "www.msftconnecttest.com",
            "example.com:80",
        ):
            r, _ = self.request("GET", "/generate_204", headers={"Host": host})
            self.assertEqual(r.status, 302, host)
            self.assertEqual(r.getheader("Location"), "http://10.42.0.1/", host)

    def test_redirects_posts_too(self):
        r, _ = self.request("POST", "/api/posts", {"kind": "offer"}, {"Host": "example.com"})
        self.assertEqual(r.status, 302)

    def test_redirect_of_a_big_post_reaches_the_phone(self):
        reply = TestRequests.answer_to_unread_body(self, host="example.com")
        self.assertTrue(reply.startswith(b"HTTP/1.1 302"), reply[:60])

    def test_known_hostnames_are_not_redirected(self):
        for host in ("10.42.0.1", "10.42.0.1:80", "localhost:8080", "LOCALHOST"):
            r, _ = self.request("GET", "/", headers={"Host": host})
            self.assertEqual(r.status, 200, host)


class TestRebinding(CampanileTestCase):
    """A page on internet can point its own name at this computer and read the answers as
    if they were its own (DNS rebinding): the Campanile answers only to local names."""

    FOREIGN = (
        "rebind.attacker.example",
        "127.0.0.1.nip.io:8080",
        "localhost.evil.com",
        "EVIL.COM.",
    )

    def test_a_domain_of_internet_reads_nothing(self):
        self.post()
        for host in self.FOREIGN:
            for path in ("/api/posts", "/api/notices", "/api/safe?q=ma", "/", "/maps/test.pmtiles"):
                with self.subTest(host=host, path=path):
                    r, content = self.request("GET", path, headers={"Host": host})
                    self.assertEqual(r.status, 421)
                    self.assertNotIn(b"20 litres", content)
            status, _ = self.json("POST", "/api/posts", {"kind": "offer"}, {"Host": host})
            self.assertEqual(status, 421)

    def test_it_cant_lock_the_admin_out(self):
        for _ in range(campanile.MAX_WRONG_CODES + 5):
            status, _ = self.json(
                "POST", "/api/admin/list", {"password": "guess"}, {"Host": self.FOREIGN[0]}
            )
            self.assertEqual(status, 421)
        self.assertEqual(self.admin("/api/admin/list")[0], 200)

    def test_names_nobody_can_register_are_answered(self):
        for host in (
            "192.168.1.20:8080", "10.42.0.1", "[::1]:8080", "[fe80::1]", "laptop.local:8080",
            "DESKTOP-4F2K:8080", "raspberrypi", "campanile.home.arpa", "box.lan", "localhost.",
        ):  # fmt: skip
            with self.subTest(host=host):
                r, _ = self.request("GET", "/api/notices", headers={"Host": host})
                self.assertEqual(r.status, 200)

    def test_without_any_name_too(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(b"GET /api/notices HTTP/1.0\r\n\r\n")  # HTTP/1.0: no Host at all
            self.assertIn(b" 200 ", s.recv(100).split(b"\r\n")[0])


class TestConnections(CampanileTestCase):
    def test_connection_cap(self):
        self.server.shutdown()
        self.server.server_close()
        self.server = campanile.create_server("127.0.0.1", 0, self.cfg, max_connections=2)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        busy = [socket.create_connection(("127.0.0.1", self.port)) for _ in range(2)]
        try:
            time.sleep(0.2)
            third = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            third.sendall(b"GET /api/status HTTP/1.1\r\nHost: localhost\r\n\r\n")
            try:
                reply = third.recv(100)
            except ConnectionResetError:
                reply = b""
            self.assertEqual(reply, b"")  # still nothing to free (too fresh): turned away
            third.close()
        finally:
            for s in busy:
                s.close()
        time.sleep(0.2)
        self.assertEqual(self.json("GET", "/api/status")[0], 200)  # slots freed again

    def broken_once(self, error):
        """The next request on this server raises error, as a dead socket would."""
        handler = self.server.RequestHandlerClass
        original = handler.handle_one_request

        def failing(this):
            handler.handle_one_request = original
            raise error

        handler.handle_one_request = failing
        self.addCleanup(setattr, handler, "handle_one_request", original)

    def stderr_of_one_request(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            # the connection dies: that's the point
            with contextlib.suppress(http.client.HTTPException, OSError):
                self.request("GET", "/api/status")
            time.sleep(0.3)
        return output.getvalue()

    def test_a_device_reading_slowly_on_every_slot_gives_one_up(self):
        """Every slot held by answers someone reads very slowly: a phone still gets in."""
        self.server.shutdown()
        self.server.server_close()
        slots = campanile.FAIR_SHARE * 2  # one device holding all of them: over its share
        self.server = campanile.create_server("127.0.0.1", 0, self.cfg, max_connections=slots)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        with open(self.data / "maps" / "big.pmtiles", "wb") as f:
            f.truncate(64 * 1024 * 1024)  # far more than the socket buffers hold
        slow = []
        for _ in range(slots):  # ask for the whole file and never read it
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            s.connect(("127.0.0.1", self.port))
            s.sendall(b"GET /maps/big.pmtiles HTTP/1.1\r\nHost: localhost\r\n\r\n")
            slow.append(s)
        try:
            time.sleep(0.5)
            self.assertEqual(len(self.server._answering), slots)  # all still being sent
            started = time.monotonic()
            self.assertEqual(self.json("GET", "/api/status")[0], 200)
            self.assertLess(time.monotonic() - started, campanile.SLOT_WAIT)
        finally:
            for s in slow:
                s.close()

    def test_a_busy_port_says_so(self):
        # Someone double-clicks twice: the launcher must get the OSError, to say "already on".
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            with self.assertRaises(OSError):
                campanile.create_server("127.0.0.1", taken.getsockname()[1], self.cfg)

    def test_network_errors_leave_no_traceback(self):
        # On Windows a connection closed by the watchdog raises WinError 10058 when read.
        self.broken_once(BrokenPipeError(10058, "socket shut down"))
        self.assertEqual(self.stderr_of_one_request(), "")
        self.assertEqual(self.json("GET", "/api/status")[0], 200)  # still serving

    def test_real_bugs_still_show_their_traceback(self):
        self.broken_once(RuntimeError("a bug"))
        self.assertIn("RuntimeError: a bug", self.stderr_of_one_request())

    def test_a_crowd_gets_in_by_closing_idle_connections(self):
        """Every slot held by a browser's idle keep-alive connection: a new phone still gets in."""
        self.server.shutdown()
        self.server.server_close()
        self.server = campanile.create_server("127.0.0.1", 0, self.cfg, max_connections=4)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        idle = []
        for _ in range(4):  # a page loaded, then the connection left open, as browsers do
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/api/status")
            self.assertEqual(c.getresponse().read()[:1], b"{")
            idle.append(c)
        time.sleep(campanile.EVICT_AFTER + 0.3)
        try:
            started = time.monotonic()
            self.assertEqual(self.json("GET", "/api/status")[0], 200)
            self.assertLess(time.monotonic() - started, campanile.SLOT_WAIT)
            # The oldest idle connection was closed for it; a browser simply reconnects.
            closed = 0
            for c in idle:
                c.request("GET", "/api/status")
                try:
                    c.getresponse().read()
                except (http.client.RemoteDisconnected, ConnectionError):  # aborted on Windows
                    closed += 1
            self.assertGreaterEqual(closed, 1)
        finally:
            for c in idle:
                c.close()


class TestSlowClients(CampanileTestCase):
    """A single device must not be able to lock everyone else out."""

    def restart(self, **options):
        self.server.shutdown()
        self.server.server_close()
        self.server = campanile.create_server("127.0.0.1", 0, self.cfg, **options)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def slow_connection(self, source="127.0.0.1", data=b"GET / HTTP/1.1\r\nHost: x\r\n"):
        s = socket.create_connection(("127.0.0.1", self.port), source_address=(source, 0))
        s.sendall(data)  # the request is never finished
        return s

    def closed_by_server(self, s, wait=5):
        s.settimeout(wait)
        try:
            return s.recv(100) == b""
        except ConnectionError:  # reset on Linux, aborted (WinError 10053) on Windows
            return True
        except socket.timeout:
            return False

    def test_unfinished_request_is_dropped_after_the_deadline(self):
        self.restart(request_deadline=1)
        s = self.slow_connection()
        try:
            self.assertTrue(self.closed_by_server(s))
        finally:
            s.close()

    def test_trickled_headers_dont_extend_the_deadline(self):
        self.restart(request_deadline=1)
        s = self.slow_connection()
        try:
            for _ in range(4):  # one header line every 0.4 s: each read is fast, the total is not
                time.sleep(0.4)
                with contextlib.suppress(OSError):
                    s.sendall(b"X-A: b\r\n")
            self.assertTrue(self.closed_by_server(s, wait=1))
        finally:
            s.close()

    def test_unfinished_post_body_is_dropped_after_the_deadline(self):
        self.restart(request_deadline=1)
        head = (
            b"POST /api/posts HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{"
        )
        s = self.slow_connection(data=head)
        try:
            self.assertTrue(self.closed_by_server(s))
        finally:
            s.close()

    def test_one_device_cannot_take_every_slot(self):
        try:
            socket.create_connection(
                ("127.0.0.1", self.port), source_address=("127.0.0.2", 0)
            ).close()
        except OSError:
            self.skipTest("this system has no 127.0.0.2 to act as a second device")
        self.restart(max_per_ip=2, request_deadline=30)
        attacker = [self.slow_connection() for _ in range(2)]
        try:
            time.sleep(0.2)
            third = self.slow_connection()
            self.assertTrue(self.closed_by_server(third))  # the attacker's third one is refused
            third.close()
            other = http.client.HTTPConnection(
                "127.0.0.1", self.port, timeout=5, source_address=("127.0.0.2", 0)
            )
            other.request("GET", "/api/status")
            self.assertEqual(other.getresponse().status, 200)  # another device still gets in
            other.close()
        finally:
            for s in attacker:
                s.close()


class TestBehindProxy(CampanileTestCase):
    """nginx in front: the phone's address arrives in X-Real-IP."""

    def setUp(self):
        super().setUp()
        self.cfg.behind_proxy = True

    def as_phone(self, ip):
        return {"X-Real-IP": ip}

    def test_write_limits_are_per_phone_not_shared(self):
        for _ in range(campanile.MAX_WRITES_PER_IP):
            status, r = self.json(
                "POST", "/api/posts", self.post_data(), self.as_phone("10.42.0.20")
            )
            self.assertEqual(status, 201)
            self.json(
                "POST",
                "/api/posts/close",
                {"id": r["id"], "code": r["code"]},
                self.as_phone("10.42.0.20"),
            )
        self.assertEqual(
            self.json("POST", "/api/posts", self.post_data(), self.as_phone("10.42.0.20"))[0], 429
        )
        self.assertEqual(
            self.json("POST", "/api/posts", self.post_data(), self.as_phone("10.42.0.21"))[0], 201
        )

    def test_admin_only_for_the_campanile_itself(self):
        ok = {"password": PASSWORD}
        self.assertEqual(
            self.json("POST", "/api/admin/list", ok, self.as_phone("127.0.0.1"))[0], 200
        )
        self.assertEqual(
            self.json("POST", "/api/admin/list", ok, self.as_phone("10.42.0.20"))[0], 403
        )

    def test_missing_or_bad_header_is_never_local(self):
        ok = {"password": PASSWORD}
        self.assertEqual(self.json("POST", "/api/admin/list", ok)[0], 403)
        self.assertEqual(
            self.json("POST", "/api/admin/list", ok, self.as_phone("localhost"))[0], 403
        )

    def test_status_uses_public_urls(self):
        self.cfg.public_url = "http://10.42.0.1/"
        self.cfg.kiwix_url = "/wiki/"
        _, r = self.json("GET", "/api/status")
        self.assertEqual((r["address"], r["kiwix_url"]), ("http://10.42.0.1/", "/wiki/"))

    def test_connection_cap_per_ip_is_left_to_nginx(self):
        server = campanile.create_server("127.0.0.1", 0, self.cfg)
        try:
            self.assertEqual(server._max_per_ip, campanile.MAX_CONNECTIONS)
        finally:
            server.server_close()

    def post_data(self):
        return {"kind": "offer", "category": "water", "text": "t", "area": "a", "contact": "c"}


class TestPlaces(CampanileTestCase):
    """Searching the maps, from the phone."""

    def setUp(self):
        super().setUp()
        (self.data / "maps" / "town.pmtiles").write_bytes(mapfixture.pmtiles(town()))
        with contextlib.redirect_stdout(io.StringIO()):  # test.pmtiles is not a real map
            self.cfg.places.refresh(now=True)
            self.cfg.places.wait()

    def find(self, query, near="7.68,45.07", lang="it"):
        path = "/api/places?q=" + quote(query) + (f"&near={near}" if near is not None else "")
        return self.json("GET", path, headers={"Accept-Language": lang})

    def test_the_nearest_pharmacy(self):
        status, r = self.find("farmacia")
        self.assertEqual(status, 200)
        self.assertTrue(r["ready"])
        first = r["results"][0]
        self.assertEqual(
            (first["name"], first["kind"], first["near"]),
            ("Farmacia Centrale", "pharmacy", "Quartiere Alfa"),
        )
        self.assertLess(first["meters"], 300)

    def test_in_the_language_of_the_page(self):
        self.assertEqual(self.find("test town", lang="en")[1]["results"][0]["name"], "Test Town")
        self.assertEqual(self.find("test town", lang="it")[1]["results"][0]["name"], "Borgo Prova")

    def test_without_a_position(self):
        status, r = self.find("fontanella", near=None)
        self.assertEqual((status, r["results"][0]["name"]), (200, "Fontanella"))
        self.assertNotIn("meters", r["results"][0])

    def test_too_short_or_not_text(self):
        for query in ("", "a", " é ", "%%", "\u200b"):
            with self.subTest(query=query):
                self.assertEqual(self.find(query)[0], 400)
        self.assertEqual(self.json("GET", "/api/places")[0], 400)

    def test_searches_are_limited_per_phone(self):
        for _ in range(campanile.SEARCHES):
            self.assertEqual(self.find("farmacia")[0], 200)
        status, r = self.find("farmacia")
        self.assertEqual(status, 429)
        self.assertIn("error", r)

    def test_one_search_at_a_time_and_the_rest_answers_meanwhile(self):
        started, release = threading.Event(), threading.Event()
        real = self.cfg.places.search

        def slow(*args):
            started.set()
            release.wait(10)
            return real(*args)

        answers = []
        with (
            mock.patch.object(self.cfg.places, "search", side_effect=slow),
            mock.patch.object(campanile, "SEARCH_WAIT", 0.3),
        ):
            first = threading.Thread(target=lambda: answers.append(self.find("farmacia")[0]))
            first.start()
            self.assertTrue(started.wait(5))
            began = time.monotonic()
            status, r = self.find("fontanella")  # waits its turn, then gives up
            self.assertEqual((status, "error" in r), (503, True))
            self.assertLess(time.monotonic() - began, 2)
            self.assertEqual(self.json("GET", "/api/notices")[0], 200)  # not held up
            release.set()
            first.join(10)
        self.assertEqual(answers, [200])
        self.assertEqual(self.find("fontanella")[0], 200)  # the turn is free again

    def test_an_impossible_position_is_refused(self):
        for near in (
            "abc",
            "7.68",
            "7.68,45.07,1",
            "200,45",
            "7,-91",
            "nan,45",
            "inf,45",
            "1e309,0",
        ):
            with self.subTest(near=near):
                self.assertEqual(self.find("farmacia", near=near)[0], 400)


class TestNoProxy(CampanileTestCase):
    def test_x_real_ip_is_ignored_without_a_proxy(self):
        old = campanile.LOCAL_ADDRESSES
        campanile.LOCAL_ADDRESSES = {"10.9.9.9"}  # the test client (127.0.0.1) is now "remote"
        try:
            status, _ = self.json(
                "POST", "/api/admin/list", {"password": PASSWORD}, {"X-Real-IP": "10.9.9.9"}
            )
            self.assertEqual(status, 403)
        finally:
            campanile.LOCAL_ADDRESSES = old


class TestTimeAndLog(CampanileTestCase):
    """Nothing stays forever, the admin's actions are written down, and the clock can be put
    right from the admin page (a Raspberry restarts behind, without internet)."""

    def later(self, days: float) -> None:
        self.cfg.store.offset += days * 86400  # as if that much time had passed
        self.cfg.store._forgot = 0

    def rows(self, table: str) -> int:
        return self.cfg.store._count(f"SELECT COUNT(*) FROM {table}")  # noqa: S608

    def test_old_posts_and_names_are_deleted_by_themselves(self):
        self.post()
        self.assertEqual(self.json("POST", "/api/safe", {"name": "Anna"})[0], 201)
        self.later(store.POST_DAYS + 1)
        self.assertEqual(self.json("GET", "/api/posts")[1]["posts"], [])
        self.assertEqual((self.rows("posts"), self.rows("safe")), (0, 1))  # deleted, not hidden
        self.later(store.SAFE_DAYS)
        self.assertEqual(self.json("GET", "/api/safe?q=anna")[1]["results"], [])
        self.assertEqual(self.rows("safe"), 0)

    def test_what_is_deleted_leaves_the_disk(self):
        # A deleted row stays in the file until overwritten: whoever takes the device could
        # read it back. Measured before the fix: the phone number was still in the file.
        def on_disk(text):
            return any(text.encode() in f.read_bytes() for f in self.data.glob("campanile.db*"))

        self.post(contact="3331234567")
        status, r = self.json("POST", "/api/safe", {"name": "Annabella Rossi"})
        self.assertEqual(status, 201)
        self.assertTrue(on_disk("3331234567") and on_disk("Annabella"))  # the control
        removed = {"id": r["id"], "code": r["code"]}
        self.assertEqual(self.json("POST", "/api/safe/remove", removed)[0], 200)
        self.assertFalse(on_disk("Annabella"))
        self.later(store.POST_DAYS + 1)
        self.post(contact="Lia")  # writing is when old posts are deleted
        self.assertFalse(on_disk("3331234567"))

    def test_zero_days_keeps_them(self):
        self.cfg.store.keep["posts"] = 0
        self.post()
        self.later(365)
        self.assertEqual(len(self.json("GET", "/api/posts")[1]["posts"]), 1)

    def test_what_the_admin_did_is_written_down(self):
        self.admin("/api/admin/notices", title="Acqua in piazza", text="Alle 16.")
        self.admin("/api/admin/close-recent", minutes=15)
        status, r = self.admin("/api/admin/log")
        self.assertEqual(status, 200)
        done = [(e["action"], e["detail"]) for e in r["log"]]
        self.assertEqual(done[:2], [("recent_closed", "15 min: 0"), ("notice", "Acqua in piazza")])
        self.assertEqual(r["keep"], {"posts": store.POST_DAYS, "safe": store.SAFE_DAYS})
        wrong = self.json("POST", "/api/admin/log", {"password": "x"})[0]
        self.assertEqual(wrong, 403)

    def test_the_clock_is_put_right_from_the_admin_page_and_kept(self):
        real = time.time() + 3 * 86400  # the Raspberry restarted three days behind
        status, r = self.admin("/api/admin/clock", now=real)
        self.assertEqual(status, 200)
        self.assertAlmostEqual(r["now"], real, delta=2)
        response, _ = self.request("GET", "/api/status")
        sent = email.utils.parsedate_to_datetime(response.getheader("Date")).timestamp()
        self.assertAlmostEqual(sent, real, delta=2)  # the phones read their clock against it
        again = store.Store(self.data / "campanile.db")  # a restart keeps it
        self.assertAlmostEqual(again.now(), real, delta=2)
        again.close()
        self.assertEqual(self.admin("/api/admin/log")[1]["log"][0]["action"], "clock_set")

    def test_the_clock_takes_only_a_sensible_time_and_only_from_the_admin(self):
        for bad in (time.time() + 401 * 86400, "domani", True, None):
            with self.subTest(bad=bad):
                self.assertEqual(self.admin("/api/admin/clock", now=bad)[0], 400)
        stolen = self.json("POST", "/api/admin/clock", {"password": "x", "now": time.time()})
        self.assertEqual(stolen[0], 403)
        self.assertEqual(self.cfg.store.offset, 0)

    def test_the_emergency_number_is_set_from_the_admin_page_and_kept(self):
        self.assertEqual(self.json("GET", "/api/status")[1]["emergency"], "112")
        self.cfg.emergency = "911"  # a laptop set to the United States starts with it
        self.assertEqual(self.json("GET", "/api/status")[1]["emergency"], "911")
        saved = self.admin("/api/admin/emergency", number="999")
        self.assertEqual(saved, (200, {"emergency": "999"}))
        self.assertEqual(self.json("GET", "/api/status")[1]["emergency"], "999")
        again = store.Store(self.data / "campanile.db")  # a restart keeps it
        self.assertEqual(again.emergency(), "999")
        again.close()
        self.assertEqual(self.admin("/api/admin/log")[1]["log"][0]["action"], "emergency_set")

    def test_the_emergency_number_is_digits_only_and_only_from_the_admin(self):
        for bad in ("11 2", "1", "1234567", "112<script>", "\u0661\u0661\u0662", 911, None, ""):
            with self.subTest(bad=bad):
                self.assertEqual(self.admin("/api/admin/emergency", number=bad)[0], 400)
        stolen = self.json("POST", "/api/admin/emergency", {"password": "x", "number": "000"})
        self.assertEqual(stolen[0], 403)
        self.assertEqual(self.json("GET", "/api/status")[1]["emergency"], "112")
        with self.assertRaises(argparse.ArgumentTypeError):
            campanile.emergency_number("9 1 1")


@unittest.skipUnless(CAN_SIGN, "signing in the tests needs the cryptography package")
class TestSignedNotices(CampanileTestCase):
    def setUp(self):
        super().setUp()
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.Ed25519PrivateKey = Ed25519PrivateKey
        self.key = Ed25519PrivateKey.generate()
        raw = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        keys = self.data / "trusted-keys.json"
        keys.write_text(
            json.dumps(
                {
                    "keys": [
                        {"name": "Protezione Civile", "public_key": base64.b64encode(raw).decode()}
                    ]
                }
            )
        )
        self.cfg.trusted_keys = signing.TrustedKeys.load(keys)

    def signed(self, key=None, issued=None, hours=24, **changes):
        key = key or self.key
        from cryptography.hazmat.primitives import serialization

        raw = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        issued = int(time.time()) if issued is None else issued
        notice = {
            "title": "Acqua non potabile",
            "text": "Bollire l'acqua.",
            "urgent": True,
            "issued": issued,
            "expires": issued + int(hours * 3600),
            "issuer": signing.key_id(raw),
        }
        signature = key.sign(signing.message(notice))
        notice.update(changes)  # changes after signing = tampering
        return {
            "format": signing.FORMAT,
            "notice": notice,
            "signature": base64.b64encode(signature).decode(),
        }

    def publish(self, signed):
        return self.admin("/api/admin/notices/signed", signed=signed)

    def test_checked_against_the_campanile_clock_as_corrected(self):
        # The admin set the clock two days ahead: a notice valid for one day has expired.
        self.cfg.store.set_clock(time.time() + 2 * 86400)
        status, r = self.publish(self.signed())
        self.assertEqual(status, 400)
        self.assertIn("scadut", r["error"])

    def test_a_lone_surrogate_in_a_signed_notice_is_refused_not_a_crash(self):
        # Found by fuzzing: the signature check re-encodes the fields before verifying.
        status, r = self.publish(self.signed(title="\ud800"))
        self.assertEqual(status, 400)
        self.assertIn("error", r)

    def test_valid_notice_is_published_and_independently_checkable(self):
        status, r = self.publish(self.signed())
        self.assertEqual((status, r["signer"]), (201, "Protezione Civile"))
        _, listing = self.json("GET", "/api/notices")
        n = listing["notices"][0]
        self.assertEqual(
            (n["signer"], n["title"], n["urgent"]),
            ("Protezione Civile", "Acqua non potabile", True),
        )
        # anyone holding the public key can re-check what the Campanile served
        self.key.public_key().verify(
            base64.b64decode(n["signed"]["signature"]), signing.message(n["signed"]["notice"])
        )

    def test_also_accepts_the_pasted_text(self):
        self.assertEqual(self.publish(json.dumps(self.signed()))[0], 201)

    def test_tampered_notice_is_refused(self):
        status, r = self.publish(self.signed(title="Evacuate subito"))
        self.assertEqual(status, 400)
        self.assertIn("alterato", r["error"])

    def test_unknown_key_is_refused(self):
        status, r = self.publish(self.signed(key=self.Ed25519PrivateKey.generate()))
        self.assertEqual(status, 400)
        self.assertIn("non riconosce", r["error"])

    def test_expired_or_too_long_is_refused(self):
        old = int(time.time()) - 3 * 24 * 3600
        self.assertEqual(self.publish(self.signed(issued=old, hours=24))[0], 400)
        self.assertEqual(self.publish(self.signed(hours=24 * 8))[0], 400)

    def test_same_notice_twice_is_refused(self):
        doc = self.signed()
        self.assertEqual(self.publish(doc)[0], 201)
        self.assertEqual(self.publish(doc)[0], 409)

    def test_garbage_is_refused(self):
        for bad in (
            None,
            "{",
            {"format": "x"},
            {**self.signed(), "signature": "!!!"},
            {**self.signed(), "signature": base64.b64encode(b"short").decode()},
        ):
            self.assertEqual(self.publish(bad)[0], 400, bad)

    def test_duplicate_keys_in_signed_text_are_refused(self):
        doc = json.dumps(self.signed())
        forged = doc.replace('"notice": {', '"notice": {"title": "Evacuate subito", ', 1)
        self.assertEqual(self.publish(forged)[0], 400)

    def test_stored_document_is_the_verified_one(self):
        doc = self.signed()
        doc["extra"] = "ignored field"
        self.assertEqual(self.publish(doc)[0], 201)
        served = self.json("GET", "/api/notices")[1]["notices"][0]["signed"]
        self.assertEqual(set(served), {"format", "notice", "signature"})

    def test_text_must_already_be_clean(self):
        from cryptography.hazmat.primitives import serialization

        raw = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        now = int(time.time())
        notice = {
            "title": "Ok",
            "text": "bad\x07",
            "urgent": False,
            "issued": now,
            "expires": now + 3600,
            "issuer": signing.key_id(raw),
        }
        doc = {
            "format": signing.FORMAT,
            "notice": notice,
            "signature": base64.b64encode(self.key.sign(signing.message(notice))).decode(),
        }
        self.assertEqual(self.publish(doc)[0], 400)

    def test_expired_notices_disappear(self):
        doc = self.signed(hours=2 / 3600)  # valid for 2 seconds
        self.assertEqual(self.publish(doc)[0], 201)
        time.sleep(2.5)
        self.assertEqual(self.json("GET", "/api/notices")[1]["notices"], [])

    def test_require_signed_refuses_plain_notices(self):
        self.cfg.require_signed = True
        self.assertEqual(self.admin("/api/admin/notices", title="x", text="y")[0], 403)
        self.assertEqual(self.publish(self.signed())[0], 201)

    def test_broken_keys_file_turns_signing_off_but_not_campanile(self):
        bad = self.data / "bad-keys.json"
        for content in (
            "{",
            '{"keys": [{"name": "x"}]}',
            '{"keys": [{"name": "x", "public_key": "AAAA"}]}',
        ):
            bad.write_text(content)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(len(signing.TrustedKeys.load(bad)), 0, content)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(signing.TrustedKeys.load(self.data / "missing.json")), 0)

    def test_status_says_signed_notices_are_on(self):
        self.assertTrue(self.json("GET", "/api/status")[1]["signed_notices"])


class TestSignedNoticesWithoutTheLibrary(TestSignedNotices):
    """Every test above again, checked by our ed25519.py as on a laptop without `cryptography`."""

    def setUp(self):
        without = mock.patch.object(signing, "Ed25519PublicKey", None)
        without.start()
        self.addCleanup(without.stop)
        super().setUp()

    def test_the_check_really_is_ours(self):
        with mock.patch.object(signing.ed25519, "verify", wraps=signing.ed25519.verify) as ours:
            self.assertEqual(self.publish(self.signed())[0], 201)
        ours.assert_called_once()


class TestStoreMigration(unittest.TestCase):
    def test_old_database_gets_the_new_columns(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE notices (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,"
                " text TEXT NOT NULL, urgent INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL)"
            )
            db.execute(
                "INSERT INTO notices (title, text, urgent, created) VALUES ('Vecchio', 'x', 0, 1)"
            )
            db.commit()
            db.close()
            s = store.Store(path)
            try:
                self.assertEqual([n["title"] for n in s.list_notices()], ["Vecchio"])
            finally:
                s.close()

    def test_an_old_log_learns_who(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            db = sqlite3.connect(path)
            db.execute(
                "CREATE TABLE admin_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,"
                " action TEXT NOT NULL, detail TEXT NOT NULL)"
            )
            db.execute("INSERT INTO admin_log (at, action, detail) VALUES (1, 'notice', 'Vecchio')")
            db.commit()
            db.close()
            s = store.Store(path)
            try:
                s.log("notice", "Nuovo", who="Maria")
                log = [(e["who"], e["detail"]) for e in s.admin_log()]
                self.assertEqual(log, [("Maria", "Nuovo"), ("", "Vecchio")])
            finally:
                s.close()


ARP_HEADER = "IP address       HW type     Flags       HW address            Mask     Device\n"


class TestDevices(CampanileTestCase):
    """Limits per phone, not per IP address; flood brake; cleanup after a flood."""

    def setUp(self):
        super().setUp()
        self.cfg.behind_proxy = True
        self.arp = self.data / "arp"
        self.arp.write_text(
            ARP_HEADER
            + "10.42.0.20  0x1  0x2  aa:aa:aa:aa:aa:aa  *  wlan0\n"
            + "10.42.0.21  0x1  0x2  aa:aa:aa:aa:aa:aa  *  wlan0\n"  # same phone, second IP
            + "10.42.0.30  0x1  0x2  bb:bb:bb:bb:bb:bb  *  wlan0\n"
            + "10.42.0.40  0x1  0x0  00:00:00:00:00:00  *  wlan0\n"  # incomplete entry
        )
        self.cfg.device_tags = devices.DeviceTags(self.arp)

    def admin(self, path, **body):  # behind nginx the admin comes from the Raspberry itself
        return self.json("POST", path, {"password": PASSWORD, **body}, {"X-Real-IP": "127.0.0.1"})

    def post_as(self, ip, **overrides):
        data = {"kind": "offer", "category": "water", "text": "t", "area": "a", "contact": "c"}
        data.update(overrides)
        return self.json("POST", "/api/posts", data, {"X-Real-IP": ip})

    def test_mac_lookup(self):
        self.assertEqual(devices.mac_for("10.42.0.20", self.arp), "aa:aa:aa:aa:aa:aa")
        self.assertIsNone(devices.mac_for("10.42.0.40", self.arp))  # incomplete
        self.assertIsNone(devices.mac_for("10.42.0.99", self.arp))  # unknown
        self.assertIsNone(devices.mac_for("10.42.0.20", self.data / "missing"))

    def test_new_ip_on_the_same_phone_shares_the_limit(self):
        for _ in range(store.MAX_OPEN_POSTS_PER_DEVICE):
            self.assertEqual(self.post_as("10.42.0.20")[0], 201)
        status, r = self.post_as("10.42.0.21")  # same MAC, different IP
        self.assertEqual(status, 429)
        self.assertIn("annunci aperti", r["error"])
        self.assertEqual(self.post_as("10.42.0.30")[0], 201)  # another phone

    def test_closing_a_post_frees_a_slot(self):
        codes = [self.post_as("10.42.0.20")[1] for _ in range(store.MAX_OPEN_POSTS_PER_DEVICE)]
        self.assertEqual(self.post_as("10.42.0.20")[0], 429)
        self.json("POST", "/api/posts/close", {"id": codes[0]["id"], "code": codes[0]["code"]})
        self.assertEqual(self.post_as("10.42.0.20")[0], 201)

    def test_unknown_device_falls_back_to_the_ip(self):
        for _ in range(store.MAX_OPEN_POSTS_PER_DEVICE):
            self.assertEqual(self.post_as("10.42.0.40")[0], 201)
        self.assertEqual(self.post_as("10.42.0.40")[0], 429)
        self.assertEqual(self.post_as("10.42.0.41")[0], 201)

    def test_flood_brake_sends_new_posts_to_review(self):
        self.cfg.post_flow = store.RateLimiter(3, 300)
        phones = ["10.42.0.50", "10.42.0.51", "10.42.0.52", "10.42.0.53", "10.42.0.54"]
        results = [self.post_as(ip)[1] for ip in phones]
        self.assertEqual([r["pending"] for r in results], [False, False, False, True, True])
        self.assertEqual(len(self.json("GET", "/api/posts")[1]["posts"]), 3)  # board stays clean
        _, admin = self.admin("/api/admin/list")
        self.assertEqual(len(admin["pending"]), 2)
        self.assertEqual(self.admin("/api/admin/approve", id=results[3]["id"])[0], 200)
        self.assertEqual(len(self.json("GET", "/api/posts")[1]["posts"]), 4)
        self.assertEqual(self.admin("/api/admin/approve", id=results[3]["id"])[0], 404)

    def test_pending_queue_has_its_own_cap(self):
        self.cfg.post_flow = store.RateLimiter(0, 300)  # everything goes to review
        old = store.MAX_PENDING_POSTS
        store.MAX_PENDING_POSTS = 2
        try:
            self.assertEqual(self.post_as("10.42.0.60")[0], 201)
            self.assertEqual(self.post_as("10.42.0.61")[0], 201)
            self.assertEqual(self.post_as("10.42.0.62")[0], 503)
        finally:
            store.MAX_PENDING_POSTS = old

    def test_close_everything_from_one_device(self):
        for _ in range(3):
            self.post_as("10.42.0.20")
        self.post_as("10.42.0.30")
        _, admin = self.admin("/api/admin/list")
        attacker = {p["device"] for p in admin["posts"] if p["text"] == "t"}
        tags = sorted(attacker)
        counts = {t: sum(p["device"] == t for p in admin["posts"]) for t in tags}
        flood = max(counts, key=counts.get)
        status, r = self.admin("/api/admin/close-device", device=flood)
        self.assertEqual((status, r["closed"]), (200, 3))
        self.assertEqual(len(self.json("GET", "/api/posts")[1]["posts"]), 1)  # the other phone's

    def test_close_recent_and_bad_input(self):
        self.post_as("10.42.0.20")
        self.assertEqual(self.admin("/api/admin/close-recent", minutes=10)[1]["closed"], 1)
        for bad in (0, 1441, "10", True, None):
            self.assertEqual(self.admin("/api/admin/close-recent", minutes=bad)[0], 400, bad)
        for bad in ("", "x" * 12, "ABCDEF123456", None, 5):
            self.assertEqual(self.admin("/api/admin/close-device", device=bad)[0], 400, bad)

    def test_safe_registry_per_device_and_cleanup(self):
        h = {"X-Real-IP": "10.42.0.20"}
        for i in range(store.MAX_SAFE_PER_DEVICE):
            self.assertEqual(self.json("POST", "/api/safe", {"name": f"Nome {i}"}, h)[0], 201)
        self.assertEqual(
            self.json("POST", "/api/safe", {"name": "Altro"}, {"X-Real-IP": "10.42.0.21"})[0], 429
        )
        _, admin = self.admin("/api/admin/list")
        tag = admin["safe"][0]["device"]
        self.assertEqual(self.admin("/api/admin/remove-device-safe", device=tag)[1]["removed"], 10)

    def test_nothing_identifying_is_stored(self):
        self.post_as("10.42.0.20")
        self.json("POST", "/api/safe", {"name": "Anna"}, {"X-Real-IP": "10.42.0.20"})
        dump = "\n".join(self.cfg.store._db.iterdump())
        for secret in ("aa:aa:aa", "10.42.0.20"):
            self.assertNotIn(secret, dump)

    def test_tags_change_every_day(self):
        day = ["2026-10-22"]
        tags = devices.DeviceTags(self.arp, today=lambda: day[0])
        first = tags.tag("10.42.0.20")
        self.assertEqual(tags.tag("10.42.0.21"), first)  # same phone, same day
        day[0] = "2026-10-23"
        self.assertNotEqual(tags.tag("10.42.0.20"), first)

    def test_tag_is_recomputed_on_every_request(self):
        # Two phones' requests on one connection (as nginx could do) must not share a tag.
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        body = json.dumps(
            {"kind": "offer", "category": "water", "text": "t", "area": "a", "contact": "c"}
        )
        for ip in ["10.42.0.20"] * store.MAX_OPEN_POSTS_PER_DEVICE:
            conn.request(
                "POST", "/api/posts", body, {"Content-Type": "application/json", "X-Real-IP": ip}
            )
            self.assertEqual(conn.getresponse().read() and 201, 201)
        conn.request(
            "POST",
            "/api/posts",
            body,
            {"Content-Type": "application/json", "X-Real-IP": "10.42.0.30"},
        )
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 201)  # not blocked by the previous phone's limit
        conn.close()


class TestLanguages(CampanileTestCase):
    def error(self, accept_language, **post):
        h = {"Accept-Language": accept_language} if accept_language is not None else {}
        data = {"kind": "offer", "category": "water", "text": "", "area": "a", "contact": "c"}
        data.update(post)
        return self.json("POST", "/api/posts", data, h)[1]["error"]

    def test_english_phone_gets_english_with_translated_field(self):
        self.assertEqual(self.error("en-GB,en;q=0.9"), "The field 'description' is required.")

    def test_italian_and_default(self):
        self.assertEqual(self.error("it-IT"), "Il campo 'descrizione' è obbligatorio.")
        self.assertEqual(self.error(None), "Il campo 'descrizione' è obbligatorio.")

    def test_unsupported_language_falls_back_to_english(self):
        self.assertEqual(self.error("de-DE,de;q=0.9"), "The field 'description' is required.")

    def test_quality_values_are_respected(self):
        self.assertEqual(self.error("en;q=0.2, it;q=0.8"), "Il campo 'descrizione' è obbligatorio.")

    def test_garbage_header_does_not_break_anything(self):
        for header in ("", ";;;", "en;q=abc", "x" * 5000, "*", "it;q=-1, ,,"):
            self.assertIn("descri", self.error(header), header)

    def test_every_message_exists_in_every_language(self):
        import messages

        for key, texts in messages.MESSAGES.items():
            self.assertEqual(set(texts), set(messages.LANGUAGES), key)
        for key, texts in messages.FIELDS.items():
            self.assertEqual(set(texts), set(messages.LANGUAGES), key)

    def test_the_laptop_window_speaks_every_language_in_plain_ascii(self):
        import messages

        for key, texts in messages.WINDOW.items():
            self.assertEqual(set(texts), set(messages.LANGUAGES), key)
            for text in texts.values():
                text.encode("ascii")  # a Windows console may show nothing else


class TestComputerLanguage(unittest.TestCase):
    """The language and country of the computer itself, for its own window."""

    def ask(self, platform="linux", env=None, mac=None):
        import messages

        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        if mac is not None:  # the Mac's settings file, as macOS writes it
            prefs = home / "Library" / "Preferences" / ".GlobalPreferences.plist"
            prefs.parent.mkdir(parents=True)
            prefs.write_bytes(plistlib.dumps(mac, fmt=plistlib.FMT_BINARY))
        with (
            mock.patch.object(messages.sys, "platform", platform),
            mock.patch.object(messages.Path, "home", return_value=home),
            mock.patch.dict(os.environ, env or {}, clear=True),
        ):
            return messages.computer_language(), messages.computer_region()

    def test_a_linux_or_raspberry_terminal(self):
        self.assertEqual(self.ask(env={"LANG": "it_IT.UTF-8"}), ("it", "IT"))
        self.assertEqual(self.ask(env={"LANG": "en_US.UTF-8"}), ("en", "US"))
        self.assertEqual(self.ask(env={"LC_ALL": "en_CA.UTF-8", "LANG": "it_IT"}), ("en", "CA"))

    def test_a_mac_follows_its_settings_even_when_the_terminal_says_nothing(self):
        mac = {"AppleLanguages": ["en-US"], "AppleLocale": "en_US"}
        self.assertEqual(self.ask("darwin", {"LANG": "C.UTF-8"}, mac), ("en", "US"))

    def test_the_first_language_we_speak_wins_and_the_region_setting_gives_the_country(self):
        mac = {"AppleLanguages": ["es-ES", "it-IT"], "AppleLocale": "it_CA"}
        self.assertEqual(self.ask("darwin", mac=mac), ("it", "CA"))

    def test_nothing_known_means_english_and_no_country(self):
        self.assertEqual(self.ask(env={"LANG": "C.UTF-8"}), ("en", ""))
        self.assertEqual(self.ask(env={"LANG": "de_DE.UTF-8"}), ("en", "DE"))
        self.assertEqual(self.ask("darwin", mac={"AppleLanguages": "it"}), ("en", ""))  # not a list
        if sys.platform != "win32":  # Windows' settings missing: it must not break
            self.assertEqual(self.ask("win32"), ("en", ""))

    def test_a_damaged_mac_settings_file_never_stops_the_start(self):
        import messages

        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        prefs = home / "Library" / "Preferences" / ".GlobalPreferences.plist"
        prefs.parent.mkdir(parents=True)
        prefs.write_bytes(b'<?xml version="1.0"?><plist><dict><key>AppleLanguages</key><array>')
        with (
            mock.patch.object(messages.sys, "platform", "darwin"),
            mock.patch.object(messages.Path, "home", return_value=home),
            mock.patch.dict(os.environ, {"LANG": "it_IT.UTF-8"}, clear=True),
        ):
            self.assertEqual(messages.computer_language(), "it")  # the terminal still says it

    def test_this_computer_answers(self):
        import messages

        self.assertIn(messages.computer_language(), messages.LANGUAGES)
        self.assertRegex(messages.computer_region(), r"^([A-Z]{2})?$")

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_windows_says_its_language_in_its_settings(self):
        import messages

        # No environment at all: what is left can only come from Windows itself.
        with mock.patch.dict(os.environ, {}, clear=True):
            tags = messages._computer_tags()
        self.assertRegex(tags[0] if tags else "", r"^[a-z]{2,3}_[A-Z]{2}")


class TestUnits(unittest.TestCase):
    def test_parse_range(self):
        f = campanile.parse_range
        self.assertEqual(f("bytes=0-0", 10), (0, 0))
        self.assertEqual(f("bytes=9-", 10), (9, 9))
        self.assertEqual(f("bytes=-1", 10), (9, 9))
        self.assertEqual(f("bytes=10-", 10), "invalid")
        self.assertEqual(f("bytes=-0", 10), "invalid")
        self.assertEqual(f("bytes=0-", 0), "invalid")
        self.assertIsNone(f("bytes=3-2", 10))
        self.assertIsNone(f("bytes=0-1,3-4", 10))

    def test_codes(self):
        codes = {store.new_code() for _ in range(2000)}
        self.assertEqual(len(codes), 2000)
        for c in list(codes)[:50]:
            self.assertRegex(c, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
            self.assertNotRegex(c, r"[01OIL]")
        self.assertEqual(store.hash_code("ab cd-efgh"), store.hash_code("ABCDEFGH"))

    def test_normalize_name(self):
        self.assertEqual(store.normalize_name("  Nicolò   DE  Santis "), "nicolo de santis")
        self.assertEqual(store.normalize_name("Straße"), "strasse")


def cap_alert(
    status="Actual",
    kind="Alert",
    scope="Public",
    ns="1.2",
    expires="2099-01-01T00:00:00+01:00",
    severity="Severe",
    identifier="IT-2026-0042",
    extra="",
    text="State lontani dal fiume.",
):
    """An official alert in CAP, in English and in Italian, like the ones IT-alert carries."""

    def info(lang, event, headline, description):
        return (
            f"<info><language>{lang}</language><category>Met</category><event>{event}</event>"
            f"<urgency>Immediate</urgency><severity>{severity}</severity>"
            f"<certainty>Observed</certainty><expires>{expires}</expires>"
            f"<senderName>{'Civil Protection' if lang == 'en-GB' else 'Protezione Civile'}"
            f"</senderName><headline>{headline}</headline><description>{description}</description>"
            + ("<instruction>Salite ai piani alti.</instruction>" if lang == "it-IT" else "")
            + "</info>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<alert xmlns="urn:oasis:names:tc:emergency:cap:{ns}">'
        f"<identifier>{identifier}</identifier>"
        "<sender>allerta@protezionecivile.it</sender><sent>2026-10-26T15:00:00+01:00</sent>"
        f"<status>{status}</status><msgType>{kind}</msgType><scope>{scope}</scope>{extra}"
        + info("en-GB", "Flood", "Flood on the Po", "Stay away from the river.")
        + info("it-IT", "Alluvione", "Piena del Po", text)
        + "</alert>"
    )


class TestCapAlerts(CampanileTestCase):
    """An official alert in CAP becomes a notice; anything else is refused with a reason."""

    def notices(self, lang="it"):
        return self.json("GET", "/api/notices", headers={"Accept-Language": lang})[1]["notices"]

    def refused(self, document, key, status=400, **params):
        before = len(self.notices())
        code, r = self.admin("/api/admin/cap", cap=document)
        self.assertEqual(
            (code, r["error"]), (status, store.RequestError(status, key, **params).text("it"))
        )
        self.assertEqual(len(self.notices()), before)  # nothing published

    def test_an_official_alert_becomes_a_notice_in_the_admin_language(self):
        status, r = self.admin("/api/admin/cap", cap=cap_alert())
        self.assertEqual(
            (status, r["title"], r["source"]), (201, "Piena del Po", "Protezione Civile")
        )
        [n] = self.notices()
        self.assertEqual(
            (n["title"], n["urgent"], n["source"]), ("Piena del Po", True, "Protezione Civile")
        )
        self.assertEqual(n["text"], "State lontani dal fiume.\n\nSalite ai piani alti.")
        self.assertEqual(n["expires"], 4070905200)  # 2099-01-01 00:00 +01:00
        self.assertEqual(self.admin("/api/admin/log")[1]["log"][0]["action"], "cap_notice")
        # In English, from an English admin page; CAP 1.1 is read too.
        english = self.json(
            "POST",
            "/api/admin/cap",
            {"password": PASSWORD, "cap": cap_alert(ns="1.1", identifier="IT-2")},
            {"Accept-Language": "en"},
        )
        self.assertEqual((english[0], english[1]["title"]), (201, "Flood on the Po"))

    def test_a_moderate_alert_is_not_red_and_an_expired_one_goes_by_itself(self):
        soon = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600))
        self.assertEqual(
            self.admin("/api/admin/cap", cap=cap_alert(severity="Moderate", expires=soon))[0], 201
        )
        self.assertFalse(self.notices()[0]["urgent"])
        self.cfg.store.offset += 7200  # two hours later
        self.assertEqual(self.notices(), [])

    def test_what_is_not_a_real_public_alert_is_refused(self):
        cases = [
            (cap_alert(status="Exercise"), "cap_exercise", {}),
            (cap_alert(status="Test"), "cap_not_actual", {"state": "Test"}),
            (cap_alert(kind="Cancel"), "cap_cancel", {}),
            (cap_alert(kind="Ack"), "cap_not_alert", {"kind": "Ack"}),
            (cap_alert(scope="Restricted"), "cap_not_public", {}),
            (cap_alert(expires="2001-01-01T00:00:00+01:00"), "cap_expired", {}),
            (cap_alert(expires="tomorrow"), "cap_bad_time", {}),
            (cap_alert(expires="2099-01-01T00:00:00"), "cap_bad_time", {}),  # no offset
            (cap_alert(ns="1.0"), "cap_not_cap", {}),
            (
                cap_alert().replace("<identifier>IT-2026-0042</identifier>", ""),
                "cap_missing",
                {"field": "identifier"},
            ),
            # a broken block in a language that would not be shown is still a broken alert
            (
                cap_alert().replace("<severity>Severe</severity>", "<severity>Huge</severity>", 1),
                "cap_bad_value",
                {"field": "severity"},
            ),
            ("<notice>just text</notice>", "cap_not_cap", {}),
            ("not xml at all", "cap_bad", {}),
        ]
        for document, key, params in cases:
            with self.subTest(key=key, params=params):
                self.refused(document, key, **params)

    def test_hostile_files_are_refused_before_parsing(self):
        laughs = (
            '<?xml version="1.0"?><!DOCTYPE alert [<!ENTITY a "aaaaaaaaaa">'
            + "".join(
                f'<!ENTITY {chr(98 + i)} "&{chr(97 + i)};&{chr(97 + i)};&{chr(97 + i)};">'
                for i in range(9)
            )
            + ']><alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
            + "<identifier>&j;</identifier></alert>"
        )
        steal = (
            '<?xml version="1.0"?><!DOCTYPE alert [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            + cap_alert().split("?>", 1)[1].replace("State lontani dal fiume.", "&x;")
        )
        for name, document in (
            ("billion laughs", laughs),
            ("external entity", steal),
            ("doctype in lower case", cap_alert().replace("<alert", "<!doctype alert><alert", 1)),
        ):
            with self.subTest(name):
                self.refused(document, "cap_unsafe")
        self.refused(cap_alert(extra="<note>" + "x" * 600_000 + "</note>"), "cap_too_big", max=512)

    def test_an_official_text_is_never_shortened_and_never_published_twice(self):
        self.refused(cap_alert(text="a" * 2001), "field_too_long", field="text", max=2000)
        self.assertEqual(self.admin("/api/admin/cap", cap=cap_alert())[0], 201)
        self.refused(cap_alert(), "cap_duplicate", status=409)

    def test_only_the_admin_on_the_campanile_itself(self):
        wrong = self.json("POST", "/api/admin/cap", {"password": "x", "cap": cap_alert()})
        self.assertEqual(wrong[0], 403)
        old = campanile.LOCAL_ADDRESSES
        campanile.LOCAL_ADDRESSES = {"10.9.9.9"}  # the test client is now a phone on the Wi-Fi
        try:
            small = self.json("POST", "/api/admin/cap", {"password": PASSWORD, "cap": cap_alert()})
            self.assertEqual(small[0], 403)
            # A phone gets the usual 8 kB, not the room an alert gets on the Campanile itself.
            big = self.json("POST", "/api/admin/cap", {"password": PASSWORD, "cap": "x" * 20_000})
            self.assertEqual(big[0], 413)
        finally:
            campanile.LOCAL_ADDRESSES = old
        self.assertEqual(self.notices(), [])

    def test_an_alert_shaped_like_it_alerts_own_is_read(self):
        # IT-alert's published messages (github.com/pcm-dpc/IT-alert-Hub): up to 108 kB of area
        # polygons, an XML signature, a block in German too, CAP-IT codes and parameters.
        polygon = " ".join(f"46.{i:05d},11.{i:05d}" for i in range(6000))
        extras = (
            "<code>CAP-IT:1.0</code>"
            '<Signature xmlns="http://www.w3.org/2000/09/xmldsig#"><SignedInfo/>'
            "<SignatureValue>AAAA</SignatureValue></Signature>"
        )
        german = (
            "<info><language>de-DE</language><category>Met</category><event>Test</event>"
            "<urgency>Unknown</urgency><severity>Extreme</severity><certainty>Unknown</certainty>"
            "<headline>Testnachricht</headline></info>"
        )
        area = (
            "<parameter><valueName>it-alert-level</valueName><value>1</value></parameter>"
            f"<area><areaDesc>Diga</areaDesc><polygon>{polygon}</polygon></area>"
        )
        document = cap_alert(extra=extras).replace(
            "</info></alert>", area + "</info>" + german + "</alert>"
        )
        self.assertGreater(len(document), 100_000)
        status, r = self.admin("/api/admin/cap", cap=document)
        self.assertEqual((status, r["title"]), (201, "Piena del Po"))

    def test_a_campanile_that_wants_signatures_refuses_cap(self):
        self.cfg.require_signed = True
        self.refused(cap_alert(), "signed_required", status=403)


class TestPfifExport(CampanileTestCase):
    """The "I'm safe" names leave as PFIF 1.4, for a larger registry; nothing else leaves."""

    NS = "{http://zesty.ca/pfif/1.4}"
    WHEN = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"

    def export(self):
        import xml.etree.ElementTree as ET

        status, r = self.admin("/api/admin/pfif")
        self.assertEqual(status, 200)
        return r, ET.fromstring(r["pfif"])  # noqa: S314 - our own export

    def field(self, element, name):
        found = element.find(self.NS + name)
        return None if found is None else found.text

    def test_the_names_leave_as_pfif_and_nothing_else_does(self):
        _, giulia = self.json(
            "POST",
            "/api/safe",
            {"name": "Giulia <Rossi> & figli", "message": "Sto bene", "place": "palestra"},
        )
        _, paolo = self.json("POST", "/api/safe", {"name": "Paolo Bianchi"})
        r, root = self.export()
        self.assertEqual((root.tag, r["count"]), (self.NS + "pfif", 2))
        people = {self.field(p, "full_name"): p for p in root.findall(self.NS + "person")}
        self.assertEqual(set(people), {"Giulia <Rossi> & figli", "Paolo Bianchi"})
        ids = set()
        for name, person in people.items():
            with self.subTest(name):
                pid = self.field(person, "person_record_id")
                self.assertRegex(pid, r"^campanile-[0-9a-f]{8}\.invalid/person\.\d+$")
                ids.add(pid)
                for when in ("entry_date", "source_date", "expiry_date"):
                    self.assertRegex(self.field(person, when), self.WHEN)
                self.assertIn("not verified", self.field(person, "description"))
                [note] = person.findall(self.NS + "note")
                self.assertEqual(self.field(note, "person_record_id"), pid)
                self.assertEqual(self.field(note, "status"), "believed_alive")
                self.assertTrue(self.field(note, "author_name") and self.field(note, "text"))
                self.assertRegex(self.field(note, "source_date"), self.WHEN)
        self.assertEqual(len(ids), 2)
        giulia_note = people["Giulia <Rossi> & figli"].find(self.NS + "note")
        self.assertEqual(self.field(giulia_note, "last_known_location"), "palestra")
        self.assertEqual(self.field(giulia_note, "text"), "Sto bene")
        self.assertIsNone(
            self.field(people["Paolo Bianchi"].find(self.NS + "note"), "last_known_location")
        )
        # Never the codes that remove a name, never the phone's tag.
        devices_seen = {row["device"] for row in self.cfg.store.all_safe()}
        for secret in [giulia["code"], paolo["code"], *filter(None, devices_seen)]:
            self.assertNotIn(secret, r["pfif"])
        # The same Campanile always signs its records the same way.
        self.assertEqual(
            self.export()[1]
            .find(self.NS + "person")
            .find(self.NS + "person_record_id")
            .text.split("/")[0],
            pid.split("/")[0],
        )
        self.assertEqual(self.admin("/api/admin/log")[1]["log"][0]["action"], "pfif_export")

    def test_an_empty_registry_is_a_valid_empty_file(self):
        r, root = self.export()
        self.assertEqual((root.tag, list(root), r["count"]), (self.NS + "pfif", [], 0))

    def test_only_the_admin(self):
        self.json("POST", "/api/safe", {"name": "Anna"})
        self.assertEqual(self.json("POST", "/api/admin/pfif", {"password": "x"})[0], 403)


if __name__ == "__main__":
    unittest.main()
