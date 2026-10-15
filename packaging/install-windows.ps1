# Installs the built app for the current Windows user (no admin rights needed):
# copies dist\V500Capture.exe to %LOCALAPPDATA%\Programs\V500 Capture and adds
# Desktop and Start menu shortcuts. Re-run after rebuilding to update.
#
#   powershell -ExecutionPolicy Bypass -File packaging\install-windows.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\install-windows.ps1 -Uninstall
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '..\dist\V500Capture.exe'
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

if (-not (Test-Path $source)) {
    throw "Build the app first: pyinstaller packaging/v500capture.spec --noconfirm  (missing $source)"
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
