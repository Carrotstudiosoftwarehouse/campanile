# DEVELOPED BY CARROTSTUDIO software house
"""Maps and Wikipedia between two Campaniles over Wi-Fi: the code, the list, and impostors."""

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sharing
from preparation import Preparation, Sources
from test_server import PASSWORD, CampanileTestCase

MAP = os.urandom(300_000)
ZIM = os.urandom(200_000)
ZIM_NAME = "wikipedia_it_medicine_maxi_2026-10.zim"


class TestCode(unittest.TestCase):
    def test_codes_are_long_random_and_readable(self):
        codes = {sharing.new_code() for _ in range(200)}
        self.assertEqual(len(codes), 200)
        for code in codes:
            self.assertEqual(len(code), 16)
            self.assertTrue(set(code) <= set(sharing.ALPHABET))
            self.assertFalse(set(code) & set("ILOU"))  # nothing to misread
        self.assertRegex(sharing.show("K7QF2M9XR4TA8WHN"), r"^K7QF-2M9X-R4TA-8WHN$")

    def test_a_typed_code_is_forgiving_about_form_not_content(self):
        for typed in ("k7qf-2m9x-r4ta-8whn", " K7QF 2M9X R4TA 8WHN ", "K7QF2M9XR4TA8WHN"):
            self.assertEqual(sharing.normalize(typed), "K7QF2M9XR4TA8WHN", typed)
        self.assertEqual(sharing.normalize("IL0O-0000-0000-0000"), "1100000000000000")
        for bad in ("", "K7QF-2M9X-R4TA", "K7QF-2M9X-R4TA-8WHNX", "K7QF-2M9X-R4TA-8WH!", None, 7):
            self.assertIsNone(sharing.normalize(bad), bad)

    def test_the_signature_depends_on_the_code_and_on_every_byte(self):
        a = sharing.tag("K7QF2M9XR4TA8WHN", b"list")
        self.assertNotEqual(a, sharing.tag("K7QF2M9XR4TA8WHP", b"list"))
        self.assertNotEqual(a, sharing.tag("K7QF2M9XR4TA8WHN", b"lisT"))
        self.assertNotEqual(
            a, sharing.token("K7QF2M9XR4TA8WHN", "list", "")
        )  # never interchangeable


class TestAddress(unittest.TestCase):
    def test_the_local_network_only(self):
        good = {
            "10.42.0.1": "http://10.42.0.1:80",
            "http://192.168.43.1:8080/": "http://192.168.43.1:8080",
            "172.20.10.1": "http://172.20.10.1:80",
            "http://campanile.local": "http://campanile.local:80",
            "127.0.0.1:18000": "http://127.0.0.1:18000",
            "http://[fe80::1]:8080": "http://[fe80::1]:8080",
        }
        for typed, address in good.items():
            self.assertEqual(sharing.lan_address(typed), address, typed)
        for bad in ("8.8.8.8", "http://example.com", "https://10.42.0.1", "ftp://10.42.0.1",
                    "http://user:pw@10.42.0.1", "http://10.42.0.1/api", "http://10.42.0.1?x=1",
                    "http://10.42.0.1:99999", "http://224.0.0.1", "", None, "x" * 300,
                    "http://evil.com#.local", "http://10.42.0.1.evil.com"):  # fmt: skip
            self.assertIsNone(sharing.lan_address(bad), bad)


def listed(**overrides):
    entry = {"name": "area.pmtiles", "kind": "map", "bytes": 10, "sha256": "a" * 64}
    entry.update(overrides)
    return entry


class TestList(unittest.TestCase):
    def manifest(self, files, **top):
        data = {"format": sharing.FORMAT, "session": "0" * 32, "files": files}
        data.update(top)
        return json.dumps(data)

    def test_a_good_list(self):
        session, files = sharing.check(
            self.manifest([listed(), listed(name=ZIM_NAME, kind="wiki")])
        )
        self.assertEqual((session, len(files)), ("0" * 32, 2))

    def test_anything_odd_is_refused(self):
        bad = [
            self.manifest([listed(name="../../evil.pmtiles")]),
            self.manifest([listed(name="area.zim")]),  # a map that isn't one
            self.manifest([listed(name="evil.exe", kind="wiki")]),
            self.manifest([listed(kind="program")]),
            self.manifest([listed(bytes=True)]),
            self.manifest([listed(bytes=-1)]),
            self.manifest([listed(bytes=10**15)]),
            self.manifest([listed(sha256="A" * 64)]),
            self.manifest([listed(extra=1)]),
            self.manifest([listed(), listed()]),  # the same name twice
            self.manifest([listed()] * 201),
            self.manifest([listed()], format="other"),
            self.manifest([listed()], session="../x"),
            self.manifest([listed()], more=1),
            '{"format": "campanile-share-1", "format": "x", "session": "'
            + "0" * 32
            + '", "files": []}',
            self.manifest([listed()]).replace('"bytes": 10', '"bytes": NaN'),
            "[]",
            "not json",
        ]
        for text in bad:
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                sharing.check(text)


class SharingCase(CampanileTestCase):
    """The Campanile that shares: the test server, with a map and a Wikipedia file."""

    def setUp(self):
        super().setUp()
        (self.data / "maps" / "test.pmtiles").unlink()  # the shared base's stand-in: not a map
        (self.data / "maps" / "area.pmtiles").write_bytes(MAP)
        (self.data / "zim").mkdir()
        (self.data / "zim" / ZIM_NAME).write_bytes(ZIM)
        self.address = f"http://127.0.0.1:{self.port}"

    def share(self, action="start"):
        status, state = self.json("POST", f"/api/admin/share/{action}", {"password": PASSWORD})
        self.assertEqual(status, 200)
        deadline = time.monotonic() + 10
        while state.get("active") and not state.get("ready") and time.monotonic() < deadline:
            time.sleep(0.05)
            state = self.json("POST", "/api/admin/share/state", {"password": PASSWORD})[1]
        return state

    def code(self, state):
        return sharing.normalize(state["code"])

    def get(self, path, headers=None):
        return self.request("GET", path, headers=headers)


class TestSharing(SharingCase):
    def test_nothing_is_shared_until_asked(self):
        self.assertEqual(self.json("GET", "/api/share")[0], 404)

    def test_the_list_is_signed_with_the_code_shown_to_the_admin(self):
        state = self.share()
        self.assertTrue(state["ready"])
        self.assertEqual(state["files"], 2)
        status, answer = self.json("GET", "/api/share")
        self.assertEqual(status, 200)
        self.assertEqual(answer["tag"], sharing.tag(self.code(state), answer["manifest"].encode()))
        _, files = sharing.check(answer["manifest"])
        hashes = {f["name"]: f["sha256"] for f in files}
        self.assertEqual(hashes["area.pmtiles"], hashlib.sha256(MAP).hexdigest())
        self.assertEqual(hashes[ZIM_NAME], hashlib.sha256(ZIM).hexdigest())
        self.assertNotIn(
            state["code"].replace("-", ""), json.dumps(answer)
        )  # the code never travels

    def test_the_code_and_the_switch_are_for_the_campanile_itself(self):
        self.assertEqual(self.json("POST", "/api/admin/share/start", {"password": "wrong"})[0], 403)
        self.cfg.behind_proxy = True
        phone = {"X-Real-IP": "10.42.0.9"}
        for action in ("start", "state", "stop"):
            status, _ = self.json(
                "POST", f"/api/admin/share/{action}", {"password": PASSWORD}, phone
            )
            self.assertEqual(status, 403, action)

    def test_files_need_the_token(self):
        state = self.share()
        session = sharing.check(self.json("GET", "/api/share")[1]["manifest"])[0]
        right = {sharing.TOKEN_HEADER: sharing.token(self.code(state), session, "127.0.0.1")}
        self.assertEqual(self.get("/api/share/file/area.pmtiles")[0].status, 404)
        wrong = {sharing.TOKEN_HEADER: "0" * 64}
        self.assertEqual(self.get("/api/share/file/area.pmtiles", wrong)[0].status, 404)
        r, body = self.get("/api/share/file/area.pmtiles", right)
        self.assertEqual((r.status, body), (200, MAP))
        r, body = self.get("/api/share/file/area.pmtiles", {**right, "Range": "bytes=100-199"})
        self.assertEqual((r.status, body), (206, MAP[100:200]))  # an interrupted download resumes

    def test_a_token_works_only_from_the_address_it_was_given_to(self):
        state = self.share()
        self.cfg.behind_proxy = True  # the Raspberry: nginx says who is asking
        receiver, overhearing = {"X-Real-IP": "10.42.0.50"}, {"X-Real-IP": "10.42.0.66"}
        answer = self.json("GET", "/api/share", headers=receiver)[1]
        self.assertEqual(answer["you"], "10.42.0.50")
        session = sharing.check(answer["manifest"])[0]
        heard = {sharing.TOKEN_HEADER: sharing.token(self.code(state), session, answer["you"])}
        self.assertEqual(
            self.get("/api/share/file/area.pmtiles", {**heard, **receiver})[0].status, 200
        )
        with mock.patch.object(sharing, "MAX_DOWNLOADS", 0):  # refused before taking a slot
            r, _ = self.get("/api/share/file/area.pmtiles", {**heard, **overhearing})
        self.assertEqual(r.status, 404)

    def test_a_token_in_other_characters_is_only_wrong(self):
        self.share()
        r, _ = self.get("/api/share/file/area.pmtiles", {sharing.TOKEN_HEADER: "\u00e9" * 64})
        self.assertEqual(r.status, 404)  # not a crash of the server

    def test_only_files_in_the_list(self):
        state = self.share()
        session = sharing.check(self.json("GET", "/api/share")[1]["manifest"])[0]
        right = {sharing.TOKEN_HEADER: sharing.token(self.code(state), session, "127.0.0.1")}
        names = ("campanile.db", "../campanile.db", "%2e%2e/campanile.db", "../maps/area.pmtiles")
        for name in (*names, "maps/area.pmtiles", "", "admin-password.txt"):
            with self.subTest(name=name):
                self.assertEqual(self.get("/api/share/file/" + name, right)[0].status, 404)

    def test_a_stopped_share_and_its_token_are_gone(self):
        state = self.share()
        session = sharing.check(self.json("GET", "/api/share")[1]["manifest"])[0]
        old = {sharing.TOKEN_HEADER: sharing.token(self.code(state), session, "127.0.0.1")}
        self.assertFalse(self.share("stop")["active"])
        self.assertEqual(self.json("GET", "/api/share")[0], 404)
        self.share()  # a new share: a new code, a new session
        self.assertEqual(self.get("/api/share/file/area.pmtiles", old)[0].status, 404)

    def test_a_share_ends_by_itself(self):
        self.share()
        with mock.patch.object(
            sharing.time, "monotonic", return_value=time.monotonic() + sharing.LASTS + 1
        ):
            self.assertEqual(self.json("GET", "/api/share")[0], 404)
            state = self.json("POST", "/api/admin/share/state", {"password": PASSWORD})[1]
        self.assertFalse(state["active"])

    def test_only_a_few_downloads_at_once(self):
        state = self.share()
        session = sharing.check(self.json("GET", "/api/share")[1]["manifest"])[0]
        right = {sharing.TOKEN_HEADER: sharing.token(self.code(state), session, "127.0.0.1")}
        with mock.patch.object(sharing, "MAX_DOWNLOADS", 0):
            self.assertEqual(self.get("/api/share/file/area.pmtiles", right)[0].status, 503)
        self.assertEqual(self.get("/api/share/file/area.pmtiles", right)[0].status, 200)
        share = self.cfg.share
        deadline = time.monotonic() + 5
        while share._sending and time.monotonic() < deadline:  # the server lets go just after
            time.sleep(0.01)
        with share.sending() as first, share.sending() as second, share.sending() as third:
            self.assertEqual((first, second, third), (True, True, False))
        with share.sending() as again:
            self.assertTrue(again)  # the slots came back

    def test_downloads_are_paced(self):
        state = self.share()
        session = sharing.check(self.json("GET", "/api/share")[1]["manifest"])[0]
        right = {sharing.TOKEN_HEADER: sharing.token(self.code(state), session, "127.0.0.1")}
        with mock.patch.object(sharing, "RATE", 1_000_000):
            started = time.monotonic()
            self.assertEqual(self.get("/api/share/file/area.pmtiles", right)[1], MAP)
            self.assertGreater(time.monotonic() - started, 0.25)  # 300 KB at 1 MB/s


class Impostor:
    """A server on the local network that answers whatever the test decides."""

    def __init__(self, routes):
        routes_ = routes

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                status, headers, body = routes_(self.path)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TestReceiving(SharingCase):
    """The Campanile that receives: a Preparation of its own, with its own data folder."""

    def setUp(self):
        super().setUp()
        self._b = tempfile.TemporaryDirectory()
        self.addCleanup(self._b.cleanup)
        self.b_data = Path(self._b.name) / "data"
        self.b = Preparation(
            self.b_data, Path(self._b.name) / "tools", sources=Sources(https_only=True)
        )

    def receive(self, address, code):
        self.assertTrue(self.b.start_receive(address, code))
        self.b.wait(30)
        return self.b.state()["job"]

    def impostor(self, routes):
        fake = Impostor(routes)
        self.addCleanup(fake.close)
        return fake

    def test_maps_and_wikipedia_arrive_identical(self):
        job = self.receive(self.address, self.code(self.share()))
        self.assertIsNone(job["error"], job)
        self.assertEqual((self.b_data / "maps" / "area.pmtiles").read_bytes(), MAP)
        self.assertEqual((self.b_data / "zim" / ZIM_NAME).read_bytes(), ZIM)

    def test_a_wrong_code_receives_nothing(self):
        self.share()
        job = self.receive(self.address, "K7QF2M9XR4TA8WHN")
        self.assertEqual(job["error"], "share_code")
        self.assertFalse(self.b_data.exists() and any(self.b_data.rglob("*.pmtiles")))

    def test_nobody_sharing_at_that_address(self):
        self.assertEqual(self.receive(self.address, "K7QF2M9XR4TA8WHN")["error"], "share_none")

    def test_a_fake_campanile_with_its_own_list_is_refused(self):
        code = self.code(self.share())  # the real one, read on the real screen
        evil = b"a map with a surprise"
        sha = hashlib.sha256(evil).hexdigest()
        entry = {"name": "area.pmtiles", "kind": "map", "bytes": len(evil), "sha256": sha}
        manifest = json.dumps({"format": sharing.FORMAT, "session": "1" * 32, "files": [entry]})
        answer = json.dumps(
            {"manifest": manifest, "tag": sharing.tag(sharing.new_code(), manifest.encode())}
        )
        fake = self.impostor(
            lambda path: (200, {}, answer.encode() if path == "/api/share" else evil)
        )
        self.assertEqual(self.receive(fake.address, code)["error"], "share_code")
        self.assertFalse(self.b_data.exists() and any(self.b_data.rglob("*.pmtiles")))

    def test_a_file_swapped_on_the_way_is_refused(self):
        code = self.code(self.share())
        real = urlopen(self.address + "/api/share").read()  # noqa: S310 (the test's own server)
        fake = self.impostor(
            lambda path: (200, {}, real if path == "/api/share" else b"x" * len(MAP))
        )
        job = self.receive(fake.address, code)
        self.assertEqual(job["error"], "checksum")
        self.assertFalse((self.b_data / "maps" / "area.pmtiles").exists())

    def test_redirects_are_never_followed(self):
        # Even to the real Campanile: followed, this one would succeed. Only the address the
        # person typed is ever contacted.
        code = self.code(self.share())
        fake = self.impostor(lambda path: (302, {"Location": self.address + path}, b""))
        self.assertEqual(self.receive(fake.address, code)["error"], "share_none")
        self.assertFalse((self.b_data / "maps" / "area.pmtiles").exists())

    def test_names_that_climb_out_are_refused_even_with_the_right_code(self):
        code = sharing.new_code()  # a Campanile that knows its own code, and lies about names
        outside = Path(self._b.name) / "evil.pmtiles"
        sha = hashlib.sha256(b"evil").hexdigest()
        entry = {"name": "../../evil.pmtiles", "kind": "map", "bytes": 4, "sha256": sha}
        manifest = json.dumps({"format": sharing.FORMAT, "session": "1" * 32, "files": [entry]})
        answer = json.dumps({"manifest": manifest, "tag": sharing.tag(code, manifest.encode())})
        fake = self.impostor(
            lambda path: (200, {}, answer.encode() if path == "/api/share" else b"evil")
        )
        self.assertEqual(self.receive(fake.address, code)["error"], "share_bad")
        self.assertFalse(outside.exists())

    def test_a_busy_or_lost_campanile_is_said_in_words(self):
        code = self.code(self.share())
        real = urlopen(self.address + "/api/share").read()  # noqa: S310 (the test's own server)
        busy = self.impostor(
            lambda path: (200, {}, real) if path == "/api/share" else (503, {}, b"")
        )
        self.assertEqual(self.receive(busy.address, code)["error"], "share_busy")
        gone = self.impostor(
            lambda path: (200, {}, real) if path == "/api/share" else (404, {}, b"")
        )
        self.assertEqual(self.receive(gone.address, code)["error"], "share_lost")

    def test_what_is_here_already_is_kept(self):
        (self.b_data / "maps").mkdir(parents=True)
        mine = self.b_data / "maps" / "area.pmtiles"
        mine.write_bytes(b"my own area, somewhere else")
        (self.b_data / "zim").mkdir()
        (self.b_data / "zim" / "same-content.zim").write_bytes(ZIM)  # already here, other name
        job = self.receive(self.address, self.code(self.share()))
        self.assertIsNone(job["error"], job)
        self.assertEqual(mine.read_bytes(), b"my own area, somewhere else")
        self.assertEqual((self.b_data / "maps" / "area-2.pmtiles").read_bytes(), MAP)
        self.assertFalse((self.b_data / "zim" / ZIM_NAME).exists())  # not downloaded twice


if __name__ == "__main__":
    unittest.main()
