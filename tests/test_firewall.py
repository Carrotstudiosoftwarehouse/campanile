# DEVELOPED BY CARROTSTUDIO software house
"""The Windows Firewall helper. The real rules are tested on Windows; here, what can't wait."""

import base64
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "campanile"))
import firewall

HOSTILE = [  # valid Windows paths, except the last one (a '"' can't be in a path)
    "C:\\Users\\O\u2019Brien\\python.exe",  # a curly quote: PowerShell ends strings there too
    "C:\\Users\\x\u2019; New-Item \\pwned.txt; \u2019\\python.exe",  # ...so this would run
    "C:\\Users\\x'; New-Item \\pwned.txt; '\\python.exe",
    "C:\\Users\\$(New-Item \\pwned.txt)\\python.exe",
    'C:\\Users\\`n"\\python.exe',
]


class TestFirewall(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "on Windows it really answers")
    def test_elsewhere_it_cannot_tell(self):
        self.assertIsNone(firewall.blocks(sys.executable))

    def test_a_path_never_enters_the_elevated_script_as_text(self):
        for path in HOSTILE:
            with self.subTest(path=path):
                script = firewall._allow_script([(path, 8080)])
                self.assertNotIn(path, script)
                encoded = re.search(r"@\('([A-Za-z0-9+/=]*):8080'\)", script).group(1)
                self.assertEqual(base64.b64decode(encoded).decode("utf-8"), path)
                # Outside the base64, the script is the same for every path.
                self.assertEqual(script.replace(encoded, ""), firewall._allow_script([("", 8080)]))

    def test_several_programs_one_permission(self):
        script = firewall._allow_script([(HOSTILE[0], 8080), (HOSTILE[1], 8081)])
        found = re.findall(r"'([A-Za-z0-9+/=]+):(\d+)'", script)
        decoded = [(base64.b64decode(e).decode("utf-8"), int(port)) for e, port in found]
        self.assertEqual(decoded, [(HOSTILE[0], 8080), (HOSTILE[1], 8081)])

    def test_only_real_ports(self):
        for port in (0, 65536, -1, "8080; calc", 8080.0, True):
            with self.subTest(port=port), self.assertRaises(ValueError):
                firewall._allow_script([(r"C:\\python.exe", port)])


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("CAMPANILE_FIREWALL_TEST") == "1",
    "changes this computer's firewall: Windows only, and only when asked",
)
class TestRealFirewall(unittest.TestCase):
    """Block rules for hostile paths, then the repair: it must work and run nothing."""

    def powershell(self, script):
        import subprocess

        return subprocess.run(  # noqa: S603 (our own test scripts)
            [firewall._powershell(), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=60,
        )

    PATHS = tuple(p for p in HOSTILE if '"' not in p)  # '"' can't be in a Windows path

    def ours(self, command):
        """Runs command on the rules of the test's own programs, and only those."""
        encoded = ",".join(f"'{base64.b64encode(p.encode('utf-8')).decode()}'" for p in self.PATHS)
        return self.powershell(
            f"$paths = @({encoded}) | ForEach-Object {{ "
            "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($_)) }; "
            "Get-NetFirewallApplicationFilter | Where-Object { $paths -contains $_.Program } | "
            "Get-NetFirewallRule | " + command
        )

    def tearDown(self):
        # Only what the test made: never someone's real Campanile rules.
        self.ours("Remove-NetFirewallRule")
        self.powershell("Remove-NetFirewallRule -DisplayName 'campanile-test-*'")
        Path(r"C:\pwned.txt").unlink(missing_ok=True)

    def test_repair_hostile_paths_without_running_them(self):
        Path(r"C:\pwned.txt").unlink(missing_ok=True)
        for n, path in enumerate(self.PATHS):
            encoded = base64.b64encode(path.encode("utf-16-le")).decode()
            made = self.powershell(
                "$p = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String("
                f"'{encoded}')); New-NetFirewallRule -DisplayName 'campanile-test-{n}' "
                "-Direction Inbound -Action Block -Program $p | Out-Null"
            )
            self.assertEqual(made.returncode, 0, made.stderr)
            self.assertTrue(firewall.blocks(path), path)
        self.assertTrue(firewall.allow([(p, 8080) for p in self.PATHS]))  # one permission
        for path in self.PATHS:
            self.assertFalse(firewall.blocks(path), path)
        # What was opened for the test's programs: TCP on 8080, nothing wider.
        opened = self.ours(
            "ForEach-Object { $f = $_ | Get-NetFirewallPortFilter; "
            "$_.Action.ToString() + ' ' + $f.Protocol + ' ' + $f.LocalPort }"
        ).stdout.split()
        self.assertTrue(opened, "no rule was created")
        self.assertEqual(
            set(zip(opened[0::3], opened[1::3], opened[2::3])), {("Allow", "TCP", "8080")}
        )
        self.assertFalse(Path(r"C:\pwned.txt").exists(), "a hidden command ran")


if __name__ == "__main__":
    unittest.main()
