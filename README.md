# V500 Capture

Time-lapse scanning with an **Epson Perfection V500 Photo**. The app takes a flatbed scan every
*N* minutes (20 by default) and saves each image to a folder you choose. It keeps going until you
press **Stop** or until an end date and time you set.

Works on Windows 10 and 11.

---

## 1. Install the Epson scanner driver (once per computer)

The app talks to the scanner through Epson's own driver, so install that first: *Scanner Driver
and EPSON Scan Utility v3.7.7.0* (`PerfV500_3770_AM.exe`) from
[Epson's V500 support page](https://epson.com/Support/Scanners/Perfection-Series/Epson-Perfection-V500-Photo/s/SPT_B11B189011).
Also install *Common Updater for Epson Scan* from the same page.

Before first use, make sure the **transportation lock** on the underside of the scanner is unlocked.

## 2. Install the app

Download `V500Capture.exe` from the
[**Releases** page](https://github.com/bowiewong-ucl/epson-v500-image-capture-tool/releases).
The app is that single file, so just double-click it. If Windows SmartScreen warns you, click
*More info → Run anyway*. The first launch takes a few seconds while it unpacks.

To get a Desktop and Start menu icon, also download `install-windows.ps1` into the same folder and run
`powershell -ExecutionPolicy Bypass -File install-windows.ps1`. Add `-Uninstall` to remove it.

## 3. Take a time-lapse

1. **Scanner**: pick the V500 from the list. If it's not there, check it's switched on and
   plugged in, then click **Refresh**. Click **Test scan** to check everything works and to see how
   long one scan takes.
2. **Save images to**: choose a folder, a file-name prefix and a file type.
   - *TIFF*: lossless, best for measurements.
   - *PNG*: lossless and smaller.
   - *JPEG*: much smaller, slight quality loss.
3. **Image settings**: choose the resolution (dpi) and colour. The app shows roughly how much disk
   space the scans will use.
4. **Schedule**: set how often to scan and choose **Until I press Stop** or **Until** a date and time.
5. Press **▶ Start**. The first scan happens immediately, then one every interval.
6. Press **■ Stop** to finish early. A scan already in progress is allowed to finish.

While capturing, the window shows the latest image, the time of the next scan and how many
scans have been saved, failed or skipped.

### What gets saved

- One image per scan, named like `scan_2026-09-29_14-00-00.tif` (the date and time the scan started).
- `scan_log.csv` in the same folder, with one row per scheduled scan: scheduled time, start and
  finish time, status (`ok` / `failed` / `skipped`), file name, size and any error. You can open it in Excel.
  If the file is open in Excel, the app can't write to it; it keeps the rows and adds
  them once you close Excel.

### Choosing a resolution

The highest resolution is **1200 dpi**. The V500 itself can scan finer, but Epson's Windows driver
allows at most 1200 dpi through the interface this app uses (WIA). This was checked on a real V500.

Sizes are for a full-bed colour scan before compression. TIFF/PNG are usually smaller; JPEG is much smaller.

| dpi | per scan | per day at 20 min |
|---:|---:|---:|
| 150 | 7 MB | 0.5 GB |
| 300 | 27 MB | 1.9 GB |
| 600 | 107 MB | 7.7 GB |
| 1200 | 430 MB | 31 GB |

Measured on a V500 over USB 2.0 (Windows, whole glass, colour):

| dpi | time per scan |
|---:|---:|
| 150 | ~20 s |
| 300 | ~27 s (including lamp warm-up) |
| 1200 | ~3.7 min |

Each scan has a fixed overhead of about 15–20 seconds, whatever the resolution.

Use **Test scan** to check that a scan works and finishes within your interval.

### Good to know

- **Keep the computer on.** The app stops the computer from going to sleep while capturing. But a
  laptop still sleeps if you close its lid, and Windows Update may restart the computer, so set
  active hours or pause updates for long runs. If the app is closed or the computer restarts,
  start a new run.
- **Close Epson Scan** (and other scanning apps) while capturing. Only one program can use the scanner at a time.
- **If a scan fails** (for example, the scanner was unplugged), the app logs it and tries again at
  the next scheduled time. After 3 failures in a row a red warning appears.
- **If a scan takes longer than the interval**, the scan that was due is *skipped* rather than taken
  late, so images stay evenly spaced. Skipped scans are recorded in `scan_log.csv`.
- **Focus:** the V500 has fixed focus at the glass surface. There is no focus setting in any
  driver. Objects raised above the glass (e.g. 1–3 cm) come out increasingly blurred and darker.
  Put the surface you care about on the glass if you can, e.g. scan dishes upside down.
  To see how much blur you get, scan a printed ruler on spacers of different heights.

### Troubleshooting

- **No scanner found:** check the power and the USB cable, then click Refresh. Close Epson Scan.
  Check the V500 appears under *Imaging devices* in Device Manager.
- **The scanner shows in Epson Scan but not in this app.** The app uses the Windows WIA
  interface. If Epson's driver doesn't provide it on your PC, install the free
  [NAPS2](https://www.naps2.com) app too. V500 Capture then finds the scanner through NAPS2
  (it's listed as "… (via NAPS2 TWAIN)").

---

## For developers

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"
python -m v500capture             # run the GUI
```

**Without a scanner**, set `V500CAPTURE_DEMO=1` to add a pretend "Demo scanner". Related variables:
- `V500CAPTURE_DEMO=only` hides real scanners. The tests use it so they never touch real hardware.
- `V500CAPTURE_DEMO_DELAY=<s>` sets how long each demo scan takes.
- `V500CAPTURE_DEMO_FAIL=1` makes every demo scan fail.
- `V500CAPTURE_DEMO_MAX_DPI=<dpi>` makes the demo scanner report a resolution limit.
- `V500CAPTURE_SCAN_TIMEOUT=<s>` sets the scan kill timeout (default 900).

**Command line**, useful for diagnosing scanner problems:

```bash
python -m v500capture --list-devices
python -m v500capture --scan --device "V500" --out test.tif --dpi 300 --color color
```

The packaged app accepts the same flags (`V500Capture.exe --list-devices`).

**Tests:** `QT_QPA_PLATFORM=offscreen python -m pytest`

**Build** the stand-alone app:

```bash
pyinstaller packaging/v500capture.spec --noconfirm
```

This produces a single file, `dist/V500Capture.exe`. `packaging/install-windows.ps1` installs it for
the current user with Desktop and Start menu shortcuts. `packaging/make_icon.py` redraws the icon.
GitHub Actions (`.github/workflows/build.yml`) tests and builds the app on every push, and attaches
`V500Capture.exe` and `install-windows.ps1` to a GitHub Release when you push a `v*` tag.

### How it works

- `gui/`: PySide6 window (`main_window.py`) and `controller.py`, which runs a capture.
  - A 1-second timer asks `scheduler.py` whether a scan is due.
  - Slots are fixed-rate from the start time. Late or overlapping slots are skipped.
- **Every scan runs in a child process**: the app re-runs itself as `--scan … --result-file x.json`.
  - A hung or crashing driver can't freeze the window.
  - A scan that hangs is killed after the timeout.
- `scanners/`: one backend per OS behind a common interface.
  - `wia.py`: Windows WIA through pywin32.
  - `naps2_cli.py`: fallback through the NAPS2 command line.
  - `demo.py`: the pretend scanner.
  - `macos_ica.py` (macOS ImageCaptureCore) and `sane_cli.py` (Linux `scanimage`, set up with
    `scripts/linux/setup-epson-v500.sh`) are untested with the scanner and not part of the releases.
- `output.py`: file names, atomic saves (`.partial` then rename), format and colour conversion
  with Pillow, and `scan_log.csv`.
- `keepawake.py`: blocks system sleep while capturing (`SetThreadExecutionState`).
