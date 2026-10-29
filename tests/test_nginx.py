# DEVELOPED BY CARROTSTUDIO software house
"""The Raspberry's nginx in front of Campanile, both real: what crosses from one to the other.

nginx runs the configuration raspberry/nginx-site.sh writes for install.sh, moved to free ports
on 127.0.0.1 only, and Campanile listens behind it as campanile.service starts it. A phone's
requests come from 127.0.0.2, which Linux has and a Mac doesn't. Skipped without nginx or bash.
"""

import contextlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import server as campanile
from test_server import PASSWORD, cap_alert

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash") if os.name != "nt" else None
NGINX = shutil.which("nginx") or next(
    (p for p in ("/usr/sbin/nginx", "/opt/homebrew/bin/nginx") if os.access(p, os.X_OK)), None
)


def site(data="/var/lib/campanile") -> str:
    """The configuration install.sh gives nginx."""
    env = {**os.environ, "CAMPANILE_CODE": str(ROOT), "CAMPANILE_DATA": str(data)}
    script = str(ROOT / "raspberry" / "nginx-site.sh")
    done = subprocess.run(  # noqa: S603 (our own script)
        [BASH, script, "10.42.0.1", "campanile.local"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def location(conf: str, start: str) -> str:
    """The inside of the location block whose line begins with `start`."""
    pattern = r"\n    location " + re.escape(start) + r"[^\n]*\{\n(.*?)\n    \}"
    found = re.search(pattern, conf, re.S)
    if not found:
        raise AssertionError(f"no location {start}")
    return found.group(1)


def big_alert() -> str:
    """Shaped like IT-alert's own: over 100 kB of area polygon."""
    polygon = " ".join(f"46.{i:05d},11.{i:05d}" for i in range(6000))
    area = f"<area><areaDesc>Diga</areaDesc><polygon>{polygon}</polygon></area>"
    return cap_alert().replace("</info></alert>", area + "</info></alert>")


def phone_address() -> bool:
    """Can requests come from 127.0.0.2, an address that is not the Raspberry's own?"""
    with contextlib.suppress(OSError), socket.socket() as s:
        s.bind(("127.0.0.2", 0))
        return True
    return False


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(BASH, "needs bash")
class TestSameRulesAsCampanile(unittest.TestCase):
    """Rules written twice, in nginx for the Raspberry and in Campanile for a laptop: they agree."""

    def setUp(self):
        self.conf = site()

    def test_room_for_a_cap_alert(self):
        self.assertEqual(campanile.CAP_BODY % 1024, 0)
        cap_room = location(self.conf, "= /api/admin/cap")
        self.assertIn(f"client_max_body_size {campanile.CAP_BODY // 1024}k;", cap_room)
        self.assertIn(f"client_max_body_size {campanile.MAX_BODY // 1024}k;", self.conf)

    def test_pace_of_a_whole_map(self):
        maps = location(self.conf, '~ "^/maps/')
        self.assertIn(f"limit_rate_after {campanile.MAP_FREE // 2**20}m;", maps)
        self.assertIn(f"limit_rate {campanile.MAP_RATE // 1024}k;", maps)


@unittest.skipUnless(BASH and NGINX, "needs nginx and bash")
class TestThroughNginx(unittest.TestCase):
    """Requests through the real nginx, as a phone sends them or the admin's own browser."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        data = root / "data"
        (data / "maps").mkdir(parents=True)
        self.map = data / "maps" / "big.pmtiles"
        # Campanile as campanile.service starts it: on 127.0.0.1 only, behind a proxy.
        self.cfg = campanile.Config(
            web=ROOT / "campanile" / "web",
            data=data,
            hostnames=["campanile.local", "localhost", "127.0.0.1"],
            admin_password=PASSWORD,
            behind_proxy=True,
            public_url="http://10.42.0.1/",
        )
        self.addCleanup(self.cfg.store.close)
        backend = campanile.create_server("127.0.0.1", 0, self.cfg)
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)

        self.port = free_port()
        conf = site(data).replace("127.0.0.1:8080", f"127.0.0.1:{backend.server_address[1]}")
        conf = re.sub(r"\n *listen \[::\][^\n]*", "", conf)  # never on the network
        conf = re.sub(r"listen 80\b", f"listen 127.0.0.1:{self.port}", conf)
        conf = re.sub(r"listen 8081\b", f"listen 127.0.0.1:{free_port()}", conf)
        conf = conf.replace("/var/log/nginx/error.log", str(root / "error.log"))
        (root / "site.conf").write_text(conf)
        kinds = ("client_body", "proxy", "fastcgi", "uwsgi", "scgi")
        temp = "".join(f"    {kind}_temp_path {root / kind};\n" for kind in kinds)
        (root / "nginx.conf").write_text(
            f"pid {root / 'nginx.pid'};\nevents {{}}\n"
            f"http {{\n{temp}    include {root / 'site.conf'};\n}}\n"
        )
        files = ["-p", str(root), "-e", str(root / "error.log"), "-c", str(root / "nginx.conf")]
        self.nginx = subprocess.Popen(  # noqa: S603 (nginx, with the configuration above)
            [NGINX, *files, "-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        self.addCleanup(self.stop_nginx)
        deadline = time.monotonic() + 10
        while True:
            with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", self.port)):
                break
            if self.nginx.poll() is not None or time.monotonic() > deadline:
                self.nginx.kill()  # still running, its error output would never end
                error = self.nginx.communicate(timeout=10)[1].decode(errors="replace")
                self.fail(f"nginx didn't start: {error}")
            time.sleep(0.05)

    def stop_nginx(self):
        self.nginx.terminate()
        self.nginx.wait(10)
        self.nginx.stderr.close()

    def call(self, method, path, body=None, headers=None, phone=False):
        """(status, body) through nginx: from the Raspberry itself, or from a phone."""
        source = ("127.0.0.2", 0) if phone else None
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30, source_address=source)
        sent = {"Host": "10.42.0.1"} if phone else {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            sent["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers={**sent, **(headers or {})})
        r = conn.getresponse()
        content = r.read()
        conn.close()
        return r.status, content

    def test_the_admins_cap_alert_of_over_100_kb_reaches_campanile(self):
        document = big_alert()
        self.assertGreater(len(document), 100_000)
        status, body = self.call("POST", "/api/admin/cap", {"password": PASSWORD, "cap": document})
        self.assertEqual(status, 201, body[:200])
        self.assertEqual(json.loads(body)["title"], "Piena del Po")

    @unittest.skipUnless(phone_address(), "no 127.0.0.2 here to play the phone (Linux has it)")
    def test_a_phone_never_gets_that_room(self):
        # Turned away by nginx before the body is read (403), not by Campanile after (413).
        big = {"password": PASSWORD, "cap": big_alert()}
        self.assertEqual(self.call("POST", "/api/admin/cap", big, phone=True)[0], 403)
        post = {"text": "x" * 20_000}
        self.assertEqual(self.call("POST", "/api/posts", post, phone=True)[0], 413)

    @unittest.skipUnless(phone_address(), "no 127.0.0.2 here to play the phone (Linux has it)")
    def test_a_phone_cannot_pass_for_the_raspberry_itself(self):
        claims = {"X-Real-IP": "127.0.0.1", "X-Forwarded-For": "127.0.0.1"}
        ask = {"password": PASSWORD}
        self.assertEqual(self.call("POST", "/api/admin/list", ask, claims, phone=True)[0], 403)
        self.assertEqual(self.call("POST", "/api/admin/list", ask)[0], 200)  # the address decides

    def test_a_whole_map_is_paced_a_tile_is_not(self):
        self.map.write_bytes(os.urandom(campanile.MAP_FREE + 6 * campanile.MAP_RATE))
        began = time.monotonic()
        status, tile = self.call("GET", "/maps/big.pmtiles", headers={"Range": "bytes=0-399999"})
        self.assertEqual((status, len(tile)), (206, 400_000))
        self.assertLess(time.monotonic() - began, 2)
        began = time.monotonic()
        status, whole = self.call("GET", "/maps/big.pmtiles")
        self.assertEqual((status, len(whole)), (200, self.map.stat().st_size))
        self.assertGreater(time.monotonic() - began, 3)  # 6 seconds' worth past the free part


if __name__ == "__main__":
    unittest.main()
