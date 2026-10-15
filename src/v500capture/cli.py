"""Command-line mode.

The GUI runs every scan (and every scanner search) through this in a child
process, so a hung or crashing driver can't take the GUI down. It is also
handy for diagnosing scanner problems:

    v500capture --list-devices
    v500capture --scan --device "V500" --out test.tif --dpi 300
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from .config import COLOR_CHOICES
from .output import save_image
from .scanners import Device, ScanError, ScanSettings, backends, get_backend, list_devices

_CLI_FLAGS = ("--list-devices", "--scan", "-h", "--help")


def is_cli(argv: list[str]) -> bool:
    return any(arg in _CLI_FLAGS for arg in argv)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="v500capture", description="Epson V500 time-lapse capture")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-devices", action="store_true", help="list connected scanners")
    mode.add_argument("--scan", action="store_true", help="take one scan")
    p.add_argument("--device", default="", help="scanner id from --list-devices, or part of its name")
    p.add_argument("--device-name", default="", help="scanner name to fall back on if the id changed")
    p.add_argument("--out", help="image file to write (.tif, .png or .jpg)")
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--color", choices=COLOR_CHOICES, default="color")
    p.add_argument("--thumbnail", help="also write a small PNG preview here")
    p.add_argument("--result-file", help="write the result as JSON to this file")
    return p


def _find_device(device: str, device_name: str) -> Device:
    prefix = device.split(":", 1)[0]
    if ":" in device and prefix in {b.name for b in backends()}:
        return get_backend(prefix).resolve(device, device_name)
    # Not an id: match (part of) the name, e.g. --device "V500".
    wanted = (device or device_name).lower()
    devices, warnings = list_devices()
    for dev in devices:
        if wanted and wanted in dev.name.lower():
            return dev
    if not wanted and devices:
        return devices[0]
    extra = f" ({'; '.join(warnings)})" if warnings else ""
    what = f"matching '{device or device_name}' " if wanted else ""
    raise ScanError(f"No scanner {what}was found{extra}. Check it is switched on and connected.")


def run_list() -> dict:
    devices, warnings = list_devices()
    return {"ok": True, "devices": [asdict(d) for d in devices], "warnings": warnings}


def run_scan(args: argparse.Namespace) -> dict:
    if not args.out:
        raise ScanError("--out is required with --scan")
    out = Path(args.out).expanduser().resolve()
    if out.suffix.lower() not in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
        raise ScanError("--out must end in .tif, .png or .jpg")
    settings = ScanSettings(dpi=args.dpi, color_mode=args.color)
    device = _find_device(args.device, args.device_name)
    backend = get_backend(device.backend)
    with tempfile.TemporaryDirectory(prefix="v500capture-") as work:
        raw = backend.scan(device, settings, Path(work))
        thumb = Path(args.thumbnail) if args.thumbnail else None
        info = save_image(raw, out, settings.color_mode, settings.dpi, thumb)
    return {"ok": True, **asdict(info), "device": asdict(device), "thumbnail": args.thumbnail or ""}


def main(argv: list[str]) -> int:
    # A windowed (no console) build has no stdout/stderr at all.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    args = build_parser().parse_args(argv)

    started = time.monotonic()
    try:
        result = run_list() if args.list_devices else run_scan(args)
    except ScanError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:
        result = {"ok": False, "error": f"Unexpected error: {type(exc).__name__}: {exc}",
                  "detail": traceback.format_exc()}
    result["duration_s"] = round(time.monotonic() - started, 1)

    if args.result_file:
        tmp = Path(args.result_file + ".tmp")
        tmp.write_text(json.dumps(result), encoding="utf-8")
        os.replace(tmp, args.result_file)
    _print_result(args, result)
    return 0 if result["ok"] else 1


def _print_result(args: argparse.Namespace, result: dict) -> None:
    if not result["ok"]:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        if "detail" in result:
            print(result["detail"], file=sys.stderr)
    elif args.list_devices:
        if not result["devices"]:
            print("No scanners found.")
        for dev in result["devices"]:
            limit = f"\n    up to {dev['max_dpi']} dpi" if dev.get("max_dpi") else ""
            print(f"{dev['name']}\n    id: {dev['id']}{limit}")
        for warning in result["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
    else:
        print(f"Saved {result['path']} ({result['width']}x{result['height']} px at {result['dpi']} dpi, "
              f"{result['bytes'] / 1e6:.1f} MB) from {result['device']['name']} "
              f"in {result['duration_s']} s")
