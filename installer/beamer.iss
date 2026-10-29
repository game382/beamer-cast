; Inno Setup script. Build with: ISCC installer\beamer.iss   (after PyInstaller has produced dist\Beamer)
#define AppName "Beamer"
#define AppVersion "0.1.0"

[Setup]
AppId={{B3A4E1D2-5C6F-4A7B-9D10-BEA3E2C0FFEE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Beamer
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=Beamer-Setup
SetupIconFile=..\beamer\assets\beamer.ico
UninstallDisplayIcon={app}\Beamer.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
LicenseFile=..\LICENSE

[Files]
Source: "..\dist\Beamer\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Beamer"; Filename: "{app}\Beamer.exe"
Name: "{autodesktop}\Beamer"; Filename: "{app}\Beamer.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\Beamer.exe"; Description: "Start Beamer"; Flags: nowait postinstall skipifsilent
