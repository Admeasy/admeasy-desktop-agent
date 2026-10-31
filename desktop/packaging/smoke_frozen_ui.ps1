# Build PyInstaller onedir and run headless UI smoke on Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Root = (Resolve-Path "..").Path
$InitPy = Join-Path $Root "admeasy_desktop\__init__.py"
$Ver = (Select-String -Path $InitPy -Pattern '^VERSION\s*=\s*"([^"]+)"' | ForEach-Object { $_.Matches.Groups[1].Value })
$Dist = if ($env:ADMEASY_SMOKE_DIST) { $env:ADMEASY_SMOKE_DIST } else { Join-Path $env:TEMP "admeasy-frozen-smoke-dist" }
$Build = if ($env:ADMEASY_SMOKE_BUILD) { $env:ADMEASY_SMOKE_BUILD } else { Join-Path $env:TEMP "admeasy-frozen-smoke-build" }
$HomeDir = if ($env:ADMEASY_HOME) { $env:ADMEASY_HOME } else { Join-Path $env:TEMP "admeasy-frozen-smoke-home" }
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Dist, $Build, $HomeDir
New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null
python -m pip install -q -U pip pyinstaller
python -m pip install -q -e $Root
$env:ADMEASY_RELEASE_VERSION = $Ver
python -m PyInstaller admeasy.spec --noconfirm --distpath $Dist --workpath $Build
$Bin = Join-Path $Dist "Admeasy\Admeasy.exe"
if (-not (Test-Path $Bin)) { throw "missing $Bin" }
$env:ADMEASY_HOME = $HomeDir
$env:ADMEASY_HEADLESS_SMOKE = "1"
& $Bin run
$log = Join-Path $HomeDir "logs\agent.log"
if ((Test-Path $log) -and (Select-String -Path $log -Pattern "Traceback" -Quiet)) {
  Get-Content $log
  throw "traceback in agent.log"
}
Write-Host "frozen UI smoke OK ($Bin)"
$env:ADMEASY_HEADLESS_SMOKE = "stress"
& $Bin run
Write-Host "frozen UI stress OK"
$env:ADMEASY_HEADLESS_SMOKE = "1"
$env:ADMEASY_HEADLESS_HOLD = "1"
$p = Start-Process -FilePath $Bin -ArgumentList "run" -PassThru -NoNewWindow
Start-Sleep -Seconds 2
$out = & $Bin run 2>&1 | Out-String
if ($out -notmatch "already running") { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; throw "second instance did not hand off: $out" }
Write-Host "second instance handoff OK"
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
