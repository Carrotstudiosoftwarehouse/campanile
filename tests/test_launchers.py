# DEVELOPED BY CARROTSTUDIO software house
"""The double clicks and the Raspberry install take Python and its commands from the system,
never from the folder they start in: that folder may be a stick someone else prepared."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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

    def test_the_service_ignores_packages_in_its_home(self):
        unit = (REPO / "raspberry" / "campanile.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/bin/python3 -s /opt/campanile/campanile/server.py", unit)


if __name__ == "__main__":
    unittest.main()
