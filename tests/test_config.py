import json

from v500capture import config


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = config.Settings(device_id="wia:x", device_name="EPSON V500", folder=str(tmp_path),
                        prefix="plate", fmt="png", dpi=600, color_mode="gray",
                        interval_min=15, use_end_time=True)
    config.save(s, path)
    assert config.load(path) == s


def test_bad_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"dpi": 123, "fmt": "gif", "interval_min": 0, "unknown": 1, "prefix": "p"}))
    s = config.load(path)
    assert (s.dpi, s.fmt, s.interval_min, s.prefix) == (300, "tiff", 20, "p")
    assert s.folder  # defaults to Pictures/V500 Capture


def test_missing_or_corrupt_file(tmp_path):
    assert config.load(tmp_path / "nope.json").dpi == 300
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert config.load(bad).interval_min == 20


def test_estimate_scan_bytes():
    # 8.5 x 11.7 in at 300 dpi, 3 bytes per pixel
    assert config.estimate_scan_bytes(300, "color") == int(2550 * 3510 * 3)
    assert config.estimate_scan_bytes(300, "gray") * 3 == config.estimate_scan_bytes(300, "color")


def test_max_dpi_offered():
    assert config.DPI_CHOICES[-1] == 6400
    assert config.estimate_scan_pixels(6400) == (54400, 74880)


def test_scan_timeout_grows_with_dpi():
    assert config.scan_timeout_s(300) == config.scan_timeout_s(1200) == 900
    assert config.scan_timeout_s(2400) == 3600
    assert config.scan_timeout_s(6400) > 7 * 3600
