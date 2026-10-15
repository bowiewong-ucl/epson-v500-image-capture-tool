"""Stop the computer going to sleep while a capture is running."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .util import external_env

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self.active = False

    def start(self) -> str | None:
        """Returns a warning message if sleep could not be blocked."""
        if self.active:
            return None
        try:
            if sys.platform == "win32":
                import ctypes

                if not ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED):
                    return "Could not stop Windows from sleeping."
            elif sys.platform == "darwin":
                self._proc = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                              env=external_env())
            else:
                exe = shutil.which("systemd-inhibit")
                if exe is None:
                    return "systemd-inhibit not found; make sure the computer is set not to sleep."
                self._proc = subprocess.Popen(
                    [exe, "--what=idle:sleep", "--who=V500 Capture", "--why=Scanning in progress",
                     "--mode=block", "sleep", "infinity"], env=external_env())
        except OSError as exc:
            return f"Could not stop the computer from sleeping: {exc}"
        self.active = True
        return None

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
