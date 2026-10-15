# PyInstaller spec. Build from the repository root with:
#     pyinstaller packaging/v500capture.spec --noconfirm
# Output: dist/V500Capture.exe (Windows) or dist/V500Capture (Linux), a single
# file to double-click; dist/V500 Capture.app on macOS.
import os
import sys

src = os.path.join(SPECPATH, "..", "src")
assets = os.path.join(src, "v500capture", "assets")

hidden = []
if sys.platform == "win32":
    hidden += ["win32com.client", "win32com.client.dynamic", "pythoncom", "pywintypes"]
elif sys.platform == "darwin":
    hidden += ["ImageCaptureCore", "Foundation", "objc", "PyObjCTools.AppHelper"]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[src],
    hiddenimports=hidden,
    datas=[(assets, "v500capture/assets")],
    excludes=["tkinter", "pytest", "PyInstaller"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS apps are bundles; a one-file build isn't supported there.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="V500Capture",
              console=False, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="V500Capture", upx=False)
    app = BUNDLE(
        coll,
        name="V500 Capture.app",
        icon=os.path.join(assets, "icon.png"),
        bundle_identifier="io.github.v500capture",
        info_plist={"CFBundleShortVersionString": "0.1.0", "NSHighResolutionCapable": True},
    )
else:
    # One file. Each scan re-runs this exe; PyInstaller lets those child
    # processes reuse the parent's unpacked files instead of unpacking again.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="V500Capture",
        console=False,  # no console window; the scan child writes its result to a file
        icon=os.path.join(SPECPATH, "icon.ico"),
        upx=False,
    )
