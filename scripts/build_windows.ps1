# Build a single portable PDFRedactor.exe. Python is needed only for this step.
# The finished exe runs without an installer and without Python.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    Write-Error "Install Python 3.12 from https://www.python.org/downloads/ and check Add python.exe to PATH. Then run this script again."
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

$VenvPython = ".\.venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt -r requirements-windows.txt
& $VenvPython -m PyInstaller --noconfirm --clean --onefile --windowed --name "PDFRedactor" --icon "redactor/static/icon.ico" --manifest "scripts/app.manifest" --collect-all pymupdf --collect-all webview --add-data "redactor/static;redactor/static" launch.py

Write-Host ""
Write-Host "Portable app: $Root\dist\PDFRedactor.exe"
Write-Host "Copy that file anywhere and double-click it. Nothing else needs to be installed."
