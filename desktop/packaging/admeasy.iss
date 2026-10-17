[Setup]
AppName=Admeasy
AppVersion=0.1.0
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
Filename: "{app}\Admeasy.exe"; Description: "Start Admeasy"; Flags: nowait postinstall skipifsilent
