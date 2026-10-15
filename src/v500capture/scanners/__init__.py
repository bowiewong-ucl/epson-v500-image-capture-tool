"""Scanner backends. Each OS has a native backend; NAPS2 is used as a fallback if installed."""

from __future__ import annotations

import sys

from . import demo
from .base import Backend, Device, ScanError, ScanSettings

__all__ = ["Backend", "Device", "ScanError", "ScanSettings", "backends", "get_backend", "list_devices"]


def backends() -> list[Backend]:
    """Backends available on this computer, native first."""
    found: list[Backend] = []
    if demo.enabled():
        found.append(demo.DemoBackend())
    if demo.exclusive():
        return found
    if sys.platform == "win32":
        from .wia import WiaBackend
        found.append(WiaBackend())
    elif sys.platform == "darwin":
        try:
            from .macos_ica import IcaBackend
            found.append(IcaBackend())
        except ImportError:
            pass
    else:
        from .sane_cli import SaneBackend
        found.append(SaneBackend())

    from .naps2_cli import Naps2Backend, find_console
    command = find_console()
    if command:
        found.append(Naps2Backend(command))
    return found


def get_backend(name: str) -> Backend:
    for backend in backends():
        if backend.name == name:
            return backend
    raise ScanError(f"The '{name}' scanner connection is not available on this computer.")


def list_devices() -> tuple[list[Device], list[str]]:
    """All scanners from all backends, plus warnings for backends that failed."""
    devices: list[Device] = []
    warnings: list[str] = []
    for backend in backends():
        try:
            devices.extend(backend.list_devices())
        except ScanError as exc:
            warnings.append(str(exc))
        except Exception as exc:  # a broken driver must not hide the other backends
            warnings.append(f"{backend.name}: {type(exc).__name__}: {exc}")
    return devices, warnings
