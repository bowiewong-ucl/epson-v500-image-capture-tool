"""Runs a capture: schedules scans, launches them and records the results."""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..config import scan_timeout_s
from ..keepawake import KeepAwake
from ..output import LogRow, ScanLog, free_bytes, make_filename, unique_path
from ..scheduler import Scheduler
from .scan_process import ChildJob



def scan_timeout(dpi: int) -> float:
    """Kill a scan that hasn't finished after this long (a hung driver or unplugged scanner)."""
    override = os.environ.get("V500CAPTURE_SCAN_TIMEOUT")
    return float(override) if override else scan_timeout_s(dpi)

FAILURE_ALERT_AFTER = 3


def fmt_bytes(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} kB"


def _stamp(t: float | datetime) -> str:
    dt = t if isinstance(t, datetime) else datetime.fromtimestamp(t)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class RunConfig:
    device_id: str
    device_name: str
    folder: Path
    prefix: str
    fmt: str
    dpi: int
    color_mode: str
    interval_s: float
    end: float | None  # epoch seconds, or None to run until stopped


class CaptureController(QObject):
    state_changed = Signal(str)  # idle | running | stopping
    message = Signal(str, str)  # level (info | warn | error), text
    scan_finished = Signal(dict)  # child result
    status_changed = Signal()
    failure_alert = Signal(bool)  # too many failures in a row / recovered

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.state = "idle"
        self.run: RunConfig | None = None
        self.scheduler: Scheduler | None = None
        self.job: ChildJob | None = None
        self.scan_log: ScanLog | None = None
        self.ok_count = self.fail_count = self.skip_count = 0
        self.consecutive_failures = 0
        self.finish_reason = ""
        self._current: dict = {}
        self._disk_warned = self._dpi_warned = False
        self._keep_awake = KeepAwake()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # ---- public ----------------------------------------------------------
    def start(self, run: RunConfig) -> None:
        if self.state != "idle":
            return
        self.run = run
        self.scheduler = Scheduler(time.time(), run.interval_s, run.end)
        self.scan_log = ScanLog(run.folder)
        self.ok_count = self.fail_count = self.skip_count = self.consecutive_failures = 0
        self.finish_reason = ""
        self._disk_warned = self._dpi_warned = False
        warning = self._keep_awake.start()
        if warning:
            self.message.emit("warn", warning)
        self._set_state("running")
        until = f"until {_stamp(run.end)}" if run.end else "until you press Stop"
        self.message.emit("info", f"Capture started: every {run.interval_s / 60:g} min {until}, "
                                  f"saving to {run.folder}")
        self._timer.start()
        self._tick()

    def stop(self, reason: str = "stopped by you") -> None:
        if self.state != "running":
            return
        self.finish_reason = reason
        if self.job is not None:
            self._set_state("stopping")
            self.message.emit("info", f"Capture {reason}; waiting for the current scan to finish…")
        else:
            self._finish()

    def force_abort(self) -> None:
        if self.job is not None:
            self.message.emit("warn", "Cancelling the current scan…")
            self.job.abort()

    def shutdown(self) -> None:
        """The app is closing: stop immediately."""
        self._timer.stop()
        if self.job is not None:
            self.job.finished.disconnect()
            self.job.abort()
            self.job = None
        self._keep_awake.stop()
        self.state = "idle"
        if self.scan_log is not None:
            self.scan_log.flush()

    def next_scan_time(self) -> float | None:
        if self.state != "running" or self.scheduler is None:
            return None
        return self.scheduler.next_time()

    @property
    def busy(self) -> bool:
        return self.job is not None

    # ---- internals -------------------------------------------------------
    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)

    def _tick(self) -> None:
        if self.state == "running":
            tick = self.scheduler.poll(time.time(), busy=self.job is not None)
            for index in tick.skipped:
                self._record_skip(index, tick.skip_reason)
            if tick.finished:
                self.stop("reached its end time")
            elif tick.fire is not None:
                self._start_scan(tick.fire)
        self.status_changed.emit()

    def _start_scan(self, index: int) -> None:
        run = self.run
        started = datetime.now()
        path = unique_path(run.folder, make_filename(run.prefix, started, run.fmt))
        thumb = Path(tempfile.gettempdir()) / f"v500capture-thumb-{uuid.uuid4().hex}.png"
        args = ["--scan", "--device", run.device_id, "--device-name", run.device_name,
                "--out", str(path), "--dpi", str(run.dpi), "--color", run.color_mode,
                "--thumbnail", str(thumb)]
        self._current = {"number": index + 1, "slot": self.scheduler.slot_time(index),
                         "started": started, "path": path}
        self.job = ChildJob(args, scan_timeout(run.dpi), self)
        self.job.finished.connect(self._on_scan_finished)
        self.message.emit("info", f"Scan #{index + 1} started…")
        self.job.start()

    def _on_scan_finished(self, result: dict) -> None:
        cur = self._current
        self.job.deleteLater()
        self.job = None
        row = LogRow(scan_number=cur["number"], scheduled_time=_stamp(cur["slot"]),
                     started=_stamp(cur["started"]), finished=_stamp(datetime.now()),
                     duration_s=str(result.get("duration_s", "")))
        if result.get("ok"):
            self.ok_count += 1
            if self.consecutive_failures >= FAILURE_ALERT_AFTER:
                self.failure_alert.emit(False)
            self.consecutive_failures = 0
            row.status, row.file, row.bytes = "ok", Path(result["path"]).name, result["bytes"]
            self.message.emit("info", f"Scan #{cur['number']} saved: {row.file} "
                                      f"({fmt_bytes(result['bytes'])}, {result.get('duration_s', '?')} s)")
            self._check_disk(result["bytes"])
            if result.get("dpi") and result["dpi"] != self.run.dpi and not self._dpi_warned:
                self._dpi_warned = True
                self.message.emit("warn", f"The scanner used {result['dpi']} dpi instead of the "
                                          f"{self.run.dpi} dpi you chose (its driver's limit).")
        else:
            self.fail_count += 1
            self.consecutive_failures += 1
            row.status, row.error = "failed", result.get("error", "unknown error")
            self.message.emit("error", f"Scan #{cur['number']} failed: {row.error}")
            if self.consecutive_failures == FAILURE_ALERT_AFTER:
                self.failure_alert.emit(True)
        self._write_log(row)
        self.scan_finished.emit(result)
        if self.state == "stopping":
            self._finish()
        else:
            self._tick()

    def _record_skip(self, index: int, reason: str) -> None:
        self.skip_count += 1
        slot = self.scheduler.slot_time(index)
        self.message.emit("warn", f"Scan #{index + 1} (due {_stamp(slot)[11:]}) skipped: {reason}")
        self._write_log(LogRow(scan_number=index + 1, scheduled_time=_stamp(slot),
                               status="skipped", error=reason))

    def _write_log(self, row: LogRow) -> None:
        error = self.scan_log.append(row)
        if error:
            self.message.emit("warn", error)

    def _check_disk(self, scan_bytes: int) -> None:
        try:
            free = free_bytes(self.run.folder)
        except OSError:
            return
        remaining = self.scheduler.remaining_slots()
        if remaining is None:  # open-ended: make sure there's room for another day
            remaining = int(86400 / self.run.interval_s)
            span = "the next 24 hours"
        else:
            span = f"the remaining {remaining} scans"
        needed = scan_bytes * remaining
        if free < scan_bytes * 3:
            self.message.emit("error", f"The disk is almost full ({fmt_bytes(free)} free). "
                                       "Scans will fail soon; free up space or choose another folder.")
        elif free < needed and not self._disk_warned:
            self._disk_warned = True
            self.message.emit("warn", f"Low disk space: {fmt_bytes(free)} free, about "
                                      f"{fmt_bytes(needed)} needed for {span}.")

    def _finish(self) -> None:
        self._timer.stop()
        self._keep_awake.stop()
        if self.scan_log is not None and self.scan_log.flush():
            self.message.emit("warn", f"Some rows could not be written to {self.scan_log.path}.")
        self._set_state("idle")
        self.message.emit("info", f"Capture {self.finish_reason}. {self.ok_count} saved, "
                                  f"{self.fail_count} failed, {self.skip_count} skipped.")
        self.status_changed.emit()
