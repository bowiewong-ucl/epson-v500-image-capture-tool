"""Common scanner interface shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    id: str  # "<backend>:<backend-specific id>"
    name: str  # model name shown to the user
    max_dpi: int | None = None  # highest resolution the driver allows, if it says

    @property
    def backend(self) -> str:
        return self.id.split(":", 1)[0]

    @property
    def native_id(self) -> str:
        return self.id.split(":", 1)[1] if ":" in self.id else ""


@dataclass(frozen=True)
class ScanSettings:
    dpi: int = 300
    color_mode: str = "color"  # color | gray | bw


# Backstop for a single scan inside the child process. The GUI's own timeout
# (which grows with dpi) is shorter and is what normally applies.
MAX_SCAN_S = 12 * 60 * 60


class ScanError(Exception):
    """A scan failed; the message is shown to the user as-is."""


class Backend:
    name = ""

    def list_devices(self) -> list[Device]:
        raise NotImplementedError

    def scan(self, device: Device, settings: ScanSettings, work_dir: Path) -> Path:
        """Scan the whole flatbed into ``work_dir`` and return the image file written.

        The file may be in any format Pillow can read; the caller converts it.
        """
        raise NotImplementedError

    def resolve(self, device_id: str, device_name: str) -> Device:
        """Find the saved device again. Some ids (e.g. SANE USB bus numbers)
        change when the scanner is re-plugged, so fall back to the name."""
        devices = self.list_devices()
        for dev in devices:
            if dev.id == device_id:
                return dev
        for dev in devices:
            if device_name and dev.name == device_name:
                return dev
        label = device_name or device_id
        raise ScanError(f"Scanner '{label}' was not found. Check it is switched on and "
                        "connected by USB, and that no other program (e.g. Epson Scan) is using it.")
