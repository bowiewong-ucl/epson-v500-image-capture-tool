"""User settings, remembered between sessions as JSON in the per-user config folder."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platformdirs import user_config_dir, user_pictures_dir

# Standard V500 resolutions, up to its 6400 dpi optical maximum (higher
# settings in Epson Scan are interpolated and add no detail). A full-bed
# colour scan at 6400 dpi is ~12 GB; it's the user's call.
DPI_CHOICES = (75, 100, 150, 200, 300, 400, 600, 800, 1200, 1600, 2400, 3200, 4800, 6400)
JPEG_MAX_SIDE = 65500  # pixels; JPEG can't store anything larger
COLOR_CHOICES = ("color", "gray", "bw")
FORMAT_CHOICES = ("tiff", "png", "jpeg")

# V500 flatbed scan area in inches (216 x 297 mm).
BED_WIDTH_IN = 8.5
BED_HEIGHT_IN = 11.7
_BYTES_PER_PIXEL = {"color": 3.0, "gray": 1.0, "bw": 1 / 8}


def estimate_scan_bytes(dpi: int, color_mode: str) -> int:
    """Uncompressed size of one full-bed scan."""
    pixels = (BED_WIDTH_IN * dpi) * (BED_HEIGHT_IN * dpi)
    return int(pixels * _BYTES_PER_PIXEL[color_mode])


def estimate_scan_pixels(dpi: int) -> tuple[int, int]:
    return int(BED_WIDTH_IN * dpi), int(BED_HEIGHT_IN * dpi)


def scan_timeout_s(dpi: int) -> float:
    """How long to wait before assuming a scan has hung. High-dpi scans are
    slow, so the limit grows with the amount of data (15 min up to 1200 dpi)."""
    return 15 * 60 * max(1.0, (dpi / 1200) ** 2)


def default_folder() -> str:
    return str(Path(user_pictures_dir()) / "V500 Capture")


@dataclass
class Settings:
    device_id: str = ""
    device_name: str = ""
    folder: str = ""
    prefix: str = "scan"
    fmt: str = "tiff"
    dpi: int = 300
    color_mode: str = "color"
    interval_min: int = 20
    use_end_time: bool = False

    def normalized(self) -> "Settings":
        """Replace any out-of-range values (e.g. from a hand-edited file) with defaults."""
        d = Settings()
        if self.fmt not in FORMAT_CHOICES:
            self.fmt = d.fmt
        if self.dpi not in DPI_CHOICES:
            self.dpi = d.dpi
        if self.color_mode not in COLOR_CHOICES:
            self.color_mode = d.color_mode
        if not isinstance(self.interval_min, int) or not 1 <= self.interval_min <= 1440:
            self.interval_min = d.interval_min
        if not self.folder:
            self.folder = default_folder()
        return self


def settings_path() -> Path:
    return Path(user_config_dir("V500Capture", appauthor=False)) / "settings.json"


def load(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings().normalized()
    known = {f.name for f in fields(Settings)}
    try:
        settings = Settings(**{k: v for k, v in data.items() if k in known})
    except TypeError:
        return Settings().normalized()
    return settings.normalized()


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
