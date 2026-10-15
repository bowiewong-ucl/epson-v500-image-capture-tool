"""Runs the command-line mode in a real child process, as the GUI does, using the demo scanner."""

import json
import os
import subprocess
import sys

from PIL import Image


def run_cli(*args, **env):
    full_env = dict(os.environ, V500CAPTURE_DEMO="only", V500CAPTURE_DEMO_DELAY="0", **env)
    return subprocess.run([sys.executable, "-m", "v500capture", *args],
                          capture_output=True, text=True, env=full_env, timeout=120)


def test_list_devices(tmp_path):
    result_file = tmp_path / "r.json"
    proc = run_cli("--list-devices", "--result-file", str(result_file))
    assert proc.returncode == 0
    result = json.loads(result_file.read_text())
    assert result["ok"]
    assert result["devices"] == [{"id": "demo:1", "name": "Demo scanner (no hardware)", "max_dpi": None}]


def test_scan_success(tmp_path):
    out, result_file = tmp_path / "img.png", tmp_path / "r.json"
    proc = run_cli("--scan", "--device", "demo:1", "--out", str(out), "--dpi", "150",
                   "--color", "gray", "--result-file", str(result_file))
    assert proc.returncode == 0, proc.stderr
    result = json.loads(result_file.read_text())
    assert result["ok"] and result["path"] == str(out)
    with Image.open(out) as im:
        assert im.mode == "L"


def test_scan_by_partial_name(tmp_path):
    proc = run_cli("--scan", "--device", "demo", "--out", str(tmp_path / "a.tif"))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "a.tif").exists()


def test_scan_failure_reported(tmp_path):
    result_file = tmp_path / "r.json"
    proc = run_cli("--scan", "--device", "demo:1", "--out", str(tmp_path / "x.tif"),
                   "--result-file", str(result_file), V500CAPTURE_DEMO_FAIL="1")
    assert proc.returncode == 1
    result = json.loads(result_file.read_text())
    assert not result["ok"] and "Simulated" in result["error"]
    assert not (tmp_path / "x.tif").exists()


def test_unknown_device(tmp_path):
    proc = run_cli("--scan", "--device", "no-such-scanner", "--out", str(tmp_path / "x.tif"))
    assert proc.returncode == 1
    assert "No scanner matching" in proc.stderr


def test_list_reports_max_dpi(tmp_path):
    result_file = tmp_path / "r.json"
    run_cli("--list-devices", "--result-file", str(result_file), V500CAPTURE_DEMO_MAX_DPI="1200")
    demo = next(d for d in json.loads(result_file.read_text())["devices"] if d["id"] == "demo:1")
    assert demo["max_dpi"] == 1200
