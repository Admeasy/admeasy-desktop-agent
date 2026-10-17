# Create a virtual environment and install the desktop agent (Windows).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
python -m pip install -U pip wheel
pip install -r requirements.txt
pip install -e .
Write-Host ""
Write-Host "Done. Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host 'Set backend: $env:ADMEASY_BACKEND="https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com"'
Write-Host "Then: python -m admeasy_desktop doctor"
Write-Host "      python -m admeasy_desktop login"
Write-Host "      python -m admeasy_desktop run"
Write-Host ""
Write-Host "Windows: pink agent cursor uses Tk (bundled with python.org installs). Use official Python 3.12+ if tkinter is missing."
