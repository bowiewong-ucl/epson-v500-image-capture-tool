import csv
from datetime import datetime

import pytest
from PIL import Image

from v500capture.output import LogRow, ScanLog, make_filename, sanitize_prefix, save_image, unique_path


def test_make_filename():
    when = datetime(2026, 9, 29, 14, 5, 9)
    assert make_filename("plate A", when, "tiff") == "plate A_2026-09-29_14-05-09.tif"
    assert make_filename("", when, "jpeg") == "scan_2026-09-29_14-05-09.jpg"


def test_sanitize_prefix():
    assert sanitize_prefix('a/b\\c:d*?"<>|') == "a_b_c_d______"
    assert sanitize_prefix("  trailing. ") == "trailing"
    assert sanitize_prefix("...") == "scan"


def test_unique_path(tmp_path):
    (tmp_path / "x.tif").write_bytes(b"")
    (tmp_path / "x_2.tif").write_bytes(b"")
    assert unique_path(tmp_path, "x.tif").name == "x_3.tif"
    assert unique_path(tmp_path, "y.tif").name == "y.tif"


@pytest.mark.parametrize("name,mode,expected_mode", [
    ("out.tif", "color", "RGB"),
    ("out.png", "gray", "L"),
    ("out.tif", "bw", "1"),
    ("out.jpg", "bw", "L"),  # JPEG can't hold 1-bit
])
def test_save_image_converts(tmp_path, name, mode, expected_mode):
    src = tmp_path / "raw.bmp"
    Image.new("RGB", (40, 30), (200, 100, 50)).save(src)
    thumb = tmp_path / "thumb.png"
    info = save_image(src, tmp_path / "sub" / name, mode, 300, thumbnail=thumb)
    assert info.width == 40 and info.height == 30 and info.bytes > 0
    assert not list(tmp_path.glob("sub/*.partial"))
    with Image.open(info.path) as im:
        assert im.mode == expected_mode
        assert round(im.info["dpi"][0]) == 300
    assert thumb.exists()


def test_scan_log_retries_when_locked(tmp_path, monkeypatch):
    log = ScanLog(tmp_path)
    real_open = open
    calls = {"n": 0}

    def flaky_open(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "Permission denied")
        return real_open(*args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)
    assert log.append(LogRow(1, "t1", status="ok")) is not None  # locked: kept for later
    assert log.append(LogRow(2, "t2", status="failed", error="boom")) is None
    rows = list(csv.DictReader(real_open(log.path, encoding="utf-8")))
    assert [r["scan_number"] for r in rows] == ["1", "2"]
    assert rows[1]["error"] == "boom"


def test_dpi_read_from_scanner_file(tmp_path):
    src = tmp_path / "raw.bmp"
    Image.new("RGB", (510, 702), "white").save(src, dpi=(60, 60))  # 8.5 x 11.7 in at 60 dpi
    info = save_image(src, tmp_path / "out.tif", "color", 300)
    assert info.dpi == 60
    with Image.open(info.path) as im:
        assert round(im.info["dpi"][0]) == 60


def test_dummy_file_dpi_ignored(tmp_path):
    src = tmp_path / "raw.bmp"
    Image.new("RGB", (2550, 20), "white").save(src, dpi=(96, 96))  # 2550 px can't be 96 dpi full-bed
    assert save_image(src, tmp_path / "out.png", "color", 300).dpi == 300


def test_huge_tiff_saved_as_bigtiff(tmp_path, monkeypatch):
    monkeypatch.setattr("v500capture.output._BIGTIFF_ABOVE_BYTES", 100)
    src = tmp_path / "raw.bmp"
    Image.new("RGB", (40, 30), (1, 2, 3)).save(src)
    info = save_image(src, tmp_path / "big.tif", "color", 300)
    with open(info.path, "rb") as fh:
        assert fh.read(4) == b"II+\x00"  # BigTIFF signature
    with Image.open(info.path) as im:
        assert im.size == (40, 30) and im.getpixel((0, 0)) == (1, 2, 3)


def test_jpeg_too_large_rejected(tmp_path, monkeypatch):
    from v500capture.scanners.base import ScanError

    monkeypatch.setattr("v500capture.output.JPEG_MAX_SIDE", 20)
    src = tmp_path / "raw.bmp"
    Image.new("RGB", (40, 30)).save(src)
    with pytest.raises(ScanError, match="too big for JPEG"):
        save_image(src, tmp_path / "x.jpg", "color", 300)
    assert not list(tmp_path.glob("x.jpg*"))
