"""Small helpers for launching external programs."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Iterable

# Stop console windows flashing up when a windowed app runs a console program.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def external_env() -> dict[str, str]:
    """Environment for running system programs such as scanimage or NAPS2.

    A PyInstaller build on Linux points LD_LIBRARY_PATH at its bundled
    libraries, which can break system tools; restore the original value.
    """
    env = dict(os.environ)
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    return env


def run_external(cmd: list[str], timeout: float, stdout=subprocess.PIPE) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=stdout, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                          timeout=timeout, env=external_env(), creationflags=NO_WINDOW)


def decode(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace").strip()


def nearest(value: float, choices: Iterable[float]) -> float:
    return min(choices, key=lambda c: (abs(c - value), -c))
