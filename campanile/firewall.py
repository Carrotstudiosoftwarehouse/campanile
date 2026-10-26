# DEVELOPED BY CARROTSTUDIO software house
"""Windows Firewall: is it blocking the phones, and fixing it if the person asks.

Pressing "Cancel" when Windows first asks about Python leaves inbound block rules for that
python.exe: no phone reaches the Campanile, and Windows never asks again. A block rule beats
any allow rule, so finding one is enough. Reading rules needs no administrator; fixing does.

The fix opens only what Campanile uses: the block rules go, one rule allows TCP on the
program's own port, and for any other port Windows asks again, as usual.
"""

from __future__ import annotations

import base64
import os
import subprocess

TIMEOUT = 30

# Rule paths may be written with %LOCALAPPDATA% and the like, and in any letter case.
_BLOCKS = """
$exe = [IO.Path]::GetFullPath($env:CAMPANILE_PYTHON)
@(Get-NetFirewallApplicationFilter |
  Where-Object { [Environment]::ExpandEnvironmentVariables($_.Program) -ieq $exe } |
  Get-NetFirewallRule |
  Where-Object { $_.Enabled -eq 'True' } |
  Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' }).Count
"""

_ALLOW = """
foreach ($pair in @({programs})) {{
  $encoded, $port = $pair -split ':'
  $path = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
  $exe = [IO.Path]::GetFullPath($path)
  Get-NetFirewallApplicationFilter |
    Where-Object {{ [Environment]::ExpandEnvironmentVariables($_.Program) -ieq $exe }} |
    Get-NetFirewallRule |
    Where-Object {{ $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' }} |
    Remove-NetFirewallRule
  $name = 'Campanile - ' + [IO.Path]::GetFileName($exe) + ' - TCP ' + $port
  Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue |
    Where-Object {{ ($_ | Get-NetFirewallApplicationFilter).Program -ieq $exe }} |
    Remove-NetFirewallRule
  New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Program $exe `
    -Protocol TCP -LocalPort ([int]$port) -Profile Any | Out-Null
}}
"""


def _powershell() -> str:
    # The full path: a bare name is looked up in the current folder too.
    root = os.environ.get("SYSTEMROOT", r"C:\Windows")  # Windows env names ignore case
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def _encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def blocks(program: str) -> bool | None:
    """True if inbound connections to this program are blocked; None if it can't tell."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(  # noqa: S603 (fixed script, the path travels in the environment)
            [_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded(_BLOCKS)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env={**os.environ, "CAMPANILE_PYTHON": program},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    count = result.stdout.strip()
    return int(count) > 0 if result.returncode == 0 and count.isdigit() else None


def _allow_script(programs: list[tuple[str, int]]) -> str:
    pairs = []
    for program, port in programs:
        if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
            raise ValueError(f"not a port: {port!r}")
        pairs.append(f"'{base64.b64encode(program.encode('utf-8')).decode('ascii')}:{port}'")
    return _ALLOW.format(programs=",".join(pairs))


def allow(programs: list[tuple[str, int]]) -> bool:
    """Opens each (program, port) to the phones in place of its block rules; Windows asks once.

    The elevated PowerShell doesn't inherit our environment, so the path goes into the script,
    as base64: PowerShell also takes curly quotes as quotes, and base64 has no quotes at all.
    """
    inner = _encoded(_allow_script(programs))
    outer = (
        "$p = Start-Process $PSHOME\\powershell.exe -Verb RunAs -Wait -PassThru "
        "-WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','{inner}'; "
        "exit $p.ExitCode"
    )
    try:
        result = subprocess.run(  # noqa: S603
            [_powershell(), "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded(outer)],
            capture_output=True,
            timeout=300,  # the person has to answer Windows' question
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and not any(blocks(p) for p, _ in programs)
