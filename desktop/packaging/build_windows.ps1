# Build Admeasy-Setup.exe on Windows. Needs: Python 3.11+, Inno Setup 6 (iscc on PATH), optional code-signing cert.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m venv .build; .\.build\Scripts\Activate.ps1
pip install -q -r ..\requirements.txt
python -m PyInstaller admeasy.spec --noconfirm --distpath dist --workpath build
if ($env:SIGN_PFX) { signtool sign /f $env:SIGN_PFX /p $env:SIGN_PFX_PASSWORD /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 dist\Admeasy\Admeasy.exe }
iscc admeasy.iss
if ($env:SIGN_PFX) { signtool sign /f $env:SIGN_PFX /p $env:SIGN_PFX_PASSWORD /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 Output\Admeasy-Setup.exe }
Write-Host "built: $PWD\Output\Admeasy-Setup.exe"
