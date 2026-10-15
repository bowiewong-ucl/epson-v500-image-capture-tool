"""A pretend scanner for trying the app and running tests without hardware.

Enabled with the environment variable V500CAPTURE_DEMO=1, or V500CAPTURE_DEMO=only
to hide real scanners (used by the tests, so they never touch real hardware).
  V500CAPTURE_DEMO_DELAY=<seconds>  how long a scan takes (default 1)
  V500CAPTURE_DEMO_FAIL=1           every scan fails
  V500CAPTURE_DEMO_MAX_DPI=<dpi>    pretend the driver's highest resolution is this
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from ..config import BED_HEIGHT_IN, BED_WIDTH_IN
from .base import Backend, Device, ScanError, ScanSettings

# Draw at a quarter of the real size so demo scans stay quick.
_SCALE = 0.25


def enabled() -> bool:
    return os.environ.get("V500CAPTURE_DEMO", "") not in ("", "0")


def exclusive() -> bool:
    return os.environ.get("V500CAPTURE_DEMO", "") == "only"


class DemoBackend(Backend):
    name = "demo"

    def list_devices(self) -> list[Device]:
        max_dpi = int(os.environ.get("V500CAPTURE_DEMO_MAX_DPI", "0")) or None
        return [Device("demo:1", "Demo scanner (no hardware)", max_dpi)]

    def scan(self, device: Device, settings: ScanSettings, work_dir: Path) -> Path:
        from PIL import Image, ImageDraw, ImageFont

        time.sleep(float(os.environ.get("V500CAPTURE_DEMO_DELAY", "1")))
        if os.environ.get("V500CAPTURE_DEMO_FAIL", "") not in ("", "0"):
            raise ScanError("Simulated scanner failure (V500CAPTURE_DEMO_FAIL is set).")

        now = datetime.now()
        w = max(1, int(BED_WIDTH_IN * settings.dpi * _SCALE))
        h = max(1, int(BED_HEIGHT_IN * settings.dpi * _SCALE))
        hue = (now.minute * 6) % 360
        im = Image.new("HSV", (w, h), (int(hue / 360 * 255), 60, 235)).convert("RGB")
        draw = ImageDraw.Draw(im)
        # A "colony" that grows through the hour, so a time-lapse visibly changes.
        r = int(min(w, h) * 0.05 + min(w, h) * 0.4 * (now.minute * 60 + now.second) / 3600)
        cx, cy = w // 2, h // 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(90, 140, 60), outline=(20, 40, 20), width=3)
        try:
            font = ImageFont.load_default(size=max(12, w // 20))
        except TypeError:
            font = ImageFont.load_default()
        draw.text((w // 20, h // 20), f"DEMO {now:%Y-%m-%d %H:%M:%S}\n{settings.dpi} dpi",
                  fill=(0, 0, 0), font=font)
        out = work_dir / "demo.png"
        im.save(out)
        return out
