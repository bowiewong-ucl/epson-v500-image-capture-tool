"""Linux scanning through SANE's ``scanimage`` command.

The V500 needs Epson's proprietary "epkowa" SANE backend and its firmware
plugin; see scripts/linux/setup-epson-v500.sh.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..util import decode, nearest, run_external
from .base import MAX_SCAN_S, Backend, Device, ScanError, ScanSettings

_OPTION_LINE = re.compile(r"^\s+(-{1,2}[A-Za-z][\w-]*)\s+(\S.*?)(?:\s+\[(.*?)\])?\s*$")
_MODE_PREFERENCES = {
    "color": ("color", "colour"),
    "gray": ("gray", "grey", "grayscale"),
    "bw": ("lineart", "binary", "black", "halftone"),
}
_NOT_INSTALLED = ("The SANE 'scanimage' program is not installed. Install it with "
                  "'sudo apt install sane-utils', then run scripts/linux/setup-epson-v500.sh.")


def parse_options(text: str) -> dict[str, str]:
    """Map option name -> allowed-values text from ``scanimage -A`` output."""
    options: dict[str, str] = {}
    for line in text.splitlines():
        m = _OPTION_LINE.match(line)
        if m and m.group(3) != "inactive":
            options[m.group(1)] = m.group(2)
    return options


def pick_mode(spec: str | None, color_mode: str) -> str | None:
    if not spec:
        return None
    values = [v.strip() for v in spec.split("|")]
    for wanted in _MODE_PREFERENCES[color_mode]:
        for v in values:
            if v.lower() == wanted:
                return v
    for wanted in _MODE_PREFERENCES[color_mode]:
        for v in values:
            if wanted in v.lower():
                return v
    return None


def _numbers(spec: str) -> tuple[list[float], bool]:
    """Numbers in a spec like '50..6400dpi' (range) or '75|150|300dpi' (list)."""
    body = re.sub(r"\(.*?\)", "", spec)
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", body)]
    return nums, ".." in body


def pick_resolution(spec: str | None, dpi: int) -> int:
    if not spec:
        return dpi
    nums, is_range = _numbers(spec)
    if not nums:
        return dpi
    if is_range and len(nums) >= 2:
        return int(min(max(dpi, nums[0]), nums[1]))
    return int(nearest(dpi, nums))


def max_resolution(spec: str | None) -> int | None:
    if not spec:
        return None
    nums, _ = _numbers(spec)
    return int(max(nums)) if nums else None


def range_max(spec: str | None) -> float | None:
    if not spec:
        return None
    nums, is_range = _numbers(spec)
    return nums[1] if is_range and len(nums) >= 2 else None


class SaneBackend(Backend):
    name = "sane"

    def _run(self, args: list[str], timeout: float, stdout=subprocess.PIPE):
        exe = shutil.which("scanimage")
        if exe is None:
            raise ScanError(_NOT_INSTALLED)
        try:
            return run_external([exe] + args, timeout=timeout, stdout=stdout)
        except subprocess.TimeoutExpired as exc:
            raise ScanError(f"scanimage did not respond within {int(timeout)} s.") from exc

    def list_devices(self) -> list[Device]:
        proc = self._run(["-f", "%d|%v|%m%n"], timeout=90)
        devices = []
        for line in decode(proc.stdout).splitlines():
            parts = line.split("|")
            if len(parts) == 3 and parts[0]:
                devices.append(Device(f"sane:{parts[0]}", f"{parts[1]} {parts[2]}".strip(),
                                      self._max_dpi(parts[0])))
        return devices

    def _max_dpi(self, dev: str) -> int | None:
        try:
            proc = self._run(["-d", dev, "-A"], timeout=90)
        except ScanError:
            return None
        return max_resolution(parse_options(decode(proc.stdout)).get("--resolution"))

    def scan(self, device: Device, settings: ScanSettings, work_dir: Path) -> Path:
        dev = device.native_id
        proc = self._run(["-d", dev, "-A"], timeout=90)
        if proc.returncode != 0:
            raise ScanError(f"Could not open the scanner: {decode(proc.stderr)}")
        opts = parse_options(decode(proc.stdout))

        args = ["-d", dev, "--format=tiff"]
        mode = pick_mode(opts.get("--mode"), settings.color_mode)
        if mode:
            args += ["--mode", mode]
        args += ["--resolution", str(pick_resolution(opts.get("--resolution"), settings.dpi))]
        # Whole flatbed.
        for flag, value in (("-l", "0"), ("-t", "0"),
                            ("-x", range_max(opts.get("-x"))), ("-y", range_max(opts.get("-y")))):
            if flag in opts and value is not None:
                args += [flag, str(value)]

        out = work_dir / "scan.tiff"
        with open(out, "wb") as fh:
            proc = self._run(args, timeout=MAX_SCAN_S, stdout=fh)
        if proc.returncode != 0 or out.stat().st_size == 0:
            raise ScanError(f"Scan failed: {decode(proc.stderr) or f'exit code {proc.returncode}'}")
        return out
