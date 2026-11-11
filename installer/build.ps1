<#
  Builds the OBSplit installer.

    ./installer/build.ps1 -Version 0.1.0              # runtime + installer (needs Inno Setup 6)
    ./installer/build.ps1 -Version 0.1.0 -RuntimeOnly # just assemble and check the bundled Python

  The bundled Python is the official "embeddable" package from python.org, matching the version of the
  Python that runs this script, plus tkinter copied from that Python (the embeddable package leaves it out).
#>
param(
    [string]$Version = "0.1.0",
    [string]$Python = "python",
    [switch]$RuntimeOnly
)
$ErrorActionPreference = "Stop"
$root  = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "build"
$dist  = Join-Path $root "dist"
Remove-Item $build -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $build, $dist | Out-Null

# --- 1. Python runtime ---------------------------------------------------------------
$pyVer  = (& $Python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])").Trim()
$pyHome = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
Write-Host "Bundling Python $pyVer (tkinter from $pyHome)"

$zip = Join-Path $build "python-$pyVer-embed-amd64.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$pyVer/python-$pyVer-embed-amd64.zip" -OutFile $zip
$py = Join-Path $build "python"
Expand-Archive $zip $py

New-Item -ItemType Directory -Force (Join-Path $py "Lib") | Out-Null
Copy-Item (Join-Path $pyHome "Lib\tkinter") (Join-Path $py "Lib\tkinter") -Recurse
Get-ChildItem (Join-Path $py "Lib\tkinter") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem (Join-Path $pyHome "DLLs") -File |
    Where-Object { $_.Name -match '^(_tkinter\.pyd|tcl\d+t?\.dll|tk\d+t?\.dll|zlib1\.dll)$' } |
    ForEach-Object { Copy-Item $_.FullName $py }
Copy-Item (Join-Path $pyHome "tcl") (Join-Path $py "tcl") -Recurse

$pth = Get-ChildItem $py -Filter "python*._pth" | Select-Object -First 1
Add-Content $pth.FullName "Lib"

& (Join-Path $py "python.exe") -c @"
import tkinter, sqlite3, ssl, ctypes, json, zlib, urllib.request
print('runtime ok: Python', __import__('sys').version.split()[0], '| Tcl', tkinter.Tcl().eval('info patchlevel'))
"@
if ($LASTEXITCODE -ne 0) { throw "Bundled Python failed its self-check" }
if ($RuntimeOnly) { Write-Host "Runtime ready in $py"; return }

# --- 2. Installer --------------------------------------------------------------------
$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isdl.php" }

& $iscc "/DAppVersion=$Version" "/DSourceRoot=$root" "/DPythonDir=$py" "/O$dist" (Join-Path $PSScriptRoot "OBSplit.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem $dist -Filter "*.exe" | ForEach-Object { Write-Host "Built $($_.FullName) ($([math]::Round($_.Length / 1MB, 1)) MB)" }
