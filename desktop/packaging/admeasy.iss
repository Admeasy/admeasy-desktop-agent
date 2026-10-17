#define MyAppVersion "0.2.0.0"
#ifndef AppVersion
  #define AppVersion MyAppVersion
#endif
#ifndef AppVerName
  #define AppVerName "0.2.0-beta"
#endif

[Setup]
AppName=Admeasy
AppVersion={#AppVersion}
AppVerName="{#AppVerName}"
DefaultDirName={autopf}\Admeasy
DefaultGroupName=Admeasy
OutputBaseFilename=Admeasy-Setup
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes

[Files]
Source: "dist\Admeasy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "install-webview2.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Admeasy"; Filename: "{app}\Admeasy.exe"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install-webview2.ps1"""; StatusMsg: "Installing WebView2 (required for the Admeasy window)..."; Flags: waituntilterminated; Check: NeedsWebView2
Filename: "{app}\Admeasy.exe"; Description: "Open Admeasy now"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsWebView2: Boolean;
var Version: String;
begin
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7CE4E}', 'pv', Version) then
    Result := False
  else if RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7CE4E}', 'pv', Version) then
    Result := False
  else
    Result := True;
end;

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Admeasy"; ValueData: """{app}\Admeasy.exe"" run --background"; Flags: uninsdeletevalue
