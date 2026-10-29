# DEVELOPED BY CARROTSTUDIO software house
"""The double clicks and the Raspberry install take Python and its commands from the system,
never from the folder they start in: that folder may be a stick someone else prepared."""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "campanile"))
import copying  # noqa: E402

WINDOWS = REPO / "Avvia Campanile (Windows).bat"
GUARD = b'set "NoDefaultCurrentDirectoryInExePath=1"\r\n'
INSTALL = (REPO / "raspberry" / "install.sh").read_text(encoding="utf-8")
PLANTED = "import sys\nprint('planted')\nsys.exit(0)\n"


class TestWindowsLauncher(unittest.TestCase):
    def test_lines_end_the_windows_way(self):
        raw = WINDOWS.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))  # cmd misreads labels otherwise

    def test_the_guard_comes_before_any_command(self):
        lines = WINDOWS.read_bytes().split(b"\r\n")
        first_command = next(i for i, line in enumerate(lines) if line.startswith((b"py ", b"%")))
        self.assertIn(GUARD.rstrip(), lines[:first_command])

    @unittest.skipUnless(os.name == "nt", "Windows")
    def test_a_py_bat_next_to_it_never_runs(self):
        self.assertFalse(self.planted_ran(WINDOWS.read_bytes()))
        # The check that inverts: without that one line, Windows runs the planted file.
        self.assertTrue(self.planted_ran(WINDOWS.read_bytes().replace(GUARD, b"")))

    def planted_ran(self, launcher: bytes) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp, "stick folder (with spaces)")
            folder.mkdir()
            bat = folder / "Avvia Campanile (Windows).bat"
            bat.write_bytes(launcher)
            for name in ("py.bat", "py.cmd", "python.bat", "python.cmd"):
                (folder / name).write_text('@echo planted> "%~dp0planted.txt"\r\n')
            subprocess.run(  # noqa: S603 (our own launcher, copied into a temporary folder)
                f'cmd.exe /d /s /c ""{bat}""',
                cwd=folder,
                stdin=subprocess.DEVNULL,  # "pause" returns at once
                capture_output=True,
                timeout=120,
                check=False,
            )
            return (folder / "planted.txt").exists()


class TestRaspberryInstall(unittest.TestCase):
    def test_every_python_the_scripts_run_is_isolated(self):
        scripts = sorted((REPO / "raspberry").glob("*.sh")) + sorted(
            (REPO / "scripts").glob("*.sh")
        )
        calls = [
            (script.name, call)
            for script in scripts
            for call in re.findall(r"\bpython3 -[^\n]*", script.read_text(encoding="utf-8"))
        ]
        self.assertGreaterEqual(len(calls), 8)
        for name, call in calls:
            self.assertTrue(call.startswith("python3 -I "), f"{name}: {call}")

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "bash")
    def test_its_password_comes_from_python_not_from_the_folder(self):
        command = re.search(r'NEW_PASSWORD="\$\((python3 .*)\)"\n', INSTALL)[1]
        python = os.path.dirname(sys.executable)  # the "python3" of this run
        env = {**os.environ, "PATH": python + os.pathsep + os.environ["PATH"]}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "secrets.py").write_text(PLANTED)

            def run(cmd: str) -> str:
                done = subprocess.run(  # noqa: S603 (a line of our own install.sh)
                    ["bash", "-c", cmd],  # noqa: S607 (bash from the PATH, as install.sh)
                    cwd=tmp,
                    env=env,
                    capture_output=True,
                    check=False,
                )
                return done.stdout.decode().strip()

            self.assertRegex(run(command), r"^[A-Za-z0-9_-]{16}$")
            self.assertEqual(run(command.replace("python3 -I ", "python3 ")), "planted")

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "bash")
    def test_maps_and_wikipedia_are_moved_once_and_links_left_out(self):
        step = re.search(r"shopt -s nullglob\n(.*?)\nshopt -u nullglob\n", INSTALL, re.S)[1]
        with tempfile.TemporaryDirectory() as tmp:
            clone, data = Path(tmp, "clone", "data"), Path(tmp, "installed")
            stubs = Path(tmp, "bin")
            for folder in (clone / "maps", clone / "zim", data / "maps", data / "zim", stubs):
                folder.mkdir(parents=True)
            (clone / "maps" / "town.pmtiles").write_bytes(b"map")
            (clone / "zim" / "medicine.zim").write_bytes(b"zim")
            Path(tmp, "secret").write_text("not for phones")
            (clone / "maps" / "evil.pmtiles").symlink_to(Path(tmp, "secret"))
            (stubs / "chown").write_text("#!/bin/sh\nexit 0\n")  # the real one needs root
            (stubs / "chown").chmod(0o755)
            path = f"{stubs}{os.pathsep}{os.environ['PATH']}"
            env = {**os.environ, "PATH": path, "SOURCE": str(clone.parent), "DATA": str(data)}
            subprocess.run(  # noqa: S603 (the data step of our own install.sh)
                ["bash", "-c", f"set -euo pipefail\nshopt -s nullglob\n{step}"],  # noqa: S607
                env=env,
                check=True,
            )
            self.assertEqual([p.name for p in (data / "maps").iterdir()], ["town.pmtiles"])
            self.assertEqual([p.name for p in (data / "zim").iterdir()], ["medicine.zim"])
            self.assertFalse((clone / "maps" / "town.pmtiles").exists())  # moved: one copy
            self.assertTrue((clone / "maps" / "evil.pmtiles").is_symlink())  # left where it was

    def test_what_it_runs_works_from_a_stick_without_exec_bits(self):
        # An update from a FAT32 stick loses the exec bits: what runs directly gets them back.
        units = "".join(u.read_text(encoding="utf-8") for u in REPO.glob("raspberry/*.service"))
        ran = re.findall(r'^\s*"\$CODE/raspberry/([\w-]+\.sh)"', INSTALL, re.M)
        ran += re.findall(r"^ExecStart=/opt/campanile/raspberry/([\w-]+\.sh)", units, re.M)
        self.assertGreaterEqual(len(ran), 3)  # nginx-site.sh, hotspot-off.sh, start-kiwix.sh
        made_executable = re.search(r"^chmod 755 (.*)$", INSTALL, re.M)[1]
        for script in ran:
            self.assertIn(f'"$NEW/raspberry/{script}"', made_executable)

    def run_with_stubs(self, script: str, stubs: dict, args=()) -> subprocess.CompletedProcess:
        """A piece of our scripts, with the system commands it calls written as small fakes."""
        with tempfile.TemporaryDirectory() as tmp:
            for name, body in stubs.items():
                stub = Path(tmp, name)
                stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "{tmp}/calls"\n{body}\n')
                stub.chmod(0o755)
            env = {**os.environ, "PATH": tmp + os.pathsep + os.environ["PATH"], "TMP": tmp}
            head = 'set -euo pipefail\nfail() { echo "ERROR: $*" >&2; exit 1; }\nusage() { :; }\n'
            done = subprocess.run(  # noqa: S603 (pieces of our own scripts, commands faked)
                ["bash", "-c", head + script, "test", *args],  # noqa: S607
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = Path(tmp, "calls")
            done.calls = calls.read_text().splitlines() if calls.exists() else []
            return done

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "bash")
    def test_the_wifi_country_is_the_one_given_or_the_one_already_set(self):
        default = re.search(r"^COUNTRY=.*$", INSTALL, re.M)[0]
        parse = re.search(r"while \[ \$# -gt 0 \]; do\n.*?\ndone\n", INSTALL, re.S)[0]
        check = re.search(r"  # Wi-Fi country:.*?\n  fi\n", INSTALL, re.S)
        script = f"{default}\nHOTSPOT=1\n{parse}{check[0] if check else ''}"
        script += 'echo "country to set: [$COUNTRY]"\n'

        def raspi(answer):  # what get_wifi_country says: a country, or nothing set
            return {"raspi-config": f"echo {answer}" if answer else "exit 1"}

        given = self.run_with_stubs(script, raspi("SE"), ["--country", "gb"])
        self.assertIn("country to set: [GB]", given.stdout)
        kept = self.run_with_stubs(script, raspi("SE; echo SE"))  # one per cmdline.txt line
        self.assertEqual(kept.returncode, 0)
        self.assertIn("Wi-Fi country: SE, as already set", kept.stdout)
        self.assertIn("country to set: []", kept.stdout)  # nothing to change
        unset = self.run_with_stubs(script, raspi(""))
        self.assertNotEqual(unset.returncode, 0)
        self.assertIn("--country", unset.stderr)
        # And the radio is set only to a country given here, never to a default.
        hotspot = re.search(r'step "Wi-Fi hotspot.*?\nfi\n', INSTALL, re.S)[0]
        setting = hotspot.index("raspi-config nonint do_wifi_country")
        self.assertIn('if [ -n "$COUNTRY" ]', hotspot[:setting])

    @unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "bash")
    def test_uninstalling_leaves_nginx_as_it_was_before_campanile(self):
        uninstall = (REPO / "raspberry" / "uninstall.sh").read_text(encoding="utf-8")
        step = re.search(r'step "Web server \(nginx\)"\n(.*?)\nstep "Code"', uninstall, re.S)[1]
        uninstalling = step.replace("/etc/nginx/", "$TMP/conf/").replace(
            "/etc/campanile", "$TMP/etc"
        )
        # From apt-get to the note of nginx's state before Campanile, if there is one.
        packages = r"\nWAIT=.*? install [^\n]*\n(?:#[^\n]*\n)?(?:if .*?\nfi\n)?"
        install = re.search(packages, INSTALL, re.S)[0]
        cases = {  # nginx before Campanile: (dpkg says, systemctl is-enabled exits with)
            "absent": ("", 1),
            "there but off, as after a purge": ("install ok installed", 1),
            "serving": ("install ok installed", 0),
        }
        for before, (package, enabled) in cases.items():
            with self.subTest(nginx_before=before):
                fakes = {
                    "systemctl": f'case "$1" in is-enabled) exit {enabled};; esac',
                    "dpkg-query": f"printf '{package}'",
                    "nginx": "",
                    "apt-get": "",
                }
                script = 'CONFIG="$TMP/etc"; NGINX_NEW=0; NGINX_WAS_OFF=0\n'
                done = self.run_with_stubs(script + install + uninstalling, fakes)
                self.assertEqual(done.returncode, 0, done.stderr)
                stopped = "systemctl disable --now nginx.service" in done.calls
                self.assertEqual(stopped, before != "serving")  # off again if it was off
                self.assertEqual("systemctl restart nginx.service" in done.calls, not stopped)

    def test_the_raspberry_keeps_all_a_stick_copy_takes(self):
        # copying.py makes a stick from /opt/campanile: what it takes must be there.
        step = re.search(r'step "Code in \$CODE"\n(.*?)\nstep ', INSTALL, re.S)[1]
        listed = re.search(r"PROGRAM=\((.*?)\)\n", step, re.S)
        copied = shlex.split(listed[1]) if listed else re.findall(r'"\$SOURCE/([^"]+)"', step)
        self.assertEqual(sorted(set(copied)), sorted(copying.PROGRAM))

    def test_the_service_ignores_packages_in_its_home(self):
        unit = (REPO / "raspberry" / "campanile.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/bin/python3 -s /opt/campanile/campanile/server.py", unit)


HOTSPOT_OFF = REPO / "raspberry" / "hotspot-off.sh"
INSTALLED = Path("/etc/systemd/system/campanile-firewall.service")  # a real Campanile here


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "bash")
@unittest.skipIf(INSTALLED.exists(), "a real Campanile is installed on this computer")
class TestHotspotOff(unittest.TestCase):
    """--no-hotspot and the uninstaller: the open Wi-Fi goes first, its firewall last."""

    # nmcli still listing the hotspot after "delete": as if deleting it had failed.
    SURVIVED = 'case "$*" in "-t -f NAME connection show") echo campanile-hotspot;; esac\n'

    def run_off(self, survives=False) -> tuple[int, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            calls = Path(tmp, "calls")
            for name in ("nmcli", "systemctl"):
                stub = Path(tmp, name)
                stub.write_text(
                    f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n'
                    + (self.SURVIVED if name == "nmcli" and survives else "")
                )
                stub.chmod(0o755)
            env = {**os.environ, "PATH": tmp + os.pathsep + os.environ["PATH"]}
            done = subprocess.run(  # noqa: S603 (our own script, commands stubbed)
                ["bash", str(HOTSPOT_OFF)],  # noqa: S607
                env=env,
                capture_output=True,
                check=False,
            )
            return done.returncode, calls.read_text().splitlines() if calls.exists() else []

    def test_the_wifi_goes_before_its_firewall(self):
        code, calls = self.run_off()
        self.assertEqual(code, 0)
        wifi = calls.index("nmcli connection delete campanile-hotspot")
        firewall = calls.index("systemctl disable --now campanile-firewall.service")
        self.assertLess(wifi, firewall)

    def test_a_wifi_that_stays_keeps_its_firewall(self):
        code, calls = self.run_off(survives=True)
        self.assertNotEqual(code, 0)
        self.assertEqual([c for c in calls if c.startswith("systemctl")], [])

    def test_no_hotspot_and_uninstall_both_use_it(self):
        branch = re.search(r'step "Firewall"\n.*?\nelse\n(.*?)\nfi\n', INSTALL, re.S)[1]
        self.assertIn('"$CODE/raspberry/hotspot-off.sh"', branch)
        uninstall = (REPO / "raspberry" / "uninstall.sh").read_text(encoding="utf-8")
        off = uninstall.index('bash "$(dirname "$0")/hotspot-off.sh"')  # bash: no exec bit needed
        self.assertLess(off, uninstall.index('step "Services"'))  # before anything else stops


if __name__ == "__main__":
    unittest.main()
