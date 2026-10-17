[Setup]
AppName=Admeasy
AppVersion=0.2.0-beta
DefaultDirName={autopf}\Admeasy
DefaultGroupName=Admeasy
OutputBaseFilename=Admeasy-Setup
PrivilegesRequired=lowest
Compression=lzma2
SolidCompression=yes

[Files]
Source: "dist\Admeasy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Admeasy"; Filename: "{app}\Admeasy.exe"

[Run]
Filename: "{app}\Admeasy.exe"; Description: "Open Admeasy now"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Admeasy"; ValueData: """{app}\Admeasy.exe"" run --background"; Flags: uninsdeletevalue
