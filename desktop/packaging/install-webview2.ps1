# Installs Microsoft Edge WebView2 runtime if missing (pywebview on Windows).
$ErrorActionPreference = "Stop"
$reg = "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7CE4E}"
if (Test-Path $reg) { exit 0 }
$dest = Join-Path $env:TEMP "MicrosoftEdgeWebview2Setup.exe"
Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $dest -UseBasicParsing
Start-Process -FilePath $dest -ArgumentList "/silent", "/install" -Wait
exit 0
