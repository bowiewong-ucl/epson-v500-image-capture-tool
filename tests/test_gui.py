"""GUI and capture-controller tests using the demo scanner (no hardware needed)."""

import csv
import time

import pytest

from v500capture import config
from v500capture.gui.controller import CaptureController, RunConfig


@pytest.fixture(autouse=True)
def demo_env(monkeypatch):
    monkeypatch.setenv("V500CAPTURE_DEMO", "only")
    monkeypatch.setenv("V500CAPTURE_DEMO_DELAY", "0.2")


def make_run(folder, interval_s=3.0, duration_s=7.0):
    return RunConfig(device_id="demo:1", device_name="Demo scanner (no hardware)", folder=folder,
                     prefix="t", fmt="png", dpi=75, color_mode="color",
                     interval_s=interval_s, end=time.time() + duration_s)


def read_log(folder):
    with open(folder / "scan_log.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_capture_runs_until_end_time(qtbot, tmp_path):
    c = CaptureController()
    c.start(make_run(tmp_path))
    assert c.state == "running"
    qtbot.waitUntil(lambda: c.state == "idle", timeout=30_000)
    assert c.finish_reason == "reached its end time"
    assert c.ok_count == 3  # at 0 s, 3 s and 6 s
    assert len(list(tmp_path.glob("t_*.png"))) == 3
    rows = read_log(tmp_path)
    assert [r["status"] for r in rows] == ["ok"] * 3


def test_stop_waits_for_running_scan(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("V500CAPTURE_DEMO_DELAY", "2")
    c = CaptureController()
    c.start(make_run(tmp_path, interval_s=60, duration_s=600))
    qtbot.waitUntil(lambda: c.busy, timeout=5_000)
    c.stop()
    assert c.state == "stopping"
    qtbot.waitUntil(lambda: c.state == "idle", timeout=30_000)
    assert c.ok_count == 1 and c.finish_reason == "stopped by you"


def test_failures_raise_alert(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("V500CAPTURE_DEMO_FAIL", "1")
    c = CaptureController()
    alerts = []
    c.failure_alert.connect(alerts.append)
    c.start(make_run(tmp_path, interval_s=2, duration_s=7))
    qtbot.waitUntil(lambda: c.state == "idle", timeout=30_000)
    assert c.fail_count >= 3 and c.ok_count == 0
    assert alerts == [True]
    assert all(r["status"] in ("failed", "skipped") for r in read_log(tmp_path))


def test_hung_scan_is_killed(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("V500CAPTURE_DEMO_DELAY", "60")
    monkeypatch.setenv("V500CAPTURE_SCAN_TIMEOUT", "3")
    c = CaptureController()
    c.start(make_run(tmp_path, interval_s=60, duration_s=600))
    qtbot.waitUntil(lambda: c.fail_count == 1, timeout=30_000)
    assert "No response from the scanner" in read_log(tmp_path)[0]["error"]
    c.stop()
    assert c.state == "idle"


def test_main_window_smoke(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "settings_path", lambda: tmp_path / "settings.json")
    from v500capture.gui.main_window import MainWindow

    settings = config.Settings(folder=str(tmp_path / "out")).normalized()
    win = MainWindow(settings)
    qtbot.addWidget(win)
    qtbot.waitUntil(lambda: win.device_combo.currentData() is not None, timeout=30_000)
    assert win.device_combo.currentData()[0] == "demo:1"
    assert win.start_btn.isEnabled() and not win.stop_btn.isEnabled()

    win.dpi_combo.setCurrentIndex(win.dpi_combo.findData(75))
    win.start_capture()
    assert win.controller.state == "running"
    assert win.stop_btn.isEnabled() and not win.start_btn.isEnabled()
    qtbot.waitUntil(lambda: win.controller.ok_count == 1, timeout=30_000)
    assert win.thumb_label.pixmap() is not None and not win.thumb_label.pixmap().isNull()
    win.controller.stop()
    qtbot.waitUntil(lambda: win.controller.state == "idle", timeout=30_000)
    assert win.start_btn.isEnabled()
    assert (tmp_path / "settings.json").exists()


@pytest.mark.parametrize("limit,expected_top,expected_current", [
    ("1200", 1200, 1200),  # driver limit: higher resolutions are removed
    ("0", 6400, 6400),     # driver doesn't say: everything is offered
])
def test_dpi_choices_follow_scanner(qtbot, tmp_path, monkeypatch, limit, expected_top, expected_current):
    monkeypatch.setenv("V500CAPTURE_DEMO_MAX_DPI", limit)
    monkeypatch.setattr(config, "settings_path", lambda: tmp_path / "settings.json")
    from v500capture.gui.main_window import MainWindow

    win = MainWindow(config.Settings(folder=str(tmp_path), dpi=6400).normalized())
    qtbot.addWidget(win)
    qtbot.waitUntil(lambda: win.device_combo.currentData() is not None, timeout=30_000)
    items = [win.dpi_combo.itemData(i) for i in range(win.dpi_combo.count())]
    assert max(items) == expected_top
    assert win.dpi_combo.currentData() == expected_current
    assert win.dpi_hint.isVisibleTo(win) == (limit != "0")
