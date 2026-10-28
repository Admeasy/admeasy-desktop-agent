# Install the Admeasy helper for the current Windows user. No administrator prompt.
# Invoke-RestMethod does not mark the script with the Mark of the Web, so SmartScreen does not prompt.
# Read the script before you run it.
#
#   $env:ADMEASY_BACKEND = "https://..."
#   $env:ADMEASY_PAIR = "CODE"   # optional, only when the backend issued one
#   irm https://raw.githubusercontent.com/Admeasy/admeasy-desktop-agent/main/desktop/packaging/install.ps1 | iex

$ErrorActionPreference = "Stop"
$Backend = if ($env:ADMEASY_BACKEND) { $env:ADMEASY_BACKEND } else { "https://admeasy-backend.6h5y8j39qxdcg.ap-south-1.cs.amazonlightsail.com" }
$Pair = $env:ADMEASY_PAIR
$Repo = if ($env:ADMEASY_REPO) { $env:ADMEASY_REPO } else { "https://github.com/Admeasy/admeasy-desktop-agent.git" }
$Root = if ($env:ADMEASY_SOURCE) { $env:ADMEASY_SOURCE } else { Join-Path $env:USERPROFILE ".admeasy\src" }

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "Python 3.11+ is required. Install it from python.org or with: winget install Python.Python.3.12"
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
  New-Item -ItemType Directory -Force -Path (Split-Path $Root) | Out-Null
  git clone --depth 1 $Repo $Root
} else {
  git -C $Root pull --ff-only
}

$Venv = Join-Path $env:USERPROFILE ".admeasy\venv"
python -m venv $Venv
$Py = Join-Path $Venv "Scripts\python.exe"
& $Py -m pip install -q -U pip
& $Py -m pip install -q -e (Join-Path $Root "desktop")
$env:ADMEASY_BACKEND = $Backend
& $Py -m admeasy_desktop register-handler
& $Py -m admeasy_desktop install-service

if ($Pair) {
  & $Py -m admeasy_desktop pair $Pair
  if ($LASTEXITCODE -eq 2) {
    Write-Host "Pairing codes are not on the backend yet. Open Admeasy and sign in with Google."
  } elseif ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} else {
  Write-Host "Helper installed. Open Admeasy and sign in with the same Google account as your phone."
}

Write-Host "Backend: $Backend"
Write-Host "Admeasy starts at login from HKCU Run. You can also run: $Py -m admeasy_desktop run"
