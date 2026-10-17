# Build unsigned Admeasy-Setup.exe (beta). Requires Python 3.11+ and Inno Setup 6 (iscc on PATH).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Root = (Resolve-Path "..").Path
$Ver = (python -c "import importlib.util; s=importlib.util.spec_from_file_location('m','$Root\admeasy_desktop\__init__.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.VERSION)")
if ($Ver -match '^(\d+\.\d+\.\d+)') {
    $InnoVer = "$($Matches[1]).0"
} else {
    $InnoVer = "0.2.0.0"
}
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .build, dist, build, Output
python -m venv .build
.\.build\Scripts\Activate.ps1
pip install -q -U pip wheel
pip install -q -r "$Root\requirements.txt" pyinstaller
$env:ADMEASY_RELEASE_VERSION = $Ver
python -m PyInstaller admeasy.spec --noconfirm --distpath dist --workpath build
iscc "/DAppVersion=$InnoVer" "/DAppVerName=$Ver" admeasy.iss
Move-Item -Force "Output\Admeasy-Setup.exe" "Admeasy-$Ver-windows-unsigned.exe"
Write-Host "built: $PWD\Admeasy-$Ver-windows-unsigned.exe"
