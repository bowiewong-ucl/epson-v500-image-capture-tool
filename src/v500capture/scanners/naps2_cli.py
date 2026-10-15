"""Fallback: scan through the free NAPS2 app's command-line tool, if installed.

Mainly for Windows, where the Epson driver may offer TWAIN but not WIA.
NAPS2 handles TWAIN (including 32-bit drivers) itself. See https://www.naps2.com
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import BED_HEIGHT_IN, BED_WIDTH_IN
from ..util import decode, run_external
from .base import MAX_SCAN_S, Backend, Device, ScanError, ScanSettings

_BITDEPTH = {"color": "color", "gray": "gray", "bw": "bw"}


def _driver() -> str:
    if sys.platform == "win32":
        return "twain"
    if sys.platform == "darwin":
        return "apple"
    return "sane"


def find_console() -> list[str] | None:
    """The command that runs NAPS2's console mode, or None if NAPS2 isn't installed."""
    if sys.platform == "win32":
        candidates = [Path(os.environ.get(v, "")) / "NAPS2" / "NAPS2.Console.exe"
                      for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
        found = shutil.which("NAPS2.Console")
        if found:
            return [found]
        for c in candidates:
            if c.is_file():
                return [str(c)]
        return None
    if sys.platform == "darwin":
        app = Path("/Applications/NAPS2.app/Contents/MacOS/NAPS2")
        return [str(app), "console"] if app.is_file() else None
    found = shutil.which("naps2")
    return [found, "console"] if found else None


class Naps2Backend(Backend):
    name = "naps2"

    def __init__(self, command: list[str]):
        self.command = command
        self.driver = _driver()

    def list_devices(self) -> list[Device]:
        try:
            proc = run_external(self.command + ["--listdevices", "--driver", self.driver], timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScanError(f"NAPS2 could not list scanners: {exc}") from exc
        names = [line.strip() for line in decode(proc.stdout).splitlines() if line.strip()]
        return [Device(f"naps2:{self.driver}:{n}", f"{n} (via NAPS2 {self.driver.upper()})") for n in names]

    def resolve(self, device_id: str, device_name: str) -> Device:
        # NAPS2 selects devices by name, so no need to list them first.
        return Device(device_id, device_name)

    def scan(self, device: Device, settings: ScanSettings, work_dir: Path) -> Path:
        driver, _, name = device.native_id.partition(":")
        out = work_dir / "scan.tif"
        cmd = self.command + [
            "--noprofile", "--driver", driver or self.driver, "--device", name,
            "--dpi", str(settings.dpi), "--bitdepth", _BITDEPTH[settings.color_mode],
            "--pagesize", f"{BED_WIDTH_IN}x{BED_HEIGHT_IN}in",
            "-o", str(out), "--force",
        ]
        try:
            proc = run_external(cmd, timeout=MAX_SCAN_S)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScanError(f"NAPS2 failed to run: {exc}") from exc
        if not out.is_file():
            detail = decode(proc.stderr) or decode(proc.stdout) or f"exit code {proc.returncode}"
            raise ScanError(f"NAPS2 scan failed: {detail}")
        return out
