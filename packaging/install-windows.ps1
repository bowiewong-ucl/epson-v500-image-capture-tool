# Installs the app for the current Windows user (no admin rights needed):
# copies V500Capture.exe (downloaded next to this script, or a local build in
# ..\dist) to %LOCALAPPDATA%\Programs\V500 Capture and adds Desktop and Start
# menu shortcuts. Re-run after downloading or building a new version to update.
#
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1 -Uninstall
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$source = @((Join-Path $PSScriptRoot 'V500Capture.exe'), (Join-Path $PSScriptRoot '..\dist\V500Capture.exe')) |
    Where-Object { Test-Path $_ } | Select-Object -First 1
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\V500 Capture'
$target = Join-Path $installDir 'V500Capture.exe'
$shortcuts = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'V500 Capture.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'V500 Capture.lnk')
)

if ($Uninstall) {
    $shortcuts | Where-Object { Test-Path $_ } | Remove-Item
    if (Test-Path $installDir) { Remove-Item $installDir -Recurse }
    Write-Host 'V500 Capture removed. (Your settings and scans are left untouched.)'
    return
}

if (-not $source) {
    throw ('V500Capture.exe not found. Put this script in the same folder as V500Capture.exe, ' +
           'or build the app first: pyinstaller packaging/v500capture.spec --noconfirm')
}
if (Get-Process -Name 'V500Capture' -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $target }) {
    throw 'V500 Capture is running. Close it, then run this again.'
}

New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item $source $target -Force

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $shortcuts) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $target
    $link.WorkingDirectory = $installDir
    $link.IconLocation = "$target,0"
    $link.Description = 'Time-lapse scanning with the Epson Perfection V500'
    $link.Save()
}
Write-Host "Installed to $target"
Write-Host 'Start it from the "V500 Capture" icon on the Desktop or in the Start menu.'
