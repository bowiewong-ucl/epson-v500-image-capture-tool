"""macOS scanning through ImageCaptureCore, the framework behind Apple's Image Capture app.

Needs Epson's "ICA Scanner Driver" for the V500 installed. ImageCaptureCore
reports progress through delegate callbacks on a run loop, so each call here
runs its own run loop until the work is done (we are in the scan child process).
"""

from __future__ import annotations

from pathlib import Path

import ImageCaptureCore as ICC
import objc
from Foundation import NSURL, NSObject
from PyObjCTools import AppHelper

from .base import MAX_SCAN_S, Backend, Device, ScanError, ScanSettings

LIST_TIMEOUT_S = 15


def _index_set(indexes) -> list[int]:
    values, i = [], indexes.firstIndex()
    while i != 0x7FFFFFFFFFFFFFFF and len(values) < 10000:  # NSNotFound
        values.append(int(i))
        i = indexes.indexGreaterThanIndex_(i)
    return values


def _device_id(device) -> str:
    uuid = device.UUIDString() if device.respondsToSelector_("UUIDString") else None
    return str(uuid or device.name())


class _Session(NSObject):
    @objc.python_method
    def setup(self, target: Device | None, settings: ScanSettings | None, work_dir: Path | None):
        self.target = target  # None = just list devices
        self.settings = settings
        self.work_dir = work_dir
        self.found = []
        self.scanner = None
        self.scan_started = False
        self.result_path = None
        self.error = None
        self.done = False
        return self

    # ---- finishing -------------------------------------------------------
    @objc.python_method
    def finish(self, error: str | None = None):
        if self.done:
            return
        self.done = True
        if error and not self.error:
            self.error = error
        if self.scanner is not None and self.scanner.hasOpenSession():
            self.scanner.requestCloseSession()
            AppHelper.callLater(5, AppHelper.stopEventLoop)  # in case close never reports back
        else:
            AppHelper.stopEventLoop()

    @objc.python_method
    def timed_out(self):
        if self.target is None:
            self.finish()
        elif self.scanner is None:
            self.finish(f"Scanner '{self.target.name}' was not found. Check it is switched on and connected.")
        else:
            self.finish("The scan did not finish in time.")

    # ---- ICDeviceBrowserDelegate ---------------------------------------
    def deviceBrowser_didAddDevice_moreComing_(self, browser, device, more):
        if self.target is None:
            self.found.append(Device(f"ica:{_device_id(device)}", str(device.name())))
            return
        if self.scanner is None and (_device_id(device) == self.target.native_id
                                     or str(device.name()) == self.target.name):
            self.scanner = device
            device.setDelegate_(self)
            device.requestOpenSession()

    def deviceBrowser_didRemoveDevice_moreGoing_(self, browser, device, more):
        if device is self.scanner:
            self.finish("The scanner was disconnected.")

    def deviceBrowserDidEnumerateLocalDevices_(self, browser):
        if self.target is None:
            self.finish()
        elif self.scanner is None:
            self.finish(f"Scanner '{self.target.name}' was not found. Check it is switched on and connected.")

    # ---- ICDeviceDelegate ------------------------------------------------
    def device_didOpenSessionWithError_(self, device, error):
        if error is not None:
            self.finish(f"Could not open the scanner: {error.localizedDescription()}")

    def deviceDidBecomeReady_(self, device):
        unit = device.selectedFunctionalUnit()
        if unit is not None and unit.type() == ICC.ICScannerFunctionalUnitTypeFlatbed:
            self.configure_and_scan(device, unit)
        else:
            device.requestSelectFunctionalUnit_(ICC.ICScannerFunctionalUnitTypeFlatbed)

    def didRemoveDevice_(self, device):
        self.finish("The scanner was disconnected.")

    def device_didCloseSessionWithError_(self, device, error):
        if self.done:
            AppHelper.stopEventLoop()

    def device_didEncounterError_(self, device, error):
        if error is not None:
            self.finish(f"Scanner error: {error.localizedDescription()}")

    # ---- ICScannerDeviceDelegate -----------------------------------------
    def scannerDevice_didSelectFunctionalUnit_error_(self, scanner, unit, error):
        if error is not None:
            self.finish(f"Could not select the flatbed: {error.localizedDescription()}")
        elif unit is not None and unit.type() == ICC.ICScannerFunctionalUnitTypeFlatbed:
            self.configure_and_scan(scanner, unit)

    def scannerDevice_didScanToURL_(self, scanner, url):
        self.result_path = str(url.path())

    def scannerDevice_didCompleteScanWithError_(self, scanner, error):
        self.finish(f"Scan failed: {error.localizedDescription()}" if error is not None else None)

    # ---- scanning --------------------------------------------------------
    @objc.python_method
    def configure_and_scan(self, scanner, unit):
        if self.scan_started:
            return
        self.scan_started = True
        mode = self.settings.color_mode
        unit.setMeasurementUnit_(ICC.ICScannerMeasurementUnitInches)
        resolutions = _index_set(unit.supportedResolutions())
        if resolutions:
            unit.setResolution_(min(resolutions, key=lambda r: abs(r - self.settings.dpi)))
        if mode == "bw":
            unit.setPixelDataType_(ICC.ICScannerPixelDataTypeBW)
            unit.setBitDepth_(ICC.ICScannerBitDepth1Bit)
        else:
            unit.setPixelDataType_(ICC.ICScannerPixelDataTypeGray if mode == "gray"
                                   else ICC.ICScannerPixelDataTypeRGB)
            unit.setBitDepth_(ICC.ICScannerBitDepth8Bits)
        size = unit.physicalSize()
        unit.setScanArea_(((0.0, 0.0), (size.width, size.height)))
        scanner.setTransferMode_(ICC.ICScannerTransferModeFileBased)
        scanner.setDownloadsDirectory_(NSURL.fileURLWithPath_(str(self.work_dir)))
        scanner.setDocumentName_("scan")
        scanner.setDocumentUTI_("public.tiff")
        scanner.requestScan()


def _run(session: _Session, timeout: float) -> None:
    browser = ICC.ICDeviceBrowser.alloc().init()
    browser.setDelegate_(session)
    browser.setBrowsedDeviceTypeMask_(ICC.ICDeviceTypeMaskScanner | ICC.ICDeviceLocationTypeMaskLocal)
    browser.start()
    AppHelper.callLater(timeout, session.timed_out)
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    finally:
        browser.stop()


class IcaBackend(Backend):
    name = "ica"

    def list_devices(self) -> list[Device]:
        session = _Session.alloc().init().setup(None, None, None)
        _run(session, LIST_TIMEOUT_S)
        return session.found

    def resolve(self, device_id: str, device_name: str) -> Device:
        # The scan itself looks the device up by id or name.
        return Device(device_id, device_name)

    def scan(self, device: Device, settings: ScanSettings, work_dir: Path) -> Path:
        session = _Session.alloc().init().setup(device, settings, work_dir)
        _run(session, MAX_SCAN_S)
        if session.error:
            raise ScanError(session.error)
        if not session.result_path or not Path(session.result_path).is_file():
            raise ScanError("The scanner finished but no image file was received.")
        return Path(session.result_path)
