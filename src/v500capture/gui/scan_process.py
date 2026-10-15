"""Runs one command-line job (a scan or a scanner search) in a child process."""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


def child_command() -> tuple[str, list[str]]:
    """How to start this app again in command-line mode."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return sys.executable, []
    return sys.executable, ["-m", "v500capture"]


class ChildJob(QObject):
    """Emits ``finished`` exactly once with the child's JSON result (always has "ok")."""

    finished = Signal(dict)

    def __init__(self, args: list[str], timeout_s: float, parent: QObject | None = None):
        super().__init__(parent)
        self._args = args
        self._timeout_s = timeout_s
        self._result_file = Path(tempfile.gettempdir()) / f"v500capture-{uuid.uuid4().hex}.json"
        self._output = bytearray()
        self._timed_out = False
        self._aborted = False
        self._done = False

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyRead.connect(self._collect_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    def start(self) -> None:
        program, prefix = child_command()
        self._proc.start(program, prefix + self._args + ["--result-file", str(self._result_file)])
        self._timer.start(int(self._timeout_s * 1000))

    def abort(self) -> None:
        self._aborted = True
        self._proc.kill()

    def _collect_output(self) -> None:
        self._output.extend(bytes(self._proc.readAll()))
        del self._output[:-4000]  # keep only the tail for error messages

    def _on_timeout(self) -> None:
        self._timed_out = True
        self._proc.kill()

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:  # no finished signal follows
            self._emit({"ok": False, "error": f"Could not start the scan process: {self._proc.errorString()}"})

    def _on_finished(self, exit_code: int, _status) -> None:
        result = None
        try:
            result = json.loads(self._result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if result is None:
            if self._timed_out:
                minutes = self._timeout_s / 60
                error = (f"No response from the scanner after {minutes:g} minutes, so the scan was "
                         "cancelled. Check the scanner is switched on and connected.")
            elif self._aborted:
                error = "Scan cancelled."
            else:
                tail = self._output.decode("utf-8", errors="replace").strip()[-600:]
                error = f"The scan process stopped unexpectedly (exit code {exit_code}). {tail}".strip()
            result = {"ok": False, "error": error}
        self._emit(result)

    def _emit(self, result: dict) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self._result_file.unlink(missing_ok=True)
        self.finished.emit(result)
