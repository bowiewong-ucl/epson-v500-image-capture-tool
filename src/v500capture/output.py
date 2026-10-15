"""File naming, image saving and the per-folder scan log."""

from __future__ import annotations

import csv
import os
import re
import shutil
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from .config import JPEG_MAX_SIDE
from .scanners.base import ScanError

# format key -> (file extension, Pillow format name)
FORMATS = {
    "tiff": (".tif", "TIFF"),
    "png": (".png", "PNG"),
    "jpeg": (".jpg", "JPEG"),
}
_PIL_FORMAT_BY_EXT = {
    ".tif": "TIFF", ".tiff": "TIFF", ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
}
_PIL_MODE = {"color": "RGB", "gray": "L", "bw": "1"}
# Pillow's compressed TIFF writer (libtiff) can't go past 4 GB; bigger images
# are written as uncompressed BigTIFF instead.
_BIGTIFF_ABOVE_BYTES = 3.5e9
_THUMB_SIDE = 480

LOG_NAME = "scan_log.csv"
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_prefix(prefix: str) -> str:
    """Make a user-typed prefix safe to use in a filename on every OS."""
    cleaned = _INVALID_CHARS.sub("_", prefix).strip().rstrip(". ")
    return cleaned or "scan"


def make_filename(prefix: str, when: datetime, fmt: str) -> str:
    ext = FORMATS[fmt][0]
    return f"{sanitize_prefix(prefix)}_{when:%Y-%m-%d_%H-%M-%S}{ext}"


def unique_path(folder: Path, filename: str) -> Path:
    """Return folder/filename, adding _2, _3, ... if that name is taken."""
    path = folder / filename
    stem, suffix = path.stem, path.suffix
    n = 2
    while path.exists():
        path = folder / f"{stem}_{n}{suffix}"
        n += 1
    return path


@dataclass
class ImageInfo:
    path: str
    bytes: int
    width: int
    height: int
    dpi: int  # as reported by the scanner, if it says


def _file_dpi(im) -> int | None:
    """The resolution the scanner wrote into the file, if it's believable.

    Only trusted when it matches a full-bed scan (8.5 in wide), since some
    drivers write a dummy value such as 96 dpi.
    """
    value = im.info.get("dpi")
    try:
        dpi = round(float(value[0]))
    except (TypeError, ValueError, IndexError):
        return None
    if not 10 <= dpi <= 20000:
        return None
    return dpi if 7.0 <= im.size[0] / dpi <= 9.0 else None


def save_image(src: Path, dest: Path, color_mode: str, dpi: int,
               thumbnail: Path | None = None) -> ImageInfo:
    """Convert the scanner's raw output to the final format and colour mode.

    Writes to ``<dest>.partial`` first and renames it, so a half-written file
    never appears under the final name.
    """
    from PIL import Image

    # A full-bed scan at 1200+ dpi exceeds Pillow's decompression-bomb limit.
    Image.MAX_IMAGE_PIXELS = None
    fmt = _PIL_FORMAT_BY_EXT.get(dest.suffix.lower())
    if fmt is None:
        raise ValueError(f"Unsupported output file type: {dest.suffix}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")

    with Image.open(src) as opened:
        opened.load()
        im = opened
        scan_dpi = _file_dpi(opened) or dpi
        if fmt == "JPEG" and max(im.size) > JPEG_MAX_SIDE:
            raise ScanError(f"The scan is {im.size[0]}x{im.size[1]} pixels, too big for JPEG "
                            f"(max {JPEG_MAX_SIDE}). Choose TIFF or PNG for this resolution.")
        target = _PIL_MODE[color_mode]
        if fmt == "JPEG" and target == "1":
            target = "L"  # JPEG cannot store 1-bit images
        if im.mode != target:
            im = im.convert(target)
        options: dict = {"dpi": (scan_dpi, scan_dpi)}
        if fmt == "TIFF":
            if im.size[0] * im.size[1] * len(im.getbands()) > _BIGTIFF_ABOVE_BYTES:
                options["big_tiff"] = True
            else:
                options["compression"] = "tiff_lzw"
        elif fmt == "JPEG":
            options["quality"] = 95
        try:
            im.save(tmp, format=fmt, **options)
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        width, height = im.size
        if thumbnail is not None:
            # Resize straight down rather than copying: the scan may be many GB.
            scale = min(1.0, _THUMB_SIDE / max(width, height))
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            resample = Image.Resampling.NEAREST if im.mode == "1" else Image.Resampling.BOX
            im.resize(size, resample).save(thumbnail, format="PNG")

    return ImageInfo(str(dest), dest.stat().st_size, width, height, scan_dpi)


def free_bytes(folder: Path) -> int:
    return shutil.disk_usage(folder).free


@dataclass
class LogRow:
    scan_number: int | str
    scheduled_time: str
    started: str = ""
    finished: str = ""
    status: str = ""  # ok | failed | skipped
    file: str = ""
    duration_s: str = ""
    bytes: int | str = ""
    error: str = ""


class ScanLog:
    """Appends rows to scan_log.csv in the output folder.

    If the file can't be written (typically because it is open in Excel on
    Windows), rows are kept in memory and written on the next attempt.
    """

    def __init__(self, folder: Path):
        self.path = Path(folder) / LOG_NAME
        self.pending: list[LogRow] = []

    def append(self, row: LogRow) -> str | None:
        """Queue a row and try to write everything queued. Returns an error message or None."""
        self.pending.append(row)
        return self.flush()

    def flush(self) -> str | None:
        if not self.pending:
            return None
        names = [f.name for f in fields(LogRow)]
        try:
            new_file = not self.path.exists() or self.path.stat().st_size == 0
            with open(self.path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=names)
                if new_file:
                    writer.writeheader()
                for row in self.pending:
                    writer.writerow(asdict(row))
        except OSError as exc:
            return (f"Could not write {LOG_NAME} ({exc.strerror or exc}). "
                    f"If it is open in Excel, close it; {len(self.pending)} row(s) will be written later.")
        self.pending.clear()
        return None
