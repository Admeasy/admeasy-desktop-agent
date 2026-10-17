# Windows release installer. Optional Authenticode: set SIGN_PFX (path) and SIGN_PFX_PASSWORD.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Root = (Resolve-Path "..").Path
$InitPy = Join-Path $Root "admeasy_desktop\__init__.py"
$Ver = (Select-String -Path $InitPy -Pattern '^VERSION\s*=\s*"([^"]+)"' | ForEach-Object { $_.Matches.Groups[1].Value })
if (-not $Ver) { throw "Could not read VERSION from $InitPy" }
if ($Ver -match '^(\d+\.\d+\.\d+)') { $InnoVer = "$($Matches[1]).0" } else { $InnoVer = "0.3.0.0" }

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .build, dist, build, Output
python -m venv .build
.\.build\Scripts\Activate.ps1
pip install -q -U pip wheel
pip install -q -r "$Root\requirements.txt" pyinstaller
$env:ADMEASY_RELEASE_VERSION = $Ver
python -m PyInstaller admeasy.spec --noconfirm --distpath dist --workpath build

$ExePath = "dist\Admeasy\Admeasy.exe"
if ($env:SIGN_PFX -and (Test-Path $env:SIGN_PFX)) {
    $pwd = $env:SIGN_PFX_PASSWORD
    & signtool sign /f $env:SIGN_PFX /p $pwd /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $ExePath
}

iscc "/DAppVersion=$InnoVer" "/DAppVerName=$Ver" admeasy.iss
$Setup = "Output\Admeasy-Setup.exe"
if ($env:SIGN_PFX -and (Test-Path $env:SIGN_PFX)) {
    & signtool sign /f $env:SIGN_PFX /p $env:SIGN_PFX_PASSWORD /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $Setup
    $Out = "Admeasy-$Ver-windows.exe"
} else {
    $Out = "Admeasy-$Ver-windows-unsigned.exe"
}
Move-Item -Force $Setup $Out
Write-Host "built: $PWD\$Out"
