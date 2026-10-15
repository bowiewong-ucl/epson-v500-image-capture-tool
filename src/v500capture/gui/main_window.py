"""The main window."""

from __future__ import annotations

import html
import math
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QDir, Qt, QTime, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDateTimeEdit, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .. import APP_NAME, config
from ..config import (
    COLOR_CHOICES, DPI_CHOICES, FORMAT_CHOICES, JPEG_MAX_SIDE, Settings, estimate_scan_bytes,
    estimate_scan_pixels,
)
from ..output import FORMATS, free_bytes, make_filename
from .controller import CaptureController, RunConfig, fmt_bytes, scan_timeout
from .scan_process import ChildJob

COLOR_LABELS = {"color": "Colour", "gray": "Greyscale", "bw": "Black & white"}
FORMAT_LABELS = {"tiff": "TIFF (lossless, largest)", "png": "PNG (lossless)", "jpeg": "JPEG (smallest, lossy)"}
LIST_TIMEOUT_S = 120
LARGE_SCAN_BYTES = 1e9


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.controller = CaptureController(self)
        self._list_job: ChildJob | None = None
        self._test_job: ChildJob | None = None
        self._test_duration: float | None = None
        self._last_image: str | None = None
        self._device_max_dpi: dict[str, int | None] = {}
        self._wanted_dpi = settings.dpi  # the user's choice, kept when a scanner can't go that high

        self.setWindowTitle(f"{APP_NAME} – Epson V500 time-lapse")
        self._build_ui()
        self._load_settings()
        self._connect()
        self._update_estimates()
        self._update_filename_example()
        self._on_state_changed("idle")
        self.refresh_devices()

    # ---- layout ----------------------------------------------------------
    def _build_ui(self) -> None:
        # 1. Scanner
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh_btn = QPushButton("Refresh")
        self.test_btn = QPushButton("Test scan")
        self.test_btn.setToolTip("Take one scan now to check the scanner and see how long a scan takes")
        row = QHBoxLayout()
        row.addWidget(self.device_combo, 1)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.test_btn)
        scanner_box = QGroupBox("1. Scanner")
        scanner_layout = QVBoxLayout(scanner_box)
        scanner_layout.addLayout(row)
        self.test_label = QLabel()
        self.test_label.setWordWrap(True)
        self.test_label.setTextFormat(Qt.TextFormat.RichText)
        self.test_label.setOpenExternalLinks(False)
        self.test_label.linkActivated.connect(self._open_path)
        scanner_layout.addWidget(self.test_label)
        self.test_label.hide()

        # 2. Where to save
        self.folder_edit = QLineEdit()
        self.browse_btn = QPushButton("Browse…")
        self.open_folder_btn = QPushButton("Open")
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_btn)
        folder_row.addWidget(self.open_folder_btn)
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setMaxLength(60)
        self.format_combo = QComboBox()
        for key in FORMAT_CHOICES:
            self.format_combo.addItem(FORMAT_LABELS[key], key)
        self.filename_example = QLabel()
        self.filename_example.setStyleSheet("color: gray")
        save_box = QGroupBox("2. Save images to")
        save_form = QFormLayout(save_box)
        save_form.addRow("Folder:", folder_row)
        save_form.addRow("File name starts with:", self.prefix_edit)
        save_form.addRow("File type:", self.format_combo)
        save_form.addRow("", self.filename_example)

        # 3. Image settings
        self.dpi_combo = QComboBox()
        for dpi in DPI_CHOICES:
            self.dpi_combo.addItem(f"{dpi} dpi", dpi)
        self.color_combo = QComboBox()
        for key in COLOR_CHOICES:
            self.color_combo.addItem(COLOR_LABELS[key], key)
        self.dpi_hint = QLabel()
        self.dpi_hint.setStyleSheet("color: gray")
        self.dpi_hint.hide()
        self.size_label = QLabel()
        self.size_label.setWordWrap(True)
        image_box = QGroupBox("3. Image settings")
        image_form = QFormLayout(image_box)
        image_form.addRow("Resolution:", self.dpi_combo)
        image_form.addRow("", self.dpi_hint)
        image_form.addRow("Colour:", self.color_combo)
        image_form.addRow("", self.size_label)

        # 4. Schedule
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setSuffix(" minutes")
        self.until_stop_radio = QRadioButton("Until I press Stop")
        self.until_time_radio = QRadioButton("Until:")
        self.end_edit = QDateTimeEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("ddd d MMM yyyy   HH:mm")
        self.until_group = QButtonGroup(self)
        self.until_group.addButton(self.until_stop_radio)
        self.until_group.addButton(self.until_time_radio)
        until_row = QHBoxLayout()
        until_row.addWidget(self.until_time_radio)
        until_row.addWidget(self.end_edit, 1)
        self.schedule_label = QLabel()
        self.schedule_label.setStyleSheet("color: gray")
        schedule_box = QGroupBox("4. Schedule")
        schedule_form = QFormLayout(schedule_box)
        schedule_form.addRow("Scan every:", self.interval_spin)
        schedule_form.addRow("Keep going:", self.until_stop_radio)
        schedule_form.addRow("", until_row)
        schedule_form.addRow("", self.schedule_label)

        # Start / Stop
        big = QFont()
        big.setPointSize(big.pointSize() + 3)
        big.setBold(True)
        self.start_btn = QPushButton("▶  Start")
        self.stop_btn = QPushButton("■  Stop")
        self.abort_btn = QPushButton("Cancel current scan")
        for btn, colour in ((self.start_btn, "#2e7d32"), (self.stop_btn, "#c62828")):
            btn.setFont(big)
            btn.setMinimumHeight(48)
            btn.setStyleSheet(f"QPushButton:enabled {{ background: {colour}; color: white; }}")
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.abort_btn)

        self.settings_boxes = [scanner_box, save_box, image_box, schedule_box]
        left = QVBoxLayout()
        for box in self.settings_boxes:
            left.addWidget(box)
        left.addLayout(buttons)
        left.addStretch(1)

        # Status
        self.state_label = QLabel()
        state_font = QFont(big)
        state_font.setPointSize(big.pointSize() + 2)
        self.state_label.setFont(state_font)
        self.alert_label = QLabel()
        self.alert_label.setWordWrap(True)
        self.alert_label.setStyleSheet(
            "background: #c62828; color: white; padding: 8px; border-radius: 4px; font-weight: bold")
        self.alert_label.hide()
        self.saved_value = QLabel("0")
        self.failed_value = QLabel("0")
        self.skipped_value = QLabel("0")
        self.next_value = QLabel("–")
        self.end_value = QLabel("–")
        stats = QGridLayout()
        for i, (text, value) in enumerate((("Scans saved:", self.saved_value),
                                           ("Failed:", self.failed_value),
                                           ("Skipped:", self.skipped_value),
                                           ("Next scan:", self.next_value),
                                           ("Ends:", self.end_value))):
            stats.addWidget(QLabel(text), i, 0)
            stats.addWidget(value, i, 1)
        stats.setColumnStretch(1, 1)
        self.thumb_label = QLabel("No scan yet")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setMinimumSize(300, 380)
        self.thumb_label.setStyleSheet("border: 1px solid #999; color: gray")
        self.last_file_label = QLabel()
        self.last_file_label.setWordWrap(True)
        self.last_file_label.setTextFormat(Qt.TextFormat.RichText)
        self.last_file_label.linkActivated.connect(self._open_path)
        status_box = QGroupBox("Status")
        status_layout = QVBoxLayout(status_box)
        status_layout.addWidget(self.state_label)
        status_layout.addWidget(self.alert_label)
        status_layout.addLayout(stats)
        status_layout.addWidget(QLabel("Latest image:"))
        status_layout.addWidget(self.thumb_label, 1)
        status_layout.addWidget(self.last_file_label)

        top = QHBoxLayout()
        top.addLayout(left, 3)
        top.addWidget(status_box, 2)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMinimumHeight(120)
        log_box = QGroupBox("Activity")
        QVBoxLayout(log_box).addWidget(self.log_view)

        central = QWidget()
        root = QVBoxLayout(central)
        root.addLayout(top, 3)
        root.addWidget(log_box, 1)
        self.setCentralWidget(central)
        self.resize(1000, 820)

    def _connect(self) -> None:
        self.refresh_btn.clicked.connect(self.refresh_devices)
        self.device_combo.currentIndexChanged.connect(self._update_dpi_choices)
        self.dpi_combo.activated.connect(self._on_dpi_picked)
        self.test_btn.clicked.connect(self.test_scan)
        self.browse_btn.clicked.connect(self._browse)
        self.open_folder_btn.clicked.connect(lambda: self._open_path(self.folder_edit.text()))
        self.prefix_edit.textChanged.connect(self._update_filename_example)
        self.format_combo.currentIndexChanged.connect(self._update_filename_example)
        self.format_combo.currentIndexChanged.connect(self._update_estimates)
        for widget in (self.dpi_combo, self.color_combo):
            widget.currentIndexChanged.connect(self._update_estimates)
        self.interval_spin.valueChanged.connect(self._update_estimates)
        self.end_edit.dateTimeChanged.connect(self._update_estimates)
        self.until_time_radio.toggled.connect(self._update_estimates)
        self.until_time_radio.toggled.connect(self.end_edit.setEnabled)
        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn.clicked.connect(lambda: self.controller.stop())
        self.abort_btn.clicked.connect(self.controller.force_abort)

        c = self.controller
        c.state_changed.connect(self._on_state_changed)
        c.message.connect(self.log)
        c.scan_finished.connect(self._on_scan_finished)
        c.status_changed.connect(self._update_status)
        c.failure_alert.connect(self._on_failure_alert)

    # ---- settings ----------------------------------------------------------
    def _load_settings(self) -> None:
        s = self.settings
        self.folder_edit.setText(QDir.toNativeSeparators(s.folder))
        self.prefix_edit.setText(s.prefix)
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(s.fmt)))
        self.dpi_combo.setCurrentIndex(max(0, self.dpi_combo.findData(s.dpi)))
        self.color_combo.setCurrentIndex(max(0, self.color_combo.findData(s.color_mode)))
        self.interval_spin.setValue(s.interval_min)
        (self.until_time_radio if s.use_end_time else self.until_stop_radio).setChecked(True)
        self.end_edit.setEnabled(s.use_end_time)
        tomorrow = QDateTime.currentDateTime().addDays(1)
        tomorrow.setTime(QTime(tomorrow.time().hour(), 0))
        self.end_edit.setDateTime(tomorrow)

    def _store_settings(self) -> None:
        s = self.settings
        device = self.device_combo.currentData()
        if device:
            s.device_id, s.device_name = device
        s.folder = self.folder_edit.text().strip()
        s.prefix = self.prefix_edit.text()
        s.fmt = self.format_combo.currentData()
        s.dpi = self.dpi_combo.currentData()
        s.color_mode = self.color_combo.currentData()
        s.interval_min = self.interval_spin.value()
        s.use_end_time = self.until_time_radio.isChecked()
        try:
            config.save(s)
        except OSError as exc:
            self.log("warn", f"Could not save settings: {exc}")

    # ---- scanners ------------------------------------------------------------
    def refresh_devices(self) -> None:
        if self._list_job is not None:
            return
        self.device_combo.clear()
        self.device_combo.addItem("Searching for scanners…", None)
        self.device_combo.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self._list_job = ChildJob(["--list-devices"], LIST_TIMEOUT_S, self)
        self._list_job.finished.connect(self._on_devices_listed)
        self._list_job.start()

    def _on_devices_listed(self, result: dict) -> None:
        self._list_job.deleteLater()
        self._list_job = None
        self.device_combo.clear()
        devices = result.get("devices", []) if result.get("ok") else []
        for warning in result.get("warnings", []):
            self.log("warn", warning)
        if not result.get("ok"):
            self.log("error", f"Could not search for scanners: {result.get('error')}")
        self._device_max_dpi = {d["id"]: d.get("max_dpi") for d in devices}
        for dev in devices:
            self.device_combo.addItem(dev["name"], (dev["id"], dev["name"]))
        if devices:
            ids = [d["id"] for d in devices]
            names = [d["name"] for d in devices]
            if self.settings.device_id in ids:
                self.device_combo.setCurrentIndex(ids.index(self.settings.device_id))
            elif self.settings.device_name in names:
                self.device_combo.setCurrentIndex(names.index(self.settings.device_name))
            self.log("info", f"Found {len(devices)} scanner(s).")
        else:
            self.device_combo.addItem("No scanner found – check it is on and plugged in, then click Refresh",
                                      None)
            self.log("warn", "No scanner found. Check the scanner is switched on, connected by USB, "
                             "and that its Epson driver is installed.")
        self._on_state_changed(self.controller.state)

    def _on_dpi_picked(self, index: int) -> None:
        self._wanted_dpi = self.dpi_combo.itemData(index)

    def _update_dpi_choices(self) -> None:
        """Offer only the resolutions the selected scanner's driver allows."""
        device = self.device_combo.currentData()
        limit = self._device_max_dpi.get(device[0]) if device else None
        choices = [d for d in DPI_CHOICES if limit is None or d <= limit] or [DPI_CHOICES[0]]
        if choices != [self.dpi_combo.itemData(i) for i in range(self.dpi_combo.count())]:
            self.dpi_combo.blockSignals(True)
            self.dpi_combo.clear()
            for dpi in choices:
                self.dpi_combo.addItem(f"{dpi} dpi", dpi)
            self.dpi_combo.blockSignals(False)
        fitting = [d for d in choices if d <= self._wanted_dpi]
        self.dpi_combo.setCurrentIndex(choices.index(fitting[-1] if fitting else choices[0]))
        if limit is not None:
            self.dpi_hint.setText(f"This scanner allows up to {limit} dpi.")
        self.dpi_hint.setVisible(limit is not None)
        self._update_estimates()

    def test_scan(self) -> None:
        device = self.device_combo.currentData()
        if not device:
            QMessageBox.warning(self, APP_NAME, "Choose a scanner first (click Refresh if the list is empty).")
            return
        fmt = self.format_combo.currentData()
        out = Path(tempfile.gettempdir()) / f"v500capture-test{FORMATS[fmt][0]}"
        thumb = Path(tempfile.gettempdir()) / "v500capture-test-thumb.png"
        args = ["--scan", "--device", device[0], "--device-name", device[1], "--out", str(out),
                "--dpi", str(self.dpi_combo.currentData()), "--color", self.color_combo.currentData(),
                "--thumbnail", str(thumb)]
        self._test_job = ChildJob(args, 2 * scan_timeout(self.dpi_combo.currentData()), self)
        self._test_job.finished.connect(self._on_test_finished)
        self.test_label.setText("Scanning… (the first scan can take a while as the lamp warms up)")
        self.test_label.show()
        self.log("info", f"Test scan started on {device[1]}…")
        self._on_state_changed(self.controller.state)
        self._test_job.start()

    def _on_test_finished(self, result: dict) -> None:
        self._test_job.deleteLater()
        self._test_job = None
        if result.get("ok"):
            self._test_duration = float(result.get("duration_s", 0))
            self.test_label.setText(
                f"✔ Test scan OK: took {self._test_duration:.0f} s, {fmt_bytes(result['bytes'])}, "
                f"{result['width']}×{result['height']} px at {result.get('dpi', '?')} dpi. <a href=\"{html.escape(result['path'])}\">Open image</a>")
            self.log("info", f"Test scan OK ({self._test_duration:.0f} s, {fmt_bytes(result['bytes'])}).")
            self._show_image(result)
            interval_s = self.interval_spin.value() * 60
            if self._test_duration >= 0.8 * interval_s:
                self.log("warn", f"A scan takes {self._test_duration:.0f} s, close to the "
                                 f"{self.interval_spin.value()} min interval. Some scans may be skipped.")
        else:
            self.test_label.setText(f"✘ Test scan failed: {html.escape(result.get('error', ''))}")
            self.log("error", f"Test scan failed: {result.get('error')}")
        self._update_estimates()
        self._on_state_changed(self.controller.state)

    # ---- capture -------------------------------------------------------------
    def start_capture(self) -> None:
        run = self._validate()
        if run is None:
            return
        self._store_settings()
        self.alert_label.hide()
        self.controller.start(run)

    def _validate(self) -> RunConfig | None:
        def fail(text: str) -> None:
            QMessageBox.warning(self, APP_NAME, text)

        device = self.device_combo.currentData()
        if not device:
            fail("Choose a scanner first (click Refresh if the list is empty).")
            return None
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            fail("Choose a folder to save the images in.")
            return None
        folder = Path(folder_text).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=folder):
                pass
        except OSError as exc:
            fail(f"Can't save images in this folder:\n{folder}\n\n{exc.strerror or exc}")
            return None

        interval_s = self.interval_spin.value() * 60
        end = None
        if self.until_time_radio.isChecked():
            end = float(self.end_edit.dateTime().toSecsSinceEpoch())
            if end <= time.time() + 60:
                fail("The end time must be at least a minute from now.")
                return None

        fmt = self.format_combo.currentData()
        dpi = self.dpi_combo.currentData()
        if fmt == "jpeg" and max(estimate_scan_pixels(dpi)) > JPEG_MAX_SIDE:
            fail(f"At {dpi} dpi the scan is too big for JPEG (max {JPEG_MAX_SIDE} pixels per side). "
                 "Choose TIFF or PNG, or a lower resolution.")
            return None
        estimate = self._estimated_scan_bytes()
        try:
            free = free_bytes(folder)
        except OSError:
            free = None
        if free is not None and free < estimate * 2:
            fail(f"There is not enough free disk space in this folder ({fmt_bytes(free)} free, "
                 f"each scan may need up to {fmt_bytes(estimate)}).")
            return None
        if self._test_duration and self._test_duration >= 0.8 * interval_s:
            answer = QMessageBox.question(
                self, APP_NAME,
                f"A test scan took {self._test_duration:.0f} s, which is close to the "
                f"{self.interval_spin.value()} minute interval, so some scans may be skipped.\n\nStart anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return None
        return RunConfig(device_id=device[0], device_name=device[1], folder=folder,
                         prefix=self.prefix_edit.text(), fmt=self.format_combo.currentData(),
                         dpi=self.dpi_combo.currentData(), color_mode=self.color_combo.currentData(),
                         interval_s=interval_s, end=end)

    def _on_state_changed(self, state: str) -> None:
        idle = state == "idle"
        other_job = self._list_job is not None or self._test_job is not None
        for box in self.settings_boxes:
            box.setEnabled(idle)
        has_device = bool(self.device_combo.currentData())
        self.device_combo.setEnabled(idle and self._list_job is None)
        self.refresh_btn.setEnabled(idle and not other_job)
        self.test_btn.setEnabled(idle and not other_job and has_device)
        self.start_btn.setEnabled(idle and not other_job)
        self.stop_btn.setEnabled(state == "running")
        self.abort_btn.setVisible(state == "stopping")
        self._update_status()

    def _on_scan_finished(self, result: dict) -> None:
        if result.get("ok"):
            self._show_image(result)

    def _on_failure_alert(self, on: bool) -> None:
        if on:
            self.alert_label.setText("⚠ The last few scans failed. Check the scanner is switched on and "
                                     "connected. Capture keeps retrying at each scheduled time.")
        self.alert_label.setVisible(on)

    def _update_status(self) -> None:
        c = self.controller
        if c.state == "running":
            text = "● Capturing (scanning now…)" if c.busy else "● Capturing"
            colour = "#2e7d32"
        elif c.state == "stopping":
            text, colour = "Stopping after this scan…", "#ef6c00"
        elif c.finish_reason:
            text, colour = f"Finished ({c.finish_reason})", "#555"
        else:
            text, colour = "Ready", "#555"
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {colour}")
        self.saved_value.setText(str(c.ok_count))
        self.failed_value.setText(str(c.fail_count))
        self.skipped_value.setText(str(c.skip_count))
        nxt = c.next_scan_time()
        if nxt is None:
            self.next_value.setText("–")
        else:
            secs = max(0, int(nxt - time.time()))
            self.next_value.setText(f"{datetime.fromtimestamp(nxt):%H:%M:%S} "
                                    f"(in {secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d})")
        if c.state != "idle" and c.run is not None:
            self.end_value.setText(f"{datetime.fromtimestamp(c.run.end):%a %d %b %Y %H:%M}"
                                   if c.run.end else "When you press Stop")
        else:
            self.end_value.setText("–")

    # ---- helpers -------------------------------------------------------------
    def _estimated_scan_bytes(self) -> int:
        return estimate_scan_bytes(self.dpi_combo.currentData(), self.color_combo.currentData())

    def _update_estimates(self) -> None:
        per_scan = self._estimated_scan_bytes()
        interval_min = self.interval_spin.value()
        per_day = per_scan * 1440 / interval_min
        text = f"≈ {fmt_bytes(per_scan)} per scan before compression · up to {fmt_bytes(per_day)} per day"
        if per_scan >= LARGE_SCAN_BYTES:
            text += (f"<br><b style='color:#c62828'>Very large: each scan can take a long time and "
                     f"needs at least {fmt_bytes(2 * per_scan)} of free memory (RAM). "
                     f"It may fill the disk quickly.</b>")
        if (self.format_combo.currentData() == "jpeg"
                and max(estimate_scan_pixels(self.dpi_combo.currentData())) > JPEG_MAX_SIDE):
            text += "<br><b style='color:#c62828'>Too big for JPEG at this resolution: choose TIFF or PNG.</b>"
        self.size_label.setText(text)

        if self.until_time_radio.isChecked():
            span = self.end_edit.dateTime().toSecsSinceEpoch() - time.time()
            if span > 0:
                count = math.ceil(span / (interval_min * 60))
                self.schedule_label.setText(f"About {count} scans, up to {fmt_bytes(per_scan * count)} in total.")
            else:
                self.schedule_label.setText("The end time is in the past.")
        else:
            self.schedule_label.setText("The first scan is taken as soon as you press Start.")

    def _update_filename_example(self) -> None:
        name = make_filename(self.prefix_edit.text(), datetime.now(), self.format_combo.currentData())
        self.filename_example.setText(f"e.g. {name}")

    def _show_image(self, result: dict) -> None:
        thumb = result.get("thumbnail")
        if thumb and os.path.exists(thumb):
            pixmap = QPixmap(thumb)
            if not pixmap.isNull():
                self.thumb_label.setPixmap(pixmap.scaled(self.thumb_label.size(),
                                                         Qt.AspectRatioMode.KeepAspectRatio,
                                                         Qt.TransformationMode.SmoothTransformation))
            try:
                os.remove(thumb)
            except OSError:
                pass
        self._last_image = result["path"]
        stamp = datetime.now().strftime("%H:%M:%S")
        self.last_file_label.setText(
            f"{html.escape(Path(result['path']).name)} (at {stamp}) – "
            f"<a href=\"{html.escape(result['path'])}\">open</a>")

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose where to save the images",
                                                  self.folder_edit.text() or str(Path.home()))
        if folder:
            self.folder_edit.setText(QDir.toNativeSeparators(folder))

    def _open_path(self, path: str) -> None:
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif path:
            QMessageBox.information(self, APP_NAME, f"{path}\n\ndoes not exist yet.")

    def log(self, level: str, text: str) -> None:
        colour = {"warn": "#ef6c00", "error": "#c62828"}.get(level)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = html.escape(text)
        if colour:
            body = f"<span style='color:{colour}'>{body}</span>"
        self.log_view.appendHtml(f"<span style='color:gray'>{stamp}</span>&nbsp;&nbsp;{body}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.controller.state != "idle":
            answer = QMessageBox.question(self, APP_NAME, "A capture is running. Stop it and close?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.controller.shutdown()
        for job in (self._list_job, self._test_job):
            if job is not None:
                job.abort()
        self._store_settings()
        event.accept()
