"""Windows scanning through WIA (Windows Image Acquisition) automation.

Needs the Epson Scan driver for the V500 installed. Only runs inside the scan
child process, so a hung driver call can't freeze the GUI.
"""

from __future__ import annotations

import time
from pathlib import Path

from ..util import nearest
from .base import Backend, Device, ScanError, ScanSettings

SCANNER_DEVICE_TYPE = 1
FORMAT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}"

# WIA property ids
DOCUMENT_HANDLING_SELECT = 3088
ITEM_NAME = 4098
DATA_TYPE = 4103
BITS_PER_PIXEL = 4104
CURRENT_INTENT = 6146
X_RES, Y_RES = 6147, 6148
X_POS, Y_POS = 6149, 6150
X_EXTENT, Y_EXTENT = 6151, 6152

FLATBED = 2
SUBTYPE_RANGE, SUBTYPE_LIST = 1, 2

# color mode -> (intent, data type, bits per pixel)
_MODES = {"color": (1, 3, 24), "gray": (2, 2, 8), "bw": (4, 0, 1)}

_RETRYABLE = {0x80210006: "busy", 0x80210007: "warming up"}
_MESSAGES = {
    0x80210005: "The scanner is offline. Check it is switched on and the USB cable is connected.",
    0x80210006: "The scanner is busy (another program may be using it; close Epson Scan).",
    0x80210007: "The scanner lamp is still warming up.",
    0x8021000A: "Lost communication with the scanner. Check the USB cable.",
    0x8021000D: "The scanner is locked. Check the transportation lock on the underside is released.",
    0x80210015: "No scanner is available.",
    0x80210016: "The scanner lid or cover is open.",
    0x80210017: "The scanner lamp is off.",
}


def _com():
    import pythoncom
    import win32com.client.dynamic

    pythoncom.CoInitialize()
    return win32com.client.dynamic


def _hresult(exc: Exception) -> int | None:
    excepinfo = getattr(exc, "excepinfo", None)
    code = excepinfo[5] if excepinfo and excepinfo[5] else getattr(exc, "hresult", None)
    return code & 0xFFFFFFFF if isinstance(code, int) else None


def _describe(exc: Exception) -> str:
    code = _hresult(exc)
    if code in _MESSAGES:
        return _MESSAGES[code]
    return f"Windows scanner error {hex(code) if code else ''}: {exc}".strip()


def _find_prop(props, prop_id: int | None = None, name: str | None = None):
    for p in props:
        if (prop_id is not None and p.PropertyID == prop_id) or (name is not None and p.Name == name):
            return p
    return None


def _set(props, prop_id: int, value, required: bool = False) -> None:
    p = _find_prop(props, prop_id)
    if p is None:
        if required:
            raise ScanError(f"The scanner driver does not support setting property {prop_id}.")
        return
    try:
        p.Value = value
    except Exception:
        if required:
            raise


def _flatbed_item(dev):
    items = list(dev.Items)
    if not items:
        raise ScanError("The scanner driver reported no scan sources.")
    for item in items:
        p = _find_prop(item.Properties, ITEM_NAME)
        if p is not None and "flat" in str(p.Value).lower():
            return item
    return items[0]


def _valid_values(p) -> list[int] | None:
    try:
        if p.SubType == SUBTYPE_LIST:
            return [int(v) for v in p.SubTypeValues]
        if p.SubType == SUBTYPE_RANGE:
            lo, hi, step = int(p.SubTypeMin), int(p.SubTypeMax), max(1, int(p.SubTypeStep))
            return list(range(lo, hi + 1, step))
    except Exception:
        pass
    return None


class WiaBackend(Backend):
    name = "wia"

    def _scanner_infos(self):
        dynamic = _com()
        manager = dynamic.Dispatch("WIA.DeviceManager")
        for info in manager.DeviceInfos:
            if info.Type == SCANNER_DEVICE_TYPE:
                name_prop = _find_prop(info.Properties, name="Name")
                yield info, str(name_prop.Value) if name_prop else str(info.DeviceID)

    def list_devices(self) -> list[Device]:
        try:
            return [Device(f"wia:{info.DeviceID}", name, self._max_dpi(info))
                    for info, name in self._scanner_infos()]
        except Exception as exc:
            raise ScanError(f"Could not list WIA scanners: {_describe(exc)}") from exc

    @staticmethod
    def _max_dpi(info) -> int | None:
        try:
            p = _find_prop(_flatbed_item(info.Connect()).Properties, X_RES)
            allowed = _valid_values(p) if p is not None else None
            return max(allowed) if allowed else None
        except Exception:  # e.g. busy in another program: still list the scanner
            return None

    def scan(self, device: Device, settings: ScanSettings, work_dir: Path) -> Path:
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                return self._scan_once(device, settings, work_dir)
            except ScanError:
                raise
            except Exception as exc:
                if _hresult(exc) in _RETRYABLE and attempt < attempts:
                    time.sleep(10)
                    continue
                raise ScanError(_describe(exc)) from exc
        raise AssertionError("unreachable")

    def _scan_once(self, device: Device, settings: ScanSettings, work_dir: Path) -> Path:
        info = next((i for i, _ in self._scanner_infos() if i.DeviceID == device.native_id), None)
        if info is None:
            raise ScanError(f"Scanner '{device.name}' is no longer connected.")
        dev = info.Connect()
        _set(dev.Properties, DOCUMENT_HANDLING_SELECT, FLATBED)

        item = _flatbed_item(dev)
        props = item.Properties

        # Intent first: changing it resets the other settings to its defaults.
        intent, data_type, bpp = _MODES[settings.color_mode]
        _set(props, CURRENT_INTENT, intent)
        _set(props, DATA_TYPE, data_type)
        _set(props, BITS_PER_PIXEL, bpp)

        for prop_id in (X_RES, Y_RES):
            p = _find_prop(props, prop_id)
            if p is None:
                raise ScanError("The scanner driver does not allow setting the resolution.")
            allowed = _valid_values(p)
            p.Value = int(nearest(settings.dpi, allowed)) if allowed else settings.dpi

        # Whole bed: the maximum extent depends on the resolution, so set it last.
        _set(props, X_POS, 0)
        _set(props, Y_POS, 0)
        for prop_id in (X_EXTENT, Y_EXTENT):
            p = _find_prop(props, prop_id)
            if p is not None and p.SubType == SUBTYPE_RANGE:
                p.Value = p.SubTypeMax

        image = item.Transfer(FORMAT_BMP)
        out = work_dir / f"scan.{image.FileExtension or 'bmp'}"
        out.unlink(missing_ok=True)
        image.SaveFile(str(out))
        return out
